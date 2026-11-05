"""Encrypted task configuration must survive the complete PG + file recovery."""
import os
import json
import sqlite3
import unittest
from uuid import uuid4
from apps.api.assistant_models import AssistantModels,defaults
from apps.api.llm_providers import PROVIDERS
from apps.api.model_library import ModelLibrary
from tests import test_analysis_workbench_backup_integration as base
from tests.test_analysis_drafts import OWNER
from tools.analysis_draft_backup import export_package

@unittest.skipUnless(os.environ.get('ONTOVIS_ANALYSIS_TEST_DATABASE_URL'), 'Set an owned disposable PG test connection')
class LlmConfigurationPairTests(unittest.TestCase):
    setUpClass=classmethod(base.AnalysisWorkbenchBackupTests.setUpClass.__func__)
    tearDownClass=classmethod(base.AnalysisWorkbenchBackupTests.tearDownClass.__func__)
    setUp=base.AnalysisWorkbenchBackupTests.setUp
    snapshot=base.AnalysisWorkbenchBackupTests.snapshot
    restore=base.AnalysisWorkbenchBackupTests.restore

    def models(self, root):
        with sqlite3.connect(root/'library.sqlite3') as db:project,context=db.execute('select project_code,context_id from library').fetchone()
        return AssistantModels(ModelLibrary(root,project,context),'ontobase-primary')

    def test_paired_recovery_retains_all_provider_keys_task_routes_and_original_evidence(self):
        models=self.models(self.source/'workbench-library')
        from cryptography.fernet import Fernet
        # Existing credentials are historical data, never a new connection source.
        config=models.read('SYNTHETIC-A')['config'];cipher=Fernet(models._key(True))
        for provider in PROVIDERS:
            raw=json.dumps(dict(connection='ontobase-primary',project='SYNTHETIC-A',provider=provider,key='synthetic-only-'+provider))
            config['providers'][provider]['credential']=cipher.encrypt(raw.encode()).decode()
        with models.library.connect() as db:
            db.execute('insert into assistant_model_configs values(?,?,?,?,?,?)',('ontobase-primary','SYNTHETIC-A',1,json.dumps(config),OWNER,'fixture'))
        for task in ('analysis','query','work_order'):
            models.save('SYNTHETIC-A',OWNER,dict(requestId=str(uuid4()),expectedRevision=models.read('SYNTHETIC-A')['revision'],
                expectedAccessRevision='synthetic',change=dict(kind='capability',taskId=task,
                    settings={**defaults(task),'goal':'Synthetic '+task},expectedConnectionVersion=None)),lambda:None,lambda *_:None)
        before=models.read('SYNTHETIC-A');original=export_package(self.urls[0])
        receipt=self.snapshot();self.restore(receipt)
        root=self.root/'recovered/workbench/workbench-library';restored=self.models(root)
        self.assertEqual(restored.read('SYNTHETIC-A'),before)
        for provider in PROVIDERS:self.assertEqual(restored._secret('SYNTHETIC-A',provider,restored.read('SYNTHETIC-A')['config']['providers'][provider]['credential']),'synthetic-only-'+provider)
        self.assertEqual((root/'llm-credentials.key').stat().st_mode&0o777,0o600)
        self.assertEqual(export_package(self.urls[0]),original)
        recovered=export_package(self.urls[1])
        self.assertNotEqual(recovered['sourceStoreId'],original['sourceStoreId'])
        self.assertEqual({k:v for k,v in recovered['tables'].items() if k!='store_meta'},
            {k:v for k,v in original['tables'].items() if k!='store_meta'})
        self.assertEqual(restored.read('OTHER-PROJECT')['revision'],0)
