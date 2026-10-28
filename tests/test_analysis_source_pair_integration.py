"""Cross-store recovery refuses dangling model and fixed work-order references."""
from copy import deepcopy
import io
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

    def test_missing_fixed_geometry_is_rejected_before_publishing_paired_manifest(self):
        model=self.model();descriptor={key:model[key] for key in ('modelAssetId','modelVersionId','contentRevision','sha256')};descriptor['sha256']='f'*64
        AnalysisEvidence(self.store).register(OWNER,self.source_body(),lambda:None,lambda *_:descriptor)
        with self.assertRaises(PreviewError) as error:self.snapshot()
        self.assertEqual(error.exception.code,'ANALYSIS_PAIR_SOURCE_MISMATCH')
        self.assertFalse((self.root/'paired/manifest.json').exists())
