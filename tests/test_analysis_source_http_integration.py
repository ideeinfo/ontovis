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

    def read_bytes(self,path,payload):
        connection=HTTPConnection(*self.server.server_address,timeout=5)
        try:
            connection.request('POST',path,json.dumps(payload|{'expectedSessionRevision':self.admin['revision']}),
                {'Host':'127.0.0.1:4180','Origin':'http://127.0.0.1:4180','Content-Type':'application/json','Cookie':self.admin['cookie']})
            response=connection.getresponse();self.assertEqual(response.status,200);self.assertEqual(response.getheader('Cache-Control'),'no-store')
            return response.read()
        finally:connection.close()

    def test_project_document_photo_registers_and_reads_without_object_or_region(self):
        from tests.test_equipment_materials import DocumentReader, DOC, VERSION, PNG
        from tools.analysis_draft_backup import export_package, validate_package
        created,_=self.create();fixed=DocumentReader();fixed.version['preview_kind']='image'
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
            self.assertTrue(self.read_bytes(ROOT+'/evidence/preview-content',payload).startswith(b'\xff\xd8\xff'))
            self.assertEqual(self.request(ROOT+'/evidence/relationships',self.body(analysisSessionId=created['analysisSessionId'],evidenceRefIds=[ref['evidenceRefId']]))[1]['items'],[])
            package=export_package(self.urls[0]);validate_package(package)
            row=next(row for row in package['tables']['analysis_evidence_refs'] if row['evidence_ref_id']==ref['evidenceRefId'])
            self.assertEqual(json.loads(row['descriptor_json']),selector|{'sourceSha256':'a'*64})
            fixed.version['source_sha256']='c'*64
            self.assertNotEqual(self.request(ROOT+'/evidence/detail',payload)[1]['availability'],'available')

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
        self.assertEqual(value[1]['sourceKind'],'simulated');self.assertEqual(len(value[1]['items']),5)
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
        self.assertTrue(self.sessions.analysis_slots.acquire(blocking=False));self.assertTrue(self.sessions.analysis_slots.acquire(blocking=False))
        self.assertFalse(self.sessions.analysis_slots.acquire(blocking=False));self.sessions.analysis_slots.release();self.sessions.analysis_slots.release()

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
