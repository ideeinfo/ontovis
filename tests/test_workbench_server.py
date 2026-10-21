"""Workbench session boundary, using synthetic actors and authority responses."""
from threading import Event, Thread
import unittest
from urllib.parse import parse_qs, urlsplit

from apps.api.authority import PreviewError
from apps.api.workbench_server import WorkbenchSessions
from tests.test_session_server import Account

CONTEXT = '00000000-0000-0000-0000-000000000071'
CHILD = 'fixture/child'


class WorkbenchAccount(Account):
    def __init__(self, base):
        super().__init__(base)
        self.hierarchy = CONTEXT + ':1'
        self.foreign = False
        self.merged = False
        self.calls = []
        self.image_wait = None
        self.image_started = None

    def request(self, method, path, body=None):
        self.calls.append((method,path,body))
        if path.startswith('/api/v1/auth/') or path.endswith('/access'):
            return super().request(method,path,body)
        if not self.allowed: raise PreviewError(403,'FORBIDDEN')
        if path.endswith('/installations/' + CONTEXT):
            return {'item':{'projectCode':'fixture-project','installationContextId':CONTEXT,
                            'rootEntityUid':'fixture-root','hierarchyRevision':self.hierarchy}}
        if path.endswith('/objects/resolve'):
            uid = body['entityUids'][0]
            return {'items':[{'resolution':'merged' if self.merged else 'exact', 'object':{
                'entityUid':uid,'installationContextId':'foreign' if self.foreign else CONTEXT,
                'entityRevision':'fixture-r1','lifecycle':'active'}}]}
        if '/children?' in path:
            query = parse_qs(urlsplit(path).query)
            return {'items':[{'object':{'entityUid':CHILD}}], 'nextCursor':'fixture-cursor',
                    'hierarchyRevision':self.hierarchy, 'query':query}
        if '/ancestors?' in path:
            return {'hierarchyRevision':self.hierarchy,'path':[],'completeness':'incomplete'}
        if path.endswith('/object-evidence/resolve'):
            return {'items':[{'evidenceRef':'fixture-evidence'}]}
        raise AssertionError('Unexpected upstream route')

    def image(self, path, body):
        self.calls.append(('POST',path,body))
        if self.image_started: self.image_started.set()
        if self.image_wait: self.image_wait.wait(3)
        return b'\x89PNG\r\n\x1a\nsynthetic'


