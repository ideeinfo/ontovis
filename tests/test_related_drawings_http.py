"""Related drawings use the authenticated HTTP boundary, with no business writes."""
from http.server import ThreadingHTTPServer
from threading import Thread
import unittest
from apps.api.session_http import handler_type
from apps.api.workbench_server import WorkbenchSessions
from tests import test_scene_engineering as objects,test_scene_engineering_http as object_http,test_scene_evidence_http as original
from tests.test_related_drawings import RelatedAuthority

class RelatedHttpAuthority(original.EvidenceHttpAuthority):
 def __init__(self,base):super().__init__(base);self.engineering=RelatedAuthority()

class RelatedDrawingsHttpTests(unittest.TestCase):
 request=original.SceneEvidenceHttpTests.request
 login=original.SceneEvidenceHttpTests.login
 account=original.SceneEvidenceHttpTests.account
 expect=original.SceneEvidenceHttpTests.expect
 selection=original.SceneEvidenceHttpTests.selection
 def setUp(self):
  self.sessions=WorkbenchSessions('http://127.0.0.1:1234',objects.PROJECT,objects.CTX,factory=RelatedHttpAuthority,ontobase_connection_id=objects.CONNECTION)
  self.server=ThreadingHTTPServer(('127.0.0.1',0),handler_type(self.sessions,object_http.scene_http.ORIGIN,development=True));self.thread=Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
  self.addCleanup(self.server.server_close);self.addCleanup(self.thread.join);self.addCleanup(self.server.shutdown);self.admin=self.login('synthetic-admin')
 def body(self):return {**self.selection(),'includeDescendants':True,'limit':2}
 def test_related_page_and_preview_keep_parent_scope_without_exposing_storage(self):
  status,value,headers=self.request(original.ROOT+'related',self.body());self.assertEqual(status,200,value);self.assertEqual(value['total'],4);self.assertEqual(headers['Cache-Control'],'no-store');self.assertNotIn('/private/',str(value))
  row=value['items'][0];body={**self.selection(),'includeDescendants':True,'drawingUid':row['drawingUid'],'expectedSourceRevision':row['sourceRevision'],'expectedContentSha256':row['contentSha256']}
  status,data,headers=self.request(original.ROOT+'related/content',body);self.assertEqual(status,200,data);self.assertTrue(data.startswith(b'\x89PNG'));self.assertEqual(headers['Content-Type'],'image/png');self.assertEqual(headers['Cache-Control'],'no-store')
 def test_anonymous_and_user_asserted_descendants_are_rejected(self):
  self.expect(self.request(original.ROOT+'related',self.body(),client=False),401,'SESSION_EXPIRED')
  self.expect(self.request(original.ROOT+'related',{**self.body(),'childEntityUids':['arbitrary']}),422,'INVALID_REQUEST')
 def test_late_revoked_project_access_discards_related_page(self):
  account=self.account();account.engineering.evidence_after=lambda *_:setattr(account,'allowed',False)
  self.expect(self.request(original.ROOT+'related',self.body()),403,'FORBIDDEN')
 def test_legacy_direct_evidence_remains_readable(self):
  self.assertEqual(self.request(original.ROOT+'resolve',self.selection())[0],200)
