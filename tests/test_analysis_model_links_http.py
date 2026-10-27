"""Actual HTTP/PG recommendation-to-link flow with synthetic engineering responses."""
from copy import deepcopy
import os
import unittest
from unittest.mock import patch
from uuid import uuid4

from apps.api import simulated_faults as sim
from apps.api.authority import PreviewError
from tests import test_analysis_http_integration as base, test_analysis_source_http_integration as sources

ROOT = '/api/workbench/analysis-sessions'


@unittest.skipUnless(os.environ.get('ONTOVIS_ANALYSIS_TEST_DATABASE_URL'), 'Disposable PG required')
class ModelLinksHttpTests(unittest.TestCase):
    setUpClass = classmethod(base.AnalysisHttpIntegrationTests.setUpClass.__func__)
    tearDownClass = classmethod(base.AnalysisHttpIntegrationTests.tearDownClass.__func__)
    setUp = base.AnalysisHttpIntegrationTests.setUp
    request = base.AnalysisHttpIntegrationTests.request
    login = base.AnalysisHttpIntegrationTests.login
    account = base.AnalysisHttpIntegrationTests.account
    start = base.AnalysisHttpIntegrationTests.start
    body = base.AnalysisHttpIntegrationTests.body
    value = base.AnalysisHttpIntegrationTests.value
    create = base.AnalysisHttpIntegrationTests.create
    model = sources.AnalysisSourceHttpTests.model
    demo = sources.AnalysisSourceHttpTests.demo

    def object(self, project, tag):
        return {'item': {'entityUid': 'synthetic-cabinet', 'entityRevision': 'r1', 'objectKind': 'cabinet', 'objectScope': 'definition',
            'identifiers': [{'value': tag, 'role': 'primary', 'scheme': 'RDS', 'status': 'accepted', 'scopeType': 'project', 'scopeKey': project}]}, 'context': None}

    def test_selected_object_model_candidate_is_not_a_binding_and_owner_scope_is_preserved(self):
        created, _ = self.create(); model, _ = self.model()
        metadata = self.sessions.shared.project_models.model(model['modelAssetId'], model['modelVersionId'], lambda: None)
        target = self.object('SYNTHETIC-A', metadata['components'][0]['displayName'])
        request = self.body(entry={'projectOnly': True}, section='models', entityUid='synthetic-cabinet', expectedEntityRevision='r1')
        with patch('apps.api.scene_engineering.SceneEngineeringReader.context_for_object', return_value=target), patch('apps.api.scene_engineering.SceneEngineeringReader.detail', return_value=target):
            recommendation = self.request(ROOT+'/recommendations', request)
            self.assertEqual(recommendation[0], 200, recommendation[1]); row = recommendation[1]['items'][0]
            self.assertEqual(row['matchType'], 'name_candidate')
            references = []
            for kind, selector in (('object', {'entityUid': 'synthetic-cabinet', 'expectedEntityRevision': 'r1'}), ('model', row['selector'])):
                response = self.request(ROOT+'/evidence/register', self.body(analysisSessionId=created['analysisSessionId'], expectedAnalysisRevision=1, requestId=str(uuid4()), sourceKind=kind, selector=selector))
                self.assertEqual(response[0], 200, response[1]); references.append(response[1]['evidenceRefId'])
            payload = self.body(analysisSessionId=created['analysisSessionId'], evidenceRefIds=references)
            linked = self.request(ROOT+'/evidence/relationships', payload)
            self.assertEqual(linked[0], 200, linked[1]); self.assertEqual(linked[1]['items'][0]['origin'], 'candidate')
            self.assertEqual(self.request(ROOT+'/evidence/relationships', payload, client=self.login('other'))[0], 404)
            self.assertEqual(self.request(ROOT+'/evidence/relationships', {**payload, 'projectRef': {**payload['projectRef'], 'projectCode': 'B'}})[0], 404)
        self.assertEqual(self.request(ROOT+'/recommendations', request, client=False)[0], 401)

    def test_selected_object_binding_uses_the_bound_fixed_version_without_demo_profile(self):
        created, _ = self.create(); model, _ = self.model()
        metadata = self.sessions.shared.project_models.model(model['modelAssetId'], model['modelVersionId'], lambda: None)
        target = self.object('SYNTHETIC-A', '=OTHER+SW9')
        binding = {'entityUid': 'synthetic-cabinet', 'modelVersionId': model['modelVersionId'],
            'componentKeys': [metadata['components'][0]['componentKey']], 'wholeModel': False,
            'sceneId': 'synthetic-scene', 'sceneRevision': 'fixed-scene', 'sceneState': 'active'}
        with patch('apps.api.scene_engineering.SceneEngineeringReader.context_for_object', return_value=target), patch('apps.api.analysis_model_links.scene_bindings', return_value=([binding], False)):
            response = self.request(ROOT+'/recommendations', self.body(entry={'projectOnly': True}, section='models', entityUid='synthetic-cabinet', expectedEntityRevision='r1'))
        self.assertEqual(response[0], 200, response[1]); row = response[1]['items'][0]
        self.assertEqual((row['matchType'], row['selector']['modelVersionId']), ('binding', model['modelVersionId']))

    def test_adding_alarm_then_mapped_object_changes_actual_relationship_response(self):
        project, created, _ = self.demo(); identity = sim.identity('13001')
        descriptor = {key: identity[key] for key in ('datasetId', 'datasetRevision')}
        alarm = self.request(ROOT+'/evidence/register', {'projectRef': project, 'analysisSessionId': created['analysisSessionId'], 'expectedAnalysisRevision': 1, 'requestId': str(uuid4()), 'sourceKind': 'alarm', 'selector': {**descriptor, 'eventId': identity['datasetId']+'-event-1'}})
        self.assertEqual(alarm[0], 200, alarm[1]); refs = [alarm[1]['evidenceRefId']]
        target = self.object('Demo-PDS', identity['primaryRds'])
        with patch('apps.api.scene_engineering.SceneEngineeringReader.context_for_object', return_value=target), patch('apps.api.scene_engineering.SceneEngineeringReader.detail', return_value=target):
            first = self.request(ROOT+'/evidence/relationships', {'projectRef': project, 'analysisSessionId': created['analysisSessionId'], 'evidenceRefIds': refs})
            self.assertEqual(first[1]['items'], [])
            obj = self.request(ROOT+'/evidence/register', {'projectRef': project, 'analysisSessionId': created['analysisSessionId'], 'expectedAnalysisRevision': 1, 'requestId': str(uuid4()), 'sourceKind': 'object', 'selector': {'entityUid': 'synthetic-cabinet', 'expectedEntityRevision': 'r1'}})
            self.assertEqual(obj[0], 200, obj[1]); refs.append(obj[1]['evidenceRefId'])
            second = self.request(ROOT+'/evidence/relationships', {'projectRef': project, 'analysisSessionId': created['analysisSessionId'], 'evidenceRefIds': refs})
        self.assertEqual(second[0], 200, second[1]); self.assertEqual(second[1]['items'][0]['kind'], 'alarm_object_mapping')
        self.assertEqual(second[1]['items'][0]['origin'], 'source')
