"""Synthetic model imports, current permissions, immutable files and revision races."""
import base64
import copy
import hashlib
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
import io
import json
from pathlib import Path
import struct
import subprocess
import tempfile
from threading import Thread
import unittest
from unittest.mock import patch
from uuid import uuid4

from apps.api.authority import PreviewError
from apps.api.model_library import ModelLibrary
from apps.api.model_validation import validate
from apps.api.session_http import handler_type
from apps.api.workbench_server import WorkbenchSessions
from tools.model_probe import ProbeError

CONTEXT='00000000-0000-0000-0000-000000000071'


def glb(path, change=None):
    binary=struct.pack('<9f',0,0,0,1,0,0,0,1,0)
    document={'asset':{'version':'2.0'},'scene':0,'scenes':[{'nodes':[0,1,2]}],
        'nodes':[{'name':key,'mesh':0,'translation':[i*2,0,0],'extras':{'component':key}} for i,key in enumerate(('CT','CN1','CN'))],
        'meshes':[{'primitives':[{'attributes':{'POSITION':0}}]}],
        'buffers':[{'byteLength':len(binary)}],'bufferViews':[{'buffer':0,'byteLength':len(binary)}],
        'accessors':[{'bufferView':0,'componentType':5126,'type':'VEC3','count':3}]}
    if change: change(document)
    raw=json.dumps(document).encode();raw+=b' '*(-len(raw)%4)
    chunks=struct.pack('<II',len(raw),0x4e4f534a)+raw+struct.pack('<II',len(binary),0x004e4942)+binary
    path.write_bytes(struct.pack('<4sII',b'glTF',2,12+len(chunks))+chunks)
    return path


class ModelAuthority:
    def __init__(self,_base):
        self.role='admin';self.grant='grant:1';self.allowed=True;self.hierarchy='hierarchy:1';self.complete=True
        self.objects={key:{'entityUid':key,'entityRevision':'object:1','installationContextId':CONTEXT,
            'objectKind':'cabinet' if key in ('CT','CN1','CN') else 'device','lifecycle':'active','displayName':key}
            for key in ('root','CT','CN1','CN','child')}
    def request(self,method,path,body=None):
        if path.endswith('/auth/login'):return {'token':'synthetic-token','user':{'username':body['username']}}
        if path.endswith('/auth/me'):return {'user':{'username':self.username,'is_active':True}}
        if not self.allowed:raise PreviewError(403,'FORBIDDEN')
        if path.endswith('/access'):return {'projectCode':'fixture','role':self.role,'accessRevision':self.grant,'capabilities':['objects.read','objects.resolve','installations.read','hierarchy.read']}
        if path.endswith('/installations/'+CONTEXT):return {'item':{'projectCode':'fixture','installationContextId':CONTEXT,'hierarchyRevision':self.hierarchy,'rootEntityUid':'root','purpose':'demonstration','engineeringUseAllowed':False}}
        if path.endswith('/objects/resolve'):return {'items':[{'resolution':'exact','object':copy.deepcopy(self.objects[uid])} for uid in body['entityUids']]}
        if '/ancestors?' in path:return {'hierarchyRevision':self.hierarchy,'completeness':'complete' if self.complete else 'incomplete','path':[{'object':self.objects['root'],'relation':{'verificationState':'assumed','engineeringUseAllowed':False}}]}
        raise AssertionError(path)


class ModelUploadTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        seed=self.root/'seed';seed.mkdir();self.path=glb(seed/'model.glb')
        seed.joinpath('model.json').write_text(json.dumps({'schemaVersion':1,'projectCode':'fixture','installationContextId':CONTEXT,'rootEntityUid':'root','sha256':hashlib.sha256(self.path.read_bytes()).hexdigest(),'bindings':[{'entityUid':key,'entityRevision':'object:1','componentKey':key,'geometryQuality':'source_candidate' if key=='CN' else 'proxy_schematic','bounds':[[0,0,0],[1,2,1]]} for key in ('CT','CN1','CN')]}))
        self.sessions=WorkbenchSessions('http://127.0.0.1:18001','fixture',CONTEXT,model_root=seed,library_root=self.root/'library',factory=ModelAuthority)
        anon,row=self.sessions.anonymous()
        self.sid,_=self.sessions.login(anon,{'username':'fixture-user','password':'synthetic-password','expectedSessionRevision':row.revision},'fixture-client')
        self.row=self.sessions.rows[self.sid];self.account=self.row.authority;self.library=self.sessions.library
    def metadata(self):return {'expectedSessionRevision':self.row.revision,'expectedLibraryRevision':self.library.listing()['libraryRevision'],'clientRequestId':str(uuid4()),'displayName':'合成模型','sourceNote':'Synthetic fixture; no third-party model.','rightsDeclared':True}
    def upload(self,metadata=None):
        data=self.path.read_bytes();return self.sessions.upload(self.sid,metadata or self.metadata(),io.BytesIO(data),len(data))['item']
    def request(self,path,body=None):return self.sessions.read(self.sid,'/api/workbench/'+path,{**(body or {}),'expectedSessionRevision':self.row.revision})
    def bind(self,item,uid='CN',component='component:2',**overrides):
        body={'modelVersionId':item['versionId'],'entityUid':uid,'componentKey':component,'expectedEntityRevision':'object:1','expectedHierarchyRevision':self.account.hierarchy,'expectedModelRevision':self.library.version(item['versionId'])['modelRevision'],'clientRequestId':str(uuid4()),**overrides}
        return self.sessions.save_binding(self.sid,{**body,'expectedSessionRevision':self.row.revision})
    def expect(self,code,fn):
        with self.assertRaises((PreviewError,ProbeError)) as caught:fn()
        self.assertEqual(caught.exception.code,code)
    def test_real_report_and_immutable_private_version_survive_restart(self):
        item=self.upload();self.assertEqual(item['report']['triangles'],3);self.assertEqual(item['report']['activeMeshInstances'],3)
        self.assertFalse(item['report']['sourceIdentityVerified']);self.assertEqual(item['report']['externalResourcesFetched'],0)
        self.assertEqual(len(item['components']),5) # Three source groups and two explicitly schematic seed proxies.
        reopened=ModelLibrary(self.root/'library','fixture',CONTEXT);stored=reopened.version(item['versionId'])
        self.assertEqual(reopened.content(stored),self.path.read_bytes());self.assertEqual(reopened.listing()['items'][0]['bindingCount'],0)
        self.assertNotIn('actor',reopened.listing()['items'][0]);self.assertEqual((reopened.root/'files'/(item['versionId']+'.glb')).stat().st_mode&0o777,0o600)
        with self.assertRaises(ValueError):ModelLibrary(self.root/'library','different-project',CONTEXT)
    def test_upload_request_replay_is_idempotent_and_conflicting_payload_is_refused(self):
        metadata=self.metadata();first=self.upload(metadata);self.assertEqual(self.upload(metadata)['versionId'],first['versionId'])
        self.assertEqual(len(self.library.listing()['items']),1)
        self.expect('REQUEST_CONFLICT',lambda:self.upload({**metadata,'displayName':'Changed'}))
    def test_stale_library_revision_never_replaces_a_model(self):
        stale=self.metadata();self.upload();self.expect('MODEL_LIBRARY_CHANGED',lambda:self.upload(stale))
        self.assertEqual(len(self.library.listing()['items']),1)
    def test_failed_temporary_cleanup_never_blocks_old_or_project_model_uploads(self):
        original=Path.unlink
        def deny_temporary(path,*args,**kwargs):
            if path.parent==self.library.root/'temporary' and path.name.startswith('upload-'):
                raise PermissionError('Synthetic cleanup failure')
            return original(path,*args,**kwargs)
        with patch.object(self.library,'process',side_effect=PreviewError(422,'INVALID_MODEL')):
            with patch.object(Path,'unlink',deny_temporary):
                self.expect('MODEL_STORAGE_UNAVAILABLE',lambda:self.upload())
        self.assertEqual(self.library.listing()['items'],[])
        self.assertTrue(self.library.slots.acquire(blocking=False))
        self.library.slots.release()
        self.assertEqual(len(list((self.library.root/'temporary').glob('upload-*.glb'))),1)
        self.assertEqual(self.upload()['state'],'ready')
    def test_reader_or_revoked_membership_cannot_upload(self):
        for role,allowed in [('reader',True),('admin',False)]:
            self.account.role,self.account.allowed=role,allowed
            self.expect('MODEL_WRITE_FORBIDDEN' if allowed else 'FORBIDDEN',lambda:self.upload())
        self.assertEqual(len(self.library.listing()['items']),0)
    def test_permission_change_after_validation_rolls_back_all_persistence(self):
        original=self.library.process
        def process(path):
            result=original(path);self.account.role='reader';return result
        with patch.object(self.library,'process',side_effect=process):self.expect('MODEL_WRITE_FORBIDDEN',lambda:self.upload())
        self.assertEqual(self.library.listing()['items'],[]);self.assertEqual(list((self.library.root/'files').iterdir()),[])
    def test_logout_while_receiving_discards_the_upload(self):
        sessions,sid,revision=self.sessions,self.sid,self.row.revision
        class Stream(io.BytesIO):
            def read(self,size=-1):
                sessions.logout(sid,revision);return super().read(size)
        self.expect('SESSION_EXPIRED',lambda:sessions.upload(sid,self.metadata(),Stream(self.path.read_bytes()),self.path.stat().st_size))
        self.assertEqual(self.library.listing()['items'],[])
    def test_concurrency_slot_and_worker_timeout_fail_closed(self):
        self.library.slots.acquire()
        try:self.expect('MODEL_BUSY',lambda:self.upload())
        finally:self.library.slots.release()
        with patch('apps.api.model_library.subprocess.run',side_effect=subprocess.TimeoutExpired('fixture',12)):
            self.expect('MODEL_LIMIT_EXCEEDED',lambda:self.upload())
        self.assertEqual(self.library.listing()['items'],[])
    def test_source_declaration_is_required_before_reading_bytes(self):
        self.expect('MODEL_RIGHTS_REQUIRED',lambda:self.upload({**self.metadata(),'rightsDeclared':False}))
        self.assertEqual(list((self.library.root/'temporary').iterdir()),[])
    def test_malformed_binding_values_cannot_reach_sqlite_or_create_an_audit(self):
        item=self.upload()
        self.expect('INVALID_CABINET',lambda:self.bind(item,uid=[]))
        self.expect('INVALID_REQUEST',lambda:self.bind(item,component=['invalid']))
        self.assertEqual(self.library.listing()['items'][0]['bindingCount'],0)
    def test_binding_preserves_demo_precision_and_checks_each_authoritative_uid(self):
        item=self.upload();self.bind(item)
        view=self.request('model',{'modelVersionId':item['versionId']})
        self.assertFalse(view['engineeringUseAllowed']);self.assertEqual(view['bindings'][0]['entityUid'],'CN')
        self.assertEqual(view['bindings'][0]['geometryQuality'],'source_candidate')
        self.expect('INVALID_CABINET',lambda:self.bind(item,uid='child'))
        self.account.complete=False;self.expect('MODEL_BINDING_CHANGED',lambda:self.bind(item,uid='CT',component='proxy:CT'))
    def test_binding_conflict_and_stale_revision_do_not_silently_overwrite(self):
        item=self.upload();self.bind(item)
        self.expect('COMPONENT_ALREADY_LINKED',lambda:self.bind(item,uid='CT'))
        self.expect('MODEL_CHANGED',lambda:self.bind(item,uid='CT',component='proxy:CT',expectedModelRevision=1))
        self.assertEqual(self.library.listing()['items'][0]['bindingCount'],1)
    def test_two_concurrent_binding_writers_do_not_lose_an_update(self):
        item=self.upload();results=[]
        def write(uid,component):
            try:self.bind(item,uid=uid,component=component,expectedModelRevision=1);results.append('saved')
            except PreviewError as error:results.append(error.code)
        workers=[Thread(target=write,args=('CT','proxy:CT')),Thread(target=write,args=('CN1','proxy:CN1'))]
        for worker in workers:worker.start()
        for worker in workers:worker.join()
        self.assertCountEqual(results,['saved','MODEL_CHANGED'])
        self.assertEqual(self.library.listing()['items'][0]['bindingCount'],1)
    def test_binding_request_retry_does_not_duplicate_audit_or_increment_again(self):
        item=self.upload();request_id=str(uuid4())
        first=self.bind(item,clientRequestId=request_id,expectedModelRevision=1)
        second=self.bind(item,clientRequestId=request_id,expectedModelRevision=1)
        self.assertEqual(first,second)
        with self.library.connect() as db:self.assertEqual(db.execute("select count(*) from audit where action='binding_saved'").fetchone()[0],1)
    def test_changed_identity_removes_stale_highlight_but_retains_a_reviewable_model(self):
        item=self.upload();self.bind(item);self.account.objects['CN']['entityRevision']='object:2'
        view=self.request('model',{'modelVersionId':item['versionId']})
        self.assertEqual(view['bindings'],[]);self.assertEqual(view['bindingWarnings'][0]['code'],'MODEL_BINDING_CHANGED')
    def test_content_rechecks_binding_after_read_and_never_returns_a_stale_view(self):
        item=self.upload();self.bind(item);view=self.request('model',{'modelVersionId':item['versionId']})
        payload={'modelVersionId':item['versionId'],'expectedModelSha256':view['sha256'],'expectedModelRevision':view['modelRevision'],'expectedViewRevision':view['viewRevision']}
        original=self.library.content
        def replaced(value):
            data=original(value);self.account.objects['CN']['entityRevision']='object:2';return data
        with patch.object(self.library,'content',side_effect=replaced):self.expect('MODEL_CHANGED',lambda:self.request('model/content',payload))
    def test_validation_rejects_external_resources_extensions_animation_and_oversized_accessors(self):
        changes=[lambda d:d['buffers'][0].update(uri='file:///private/secret'),lambda d:d.update(extensionsUsed=['unknown']),lambda d:d.update(animations=[{}]),lambda d:d['accessors'][0].update(count=500001),lambda d:d['nodes'][0]['extras'].update(__proto__={'ontoVisKey':'spoofed'})]
        for change in changes:
            with self.subTest(change=change):
                path=glb(self.root/'bad.glb',change)
                with self.assertRaises(ProbeError):validate(path)
    def test_invalid_png_and_nonfinite_transforms_never_become_ready(self):
        changes=[lambda d:d.update(images=[{'bufferView':0,'mimeType':'image/png'}]),lambda d:d['nodes'][0].update(scale=[1e308,1e308,1e308],translation=[1e308,0,0])]
        for change in changes:
            with self.subTest(change=change):
                path=glb(self.root/'bad.glb',change)
                with self.assertRaises(ProbeError):validate(path)
    def test_authorization_failure_at_final_commit_rolls_back_file_and_audit(self):
        path=glb(self.root/'pending.glb');calls=[]
        def authorize():
            calls.append(True)
            if len(calls)==2:raise PreviewError(403,'FORBIDDEN')
        self.expect('FORBIDDEN',lambda:self.library.save_upload(path,self.metadata(),'fixture-user',validate(path),authorize))
        self.assertEqual(self.library.listing()['items'],[])
        with self.library.connect() as db:self.assertEqual(db.execute('select count(*) from audit').fetchone()[0],0)
        self.assertEqual(list((self.library.root/'files').iterdir()),[])
    def test_binary_http_boundary_requires_origin_session_and_bounded_metadata(self):
        server=ThreadingHTTPServer(('127.0.0.1',0),handler_type(self.sessions,'http://127.0.0.1:4180',development=True))
        thread=Thread(target=server.serve_forever,daemon=True);thread.start()
        self.addCleanup(server.server_close);self.addCleanup(thread.join);self.addCleanup(server.shutdown)
        def request(changes=None,cookie=True):
            headers={'Host':'127.0.0.1:4180','Origin':'http://127.0.0.1:4180','Content-Type':'model/gltf-binary','X-Model-Metadata':base64.b64encode(json.dumps(self.metadata()).encode()).decode()}
            if cookie:headers['Cookie']='ontovis_development_session='+self.sid
            headers.update(changes or {})
            connection=HTTPConnection(*server.server_address,timeout=5)
            try:
                connection.request('POST','/api/workbench/models/upload',self.path.read_bytes(),headers)
                response=connection.getresponse();data=json.loads(response.read());return response.status,data
            finally:connection.close()
        self.assertEqual(request({'Origin':'https://foreign.invalid'})[0],403)
        self.assertEqual(request(cookie=False)[0],401)
        self.assertEqual(request({'Content-Type':'application/octet-stream'})[0],415)
        self.assertEqual(request({'X-Model-Metadata':'a'*9000})[0],422)
        status,data=request();self.assertEqual(status,200);self.assertEqual(data['item']['report']['triangles'],3)
