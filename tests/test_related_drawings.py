"""Parent-bound aggregate drawing reads; all authorities are synthetic."""
import copy
import hashlib
import unittest
from apps.api.related_drawings import RelatedDrawingsReader
from apps.api.scene_engineering import SceneEngineeringReader
from tests import test_scene_engineering as objects
from tests import test_scene_evidence as evidence
EvidenceAuthority=evidence.EvidenceAuthority
PNG=evidence.PNG

class RelatedAuthority(EvidenceAuthority):
 def request(self,method,path,body=None):
  if not path.endswith('/object-evidence/related'):return super().request(method,path,body)
  self.calls.append((method,path,copy.deepcopy(body)));self.selection(body)
  match={'entityUid':'registered-child','entityRevision':'child:r1','displayName':'合成柜内温度传感器','relation':'definition_descendant','viaEntityUid':body['entityUid'],'viaName':'合成机舱动力柜'}
  if not body['includeDescendants']:match.update(entityUid=body['entityUid'],entityRevision=body['expectedEntityRevision'],relation='self')
  row={'drawingUid':'drawing-1','title':'合成接线图','drawingNumber':'DWG-01','pageNumber':6,'sourceRevision':'a'*64,'contentSha256':hashlib.sha256(self.pdf).hexdigest(),'availability':'available','matchedObjects':[match],'precision':'page','region':None,'privateServerPath':'/private/not-public'}
  value={**{key:body[key] for key in ('entityUid','installationContextId','includeDescendants')},'entityRevision':body['expectedEntityRevision'],'hierarchyRevision':body['expectedHierarchyRevision'],'items':[row],'total':4,'nextCursor':'synthetic-next','snapshotRevision':'c'*64,'scopeComplete':True}
  if self.metadata_edit:self.metadata_edit(value)
  if self.evidence_after:self.evidence_after(self)
  return value
 def image(self,path,body):
  if not path.endswith('/object-evidence/related/content'):return super().image(path,body)
  self.calls.append(('POST',path,copy.deepcopy(body)));self.selection(body)
  if self.image_after:self.image_after(self)
  return PNG

class RelatedDrawingsTests(unittest.TestCase):
 selection=evidence.SceneEvidenceTests.selection
 expect=evidence.SceneEvidenceTests.expect
 def setUp(self):
  self.authority=RelatedAuthority();self.engineering=SceneEngineeringReader(self.authority,objects.CONNECTION,objects.PROJECT,self.authority.guard);self.reader=RelatedDrawingsReader(self.engineering)
 def body(self,**fields):return {**self.selection(),'includeDescendants':True,'limit':3,**fields}
 def content(self):
  body=self.body();row=self.reader.resolve(body)['items'][0]
  return {**self.selection(),'includeDescendants':True,'drawingUid':row['drawingUid'],'expectedSourceRevision':row['sourceRevision'],'expectedContentSha256':row['contentSha256']}
 def test_parent_selection_pagination_and_member_provenance_are_preserved(self):
  body=self.body(cursor='source-cursor');value=self.reader.resolve(body)
  self.assertEqual(value['total'],4);self.assertEqual(value['nextCursor'],'synthetic-next')
  self.assertEqual(value['items'][0]['matchedObjects'][0]['relation'],'definition_descendant')
  call=next(call for call in self.authority.calls if call[1].endswith('/object-evidence/related'))
  self.assertEqual(call[2],body);self.assertNotIn('privateServerPath',str(value))
 def test_only_object_is_explicit_and_descendant_response_is_rejected(self):
  self.assertEqual(self.reader.resolve(self.body(includeDescendants=False))['items'][0]['matchedObjects'][0]['relation'],'self')
  self.authority.metadata_edit=lambda v:v['items'][0]['matchedObjects'][0].update(relation='definition_descendant')
  self.expect('SOURCE_UNAVAILABLE',lambda:self.reader.resolve(self.body(includeDescendants=False)),502)
 def test_malformed_client_scope_or_external_locations_never_reach_source(self):
  for fields in ({'includeDescendants':1},{'limit':True},{'limit':21},{'cursor':''},{'childEntityUids':['arbitrary']},{'url':'https://arbitrary.invalid'}):
   self.expect('INVALID_REQUEST',lambda:self.reader.resolve(self.body(**fields)),422)
  self.assertEqual(self.authority.calls,[])
 def test_wrong_parent_or_incomplete_scope_cannot_masquerade_as_empty(self):
  for change,code in (({'entityUid':'other'},'ENGINEERING_CHANGED'),({'includeDescendants':False},'ENGINEERING_CHANGED'),({'scopeComplete':False},'SOURCE_UNAVAILABLE')):
   self.authority.metadata_edit=lambda v:v.update(change)
   self.expect(code,lambda:self.reader.resolve(self.body()))
 def test_duplicate_drawings_or_missing_match_and_tokens_are_rejected(self):
  edits=[lambda v:v['items'].append(copy.deepcopy(v['items'][0])),lambda v:v['items'][0].update(matchedObjects=[]),lambda v:v['items'][0].update(sourceRevision='old'),lambda v:v['items'][0]['matchedObjects'].append(copy.deepcopy(v['items'][0]['matchedObjects'][0]))]
  for edit in edits:
   self.authority.metadata_edit=edit;self.expect('SOURCE_UNAVAILABLE',lambda:self.reader.resolve(self.body()))
 def test_authorized_preview_keeps_parent_scope_and_group_tokens(self):
  body=self.content();value=self.reader.content(body)
  self.assertEqual(value['content'],PNG)
  call=next(c for c in self.authority.calls if c[1].endswith('/related/content'))
  self.assertEqual(call[2],{**body,'representation':'image'})
 def test_revocation_and_late_parent_change_return_no_preview(self):
  body=self.content();self.authority.image_after=lambda a:a.objects[objects.CHILD].update(entityRevision='changed')
  self.expect('ENGINEERING_CHANGED',lambda:self.reader.content(body),409)
 def test_missing_content_or_user_asserted_paths_are_rejected(self):
  body=self.content()
  for fields in ({'expectedSourceRevision':'wrong'},{'expectedContentSha256':None},{'representation':'pdf'}):
   self.expect('INVALID_REQUEST',lambda:self.reader.content({**body,**fields}),422)
