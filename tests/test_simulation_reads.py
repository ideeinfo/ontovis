"""Simulation viewing needs current project access, not an analysis database."""
import unittest
from unittest.mock import patch

from apps.api.authority import PreviewError
from apps.api import simulated_faults as sim
from tests import test_project_workspaces as projects

ROOT = '/api/workbench/analysis-sessions/simulation/'


class SimulationReadTests(unittest.TestCase):
    def setUp(self):
        self.fixture = projects.ProjectWorkspaceTests(); self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.sessions = self.fixture.sessions
        catalogue = patch.dict(projects.ProjectsAuthority.projects, {'Demo-PDS': 'Synthetic demo'})
        catalogue.start(); self.addCleanup(catalogue.stop)
        grants = patch.dict(projects.ProjectsAuthority.permissions['member'], {'Demo-PDS': 'viewer'})
        grants.start(); self.addCleanup(grants.stop)
        unavailable = patch('apps.api.analysis_drafts.AnalysisDrafts', side_effect=AssertionError('Unrelated analysis database'))
        unavailable.start(); self.addCleanup(unavailable.stop)

    def read(self, action='catalogue', project='Demo-PDS', **body):
        return self.sessions.analysis_request(self.fixture.sid, ROOT+action, self.fixture.payload(project, **body))

    def test_readonly_view_works_without_analysis_storage_or_workspace(self):
        authority = self.sessions.current(self.fixture.sid).authority
        with patch.object(authority, 'request', wraps=authority.request) as requests:
            value = self.read(includeDetail=True)
        self.assertEqual(requests.call_args_list[0].args, ('GET', '/api/v1/projects/Demo-PDS/access'))
        self.assertEqual(requests.call_count, 1)
        self.assertEqual(len(value['initialDetail']['trends']), 5)
        self.assertEqual(value['capabilities'], {'canWrite': False, 'canConfirmConclusion': False})
        self.assertIsNone(self.sessions.registry.lookup('Demo-PDS'))
        item = value['items'][1]
        self.assertEqual(self.read('detail', **{key:item[key] for key in ('datasetId','datasetRevision')})['dataset'], item)

    def test_revocation_is_checked_again_and_other_project_does_not_receive_demo(self):
        self.read()
        del projects.ProjectsAuthority.permissions['member']['Demo-PDS']
        with self.assertRaises(PreviewError) as denied: self.read(includeDetail=True)
        self.assertEqual(denied.exception.status, 403)
        with self.assertRaises(PreviewError) as other: self.read(project='B', includeDetail=True)
        self.assertEqual(other.exception.code, 'SIMULATION_PROJECT_REQUIRED')

    def test_expired_source_invalidates_session_before_returning_data(self):
        authority = self.sessions.current(self.fixture.sid).authority
        with patch.object(authority, 'request', side_effect=PreviewError(401, 'SESSION_EXPIRED')):
            with self.assertRaises(PreviewError): self.read(includeDetail=True)
        with self.assertRaises(PreviewError): self.sessions.current(self.fixture.sid)

    def test_logout_during_generation_does_not_return_a_late_replay(self):
        original = sim.browser_catalogue
        def logout(project, body):
            self.sessions.logout(self.fixture.sid, self.fixture.revision)
            return original(project, body)
        with patch.object(sim, 'browser_catalogue', side_effect=logout):
            with self.assertRaises(PreviewError) as denied: self.read(includeDetail=True)
        self.assertEqual(denied.exception.status, 401)

    def test_session_revision_and_fixed_dataset_revision_remain_required(self):
        with self.assertRaises(PreviewError) as stale:
            self.sessions.analysis_request(self.fixture.sid,ROOT+'catalogue',self.fixture.payload('Demo-PDS',expectedSessionRevision='stale'))
        self.assertEqual(stale.exception.code,'SESSION_CHANGED')
        with self.assertRaises(PreviewError) as changed:
            self.read('detail',datasetId='SIM-PDS-13001',datasetRevision='changed')
        self.assertEqual(changed.exception.code,'SIMULATION_DATASET_CHANGED')
