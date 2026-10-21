import copy
import hashlib
from http.server import ThreadingHTTPServer
import json
from pathlib import Path
import tempfile
from threading import Thread
import unittest
import urllib.error
import urllib.parse
import urllib.request

from tools.installation_preview import Authority, InstallationPreview, PreviewError, handler_type, load_manifest


CONTEXT = 'fixture-context'
ROOT, CT, CN1, CN, CHILD = 'fixture-root','fixture-ct','fixture-cn1','fixture-cn','fixture-child'


def manifest():
    return {'schemaVersion':1,'projectCode':'fixture-project','installationContextId':CONTEXT,'unitLabel':'7',
            'rootEntityUid':ROOT,'childEntityUid':CHILD,'sourceModelSha256':'a'*64,'derivedModelSha256':'b'*64,
            'bindings':[{'entityUid':uid,'componentKey':key,'geometryQuality':quality} for uid,key,quality in
                        [(CT,'CT','proxy_schematic'),(CN1,'CN1','proxy_schematic'),(CN,'CN','source_candidate')]]}


def obj(uid):
    return {'entityUid':uid,'displayName':{CHILD:'合成子设备',CN:'合成信号柜'}.get(uid,uid),
            'installationContextId':CONTEXT,'lifecycle':'active','entityRevision':'fixture-object-r1'}


def edge(child,parent):
    return {'object':obj(parent),'relation':{'childEntityUid':child,'parentEntityUid':parent,'status':'assumed'}}


class FixtureAuthority:
    username = 'fixture-admin'
    def __init__(self):
        self.calls = []
        self.context_revision = 'fixture-r1'
        self.tree_revision = 'fixture-r1'
        self.refuse = False
        self.item = None
        self.tree = None
        self.catalog_items = [obj(uid) for uid in (ROOT,CT,CN1,CN,CHILD)]

    def request(self,method,path,body=None):
        self.calls.append((method,path,copy.deepcopy(body)))
        if self.refuse:
            raise PreviewError(403,'FORBIDDEN')
        query = urllib.parse.parse_qs(urllib.parse.urlsplit(path).query)
        if path.endswith('/installations/'+CONTEXT):
            return {'item':{'installationContextId':CONTEXT,'projectCode':'fixture-project',
                            'purpose':'demonstration','engineeringUseAllowed':False,'rootEntityUid':ROOT,
                            'hierarchyRevision':self.context_revision}}
        if path.endswith('/objects/resolve'):
            uid = body['entityUids'][0]
            return {'items':[self.item or {'object':obj(uid),'resolution':'exact','canonicalEntityUid':uid}]}
        if '/ancestors?' in path:
            uid = query['entityUid'][0]
            path_items = [] if uid==ROOT else [edge(CHILD,CN),edge(CN,ROOT)] if uid==CHILD else [edge(uid,ROOT)]
            return self.tree or {'installationContextId':CONTEXT,'purpose':'demonstration','engineeringUseAllowed':False,
                                 'hierarchyRevision':self.tree_revision,'completeness':'complete','path':path_items,
                                 'resolvedAsOf':'2026-10-21T00:00:00Z'}
        if '/objects?' in path:
            return {'items':self.catalog_items,'nextCursor':None}
        raise AssertionError('Unexpected source operation')


