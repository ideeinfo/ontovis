"""Actual protected HTTP against disposable PG and synthetic project sources."""
from copy import deepcopy
from http.client import HTTPConnection
import io
import json
import os
import unittest
from unittest.mock import patch
from uuid import uuid4

from apps.api.authority import PreviewError
from apps.api.work_orders import WorkOrders
from tests import test_analysis_http_integration as base
from tests.test_model_upload import glb

ROOT='/api/workbench/analysis-sessions'


@unittest.skipUnless(os.environ.get('ONTOVIS_ANALYSIS_TEST_DATABASE_URL'), 'Set an owned disposable PG test connection')
class AnalysisSourceHttpTests(unittest.TestCase):
    photo_media_origin = 'https://vis-media.ontobase.ai'
    setUpClass=classmethod(base.AnalysisHttpIntegrationTests.setUpClass.__func__)
    tearDownClass=classmethod(base.AnalysisHttpIntegrationTests.tearDownClass.__func__)
    setUp=base.AnalysisHttpIntegrationTests.setUp
    request=base.AnalysisHttpIntegrationTests.request
    login=base.AnalysisHttpIntegrationTests.login
    account=base.AnalysisHttpIntegrationTests.account
    start=base.AnalysisHttpIntegrationTests.start
    body=base.AnalysisHttpIntegrationTests.body
    value=base.AnalysisHttpIntegrationTests.value
    create=base.AnalysisHttpIntegrationTests.create
    detail=base.AnalysisHttpIntegrationTests.detail

    def model(self):
        data=glb(self.root/'source.glb').read_bytes();models=self.sessions.shared.project_models
        value=models.upload(io.BytesIO(data),len(data),{'expectedLibraryRevision':self.sessions.shared.library.listing()['libraryRevision'],
            'clientRequestId':str(uuid4()),'displayName':'Synthetic source model','purpose':'equipment','sourceNote':'Synthetic fixture','rightsDeclared':True},'fixture-admin',lambda:None)
        return value,data

    def register(self):
        created,_=self.create();model,data=self.model()
        body=self.body(analysisSessionId=created['analysisSessionId'],expectedAnalysisRevision=1,requestId=str(uuid4()),sourceKind='model',
            selector={'modelAssetId':model['modelAssetId'],'modelVersionId':model['modelVersionId'],
                      'expectedContentRevision':model['contentRevision'],'expectedSha256':model['sha256']})
        response=self.request(ROOT+'/evidence/register',body);self.assertEqual(response[0],200,response[1])
        return created,model,data,body,response[1]

    def reference(self,created,ref):
        return self.body(analysisSessionId=created['analysisSessionId'],evidenceRefId=ref['evidenceRefId'])

    def test_object_recommendations_report_owned_registered_revisions_without_writing_evidence(self):
        from tools.analysis_draft_backup import export_package
        created, _ = self.create()
        other, _ = self.create()
        selection = {'entityUid': 'fixture-cabinet', 'expectedEntityRevision': 'r7'}
        primary = dict(entityUid=selection['entityUid'], entityRevision='r7', displayName='Same name')
        sibling = {**primary, 'entityUid': 'another-cabinet'}
        original = self.source.request

        def source(account, method, path, body=None):
            if '/objects?q=' in path:
                return {'items': [primary, sibling], 'nextCursor': None}
            return original(account, method, path, body)

        with patch.object(self.source, 'request', source), patch(
                'apps.api.scene_engineering.SceneEngineeringReader.context_for_object',
                return_value={'item': primary, 'context': {'installationContextId': 'context', 'hierarchyRevision': 'h1'}}), patch(
                'apps.api.scene_engineering.SceneEngineeringReader.detail', return_value={'item': primary}):
            status, ref, _ = self.request(ROOT+'/evidence/register', self.body(analysisSessionId=created['analysisSessionId'],
                expectedAnalysisRevision=1, requestId=str(uuid4()), sourceKind='object', selector=selection))
            self.assertEqual(status, 200, ref)
            viewer = self.login('other')
            before = export_package(self.urls[0])
            request = self.body(entry={'projectOnly': True}, section='objects', q='Same name',
                                analysisSessionId=created['analysisSessionId'])
            status, result, _ = self.request(ROOT+'/recommendations', request)
            self.assertEqual(status, 200, result)
            self.assertEqual(result['items'][0]['registeredSourceRevisions'], [ref['sourceRevision']])
            self.assertNotIn('registeredSourceRevisions', result['items'][1])
            status, result, _ = self.request(ROOT+'/recommendations', {**request, 'analysisSessionId': other['analysisSessionId']})
            self.assertEqual(status, 200, result)
            self.assertTrue(all('registeredSourceRevisions' not in item for item in result['items']))
            self.assertEqual(self.request(ROOT+'/recommendations', request, client=viewer)[0], 404)
            scope = {**request, 'q': '', 'canvasEvidenceRefIds': [ref['evidenceRefId']]}
            status, result, _ = self.request(ROOT+'/recommendations', scope)
            self.assertEqual(status, 200, result)
            self.assertEqual([ref['evidenceRefId']], result['items'][0]['relatedSourceRefs'])
            self.assertEqual([ref['sourceRevision']], result['items'][0]['registeredSourceRevisions'])
            self.assertEqual(self.request(ROOT+'/recommendations', {**scope, 'analysisSessionId': other['analysisSessionId']})[0], 404)
            self.assertEqual(self.request(ROOT+'/recommendations', scope, client=viewer)[0], 404)
            self.assertEqual(export_package(self.urls[0]), before)

    def read_bytes(self,path,payload):
        connection=HTTPConnection(*self.server.server_address,timeout=5)
        try:
            connection.request('POST',path,json.dumps(payload|{'expectedSessionRevision':self.admin['revision']}),
                {'Host':'127.0.0.1:4180','Origin':'http://127.0.0.1:4180','Content-Type':'application/json','Cookie':self.admin['cookie']})
            response=connection.getresponse();self.assertEqual(response.status,200);self.assertEqual(response.getheader('Cache-Control'),'no-store')
            return response.read()
        finally:connection.close()

    def redeem_photo(self, ticket):
        connection = HTTPConnection(*self.server.server_address, timeout=5)
        try:
            connection.request('POST', '/v1/fixed-photo', ticket, {'Host':'vis-media.ontobase.ai',
                'Origin':'http://127.0.0.1:4180','Content-Type':'text/plain'})
            response = connection.getresponse()
            return response.status, response.getheader('X-Fixed-Photo-SHA256'), response.read()
        finally:
            connection.close()

    def test_project_document_photo_registers_and_reads_without_object_or_region(self):
        from tests.test_equipment_materials import DocumentReader, DOC, VERSION, PNG
        from tools.analysis_draft_backup import export_package, validate_package
        created,_=self.create();fixed=DocumentReader();fixed.version['preview_kind']='image';fixed.document['kind']='photo'
        original=self.source.request
        def source(account,method,path,body=None):
            if '/documents/' in path:return fixed._request(method,path,body)
            return original(account,method,path,body)
        with patch.object(self.source,'request',source),patch.object(self.source,'document_page',return_value=dict(content=PNG,mediaType='image/png',sha256='b'*64),create=True):
            selector=dict(sourceType='project_document',documentId=DOC,contentVersionId=VERSION)
            status,ref,*_=self.request(ROOT+'/evidence/register',self.body(analysisSessionId=created['analysisSessionId'],expectedAnalysisRevision=1,requestId=str(uuid4()),sourceKind='photo',selector=selector))
            self.assertEqual(status,200,ref);payload=self.reference(created,ref)
            read=self.request(ROOT+'/evidence/detail',payload)
            self.assertEqual((read[0],read[1]['availability']),(200,'available'));self.assertIsNone(read[1]['source']['selector'])
            self.assertEqual(self.read_bytes(ROOT+'/evidence/content',payload),PNG)
            self.assertEqual(self.read_bytes(ROOT+'/evidence/content',payload|{'representation':'full_resolution'}),PNG)
            self.assertEqual(self.read_bytes(ROOT+'/evidence/content',payload|{'representation':'full_resolution_avif'}),PNG)
            native = payload | {'representation':'full_resolution_avif'}
            photo_header = {'X-Vis-Photo-Read':'full_resolution_avif'}
            def mint(request):
                reply = self.request(ROOT+'/evidence/content', request, headers=photo_header)
                self.assertEqual(reply[0], 200, reply[1])
                return reply[1]['photoTicket']
            self.assertEqual(self.redeem_photo(mint(native)), (200, 'b'*64, PNG))
            wrong_project = native | {'projectRef':self.body()['projectRef'] | {'projectCode':'B'}}
            self.assertEqual(self.redeem_photo(mint(wrong_project))[0], 404)
            ticket = mint(native)
            previous_role = self.source.permissions['writer'].pop('SYNTHETIC-A')
            try:
                self.assertEqual(self.redeem_photo(ticket)[0], 403)
            finally:
                self.source.permissions['writer']['SYNTHETIC-A'] = previous_role
            self.assertEqual(self.request(ROOT+'/evidence/content',payload|{'representation':'other'})[0],422)
            self.assertTrue(self.read_bytes(ROOT+'/evidence/preview-content',payload).startswith(b'\xff\xd8\xff'))
            self.assertEqual(self.request(ROOT+'/evidence/relationships',self.body(analysisSessionId=created['analysisSessionId'],evidenceRefIds=[ref['evidenceRefId']]))[1]['items'],[])
            package=export_package(self.urls[0]);validate_package(package)
            row=next(row for row in package['tables']['analysis_evidence_refs'] if row['evidence_ref_id']==ref['evidenceRefId'])
            self.assertEqual(json.loads(row['descriptor_json']),selector|{'sourceSha256':'a'*64})
            ticket = mint(native)
            fixed.version['source_sha256']='c'*64
            self.assertEqual(self.redeem_photo(ticket)[0], 409)
            self.assertNotEqual(self.request(ROOT+'/evidence/detail',payload)[1]['availability'],'available')

    def test_cabinet_member_photo_recommendation_preserves_scope_and_writes_only_on_explicit_register(self):
        from tests.test_equipment_materials import DocumentReader, DOC, VERSION
        from tools.analysis_draft_backup import export_package
        created,_=self.create();before=export_package(self.urls[0]);fixed=DocumentReader();fixed.version['preview_kind']='image'
        target={'item':{'entityUid':'cabinet','entityRevision':'r7','displayName':'Cabinet','objectScope':'definition'},'context':None}
        original=self.source.request;calls=[]
        def source(account,method,path,body=None):
            if path.endswith('/equipment/shared-photos/query'):
                calls.append(body)
                return dict(projectCode='SYNTHETIC-A',items=[dict(documentId=DOC,contentVersionId=VERSION,
                    title='Cabinet member photo',availability='available')],nextCursor=None)
            if '/documents/' in path:return fixed._request(method,path,body)
            return original(account,method,path,body)
        request=self.body(entry={'projectOnly':True},section='photos',entityUid='cabinet',expectedEntityRevision='r7')
        with patch.object(self.source,'request',source),patch('apps.api.scene_engineering.SceneEngineeringReader.context_for_object',return_value=target),patch('apps.api.scene_photos.ScenePhotoReader.resolve',return_value={'items':[]}):
            status,value,*_=self.request(ROOT+'/recommendations',request)
            self.assertEqual(status,200,value);self.assertEqual(calls[0]['entityUid'],'cabinet')
            self.assertEqual(value['items'][0]['selector'],dict(sourceType='project_document',documentId=DOC,contentVersionId=VERSION))
            self.assertEqual(export_package(self.urls[0]),before)
            self.assertEqual(self.request(ROOT+'/recommendations',request,client=False)[0],401)
            self.assertEqual(self.request(ROOT+'/recommendations',request,headers={'Origin':'https://wrong.invalid'})[0],403)
            status,ref,*_=self.request(ROOT+'/evidence/register',self.body(analysisSessionId=created['analysisSessionId'],expectedAnalysisRevision=1,
                requestId=str(uuid4()),sourceKind='photo',selector=value['items'][0]['selector']))
            self.assertEqual(status,200,ref)
            read=self.request(ROOT+'/evidence/detail',self.reference(created,ref))
            self.assertEqual(read[0],200,read[1]);self.assertIsNone(read[1]['source']['selector'])
            self.assertEqual(self.detail(created)[1]['analysisRevision'],1)

    def test_unpublished_pdf_minimal_selection_keeps_fixed_hash_and_page(self):
        from tests.test_equipment_materials import DocumentReader, DOC, VERSION, PNG
        created,_=self.create();fixed=DocumentReader();original=self.source.request
        def source(account,method,path,body=None):
            if '/documents/' in path:return {'outline':[]} if path.endswith('/navigation') else fixed._request(method,path,body)
            return original(account,method,path,body)
        with patch.object(self.source,'request',source),patch.object(self.source,'document_page',return_value=dict(content=PNG,mediaType='image/png',sha256='b'*64),create=True) as binary:
            status,ref,*_=self.request(ROOT+'/evidence/register',self.body(analysisSessionId=created['analysisSessionId'],expectedAnalysisRevision=1,requestId=str(uuid4()),sourceKind='document',selector=dict(documentId=DOC,contentVersionId=VERSION,pageNumber=2)))
            self.assertEqual(status,200,ref);payload=self.reference(created,ref)
            read=self.request(ROOT+'/evidence/detail',payload)
            self.assertEqual(read[1]['source']['pageNumber'],2);self.assertEqual(read[1]['source']['sourceSha256'],'a'*64)
            self.assertNotIn('knowledgeReleaseId',read[1]['source'])
            self.assertEqual(self.read_bytes(ROOT+'/evidence/preview-content',payload|{'options':{'pageNumber':3}}),PNG)
            self.assertIn('version_id='+VERSION,binary.call_args.args[0]);self.assertIn('page=3',binary.call_args.args[0])
            self.assertEqual(self.request(ROOT+'/evidence/detail',payload)[1]['source']['pageNumber'],2)

    def test_comparing_and_adopting_another_document_version_preserves_saved_history(self):
        from tests.test_equipment_materials import DocumentReader, DOC, VERSION
        created, _ = self.create()
        fixed = DocumentReader()
        current = fixed.document['current_version_id']
        current_item = dict(fixed.version, id=current, version_number=3, source_sha256='c'*64)
        original = self.source.request

        def source(account, method, path, body=None):
            if path.endswith('/navigation'):
                return {'outline': []}
            if path.endswith('/versions/'+current):
                return {'item': current_item}
            if '/documents/' in path:
                return fixed._request(method, path, body)
            return original(account, method, path, body)

        def register(revision, selector):
            status, value, *_ = self.request(ROOT+'/evidence/register', self.body(
                analysisSessionId=created['analysisSessionId'], expectedAnalysisRevision=revision,
                requestId=str(uuid4()), sourceKind='document', selector=selector))
            self.assertEqual(status, 200, value)
            return value

        def save(snapshot, revision):
            return self.request(ROOT+'/save', self.body(analysisSessionId=created['analysisSessionId'],
                expectedAnalysisRevision=revision, requestId=str(uuid4()), snapshot=snapshot))

        with patch.object(self.source, 'request', source):
            old = register(1, dict(documentId=DOC, contentVersionId=VERSION, pageNumber=2))
            snapshot = dict(self.value(), schemaVersion=2)
            card = dict(id=str(uuid4()), kind='document', title='Synthetic manual', x=16, y=32,
                        width=340, height=360, pinned=False)
            card['source'] = dict(self.body()['projectRef'], system='ontobase', id=old['evidenceRefId'],
                                  revision=old['sourceRevision'])
            snapshot['cards'].append(card)
            self.assertEqual(save(snapshot, 1)[1]['analysisRevision'], 2)

            basis = self.request(ROOT+'/evidence/detail', self.reference(created, old))[1]['source']
            compared = self.request('/api/workbench/equipment/materials/metadata', self.body(
                documentId=DOC, contentVersionId=basis['currentContentVersionId']))
            self.assertEqual(compared[0], 200, compared[1])
            self.assertEqual(compared[1]['sourceSha256'], 'c'*64)
            self.assertEqual(self.detail(created)[1]['snapshot']['cards'][-1]['source'], card['source'])

            adopted = register(2, dict(documentId=DOC, contentVersionId=current, sourceSha256='c'*64, pageNumber=3))
            updated = deepcopy(snapshot)
            updated['cards'][-1]['source'].update(id=adopted['evidenceRefId'], revision=adopted['sourceRevision'])
            self.assertEqual(save(updated, 2)[1]['analysisRevision'], 3)
            history = self.request(ROOT+'/detail', self.body(analysisSessionId=created['analysisSessionId'], analysisRevision=2))
            self.assertEqual(history[1]['snapshot'], snapshot)
            detail = self.request(ROOT+'/evidence/detail', self.reference(created, adopted))[1]['source']
            self.assertEqual((detail['contentVersionId'], detail['pageNumber']), (current, 3))

    def test_recommendation_continuation_is_read_only_and_bound_to_current_login_and_source_page(self):
        from tools.analysis_draft_backup import export_package
        target={'item':{'entityUid':'cabinet','entityRevision':'r7'},'context':None}
        rows=[dict(documentId=str(uuid4()),contentVersionId=str(uuid4()),title='Member '+str(i),availability='available') for i in range(12)]
        last=dict(rows[0],documentId=str(uuid4()),title='Next page');original=self.source.request
        def source(account,method,path,body=None):
            if path.endswith('/equipment/shared-photos/query'):
                return dict(projectCode='SYNTHETIC-A',items=rows if body['cursor'] is None else [last],
                    nextCursor='source:next' if body['cursor'] is None else None)
            return original(account,method,path,body)
        request=self.body(entry={'projectOnly':True},section='photos',entityUid='cabinet',expectedEntityRevision='r7')
        before=export_package(self.urls[0])
        with patch.object(self.source,'request',source),patch('apps.api.scene_engineering.SceneEngineeringReader.context_for_object',return_value=target),patch('apps.api.scene_photos.ScenePhotoReader.resolve',return_value={'items':[]}):
            status,first,*_=self.request(ROOT+'/recommendations',request);self.assertEqual(status,200,first)
            continuation=request|{'cursor':first['nextCursor']}
            status,second,*_=self.request(ROOT+'/recommendations',continuation)
            self.assertEqual(status,200,second);self.assertEqual(second['items'][0]['title'],'Next page')
            self.assertEqual(self.request(ROOT+'/recommendations',continuation|{'q':'other'})[0],409)
            other=self.login('other');self.assertEqual(self.request(ROOT+'/recommendations',continuation,client=other)[0],409)
            rows[0]['title']='Changed source page'
            self.assertEqual(self.request(ROOT+'/recommendations',continuation)[0],409)
            rows[0]['title']='Member 0';self.admin=self.login('writer')
            self.assertEqual(self.request(ROOT+'/recommendations',continuation)[0],409)
            self.assertEqual(export_package(self.urls[0]),before)

    def demo(self):
        self.source.projects['Demo-PDS']='Synthetic demo';self.source.permissions['writer']['Demo-PDS']='admin'
        project={'ontobaseConnectionId':'ontobase-primary','projectCode':'Demo-PDS'}
        value=self.value();value['projectCode']='Demo-PDS'
        response=self.request(ROOT+'/create',{'projectRef':project,'requestId':str(uuid4()),'snapshot':value})
        self.assertEqual(response[0],200,response[1]);created=response[1]
        service=self.sessions._workspace(self.sessions.registry.lookup('Demo-PDS'))
        orders=WorkOrders(service.library,'Demo-PDS')
        orders.seed({'requestId':str(uuid4()),'expectedSnapshotRevision':'work-orders:empty'},
            {key:{'entityUid':'synthetic-'+key} for key in ('CN','CN1')},'fixture-admin',lambda:None)
        return project,created,orders

    def test_metadata_batch_keeps_input_order_and_at_most_two_reads(self):
        from threading import Lock
        import time
        created,_=self.create();ids=[str(uuid4()) for _ in range(6)]
        active=peak=0;lock=Lock()
        def descriptor(_store,actor,body,guard):
            guard();identity=body['evidenceRefId']
            return {'evidenceRefId':identity,'sourceKind':'model','sourceRevision':'a'*64},{'marker':identity}
        def read(_reader,kind,descriptor):
            nonlocal active,peak
            with lock:active+=1;peak=max(peak,active)
            try:
                time.sleep(.005*(len(ids)-ids.index(descriptor['marker'])))
                return {'marker':descriptor['marker']}
            finally:
                with lock:active-=1
        with patch('apps.api.analysis_evidence.AnalysisEvidence.descriptor',descriptor),patch('apps.api.analysis_source_reader.AnalysisSourceReader.read',read):
            status,value,*_=self.request(ROOT+'/evidence/batch',self.body(analysisSessionId=created['analysisSessionId'],evidenceRefIds=ids))
        self.assertEqual(status,200,value);self.assertEqual(peak,2)
        self.assertEqual([item['source']['marker'] for item in value['items']],ids)

    def test_model_handle_read_binary_and_replay_preserve_fixed_identity(self):
        created,model,data,body,ref=self.register()
        self.assertEqual(self.request(ROOT+'/evidence/register',body)[1]['evidenceRefId'],ref['evidenceRefId'])
        payload=self.reference(created,ref);read=self.request(ROOT+'/evidence/detail',payload)
        self.assertEqual((read[0],read[1]['availability']),(200,'available'))
        self.assertEqual(read[1]['source']['modelVersionId'],model['modelVersionId'])
        connection=HTTPConnection(*self.server.server_address,timeout=5)
        try:
            connection.request('POST',ROOT+'/evidence/content',json.dumps({**payload,'expectedSessionRevision':self.admin['revision']}),
                {'Host':'127.0.0.1:4180','Origin':'http://127.0.0.1:4180','Content-Type':'application/json','Cookie':self.admin['cookie']})
            response=connection.getresponse();self.assertEqual(response.status,200);self.assertEqual(response.read(),data)
            self.assertEqual(response.getheader('Cache-Control'),'no-store')
        finally:connection.close()
        self.assertTrue(read[1]['capabilities']['sourceCardsEnabled'])
        self.assertEqual(read[1]['capabilities']['sourceReferenceApiVersion'],2)

    def test_full_preview_and_relationship_reads_keep_owner_project_and_input_boundaries(self):
        created,model,data,body,ref=self.register();payload=self.reference(created,ref)
        result=self.request(ROOT+'/evidence/preview',{**payload,'options':{}})
        self.assertEqual((result[0],result[1]['kind']),(200,'model'))
        related=self.body(analysisSessionId=created['analysisSessionId'],evidenceRefIds=[ref['evidenceRefId']])
        result=self.request(ROOT+'/evidence/relationships',related)
        self.assertEqual((result[0],result[1]['items']),(200,[]))
        for suffix,payload in (('preview',payload),('relationships',related)):
            self.assertEqual(self.request(ROOT+'/evidence/'+suffix,payload,client=False)[0],401)
            self.assertEqual(self.request(ROOT+'/evidence/'+suffix,payload,client=self.login('other'))[0],404)
            self.assertEqual(self.request(ROOT+'/evidence/'+suffix,{**payload,'projectRef':{'ontobaseConnectionId':'ontobase-primary','projectCode':'B'}})[0],404)
        self.assertEqual(self.request(ROOT+'/evidence/preview',{**self.reference(created,ref),'options':{'cursor':10001}})[0],422)
        self.assertEqual(self.request(ROOT+'/evidence/relationships',{**related,'evidenceRefIds':[]})[0],422)
        self.assertEqual(self.request(ROOT+'/evidence/relationships',{**related,'evidenceRefIds':[{}]})[0],422)
        self.assertEqual(self.request(ROOT+'/evidence/preview-content',self.reference(created,ref))[0],422)

    def test_document_page_browsing_returns_bytes_without_changing_saved_citation(self):
        created,_=self.create();selector={'documentId':str(uuid4()),'contentVersionId':str(uuid4()),'sourceSha256':'a'*64,'pageNumber':48}
        with patch('apps.api.analysis_source_reader.AnalysisSourceReader.resolve',return_value=selector):
            result=self.request(ROOT+'/evidence/register',self.body(analysisSessionId=created['analysisSessionId'],expectedAnalysisRevision=1,requestId=str(uuid4()),sourceKind='document',selector=selector))
        self.assertEqual(result[0],200,result[1]);ref=result[1];payload=self.reference(created,ref)
        self.assertEqual(self.request(ROOT+'/evidence/preview-content',{**payload,'options':['pageNumber']})[0],422)
        with patch('apps.api.analysis_source_reader.AnalysisSourceReader.content',return_value={'content':b'page','mediaType':'image/png','sha256':'b'*64}) as read:
            connection=HTTPConnection(*self.server.server_address,timeout=5)
            try:
                connection.request('POST',ROOT+'/evidence/preview-content',json.dumps({**payload,'options':{'pageNumber':49},'expectedSessionRevision':self.admin['revision']}),
                    {'Host':'127.0.0.1:4180','Origin':'http://127.0.0.1:4180','Content-Type':'application/json','Cookie':self.admin['cookie']})
                response=connection.getresponse();self.assertEqual(response.status,200);self.assertEqual(response.read(),b'page');self.assertEqual(response.getheader('Cache-Control'),'no-store')
            finally:connection.close()
            self.assertEqual(read.call_args.args[1]['pageNumber'],49)
        with patch('apps.api.analysis_source_reader.AnalysisSourceReader.read',return_value={}) as read:
            self.assertEqual(self.request(ROOT+'/evidence/detail',payload)[0],200)
            self.assertEqual(read.call_args.args[1]['pageNumber'],48)

    def test_owner_project_origin_anonymous_and_write_denial_do_not_expose_sources(self):
        created,model,data,body,ref=self.register();payload=self.reference(created,ref)
        self.assertEqual(self.request(ROOT+'/evidence/detail',payload,client=False)[0],401)
        self.assertEqual(self.request(ROOT+'/evidence/detail',payload,headers={'Origin':'https://outside.invalid'})[0],403)
        self.assertEqual(self.request(ROOT+'/evidence/detail',payload,client=self.login('other'))[0],404)
        cross=deepcopy(payload);cross['projectRef']['projectCode']='B'
        self.assertEqual(self.request(ROOT+'/evidence/detail',cross)[0],404)
        self.source.permissions['writer']['SYNTHETIC-A']='viewer'
        self.assertEqual(self.request(ROOT+'/evidence/register',{**body,'requestId':str(uuid4())})[0],403)
        self.assertEqual(self.request(ROOT+'/evidence/detail',payload)[0],200)
        with patch('apps.api.analysis_source_reader.AnalysisSourceReader.read',side_effect=PreviewError(403,'SOURCE_FORBIDDEN')):
            value=self.request(ROOT+'/evidence/detail',payload)
            self.assertEqual(value[1]['availability'],'restricted');self.assertNotIn('source',value[1])

    def test_deleted_model_retains_existing_reference_but_cannot_register_again(self):
        created,model,data,body,ref=self.register();models=self.sessions.shared.project_models
        models.lifecycle({'modelAssetId':model['modelAssetId'],'modelVersionId':model['modelVersionId'],
            'expectedAssetRevision':model['assetRevision'],'expectedLifecycleRevision':0,'clientRequestId':str(uuid4())},'fixture-admin',lambda:None,action='delete')
        self.assertEqual(self.request(ROOT+'/evidence/detail',self.reference(created,ref))[1]['availability'],'available')
        result=self.request(ROOT+'/evidence/register',{**body,'requestId':str(uuid4())});self.assertEqual((result[0],result[1]['code']),(410,'MODEL_DELETED'))

    def test_full_work_order_reference_stays_old_and_link_uses_fixed_analysis_revision(self):
        project,created,orders=self.demo()
        body={'projectRef':project,'analysisSessionId':created['analysisSessionId'],'expectedAnalysisRevision':1,
              'requestId':str(uuid4()),'sourceKind':'work_order','selector':{'orderId':'DEMO-PDS-WO-001','expectedOrderRevision':1}}
        ref=self.request(ROOT+'/evidence/register',body);self.assertEqual(ref[0],200,ref[1])
        linked=self.request(ROOT+'/link-work-order',{'projectRef':project,'analysisSessionId':created['analysisSessionId'],
            'analysisRevision':1,'orderId':'DEMO-PDS-WO-001','expectedOrderRevision':1,'requestId':str(uuid4())})
        self.assertEqual(linked[0],200,linked[1]);self.assertEqual(orders.detail({'orderId':'DEMO-PDS-WO-001'})['state'],'open')
        read=self.request(ROOT+'/evidence/detail',{'projectRef':project,'analysisSessionId':created['analysisSessionId'],'evidenceRefId':ref[1]['evidenceRefId']})
        self.assertEqual(read[1]['source']['orderRevision'],1);self.assertEqual(len(read[1]['source']['events']),1)
        changed=self.value();changed['projectCode']='Demo-PDS';changed['cards'][0]['note']='new analysis revision'
        saved=self.request(ROOT+'/save',{'projectRef':project,'analysisSessionId':created['analysisSessionId'],
            'expectedAnalysisRevision':1,'requestId':str(uuid4()),'snapshot':changed});self.assertEqual(saved[0],200,saved[1])
        self.assertEqual(orders.detail({'orderId':'DEMO-PDS-WO-001'})['analysisLinks'][0]['analysisRevision'],1)

    def test_rehearsal_catalogue_is_project_scoped_and_extra_paths_are_closed(self):
        project,created,orders=self.demo()
        value=self.request(ROOT+'/simulation/catalogue',{'projectRef':project});self.assertEqual(value[0],200,value[1])
        self.assertEqual(value[1]['sourceKind'],'simulated')
        cases = ('13001','13002','13003','13004','13033','13035','13058','13001-recurrence-1')
        self.assertCountEqual([item['datasetId'] for item in value[1]['items']], ['SIM-PDS-'+case for case in cases])
        self.assertEqual(self.request(ROOT+'/simulation/catalogue',self.body())[0],404)
        for suffix in ('evidence/register/extra','simulation/qualify/','simulation/reset','evidence/delete','confirm'):
            self.assertEqual(self.request(ROOT+'/'+suffix,self.body())[0],404)
        self.assertEqual(self.request(ROOT+'/evidence/register',raw=b' '*16385)[0],413)

    def test_replay_browser_reads_without_creating_analysis_or_project_workspace(self):
        from tools.analysis_draft_backup import export_package
        self.source.projects['Demo-PDS']='Synthetic demo';self.source.permissions['writer']['Demo-PDS']='viewer'
        project={'ontobaseConnectionId':'ontobase-primary','projectCode':'Demo-PDS'}
        before=export_package(self.urls[0])
        with patch('apps.api.analysis_drafts.AnalysisDrafts',side_effect=AssertionError('Unrelated analysis storage')):
            result=self.request(ROOT+'/simulation/catalogue',{'projectRef':project,'includeDetail':True})
        self.assertEqual(result[0],200,result[1]);item=result[1]['items'][0]
        self.assertEqual(result[1]['initialDetail']['dataset'],item)
        body={'projectRef':project,**{key:item[key] for key in ('datasetId','datasetRevision')}}
        result=self.request(ROOT+'/simulation/detail',body)
        self.assertEqual(result[0],200,result[1]);self.assertEqual(len(result[1]['trends']),5)
        self.assertFalse(result[1]['capabilities']['canWrite'])
        self.assertEqual(export_package(self.urls[0]),before)
        self.assertIsNone(self.sessions.registry.lookup('Demo-PDS'))
        self.assertEqual(self.request(ROOT+'/simulation/detail',body,client=False)[0],401)
        self.assertEqual(self.request(ROOT+'/simulation/detail',{**body,'datasetRevision':'changed'})[0],409)
        self.assertEqual(self.request(ROOT+'/simulation/detail',{**body,'extra':True})[0],422)
        self.assertEqual(self.request(ROOT+'/simulation/detail',{**body,'projectRef':self.body()['projectRef']})[0],404)
        self.assertEqual(self.request(ROOT+'/simulation/detail/',body)[0],404)

    def test_batch_registration_uses_owned_fixed_handles_and_current_write_grant(self):
        created,model,data,body,ref=self.register()
        request=self.body(analysisSessionId=created['analysisSessionId'],expectedAnalysisRevision=1,
            items=[{'key':'model','requestId':str(uuid4()),'sourceKind':'model','selector':body['selector']}])
        result=self.request(ROOT+'/evidence/register-batch',request)
        self.assertEqual(result[0],200,result[1]);self.assertEqual(result[1]['items'][0]['reference']['evidenceRefId'],ref['evidenceRefId'])
        batch=self.request(ROOT+'/evidence/batch',self.body(analysisSessionId=created['analysisSessionId'],evidenceRefIds=[ref['evidenceRefId']]))
        self.assertEqual(batch[0],200,batch[1]);self.assertEqual(batch[1]['items'][0]['availability'],'available')
        self.source.permissions['writer']['SYNTHETIC-A']='viewer'
        self.assertEqual(self.request(ROOT+'/evidence/register-batch',request)[0],403)
        # Read paths released their database slot before source work.
        for _ in range(4):
            self.assertTrue(self.sessions.analysis_slots.acquire(blocking=False))
        self.assertFalse(self.sessions.analysis_slots.acquire(blocking=False))
        for _ in range(4):
            self.sessions.analysis_slots.release()

    def test_revoke_during_source_read_does_not_return_previously_read_content(self):
        from apps.api.analysis_source_reader import AnalysisSourceReader
        created,model,data,body,ref=self.register();original=AnalysisSourceReader.read
        def revoked(reader,kind,descriptor):
            value=original(reader,kind,descriptor)
            del self.source.permissions['writer']['SYNTHETIC-A']
            return value
        with patch.object(AnalysisSourceReader,'read',revoked):
            response=self.request(ROOT+'/evidence/batch',self.body(analysisSessionId=created['analysisSessionId'],evidenceRefIds=[ref['evidenceRefId']]))
        self.assertEqual(response[0],403);self.assertNotIn('items',response[1]);self.assertNotIn('source',response[1])

    def test_revoke_during_batch_resolution_cannot_commit_a_reference_receipt(self):
        from apps.api.analysis_source_reader import AnalysisSourceReader
        from tools.analysis_draft_backup import export_package
        created,model,data,body,ref=self.register();original=AnalysisSourceReader.resolve
        before=export_package(self.urls[0])
        def revoked(reader,kind,selector):
            value=original(reader,kind,selector)
            self.source.permissions['writer']['SYNTHETIC-A']='viewer'
            return value
        request=self.body(analysisSessionId=created['analysisSessionId'],expectedAnalysisRevision=1,
            items=[{'key':'model','requestId':str(uuid4()),'sourceKind':'model','selector':body['selector']}])
        with patch.object(AnalysisSourceReader,'resolve',revoked):
            response=self.request(ROOT+'/evidence/register-batch',request)
        self.assertEqual((response[0],response[1]['code']),(409,'ACCESS_CHANGED'))
        self.assertEqual(export_package(self.urls[0]),before)
