"""Inspection reads through existing HTTP/session and shared-library boundaries."""
import unittest
from unittest.mock import patch

from tests import test_project_model_http as http_fixtures
from tests import test_shared_models as shared_fixtures
from tests.test_project_workspaces import ProjectsAuthority


class ModelInspectionHttpTests(unittest.TestCase):
    def setUp(self):
        self.fixture = http_fixtures.ProjectModelHttpTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.version = self.fixture.new_version()
        self.body = {'modelVersionId': self.version['modelVersionId'],
                     'expectedContentRevision': self.version['contentRevision'], 'expectedSha256': self.version['sha256']}

    def request(self, body=None, **options):
        return self.fixture.request('/api/workbench/resources/model/inspection', self.body if body is None else body, **options)

    def test_reader_can_read_current_report_with_no_store_and_session_revision(self):
        member = self.fixture.login('fixture-reader')
        self.fixture.authority(member).role = 'reader'
        status, result, headers = self.request(client=member)
        self.assertEqual(status, 200, result)
        self.assertEqual(headers['Cache-Control'], 'no-store')
        self.assertEqual(result['sessionRevision'], member['revision'])
        self.assertEqual(result['sha256'], self.version['sha256'])
        self.assertEqual(len(result['sourceNodes']), 3)
        self.assertFalse(result['capabilities']['canUpload'])
        self.assertFalse(result['bindingMigrationApproved'])

    def test_anonymous_logout_revocation_and_stale_session_are_rejected(self):
        self.assertEqual(self.request(client=False)[0], 401)
        self.assertEqual(self.request({'expectedSessionRevision': 'stale', **self.body})[0], 409)
        reader = self.fixture.login('revoked-reader')
        self.fixture.authority(reader).allowed = False
        self.assertEqual(self.request(client=reader)[0], 403)
        self.fixture.request('/api/session/logout')
        self.assertEqual(self.request()[0], 401)

    def test_exact_reference_and_bounded_same_origin_post_are_required(self):
        self.assertEqual(self.request({**self.body, 'expectedSha256': '0' * 64})[0], 409)
        self.assertEqual(self.request({**self.body, 'expectedContentRevision': 'stale'})[0], 409)
        self.assertEqual(self.request({**self.body, 'path': '/etc/passwd'})[0], 422)
        self.assertEqual(self.request(headers={'Origin': 'https://other.invalid'})[0], 403)
        self.assertEqual(self.request(raw=b' ' * 16385)[0], 413)
        self.assertEqual(self.request(method='GET')[0], 404)
        self.assertEqual(self.fixture.request('/api/workbench/resources/model/inspection?x=1', self.body)[0], 404)

    def test_logout_while_worker_is_processing_suppresses_the_report(self):
        engine = self.fixture.sessions.model_inspection
        original = engine._process
        def logout(path):
            result = original(path)
            self.fixture.request('/api/session/logout')
            return result
        with patch.object(engine, '_process', side_effect=logout):
            self.assertEqual(self.request()[0], 401)


class ModelInspectionSharedTests(unittest.TestCase):
    def setUp(self):
        self.fixture = shared_fixtures.SharedModelTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.version = self.fixture.upload()

    def read(self, **changes):
        return self.fixture.resource('model/inspection', modelVersionId=self.version['modelVersionId'],
            expectedContentRevision=self.version['contentRevision'], expectedSha256=self.version['sha256'], **changes)

    def test_current_active_user_without_projects_can_read_shared_report(self):
        ProjectsAuthority.permissions['member'] = {}
        result = self.read()
        self.assertEqual(result['capabilities']['scope'], 'shared_static_glb_resources')
        self.assertFalse(result['capabilities']['canUpload'])
        self.assertNotIn('projectRef', result)
        self.assertEqual(len(result['sourceNodes']), 3)
        self.assertEqual(list(self.fixture.sessions.registry.root.glob('libraries/*')), [])

    def test_identity_disabled_after_processing_is_rejected_and_session_cleared(self):
        engine = self.fixture.sessions.shared.model_inspection
        original = engine._process
        row = self.fixture.sessions.current(self.fixture.sid)
        request = row.authority.request
        def disable(path):
            value = original(path)
            row.authority.request = lambda method, path, body=None: ({'user': {'username': row.authority.username, 'is_active': False}}
                if path == '/api/v1/auth/me' else request(method, path, body))
            return value
        with patch.object(engine, '_process', side_effect=disable):
            self.fixture.assertCode('SESSION_EXPIRED', self.read)
        self.assertNotIn(self.fixture.sid, self.fixture.sessions.rows)


if __name__ == '__main__':
    unittest.main()
