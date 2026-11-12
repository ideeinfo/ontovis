"""Cockpit event navigation must not resume another fixed source/window/identity."""
from copy import deepcopy
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock, patch
from uuid import uuid4

from apps.api.analysis_queries import start_analysis


class CreateReached(Exception):
    pass


class CockpitAnalysisResumeTests(TestCase):
    def setUp(self):
        self.dataset = dict(datasetId='SIM-PDS-13001', datasetRevision='fixed-revision',
                            sourceConnectionId='simulation-source', faultCode='13001',
                            title='Fixed simulated event', primaryRds='=A+CN1-T1',
                            timeFrom='2026-10-30T00:00:00Z', timeTo='2026-10-30T00:20:00Z')
        self.context = {k: self.dataset[k] for k in ('datasetId','datasetRevision','sourceConnectionId','timeFrom','timeTo')}
        self.context.update(eventId='SIM-PDS-13001-event-1', objectIds=['installed-1'])
        self.store = SimpleNamespace(connection_id='source', project_code='P', write=Mock(side_effect=CreateReached))
        self.reader = SimpleNamespace(_rds=Mock(return_value={'item': {'entityUid': 'installed-1'}}))

    def start(self, context):
        history = [{'analysisSessionId':'prior', 'analysisRevision':3, 'snapshot':{'context':context}}]
        with patch('apps.api.analysis_queries.entry_dataset', return_value=(self.dataset, None)), \
             patch('apps.api.analysis_queries.matching_history', return_value=history):
            return start_analysis(self.store, 'user', self.reader,
                                  {'entry':{'datasetId':self.dataset['datasetId'],'datasetRevision':self.dataset['datasetRevision']},
                                   'requestId':str(uuid4())}, lambda:None)

    def test_same_fixed_event_returns_existing_owned_analysis_without_writing(self):
        result=self.start(self.context)
        self.assertTrue(result['resumed'])
        self.assertEqual(result['analysisSessionId'], 'prior')
        self.store.write.assert_not_called()

    def test_changed_source_revision_requires_a_new_analysis(self):
        context=deepcopy(self.context);context['datasetRevision']='older-revision'
        with self.assertRaises(CreateReached):self.start(context)

    def test_changed_window_does_not_overwrite_prior_analysis(self):
        context=deepcopy(self.context);context['timeTo']='2026-10-30T01:00:00Z'
        with self.assertRaises(CreateReached):self.start(context)

    def test_same_alarm_code_on_another_installation_is_not_reused(self):
        context=deepcopy(self.context);context['objectIds']=['installed-2']
        with self.assertRaises(CreateReached):self.start(context)

    def test_legacy_analysis_without_fixed_revision_is_only_a_history_candidate(self):
        context=deepcopy(self.context);context.pop('datasetRevision')
        with self.assertRaises(CreateReached):self.start(context)
