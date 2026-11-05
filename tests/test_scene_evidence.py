"""Synthetic current-drawing boundary tests; no OntoBase or storage access."""
import base64
import copy
from email.message import Message
import hashlib
import io
from threading import Event,Thread
import unittest
from urllib.parse import urlsplit

from apps.api.authority import Authority,PreviewError
from apps.api.scene_engineering import SceneEngineeringReader
from apps.api.scene_evidence import SceneEvidenceReader
from tests import test_scene_engineering as engineering

OTHER_CHILD='synthetic-device-B/child'
PNG=base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jRZkAAAAASUVORK5CYII=')
PDF=b'%PDF-synthetic-current-content-not-a-real-document'


class EvidenceAuthority(engineering.SyntheticAuthority):
    def __init__(self):
        super().__init__()
        self.objects[OTHER_CHILD]=self.object(OTHER_CHILD,engineering.OTHER_CTX)
        self.parents[OTHER_CHILD]=engineering.OTHER_ROOT
        self.relations[OTHER_CHILD,engineering.OTHER_ROOT]=self.relation(OTHER_CHILD,engineering.OTHER_ROOT)
        self.source_revision='a'*64;self.pdf=PDF;self.missing=False;self.metadata_edit=None
        self.evidence_after=None;self.image_started=None;self.image_gate=None;self.image_after=None
        self.template_objects={engineering.CHILD,OTHER_CHILD}

    def selection(self,body):
        self.guard();uid=body['entityUid'];item=self.objects.get(uid)
        if not item or item['installationContextId']!=body['installationContextId']:
            raise PreviewError(403,'NOT_FOUND_OR_FORBIDDEN')
        if item['entityRevision']!=body['expectedEntityRevision']:raise PreviewError(409,'REVISION_CONFLICT')
        context=self.contexts.get(body['installationContextId'])
        if context and context['hierarchyRevision']!=body['expectedHierarchyRevision']:raise PreviewError(409,'REVISION_CONFLICT')
        return item

    def metadata(self,body):
        item=self.selection(body);template=item['entityUid'] in self.template_objects
        return {'evidenceRef':'evidence:'+item['entityUid'],'sourceRelation':'template_definition' if template else 'direct',
            'sourceEntityUid':item['sourceTemplateEntityUid'] if template else item['entityUid'],
            'sourceEntityRevision':'synthetic-template:3' if template else item['entityRevision'],
            'sourceTemplateRevision':'synthetic-template:3' if template else None,
            'sourceRevision':self.source_revision,'recordDigest':'b'*64,
            'contentSha256':None if self.missing else hashlib.sha256(self.pdf).hexdigest(),
            'title':'Synthetic current drawing','pageNumber':8,'availability':'missing' if self.missing else 'available',
            'versionMode':'current_content_snapshot','precision':'page','region':None,'mediaType':'application/pdf',
            'privateServerPath':'/private/not-public','url':'https://not-a-source.invalid'}

    def request(self,method,path,body=None):
        if not path.endswith('/object-evidence/resolve'):return super().request(method,path,body)
        self.calls.append((method,path,copy.deepcopy(body)))
        assert method=='POST' and set(body)=={'entityUid','installationContextId','expectedEntityRevision','expectedHierarchyRevision'}
        row=self.metadata(body)
        value={'entityUid':body['entityUid'],'entityRevision':body['expectedEntityRevision'],
            'installationContextId':body['installationContextId'],'hierarchyRevision':body['expectedHierarchyRevision'],
            'items':[row],'complete':True,'versionMode':'current_content_snapshot'}
        if self.metadata_edit:self.metadata_edit(value)
        if self.evidence_after:self.evidence_after(self)
        return value

    def image(self,path,body):
        self.calls.append(('POST',path,copy.deepcopy(body)))
        assert path.endswith('/object-evidence/content') and body['representation']=='image'
        assert set(body)=={'entityUid','installationContextId','expectedEntityRevision','expectedHierarchyRevision',
                           'evidenceRef','expectedSourceRevision','expectedContentSha256','representation'}
        row=self.metadata(body)
        if body['evidenceRef']!=row['evidenceRef']:raise PreviewError(404,'SOURCE_MISSING')
        if body['expectedSourceRevision']!=row['sourceRevision']:raise PreviewError(409,'SOURCE_CHANGED')
        if self.missing:raise PreviewError(404,'SOURCE_MISSING')
        if body['expectedContentSha256']!=row['contentSha256']:raise PreviewError(409,'CONTENT_CHANGED')
        if self.image_started:self.image_started.set()
        if self.image_gate:self.image_gate.wait(3)
        if self.image_after:self.image_after(self)
        return PNG


class SceneEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.authority=EvidenceAuthority()
        self.engineering=SceneEngineeringReader(self.authority,engineering.CONNECTION,engineering.PROJECT,self.authority.guard)
        self.reader=SceneEvidenceReader(self.engineering)

    def selection(self,uid=engineering.CHILD):
        item=self.authority.objects[uid];context=item['installationContextId']
        return {'entityUid':uid,'installationContextId':context,'expectedEntityRevision':item['entityRevision'],
                'expectedHierarchyRevision':None if context is None else self.authority.contexts[context]['hierarchyRevision']}

    def content_selection(self,uid=engineering.CHILD):
        selected=self.selection(uid);metadata=self.authority.metadata(selected)
        return {**selected,'evidenceRef':metadata['evidenceRef'],'expectedSourceRevision':metadata['sourceRevision'],
                'expectedContentSha256':metadata['contentSha256']}

    def expect(self,code,call,status=None):
        with self.assertRaises(PreviewError) as caught:call()
        self.assertEqual(caught.exception.code,code)
        if status is not None:self.assertEqual(caught.exception.status,status)

    def evidence_calls(self):
        return [call for call in self.authority.calls if '/object-evidence/' in call[1]]

    def test_children_in_two_explicit_contexts_keep_their_own_source_selection(self):
        for uid,context in ((engineering.CHILD,engineering.CTX),(OTHER_CHILD,engineering.OTHER_CTX)):
            result=self.reader.resolve(self.selection(uid));call=self.evidence_calls()[-1]
            self.assertEqual(call[2]['entityUid'],uid);self.assertEqual(call[2]['installationContextId'],context)
            self.assertEqual(result['items'][0]['sourceRelation'],'template_definition')
            self.assertEqual(result['items'][0]['sourceEntityUid'],'synthetic-shared-definition')
            self.assertIn('/synthetic%20project%2F1/object-evidence/',call[1])
        self.assertNotEqual(self.evidence_calls()[0][2],self.evidence_calls()[1][2])

    def test_context_null_definition_and_unclassified_objects_read_their_own_drawings(self):
        for uid in ('definition','unclassified'):
            self.authority.calls.clear();result=self.reader.resolve(self.selection(uid))
            self.assertEqual(result['items'][0]['sourceEntityUid'],uid)
            self.assertEqual(result['items'][0]['sourceRelation'],'direct')
            self.assertIsNone(self.evidence_calls()[0][2]['installationContextId'])
            self.assertIsNone(self.evidence_calls()[0][2]['expectedHierarchyRevision'])
            self.assertFalse(any('/installations/' in path for _,path,_ in self.authority.calls))

    def test_incomplete_or_invalid_chain_does_not_block_selected_objects_own_source(self):
        for invalid in (False,True):
            def edit(value):
                value.update(completeness='incomplete',reasonCode='PATH_UNAVAILABLE')
                if invalid:value['path'][0]['relation']['parentEntityUid']='invalid-synthetic-parent'
                else:value['path']=[]
            self.authority.ancestor_edit=edit
            result=self.reader.resolve(self.selection())
            self.assertEqual(result['items'][0]['sourceRelation'],'template_definition')
            self.assertEqual(self.evidence_calls()[-1][2]['entityUid'],engineering.CHILD)
            content=self.reader.content(self.content_selection())
            self.assertEqual(content['content'],PNG)

    def test_no_model_geometry_or_ancestor_host_is_required_or_accepted(self):
        result=self.reader.resolve(self.selection())
        self.assertEqual(len(result['items']),1)
        for field in ({'hostEntityUid':engineering.CABINET},{'modelVersionId':'synthetic-model'},
                      {'url':'https://not-permitted.invalid'},{'projectCode':'other-project'}):
            before=len(self.authority.calls)
            self.expect('INVALID_REQUEST',lambda:self.reader.resolve({**self.selection(),**field}),422)
            self.assertEqual(len(self.authority.calls),before)

    def test_wrong_context_and_stale_object_or_hierarchy_never_fetch_evidence(self):
        selected=self.selection()
        cases=[({**selected,'installationContextId':engineering.OTHER_CTX,'expectedHierarchyRevision':engineering.OTHER_CTX+':7'},'NOT_FOUND_OR_FORBIDDEN'),
               ({**selected,'expectedEntityRevision':'old-object'},'ENGINEERING_CHANGED'),
               ({**selected,'expectedHierarchyRevision':'old-hierarchy'},'ENGINEERING_CHANGED')]
        for body,code in cases:
            self.expect(code,lambda:self.reader.resolve(body));self.assertEqual(self.evidence_calls(),[])

    def test_context_revision_pair_and_content_conditions_are_strict(self):
        for body in ({**self.selection(),'expectedHierarchyRevision':None},
                     {**self.selection('definition'),'expectedHierarchyRevision':'unexpected'},
                     {**self.selection(),'installationContextId':'other'},
                     {**self.selection(),'expectedEntityRevision':None}):
            self.expect('INVALID_REQUEST',lambda:self.reader.resolve(body),422)
        for extra in ({'representation':'pdf'},{'expectedContentSha256':'not-a-digest'},{'evidenceRef':''}):
            self.expect('INVALID_REQUEST',lambda:self.reader.content({**self.content_selection(),**extra}),422)

    def test_metadata_is_small_current_page_only_and_removes_private_fields(self):
        self.authority.metadata_edit=lambda value:value['items'][0].update(title='合成图纸\n接线说明\t第八页')
        result=self.reader.resolve(self.selection());row=result['items'][0]
        self.assertEqual(set(result),{'items','complete'})
        self.assertEqual(row['versionMode'],'current_content_snapshot');self.assertEqual(row['precision'],'page')
        self.assertIsNone(row['region']);self.assertNotIn('url',row);self.assertNotIn('privateServerPath',row)
        self.assertEqual(row['sourceTemplateRevision'],row['sourceEntityRevision'])
        self.assertEqual(row['title'],'合成图纸\n接线说明\t第八页')

    def test_list_limits_duplicate_references_and_incomplete_responses_are_not_silent(self):
        self.authority.metadata_edit=lambda value:value.update(items=[copy.deepcopy(value['items'][0]) for _ in range(21)])
        self.expect('EVIDENCE_SCOPE_LIMIT',lambda:self.reader.resolve(self.selection()),413)
        self.authority.metadata_edit=lambda value:value['items'].append(copy.deepcopy(value['items'][0]))
        self.expect('SOURCE_UNAVAILABLE',lambda:self.reader.resolve(self.selection()),502)
        self.authority.metadata_edit=lambda value:value.update(complete=False)
        self.expect('SOURCE_UNAVAILABLE',lambda:self.reader.resolve(self.selection()),502)

    def test_empty_and_missing_source_remain_distinct(self):
        self.authority.metadata_edit=lambda value:value.update(items=[])
        self.assertEqual(self.reader.resolve(self.selection()),{'items':[],'complete':True})
        self.authority.metadata_edit=None;self.authority.missing=True
        value=self.reader.resolve(self.selection())['items'][0]
        self.assertEqual(value['availability'],'missing');self.assertIsNone(value['contentSha256'])
        body=self.content_selection();body['expectedContentSha256']=hashlib.sha256(PDF).hexdigest()
        self.expect('SOURCE_MISSING',lambda:self.reader.content(body),404)

    def test_source_metadata_cannot_substitute_a_spatial_ancestor_or_unfixed_definition(self):
        self.authority.metadata_edit=lambda value:value['items'][0].update(sourceRelation='direct',sourceEntityUid=engineering.CABINET,
            sourceEntityRevision=self.authority.objects[engineering.CABINET]['entityRevision'],sourceTemplateRevision=None)
        self.expect('SOURCE_CHANGED',lambda:self.reader.resolve(self.selection()),409)
        self.authority.metadata_edit=lambda value:value['items'][0].update(sourceTemplateRevision='old-template')
        self.expect('SOURCE_DEFINITION_CHANGED',lambda:self.reader.resolve(self.selection()),409)
        self.authority.metadata_edit=lambda value:value.update(entityUid=engineering.ROOT)
        self.expect('ENGINEERING_CHANGED',lambda:self.reader.resolve(self.selection()),409)

    def test_content_keeps_pdf_and_png_digests_separate_and_never_rehashes_the_whole_list(self):
        body=self.content_selection();before=copy.deepcopy(body);value=self.reader.content(body)
        self.assertEqual(value,{'content':PNG,'mediaType':'image/png','sourceContentSha256':hashlib.sha256(PDF).hexdigest(),
                               'imageSha256':hashlib.sha256(PNG).hexdigest()})
        self.assertEqual(body,before);self.assertEqual(len(self.evidence_calls()),1)
        self.assertTrue(self.evidence_calls()[0][1].endswith('/content'))
        self.assertEqual(self.evidence_calls()[0][2]['entityUid'],engineering.CHILD)
        self.assertEqual(self.evidence_calls()[0][2]['representation'],'image')

    def test_old_source_and_changed_pdf_content_are_refused_by_existing_fixed_endpoint(self):
        old=self.content_selection();self.authority.source_revision='c'*64
        self.expect('SOURCE_CHANGED',lambda:self.reader.content(old),409)
        old=self.content_selection();self.authority.pdf=PDF+b'changed'
        self.expect('CONTENT_CHANGED',lambda:self.reader.content(old),409)

    def test_read_after_revoke_during_image_discards_bytes(self):
        self.authority.image_started=Event();self.authority.image_gate=Event();result=[]
        body=self.content_selection()
        def read():
            try:result.append(self.reader.content(body))
            except PreviewError as error:result.append(error.code)
        thread=Thread(target=read);thread.start();self.assertTrue(self.authority.image_started.wait(2))
        self.authority.allowed=False;self.authority.image_gate.set();thread.join(3)
        self.assertFalse(thread.is_alive());self.assertEqual(result,['FORBIDDEN'])

    def test_late_object_or_hierarchy_changes_refuse_metadata_and_image(self):
        self.authority.evidence_after=lambda source:source.objects[engineering.CHILD].update(entityRevision='changed:2')
        self.expect('ENGINEERING_CHANGED',lambda:self.reader.resolve(self.selection()),409)
        self.authority.evidence_after=None;body=self.content_selection()
        self.authority.image_after=lambda source:source.contexts[engineering.CTX].update(hierarchyRevision=engineering.CTX+':8')
        self.expect('ENGINEERING_CHANGED',lambda:self.reader.content(body),409)

    def test_project_authorization_revision_change_discards_late_bytes(self):
        changed=False
        def guard():
            self.authority.guard()
            if changed:raise PreviewError(409,'ACCESS_CHANGED')
        def after(_source):
            nonlocal changed
            changed=True
        self.engineering.authorize=guard;self.authority.image_after=after
        self.expect('ACCESS_CHANGED',lambda:self.reader.content(self.content_selection()),409)

    def test_invalid_or_oversized_image_does_not_return_content(self):
        for value in (b'not-png',b'\x89PNG\r\n\x1a\n'+bytes(20*1024*1024)):
            self.authority.image=lambda _path,_body:value
            self.expect('SOURCE_UNAVAILABLE',lambda:self.reader.content(self.content_selection()),502)

    def test_real_authority_image_transport_requires_matching_source_digest_header(self):
        transport=Authority('http://127.0.0.1:1234');transport.token='synthetic-transport-token'
        seen=[]
        class Response(io.BytesIO):
            headers=Message()
        Response.headers['Content-Type']='image/png';Response.headers['X-Source-Content-SHA256']='d'*64
        class Opener:
            def open(_self,request,timeout):
                seen.append((urlsplit(request.full_url),timeout));return Response(PNG)
        transport.opener=Opener();self.authority.image=transport.image
        self.expect('SOURCE_UNAVAILABLE',lambda:self.reader.content(self.content_selection()),502)
        self.assertEqual(seen[0][0].hostname,'127.0.0.1');self.assertEqual(seen[0][1],30)


if __name__=='__main__':unittest.main()