class InstallationPreviewTests(unittest.TestCase):
    def setUp(self):
        self.authority = FixtureAuthority()
        self.preview = InstallationPreview(self.authority,manifest())

    def test_three_cabinets_resolve_directly_with_explicit_preview_quality(self):
        for uid,key,quality in ((CT,'CT','proxy_schematic'),(CN1,'CN1','proxy_schematic'),(CN,'CN','source_candidate')):
            result = self.preview.locate(uid,'7','fixture-epoch')
            self.assertEqual(result['locationMode'],'demo_direct_geometry')
            self.assertEqual(result['componentKey'],key)
            self.assertEqual(result['geometryQuality'],quality)
            self.assertTrue(result['previewOnly'])
            self.assertFalse(result['engineeringUseAllowed'])
            self.assertEqual(result['bindingStatus'],'demonstration_draft')

    def test_child_selection_is_preserved_while_ancestor_cabinet_is_located(self):
        result = self.preview.locate(CHILD,'7','fixture-epoch')
        self.assertEqual(result['selectedObjectRef']['entityUid'],CHILD)
        self.assertEqual(result['locatedObjectRef']['entityUid'],CN)
        self.assertEqual(result['locationMode'],'demo_ancestor_proxy')
        self.assertEqual(result['contextEpoch'],'fixture-epoch')
        self.assertNotIn('position',result)
        self.assertNotIn(CHILD,self.preview.bindings)

    def test_project_refusal_prevents_any_geometry_result(self):
        self.authority.refuse = True
        with self.assertRaises(PreviewError) as error:
            self.preview.locate(CHILD,'7','epoch')
        self.assertEqual(error.exception.code,'FORBIDDEN')

    def test_unknown_uid_and_other_unit_are_rejected_before_source_reads(self):
        for uid,unit,code in [('fixture-other','7','NOT_FOUND_OR_FORBIDDEN'),(CHILD,'8','INSTANCE_MISMATCH')]:
            with self.subTest(code=code),self.assertRaises(PreviewError) as error:
                self.preview.locate(uid,unit,'epoch')
            self.assertEqual(error.exception.code,code)
        self.assertEqual(self.authority.calls,[])

    def test_merged_object_keeps_original_selection_and_never_reuses_geometry(self):
        self.authority.item = {'object':obj(CHILD),'resolution':'merged','canonicalEntityUid':CN}
        result = self.preview.locate(CHILD,'7','epoch')
        self.assertEqual(result['selectedObjectRef']['entityUid'],CHILD)
        self.assertEqual(result['reasonCode'],'IDENTITY_CHANGED')
        self.assertIsNone(result['componentKey'])
        self.assertIsNone(result['locatedObjectRef'])

    def test_incomplete_path_does_not_expose_a_partial_route_or_fallback(self):
        tree = self.authority.request('GET','/ancestors?entityUid='+CHILD)
        tree.update(completeness='incomplete',reasonCode='PATH_UNAVAILABLE')
        self.authority.tree = tree
        result = self.preview.locate(CHILD,'7','epoch')
        self.assertEqual(result['locationMode'],'unlocated')
        self.assertEqual(result['path'],[])
        self.assertIsNone(result['locatedObjectRef'])

    def test_direct_binding_also_requires_a_complete_same_snapshot_tree(self):
        tree = self.authority.request('GET','/ancestors?entityUid='+CN)
        tree.update(completeness='incomplete',reasonCode='DEPTH_LIMIT')
        self.authority.tree = tree
        self.assertEqual(self.preview.locate(CN,'7','epoch')['locationMode'],'unlocated')

    def test_changed_tree_is_retried_once_then_refused(self):
        self.authority.tree_revision = 'fixture-r2'
        with self.assertRaises(PreviewError) as error:
            self.preview.locate(CHILD,'7','epoch')
        self.assertEqual(error.exception.code,'REVISION_CONFLICT')
        self.assertEqual(sum('/ancestors?' in path for _,path,_ in self.authority.calls),2)

    def test_root_without_geometry_is_unlocated(self):
        result = self.preview.locate(ROOT,'7','epoch')
        self.assertEqual(result['reasonCode'],'NO_GEOMETRY')
        self.assertEqual(result['path'],[])

    def test_cross_context_or_unreviewed_path_is_rejected(self):
        for change in ('scope','status','child','root'):
            tree = self.authority.request('GET','/ancestors?entityUid='+CHILD)
            if change=='scope': tree['path'][0]['object']['installationContextId']='fixture-other-context'
            if change=='status': tree['path'][0]['relation']['status']='candidate'
            if change=='child': tree['path'][0]['relation']['childEntityUid']='fixture-other-child'
            if change=='root': tree['path']=tree['path'][:1]
            self.authority.tree=tree
            with self.subTest(change=change),self.assertRaises(PreviewError) as error:
                self.preview.locate(CHILD,'7','epoch')
            self.assertEqual(error.exception.code,'INVALID_HIERARCHY')

    def test_catalog_is_limited_to_reviewed_roles_and_cannot_silently_truncate(self):
        result = self.preview.catalog()
        self.assertEqual(len(result['items']),5)
        self.authority.catalog_items.pop()
        with self.assertRaises(PreviewError) as error:
            self.preview.catalog()
        self.assertEqual(error.exception.code,'PREVIEW_INPUT_CHANGED')

    def test_authority_rejects_public_urls_credentials_redirect_prefixes_and_path(self):
        for url in ('https://example.com','http://192.168.2.153:18001','http://127.0.0.1:80/path',
                    'http://user:password@127.0.0.1:80','http://127.0.0.1:80?source=other'):
            with self.subTest(url=url),self.assertRaises(ValueError): Authority(url)

    def test_manifest_binds_actual_source_and_derived_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            models=root/'assets/models'
            models.mkdir(parents=True)
            (models/'tu3000-geared-original.glb').write_bytes(b'fixture-source')
            (models/'tu3000-geared-merged.glb').write_bytes(b'fixture-derived')
            value=manifest()
            value.update(sourceModelSha256=hashlib.sha256(b'fixture-source').hexdigest(),derivedModelSha256=hashlib.sha256(b'fixture-derived').hexdigest())
            path=root/'manifest.json'
            path.write_text(json.dumps(value))
            self.assertEqual(load_manifest(path,root),value)
            (models/'tu3000-geared-merged.glb').write_bytes(b'changed')
            with self.assertRaises(ValueError): load_manifest(path,root)

    def test_http_surface_is_read_only_origin_bound_and_no_store(self):
        with tempfile.TemporaryDirectory() as directory:
            server=ThreadingHTTPServer(('127.0.0.1',0),None)
            server.RequestHandlerClass=handler_type(self.preview,Path(directory),server.server_port)
            thread=Thread(target=server.serve_forever,daemon=True)
            thread.start()
            opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
            base=f'http://127.0.0.1:{server.server_port}'
            try:
                with opener.open(base+'/api/demo/context') as response:
                    self.assertEqual(response.headers['Cache-Control'],'no-store')
                    self.assertEqual(len(json.load(response)['items']),5)
                for headers,status in (({'Origin':'https://foreign.example'},403),({'Host':'foreign.example'},403),({'Sec-Fetch-Site':'cross-site'},403)):
                    with self.subTest(headers=headers),self.assertRaises(urllib.error.HTTPError) as error:
                        opener.open(urllib.request.Request(base+'/api/demo/context',headers=headers))
                    self.assertEqual(error.exception.code,status)
                    error.exception.close()
                with self.assertRaises(urllib.error.HTTPError) as error:
                    opener.open(urllib.request.Request(base+'/api/demo/context',data=b'{}',method='POST'))
                self.assertEqual(error.exception.code,405)
                error.exception.close()
                with self.assertRaises(urllib.error.HTTPError) as error:
                    opener.open(base+'/api/demo/context?projectCode=foreign')
                self.assertEqual(error.exception.code,404)
                error.exception.close()
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=2)


if __name__=='__main__':
    unittest.main()
