from copy import deepcopy
from io import BytesIO
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock, patch
from urllib.parse import urlsplit, parse_qs
from uuid import uuid4
import hashlib
import json
import sqlite3

from apps.api.authority import PreviewError
from apps.api.analysis_evidence import validate_descriptor
from apps.api.analysis_preview import drawing_preview, drawing_bytes, document_preview, fault_documents, relationships, preview
from apps.api import analysis_media


class SourceViewerTests(TestCase):
    def setUp(self):
        self.sha='a'*64
        self.drawing={'drawingUid':'project:drawing-1','expectedContentSha256':self.sha}
        self.document={'documentId':str(uuid4()),'contentVersionId':str(uuid4()),'sourceSha256':self.sha,'pageNumber':48,
                       'knowledgeReleaseId':str(uuid4()),'knowledgeNodeId':'fault-13001'}
        self.location={'id':'region','project_code':'P','drawing_uid':'project:drawing-1','entity_uid':'sensor',
            'row_version':2,'entity_properties':{'result_import':{'drawing_revision':self.sha}},
            'bbox':{'x':.2,'y':.3,'width':.1,'height':.1},'display_name':'Temperature sensor'}
        self.location.update(object_type='unknown',text_span={'source_instance_id':'instance-1'})
        self.location['entity_properties']['result_import']['classification']={'standard':{'code':'BTA','revision_id':'catalogue-v1','name_zh':'温度变送器','name_en':'Temperature transmitter','review_state':'unreviewed'}}
        self.extra_locations=[];self.owner_resolution='resolved'
        self.wrapper=SimpleNamespace(project_code='P',connection_id='source',prefix='/api/v1/projects/P',
                                    _request=Mock(side_effect=self.request),authority=SimpleNamespace(source_bytes=Mock(return_value={'content':b'pdf','sha256':self.sha})))
        self.reader=SimpleNamespace(reader=self.wrapper,read=Mock(return_value={}),authorize=Mock())
        self.current=True;self.published=True;self.project='P';self.mapping=True
        self.graph_nodes=[{'local_id':'fault-13001','kind':'FaultDefinition','payload':{'properties':{
            'urn:ontobase:document-knowledge:1:title':[{'value':'Cabinet temperature high'}],
            'urn:ontobase:document-knowledge:1:fault_code':[{'value':'13001'}]}}}]

    def request(self,method,path,*args):
        self.assertEqual(method,'GET')
        url=urlsplit(path);q=parse_qs(url.query)
        if url.path.endswith('/document-knowledge/graph'):
            node=deepcopy(self.graph_nodes[0]);node['source']={'document':{'id':self.document['documentId'],'name':'Fault manual'},
                'version':{'id':self.document['contentVersionId']},'release_id':self.document['knowledgeReleaseId'],'local_id':node['local_id']}
            return {'nodes':[node]}
        if '/versions/' in path:return {'item':{'id':self.document['contentVersionId'],'source_sha256':self.sha}}
        if url.path.endswith('/evidence'):return {'document_id':self.document['documentId'],'content_version_id':self.document['contentVersionId'],
            'items':[{'local_id':'ev','raw_text':'13001: temperature above threshold','selector':{'page':48,'bbox':self.location['bbox'],'rendition_id':'page48'}}]}
        if url.path.endswith('/graph'):return {'document_id':self.document['documentId'],'content_version_id':self.document['contentVersionId'],
            'state':'published' if self.published else 'withdrawn','available_for_analysis':self.published,'nodes':self.graph_nodes,'relations':[],
            'next_cursor':100 if q.get('cursor')==['0'] else None,'scope':{}}
        if '/knowledge/releases/' in path:return {'item':{'payload':{'mappings':[{'state':'confirmed','local_id':'fault-13001','target':{'kind':'formal','id':'region','row_version':2}}] if self.mapping else []}}}
        if url.path.endswith('/knowledge/releases'):
            self.assertEqual(q['version_id'],[self.document['contentVersionId']])
            return {'items':[{'id':self.document['knowledgeReleaseId'],'content_version_id':self.document['contentVersionId'],'state':'published'}]}
        if '/object-locations/' in path:return {**deepcopy(self.location),'project_code':self.project}
        if url.path.endswith('/object-locations'):return {'items':[self.location,*self.extra_locations]}
        if url.path.endswith('/result-relation-imports'):return {'items':[{'id':'batch'}]}
        if url.path.endswith('/records'):
            kind=q['kind'][0]
            row={'source_reference_id':'cross-page','target_label':'/22.4','normalized_bbox':self.location['bbox'],
                'target':{'status':'bound','drawing_uid':'project:next','drawing_revision':self.sha,'drawing_name':'Next drawing','basis':'printed page reference'},'relationship_semantics':'document_reference'}
            if kind=='ports':row={'source_port_id':'P1','source_instance_id':'instance-1','owner_resolution':{'state':self.owner_resolution},'position':{'state':'located','normalized':{'x':.4,'y':.5}},'label':'1'}
            return {'source_state':'current' if self.current else 'stale','drawing_revision':self.sha,'next_after':None,'items':[{'document':row}]}
        if '/drawings/' in path:return {'drawing_uid':'project:drawing-1','project_code':self.project,'drawing_name':'Source drawing'}
        raise AssertionError(path)

    def test_drawing_objects_and_ports_locate_only_on_the_fixed_revision(self):
        result=drawing_preview(self.reader,self.drawing,{})
        self.assertEqual(result['objects'][0]['bbox'],self.location['bbox'])
        self.assertIsNotNone(drawing_preview(self.reader,self.drawing,{'section':'ports'})['ports'][0]['bbox'])
        self.location['entity_properties']['result_import']['drawing_revision']='b'*64
        self.assertIsNone(drawing_preview(self.reader,self.drawing,{})['objects'][0]['bbox'])
        self.current=False
        self.assertIsNone(drawing_preview(self.reader,self.drawing,{'section':'ports'})['ports'][0]['bbox'])

    def test_cross_page_reference_is_document_reference_not_electrical_connectivity(self):
        row=drawing_preview(self.reader,self.drawing,{'section':'references'})['references'][0]
        self.assertEqual(row['semantics'],'document_reference');self.assertEqual(row['selector']['drawingUid'],'project:next')
        self.current=False;row=drawing_preview(self.reader,self.drawing,{'section':'references'})['references'][0]
        self.assertNotIn('selector',row);self.assertIsNone(row['bbox'])

    def test_object_and_port_groups_preserve_the_source_standard_and_owner_identity(self):
        obj=drawing_preview(self.reader,self.drawing,{})['objects'][0]
        port=drawing_preview(self.reader,self.drawing,{'section':'ports'})['ports'][0]
        self.assertEqual(obj['objectType'],'unknown')
        self.assertEqual(obj['classification']['code'],'BTA')
        self.assertEqual(obj['classification']['reviewState'],'unreviewed')
        self.assertEqual(port['classification'],obj['classification'])
        self.assertEqual(port['ownerId'],'instance-1')
        self.assertEqual(port['owner'],'Temperature sensor')

    def test_stale_unresolved_or_ambiguous_ports_do_not_borrow_current_object_types(self):
        self.current=False
        self.assertIsNone(drawing_preview(self.reader,self.drawing,{'section':'ports'})['ports'][0]['classification'])
        self.current=True;self.owner_resolution='unresolved'
        self.assertIsNone(drawing_preview(self.reader,self.drawing,{'section':'ports'})['ports'][0]['classification'])
        self.owner_resolution='resolved';other=deepcopy(self.location);other['id']='another-location';self.extra_locations=[other]
        port=drawing_preview(self.reader,self.drawing,{'section':'ports'})['ports'][0]
        self.assertIsNone(port['classification']);self.assertEqual(port['owner'],'instance-1')

    def test_generic_type_without_standard_stays_available_for_grouping(self):
        self.location['entity_properties']['result_import'].pop('classification');self.location['object_type']='terminal'
        self.assertEqual(drawing_preview(self.reader,self.drawing,{})['objects'][0]['objectType'],'terminal')
        port=drawing_preview(self.reader,self.drawing,{'section':'ports'})['ports'][0]
        self.assertEqual(port['objectType'],'terminal');self.assertIsNone(port['classification'])
        self.location['entity_properties']['result_import']['classification']=None
        self.assertIsNone(drawing_preview(self.reader,self.drawing,{})['objects'][0]['classification'])

    def test_referenced_pdf_cannot_change_or_cross_project(self):
        self.assertEqual(drawing_bytes(self.reader,self.drawing)['content'],b'pdf')
        self.wrapper.authority.source_bytes.return_value['sha256']='b'*64
        with self.assertRaises(PreviewError) as error:drawing_bytes(self.reader,self.drawing)
        self.assertEqual(error.exception.status,409)
        self.project='OTHER'
        with self.assertRaises(PreviewError):drawing_bytes(self.reader,self.drawing)

    def test_manual_discovery_uses_exact_published_code_and_evidence_page(self):
        rows=fault_documents(self.reader,'13001');self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]['selector'],self.document)
        self.assertEqual(fault_documents(self.reader,'130010'),[])

    def test_document_graph_preserves_version_page_and_current_mapping(self):
        result=document_preview(self.reader,self.document,{'cursor':0})
        self.assertEqual(result['focusId'],'fault-13001');self.assertEqual(result['evidence'][0]['page'],48)
        self.assertEqual(result['objectMappings'][0]['entityUid'],'sensor');self.assertEqual(result['nextCursor'],100)
        self.location['row_version']=3
        self.assertEqual(document_preview(self.reader,self.document,{})['objectMappings'],[])
        self.project='OTHER';self.location['row_version']=2
        self.assertEqual(document_preview(self.reader,self.document,{})['objectMappings'],[])

    def test_unpublished_graph_is_not_replayed_and_discovery_is_version_scoped(self):
        descriptor={k:v for k,v in self.document.items() if not k.startswith('knowledge')}
        self.assertEqual(document_preview(self.reader,descriptor,{})['releaseId'],self.document['knowledgeReleaseId'])
        self.published=False
        with self.assertRaises(PreviewError):document_preview(self.reader,self.document,{})

    def test_full_graph_keeps_bounded_pagination_without_alarm_root_filter(self):
        preview(self.reader,'document',self.document,{'graphScope':'all','cursor':100})
        graph_paths=[call.args[1] for call in self.wrapper._request.call_args_list if '/graph?' in call.args[1]]
        query=parse_qs(urlsplit(graph_paths[-1]).query)
        self.assertNotIn('root',query);self.assertEqual(query['limit'],['100']);self.assertEqual(query['cursor'],['100'])
        with self.assertRaises(PreviewError):preview(self.reader,'document',self.document,{'graphScope':'unbounded'})

    def test_relations_are_sourced_do_not_guess_same_name_and_keep_other_available_links(self):
        photo={'entityUid':'sensor'};obj={'entityUid':'sensor'}
        self.reader.read.side_effect=lambda kind,value:{'item':{'displayName':'same name'}} if kind=='object' else {'selector':{'bbox':self.location['bbox']}}
        fixed=[({'evidenceRefId':'object','sourceKind':'object'},obj),({'evidenceRefId':'photo','sourceKind':'photo'},photo)]
        found=relationships(self.reader,fixed,None)['items'];self.assertEqual(found[0]['kind'],'photo_location');self.assertEqual(found[0]['origin'],'source')
        photo['entityUid']='other';self.assertEqual(relationships(self.reader,fixed,None)['items'],[])
        self.reader.read.side_effect=PreviewError(403,'FORBIDDEN')
        with self.assertRaises(PreviewError):relationships(self.reader,fixed,None)

    def test_viewer_rejects_arbitrary_urls_unbounded_cursors_and_malformed_fixed_handles(self):
        validate_descriptor('document',self.document);validate_descriptor('drawing',self.drawing)
        for value in ({'url':'https://untrusted.invalid'},{'cursor':10001},{'cursor':True}):
            with self.assertRaises(PreviewError):preview(self.reader,'drawing',self.drawing,value)
        for value in ({**self.document,'knowledgeReleaseId':'not-uuid'},{**self.document,'url':'https://untrusted.invalid'}):
            with self.assertRaises(PreviewError):validate_descriptor('document',value)

    def test_model_location_requires_saved_scope_version_and_component_binding(self):
        db=sqlite3.connect(':memory:')
        self.addCleanup(db.close)
        db.executescript('''create table scenes(id text,head_revision text,project_code text);
            create table scene_revisions(revision text,snapshot text);
            create table scene_spatial_validations(revision text,validation text);
            create table scene_lifecycle(scene_id text,state text);
            create table scene_resource_uses(revision text,model_version_id text);''')
        binding={'componentKeys':['cabinet'],'objectRef':{'entityUid':'installed-cabinet','projectCode':'P','ontobaseConnectionId':'source'}}
        snapshot={'instances':[{'modelVersionId':'model-version','sceneModelInstanceId':'instance','componentBindings':[binding]}]}
        for scene in ('one','two'):
            db.execute('insert into scenes values(?,?,?)',(scene,scene,'P'))
            db.execute('insert into scene_revisions values(?,?)',(scene,json.dumps(snapshot)))
            db.execute('insert into scene_resource_uses values(?,?)',(scene,'model-version'))
        self.reader.read.side_effect=lambda kind,value:{'components':[{'componentKey':'cabinet'}]} if kind=='model' else {'item':{}}
        fixed=[({'evidenceRefId':'cab','sourceKind':'object'},{'entityUid':'installed-cabinet'}),
               ({'evidenceRefId':'model','sourceKind':'model'},{'modelVersionId':'model-version'})]
        found=relationships(self.reader,fixed,SimpleNamespace(connect=lambda:db))['items']
        self.assertEqual(len(found),1);self.assertEqual(found[0]['anchor']['componentKeys'],['cabinet'])
        fixed[0][1]['entityUid']='same-name-project-definition'
        self.assertEqual(relationships(self.reader,fixed,SimpleNamespace(connect=lambda:db))['items'],[])
        fixed[0][1]['entityUid']='installed-cabinet';fixed[1][1]['modelVersionId']='new-model-version'
        self.assertEqual(relationships(self.reader,fixed,SimpleNamespace(connect=lambda:db))['items'],[])


