"""Cross-store recovery refuses dangling model and fixed work-order references."""
from copy import deepcopy
import io
import json
import os
import sqlite3
import unittest
from uuid import uuid4

from apps.api import analysis_drafts as draft
from apps.api.analysis_evidence import AnalysisEvidence
from apps.api.authority import PreviewError
from apps.api.model_library import ModelLibrary
from apps.api.project_model_library import ProjectModelLibrary
from tests import test_analysis_workbench_backup_integration as base
from tests.test_analysis_drafts import OWNER
from tests.test_model_upload import glb
from tools import analysis_workbench_backup as pair, analysis_draft_backup as backup


@unittest.skipUnless(os.environ.get('ONTOVIS_ANALYSIS_TEST_DATABASE_URL'), 'Set an owned disposable PG test connection')
class AnalysisSourcePairTests(unittest.TestCase):
    setUpClass=classmethod(base.AnalysisWorkbenchBackupTests.setUpClass.__func__)
    tearDownClass=classmethod(base.AnalysisWorkbenchBackupTests.tearDownClass.__func__)
    setUp=base.AnalysisWorkbenchBackupTests.setUp
    snapshot=base.AnalysisWorkbenchBackupTests.snapshot
    restore=base.AnalysisWorkbenchBackupTests.restore

    def model(self):
        root=self.source/'workbench-library'
        with sqlite3.connect(root/'library.sqlite3') as db:scope=db.execute('select project_code,context_id from library').fetchone()
        library=ModelLibrary(root,*scope);models=ProjectModelLibrary(library);data=glb(self.root/'reference.glb').read_bytes()
        return models.upload(io.BytesIO(data),len(data),{'expectedLibraryRevision':library.listing()['libraryRevision'],'clientRequestId':str(uuid4()),
            'displayName':'Synthetic recovery source','purpose':'equipment','sourceNote':'Synthetic fixture','rightsDeclared':True},'synthetic',lambda:None)

    def source_body(self):
        return {'analysisSessionId':self.created['analysisSessionId'],'expectedAnalysisRevision':2,'requestId':str(uuid4()),'sourceKind':'model','selector':{}}

    def test_paired_recovery_keeps_fixed_source_identity_and_original_scene(self):
        model=self.model();descriptor={key:model[key] for key in ('modelAssetId','modelVersionId','contentRevision','sha256')}
        reference=AnalysisEvidence(self.store).register(OWNER,self.source_body(),lambda:None,lambda *_:descriptor)
        receipt=self.snapshot();restored=self.restore(receipt)
        consumer=draft.AnalysisDrafts(self.urls[1],'ontobase-primary','SYNTHETIC-A');self.addCleanup(consumer.close)
        read=AnalysisEvidence(consumer).descriptor(OWNER,{'analysisSessionId':self.created['analysisSessionId'],'evidenceRefId':reference['evidenceRefId']},lambda:None)
        self.assertEqual(read[1],descriptor);self.assertEqual(restored['analysisCounts']['analysis_evidence_refs'],1)
        self.assertEqual(pair.verify(self.root/'paired',receipt['manifestSha256'])[2]['tables']['analysis_evidence_refs'][0]['descriptor_sha256'],reference['sourceRevision'])

    def test_configuration_reference_survives_paired_recovery(self):
        from apps.api.equipment_configurations import EquipmentConfigurations
        model=self.model()
        path=self.source/'project-spaces/libraries'/self.workspace['storage_key']
        with sqlite3.connect(path/'library.sqlite3') as db:project,context=db.execute('select project_code,context_id from library').fetchone()
        library=ModelLibrary(path,project,context)
        store=EquipmentConfigurations(library,'ontobase-primary','SYNTHETIC-A');cid=str(uuid4())
        saved=store.save({'configurationId':cid,'expectedConfigurationRevision':None,'clientRequestId':str(uuid4()),
            'snapshot':{'displayName':'共享型号','objectKind':'equipment','rootDefinition':None,
                'models':[{'modelVersionId':model['modelVersionId'],'mappings':[]}]}},OWNER,lambda:None,lambda _:None,lambda _:model['components'])
        descriptor={key:model[key] for key in ('modelAssetId','modelVersionId','contentRevision','sha256')}
        descriptor['configurationRefs']=[{'configurationId':cid,'configurationRevision':saved['configurationRevision'],'equipmentEntityUids':[]}]
        reference=AnalysisEvidence(self.store).register(OWNER,self.source_body(),lambda:None,lambda *_:descriptor)
        receipt=self.snapshot();self.restore(receipt)
        consumer=draft.AnalysisDrafts(self.urls[1],'ontobase-primary','SYNTHETIC-A');self.addCleanup(consumer.close)
        _,read=AnalysisEvidence(consumer).descriptor(OWNER,{'analysisSessionId':self.created['analysisSessionId'],'evidenceRefId':reference['evidenceRefId']},lambda:None)
        self.assertEqual(read['configurationRefs'],descriptor['configurationRefs'])

    def test_whole_project_photo_and_unpublished_pdf_keep_fixed_versions_after_paired_recovery(self):
        descriptors=[('photo',dict(sourceType='project_document',documentId=str(uuid4()),contentVersionId=str(uuid4()),sourceSha256='a'*64)),
                     ('document',dict(documentId=str(uuid4()),contentVersionId=str(uuid4()),sourceSha256='b'*64,pageNumber=2))]
        refs=[]
        for kind,descriptor in descriptors:
            body=self.source_body()|{'sourceKind':kind}
            refs.append(AnalysisEvidence(self.store).register(OWNER,body,lambda:None,lambda *_,value=descriptor:value))
        value=deepcopy(self.store.detail(OWNER,self.created['analysisSessionId'],lambda:None)['snapshot'])
        value['schemaVersion']=2
        for ref,(kind,_) in zip(refs,descriptors):
            value['cards'].append({'id':str(uuid4()),'kind':kind,'title':'Fixed pixel preview','x':100,'y':200,'width':340,'height':300,'pinned':False,
                'source':{'system':'ontobase','ontobaseConnectionId':'ontobase-primary','projectCode':'SYNTHETIC-A','id':ref['evidenceRefId'],'revision':ref['sourceRevision']},
                'view':{'zoom':.037739 if kind=='photo' else 1.3,'zoomBasis':'pixels','centerX':.4,'centerY':.6}})
        saved=self.store.write(OWNER,'admin','save',{'analysisSessionId':self.created['analysisSessionId'],'expectedAnalysisRevision':2,
            'requestId':str(uuid4()),'snapshot':value},lambda:None)
        self.assertEqual(saved['analysisRevision'],3)
        receipt=self.snapshot();restored=self.restore(receipt)
        consumer=draft.AnalysisDrafts(self.urls[1],'ontobase-primary','SYNTHETIC-A');self.addCleanup(consumer.close)
        for ref,(_,descriptor) in zip(refs,descriptors):
            _,read=AnalysisEvidence(consumer).descriptor(OWNER,{'analysisSessionId':self.created['analysisSessionId'],'evidenceRefId':ref['evidenceRefId']},lambda:None)
            self.assertEqual(read,descriptor)
        self.assertEqual(restored['analysisCounts']['analysis_evidence_refs'],2)
        self.assertEqual(consumer.detail(OWNER,self.created['analysisSessionId'],lambda:None)['snapshot'],value)

    def test_missing_fixed_geometry_is_rejected_before_publishing_paired_manifest(self):
        model=self.model();descriptor={key:model[key] for key in ('modelAssetId','modelVersionId','contentRevision','sha256')};descriptor['sha256']='f'*64
        AnalysisEvidence(self.store).register(OWNER,self.source_body(),lambda:None,lambda *_:descriptor)
        with self.assertRaises(PreviewError) as error:self.snapshot()
        self.assertEqual(error.exception.code,'ANALYSIS_PAIR_SOURCE_MISMATCH')
        self.assertFalse((self.root/'paired/manifest.json').exists())

    def assistant_transfer(self):
        from apps.api.assistant_store import AssistantStore
        from apps.api.assistant_work_orders import proposal
        from apps.api.work_orders import WorkOrders
        from tests.test_assistant import answer
        from unittest.mock import patch
        model = self.model(); descriptor = {key: model[key] for key in ('modelAssetId', 'modelVersionId', 'contentRevision', 'sha256')}
        ref = AnalysisEvidence(self.store).register(OWNER, self.source_body(), lambda: None, lambda *_: descriptor)
        shared_root = self.source/'workbench-library'
        with sqlite3.connect(shared_root/'library.sqlite3') as db:
            project, context = db.execute('select project_code,context_id from library').fetchone()
        assistant = AssistantStore(ModelLibrary(shared_root, project, context), 'ontobase-primary')
        body = {'requestId': str(uuid4()), 'analysisSessionId': self.created['analysisSessionId'],
                'expectedAnalysisRevision': 2, 'question': '合成工单联动恢复', 'evidenceRefIds': [ref['evidenceRefId']]}
        run, _ = assistant.begin('SYNTHETIC-A', OWNER, body, 1, 's'*64)
        assistant.update(run['id'], 'complete', sources=[{'key': 'E1', 'kind': 'model', 'availability': 'available',
            'evidenceRefId': ref['evidenceRefId'], 'sourceRevision': ref['sourceRevision'], 'summaryHash': 'a'*64}],
            result={'answer': answer()})
        proposed = proposal(assistant.public(assistant.run('SYNTHETIC-A', OWNER, run['id'])))
        root = self.source/'project-spaces/libraries'/self.workspace['storage_key']
        with sqlite3.connect(root/'library.sqlite3') as db:
            project, context = db.execute('select project_code,context_id from library').fetchone()
        orders = WorkOrders(ModelLibrary(root, project, context), project)
        with patch('apps.api.work_orders.DEMO_PROJECT', project):
            orders.seed({'requestId': str(uuid4()), 'expectedSnapshotRevision': 'work-orders:empty'},
                        {key: {'entityUid': 'synthetic-'+key} for key in ('CN', 'CN1')}, OWNER, lambda: None)
        identifier = orders.listing({}, True)['items'][0]['orderId']
        orders.action({'requestId': str(uuid4()), 'orderId': identifier, 'expectedOrderRevision': 1,
                       'action': 'accept', 'checks': [], 'note': ''}, OWNER, lambda: None)
        value = orders.apply_assistant({'requestId': str(uuid4()), 'runId': run['id'], 'orderId': identifier,
            'expectedOrderRevision': 2, 'expectedProposalSha256': proposed['proposalSha256'],
            'items': [{'id': 'hypotheses-0', 'text': '合成待验证假设', 'targetKey': ''}]}, OWNER, lambda: None,
            proposed, {'contentSha256': self.saved['contentSha256']})
        return value, orders, assistant, run['id']

    def test_assistant_transfer_restores_immutable_provenance_and_its_original_run(self):
        value, orders, assistant, run_id = self.assistant_transfer()
        receipt = self.snapshot(); self.restore(receipt)
        target = self.root/'recovered/workbench/project-spaces/libraries'/self.workspace['storage_key']/'library.sqlite3'
        with sqlite3.connect(target) as db:
            transfer = json.loads(db.execute('select snapshot_json from work_order_assistant_transfers').fetchone()[0])
            self.assertEqual(value['assistantTransfers'][0], transfer)
            self.assertEqual(3, db.execute('select revision from work_orders where order_id=?', (value['orderId'],)).fetchone()[0])
        shared = self.root/'recovered/workbench/workbench-library/library.sqlite3'
        with sqlite3.connect(shared) as db:
            self.assertEqual('complete', db.execute('select state from assistant_runs where id=?', (run_id,)).fetchone()[0])

    def test_assistant_source_owner_mismatch_refuses_a_new_backup(self):
        value, orders, assistant, run_id = self.assistant_transfer()
        with assistant.library.connect() as db:
            db.execute('update assistant_runs set owner=? where id=?', (str(uuid4()), run_id))
        with self.assertRaises(PreviewError) as found: self.snapshot()
        self.assertEqual('ANALYSIS_PAIR_ASSISTANT_MISMATCH', found.exception.code)
        self.assertFalse((self.root/'paired/manifest.json').exists())
