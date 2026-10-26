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