class PhotoPreviewTests(TestCase):
    def setUp(self):
        from PIL import Image
        out=BytesIO();Image.new('RGB',(800,5000),'#689a82').save(out,'JPEG')
        self.raw=out.getvalue();self.before=hashlib.sha256(self.raw).hexdigest()
        self.reader=SimpleNamespace(read=Mock(),content=Mock(return_value={'content':self.raw}))
        self.descriptor={'expectedDisplayRevision':self.before}
        analysis_media._cache.clear()

    def test_quick_preview_preserves_aspect_and_original_while_reusing_fixed_bytes(self):
        from PIL import Image
        first=analysis_media.photo_preview(self.reader,self.descriptor)
        image=Image.open(BytesIO(first['content']));self.assertLessEqual(max(image.size),4096)
        self.assertLess(abs(image.width/image.height-800/5000),1/4096)
        self.assertEqual(first,analysis_media.photo_preview(self.reader,self.descriptor))
        self.assertEqual(self.reader.content.call_count,1);self.assertEqual(self.reader.read.call_count,2)
        self.assertEqual(hashlib.sha256(self.raw).hexdigest(),self.before)

    def test_cached_preview_still_obeys_revocation(self):
        analysis_media.photo_preview(self.reader,self.descriptor)
        self.reader.read.side_effect=PreviewError(403,'FORBIDDEN')
        with self.assertRaises(PreviewError):analysis_media.photo_preview(self.reader,self.descriptor)
        self.assertEqual(self.reader.content.call_count,1)

    def test_invalid_or_oversized_input_has_no_partial_cache_entry(self):
        self.reader.content.return_value={'content':b'not an image'}
        with self.assertRaises(PreviewError):analysis_media.photo_preview(self.reader,self.descriptor)
        self.assertEqual(len(analysis_media._cache),0)