class WorkbenchTests(unittest.TestCase):
    def setUp(self):
        self.accounts = []
        def factory(base):
            account = WorkbenchAccount(base); self.accounts.append(account); return account
        self.sessions = WorkbenchSessions('http://127.0.0.1:1234','fixture-project',CONTEXT,factory=factory)
        sid,row = self.sessions.anonymous()
        self.sid,view = self.sessions.login(sid,{'username':'fixture-user','password':'synthetic-password',
            'expectedSessionRevision':row.revision},'fixture-client')
        self.revision = view['sessionRevision']

    def read(self, suffix, **body):
        return self.sessions.read(self.sid,'/api/workbench/' + suffix,
                                  {'expectedSessionRevision':self.revision, **body})

    def selection(self):
        return {'entityUid':CHILD,'installationContextId':CONTEXT,
                'expectedEntityRevision':'fixture-r1','expectedHierarchyRevision':CONTEXT+':1'}

    def assert_error(self, code, call):
        with self.assertRaises(PreviewError) as caught: call()
        self.assertEqual(caught.exception.code,code)

    def test_context_resolves_the_authoritative_root_without_a_five_uid_manifest(self):
        result = self.read('context')
        self.assertEqual(result['root']['entityUid'],'fixture-root')
        self.assertEqual(result['sessionRevision'],self.revision)
        self.assertFalse(hasattr(self.sessions,'manifest'))

    def test_child_pages_preserve_server_cursor_and_expected_revision(self):
        result = self.read('children',parentEntityUid='fixture-root',cursor='fixture-cursor',expectedHierarchyRevision=CONTEXT+':1')
        self.assertEqual(result['nextCursor'],'fixture-cursor')
        self.assertEqual(result['query']['cursor'],['fixture-cursor'])
        self.assertEqual(result['query']['limit'],['50'])

    def test_incomplete_parent_chain_does_not_block_a_legitimate_direct_source_read(self):
        result = self.read('object',entityUid=CHILD,expectedHierarchyRevision=CONTEXT+':1')
        self.assertEqual(result['ancestors']['completeness'],'incomplete')
        self.assertEqual(len(self.read('evidence/resolve',**self.selection())['items']),1)

    def test_other_installation_or_merged_identity_does_not_return_details(self):
        self.accounts[0].foreign=True
        self.assert_error('NOT_FOUND_OR_FORBIDDEN',lambda:self.read('object',entityUid=CHILD,expectedHierarchyRevision=CONTEXT+':1'))
        self.accounts[0].foreign=False; self.accounts[0].merged=True
        self.assert_error('IDENTITY_CHANGED',lambda:self.read('object',entityUid=CHILD,expectedHierarchyRevision=CONTEXT+':1'))

    def test_client_cannot_select_a_project_connection_or_arbitrary_content_url(self):
        for fields in ({'url':'https://example.invalid/private'}, {'projectCode':'other'}, {'role':'admin'}):
            self.assert_error('INVALID_REQUEST',lambda:self.read('evidence/resolve',**self.selection(),**fields))
        self.assert_error('INVALID_REQUEST',lambda:self.read('evidence/resolve',**{**self.selection(),'installationContextId':'other'}))

    def test_source_content_uses_only_the_fixed_endpoint_and_image_representation(self):
        result=self.read('evidence/content',**self.selection(),evidenceRef='fixture-evidence',
                         expectedSourceRevision='a'*64,expectedContentSha256='b'*64)
        self.assertTrue(result['content'].startswith(b'\x89PNG'))
        calls=[item for item in self.accounts[0].calls if item[1].endswith('/object-evidence/content')]
        self.assertEqual(len(calls),1);self.assertEqual(calls[0][2]['representation'],'image')

    def test_session_and_installation_changes_refuse_stale_requests(self):
        self.assert_error('SESSION_CHANGED',lambda:self.sessions.read(self.sid,'/api/workbench/context',{'expectedSessionRevision':'old'}))
        self.accounts[0].hierarchy=CONTEXT+':2'
        self.assert_error('REVISION_CONFLICT',lambda:self.read('evidence/resolve',**self.selection()))

    def test_logout_during_image_read_discards_the_bytes(self):
        account=self.accounts[0]; account.image_wait=Event();account.image_started=Event(); result=[]
        def read():
            try: result.append(self.read('evidence/content',**self.selection(),evidenceRef='fixture-evidence',expectedSourceRevision='a'*64,expectedContentSha256='b'*64))
            except PreviewError as error: result.append(error.code)
        thread=Thread(target=read);thread.start();self.assertTrue(account.image_started.wait(2))
        self.sessions.logout(self.sid,self.revision);account.image_wait.set();thread.join(3)
        self.assertEqual(result,['SESSION_EXPIRED'])

    def test_permission_change_during_image_read_discards_the_bytes(self):
        account=self.accounts[0]; original=account.image
        def image(*args):
            value=original(*args);account.allowed=False;return value
        account.image=image
        self.assert_error('FORBIDDEN',lambda:self.read('evidence/content',**self.selection(),evidenceRef='fixture-evidence',expectedSourceRevision='a'*64,expectedContentSha256='b'*64))

    def test_project_catalog_forwards_only_bounded_search_and_server_cursor(self):
        account=self.accounts[0];original=account.request
        def request(method,path,body=None):
            if '/objects?' in path:return {'items':[], 'nextCursor':'opaque', 'query':parse_qs(urlsplit(path).query)}
            return original(method,path,body)
        account.request=request
        result=self.read('catalog',q='CN + 01',cursor='opaque',scope='project')
        self.assertEqual(result['query'],{'q':['CN + 01'],'cursor':['opaque'],'limit':['50']})
        self.assertEqual(result['nextCursor'],'opaque')
        self.assertFalse(any('/installations/' in call[1] for call in account.calls))
        self.assert_error('INVALID_REQUEST',lambda:self.read('catalog',q='x'*201))
        self.assert_error('INVALID_REQUEST',lambda:self.read('catalog',url='https://example.invalid'))

    def test_project_definition_does_not_borrow_an_equipment_parent(self):
        account=self.accounts[0];original=account.request
        def request(method,path,body=None):
            value=original(method,path,body)
            if path.endswith('/objects/resolve'):value['items'][0]['object']['installationContextId']=None
            return value
        account.request=request
        result=self.read('object',entityUid='definition',expectedHierarchyRevision=CONTEXT+':1',scope='project')
        self.assertEqual(result['ancestors'],{'path':[],'completeness':'not_applicable'})
        self.assertFalse(any('/ancestors?' in call[1] for call in account.calls))
        self.assert_error('NOT_FOUND_OR_FORBIDDEN',lambda:self.read('object',entityUid='definition',expectedHierarchyRevision=CONTEXT+':1',scope='equipment'))

    def test_definition_evidence_keeps_nullable_identity_pair(self):
        selection={**self.selection(),'installationContextId':None,'expectedHierarchyRevision':None}
        self.assertEqual(len(self.read('evidence/resolve',**selection)['items']),1)
        self.assert_error('INVALID_REQUEST',lambda:self.read('evidence/resolve',**{**selection,'expectedHierarchyRevision':'unexpected'}))

    def test_model_read_is_fixed_version_and_rechecks_permission_after_bytes(self):
        account=self.accounts[0]
        class Model:
            value={'sha256':'a'*64,'bindings':[{'entityUid':'CT'},{'entityUid':'CN'},{'entityUid':'CN1'}]}
            def metadata(self,items,context):return {'sha256':'a'*64,'engineeringUseAllowed':False}
            def content(self):return b'glTFsynthetic'
        self.sessions.model=Model()
        self.assertTrue(self.read('model/content',expectedModelSha256='a'*64)['content'].startswith(b'glTF'))
        self.assert_error('MODEL_CHANGED',lambda:self.read('model/content',expectedModelSha256='b'*64))
        self.assert_error('INVALID_REQUEST',lambda:self.read('model/content',expectedModelSha256='a'*64,url='https://example.invalid'))
        def revoked():account.allowed=False;return b'glTFsynthetic'
        self.sessions.model.content=revoked
        self.assert_error('FORBIDDEN',lambda:self.read('model/content',expectedModelSha256='a'*64))
