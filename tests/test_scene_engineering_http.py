"""Explicit scene-object reads over real HTTP and synthetic current authority."""
from http.server import ThreadingHTTPServer
import json
from threading import Event, Thread
import unittest

from apps.api.session_http import handler_type
from apps.api.workbench_server import WorkbenchSessions
import tests.test_scene_engineering as engineering
import tests.test_scene_http as scene_http


ROOT = '/api/workbench/objects/'


class ObjectAuthority(scene_http.SceneAuthority):
    def __init__(self, base):
        super().__init__(base)
        self.project = engineering.PROJECT
        self.engineering = engineering.SyntheticAuthority()

    def request(self, method, path, body=None):
        if path.startswith('/api/v1/auth/') or path.endswith('/access'):
            return super().request(method, path, body)
        return self.engineering.request(method, path, body)


class SceneEngineeringHttpTests(unittest.TestCase):
    request = scene_http.SceneHttpTests.request
    login = scene_http.SceneHttpTests.login
    account = scene_http.SceneHttpTests.account

    def setUp(self):
        self.sessions = WorkbenchSessions('http://127.0.0.1:1234', engineering.PROJECT, engineering.CTX,
            ontobase_connection_id=engineering.CONNECTION, factory=ObjectAuthority)
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), handler_type(self.sessions, scene_http.ORIGIN, development=True))
        self.thread = Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.thread.join)
        self.addCleanup(self.server.shutdown)
        self.admin = self.login('synthetic-admin')

    def detail_body(self, uid=engineering.CHILD):
        return {'installationContextId': engineering.CTX, 'entityUid': uid,
                'expectedHierarchyRevision': engineering.CTX + ':7'}

    def expect(self, response, status, code):
        self.assertEqual(response[0], status, response[1])
        self.assertEqual(response[1], {'code': code})

    def test_context_is_discovered_from_exact_object_not_legacy_default_installation(self):
        self.account().calls.clear()
        status, value, _ = self.request(ROOT + 'context', {'entityUid': engineering.OTHER_ROOT})
        self.assertEqual(status, 200, value)
        self.assertEqual(value['context']['installationContextId'], engineering.OTHER_CTX)
        self.assertEqual(value['objectRef']['ontobaseConnectionId'], engineering.CONNECTION)
        self.assertEqual(value['sessionRevision'], self.admin['revision'])
        self.assertTrue(value['bindingEligible'])
        paths = [path for _, path, _ in self.account().engineering.calls]
        self.assertFalse(any(engineering.CTX in path for path in paths))
        self.assertFalse(any(method != 'GET' and not path.endswith('/objects/resolve')
                             for method, path, _ in self.account().engineering.calls))
        self.assertNotIn('privateServerPath', json.dumps(value))
        self.assertEqual(sum(path.endswith('/access') for _, path in self.account().calls), 3)

    def test_explicit_detail_and_children_keep_current_context_and_revisions(self):
        body = self.detail_body()
        status, detail, _ = self.request(ROOT + 'detail', body)
        self.assertEqual(status, 200, detail)
        self.assertEqual([row['object']['entityUid'] for row in detail['ancestors']['path']],
                         [engineering.CABINET, engineering.ROOT])
        status, children, _ = self.request(ROOT + 'children', self.detail_body(engineering.CABINET))
        self.assertEqual(status, 200, children)
        self.assertEqual(children['items'][0]['object']['entityUid'], engineering.CHILD)
        self.assertEqual(children['hierarchyRevision'], body['expectedHierarchyRevision'])
        self.assertIsNotNone(children['nextCursor'])
        status, _, _ = self.request(ROOT + 'children', {**self.detail_body(engineering.CABINET),
                                                       'cursor': children['nextCursor']})
        self.assertEqual(status, 200)

    def test_definitions_remain_readable_without_claiming_installation_or_binding(self):
        status, value, _ = self.request(ROOT + 'detail', {'entityUid': 'definition',
            'installationContextId': None, 'expectedHierarchyRevision': None})
        self.assertEqual(status, 200, value)
        self.assertEqual(value['item']['objectScope'], 'definition')
        self.assertFalse(value['bindingEligible'])
        self.assertIsNone(value['expectation'])
        self.assertFalse(any('/installations/' in path for _, path, _ in self.account().engineering.calls))

    def test_read_only_member_can_read_independent_of_model_storage(self):
        self.account().role = 'reader'
        self.assertIsNone(self.sessions.library)
        self.assertEqual(self.request(ROOT + 'context', {'entityUid': engineering.CHILD})[0], 200)
        self.assertEqual(self.request(ROOT + 'children', self.detail_body(engineering.ROOT))[0], 200)

    def test_wrong_context_and_stale_conditions_are_not_upgraded_to_latest(self):
        self.expect(self.request(ROOT + 'detail', {**self.detail_body(),
            'installationContextId': engineering.OTHER_CTX}), 403, 'NOT_FOUND_OR_FORBIDDEN')
        self.expect(self.request(ROOT + 'detail', {**self.detail_body(),
            'expectedHierarchyRevision': 'old'}), 409, 'ENGINEERING_CHANGED')
        self.expect(self.request(ROOT + 'context', {'entityUid': engineering.CHILD,
            'expectedEntityRevision': 'old'}), 409, 'ENGINEERING_CHANGED')

    def test_incomplete_path_is_readable_but_never_returns_binding_expectation(self):
        self.account().engineering.parents.pop(engineering.CABINET)
        status, value, _ = self.request(ROOT + 'detail', self.detail_body())
        self.assertEqual(status, 200, value)
        self.assertEqual(value['ancestors']['completeness'], 'incomplete')
        self.assertFalse(value['bindingEligible'])
        self.assertIsNone(value['expectation'])

    def test_unauthenticated_or_revoked_user_cannot_read_object_payload(self):
        self.expect(self.request(ROOT + 'context', {'entityUid': engineering.CHILD}, client=False), 401, 'SESSION_EXPIRED')
        account = self.account()
        account.engineering.after = lambda *_: setattr(account, 'allowed', False)
        self.expect(self.request(ROOT + 'context', {'entityUid': engineering.CHILD}), 403, 'FORBIDDEN')

    def test_grant_change_during_current_read_discards_all_object_content(self):
        account = self.account()
        account.engineering.after = lambda *_: setattr(account, 'grant', 'grant:changed')
        self.expect(self.request(ROOT + 'context', {'entityUid': engineering.CHILD}), 409, 'ACCESS_CHANGED')

    def test_expired_and_changed_sessions_are_rejected_before_upstream_identity_read(self):
        self.expect(self.request(ROOT + 'context', {'entityUid': engineering.CHILD,
            'expectedSessionRevision': 'stale'}), 409, 'SESSION_CHANGED')
        account = self.account()
        account.expired = True
        self.expect(self.request(ROOT + 'context', {'entityUid': engineering.CHILD}), 401, 'SESSION_EXPIRED')
        self.assertEqual(account.engineering.calls, [])

    def test_project_connection_and_arbitrary_fields_cannot_change_read_scope(self):
        for field, value in [('projectCode', 'other'), ('ontobaseConnectionId', 'other'),
                             ('source', 'http://arbitrary.invalid'), ('installationContextId', engineering.OTHER_CTX)]:
            self.expect(self.request(ROOT + 'context', {'entityUid': engineering.CHILD, field: value}), 422, 'INVALID_REQUEST')
        self.expect(self.request(ROOT + 'detail', {'entityUid': engineering.CHILD}), 422, 'INVALID_REQUEST')
        self.assertEqual(self.account().engineering.calls, [])

    def test_request_method_origin_duplicate_fields_and_read_limit_stay_restricted(self):
        self.expect(self.request(ROOT + 'context', method='GET'), 404, 'NOT_FOUND')
        self.expect(self.request(ROOT + 'context', {'entityUid': engineering.CHILD},
            headers={'Origin': 'http://other.invalid'}), 403, 'FORBIDDEN')
        raw = json.dumps({'expectedSessionRevision': self.admin['revision'], 'entityUid': engineering.CHILD})
        raw = raw[:-1] + ',"entityUid":"another"}'
        self.expect(self.request(ROOT + 'context', raw=raw.encode()), 422, 'INVALID_REQUEST')
        self.expect(self.request(ROOT + 'context', raw=b'{}', headers={'Content-Length': '16385'}), 413, 'INVALID_REQUEST')

    def test_direct_upstream_401_invalidates_only_the_current_session(self):
        account = self.account()
        def expired(*_args):
            raise scene_http.PreviewError(401, 'SESSION_EXPIRED')
        account.engineering.request = expired
        self.expect(self.request(ROOT + 'context', {'entityUid': engineering.CHILD}), 401, 'SESSION_EXPIRED')
        self.assertNotIn(self.admin['cookie'].split('=', 1)[1], self.sessions.rows)

    def test_logout_during_read_discards_late_details_without_touching_new_session(self):
        account = self.account()
        started, release = Event(), Event()
        def hold(*_args):
            started.set()
            release.wait(3)
        account.engineering.after = hold
        result = []
        worker = Thread(target=lambda: result.append(self.request(ROOT + 'context', {'entityUid': engineering.CHILD})))
        worker.start()
        try:
            self.assertTrue(started.wait(3))
            self.assertEqual(self.request('/api/session/logout')[0], 200)
            fresh = self.login('synthetic-admin')
        finally:
            release.set()
            worker.join(4)
        self.assertFalse(worker.is_alive())
        self.expect(result[0], 401, 'SESSION_EXPIRED')
        self.assertIn(fresh['cookie'].split('=', 1)[1], self.sessions.rows)
        self.assertEqual(self.request(ROOT + 'context', {'entityUid': engineering.CHILD}, client=fresh)[0], 200)

    def test_bad_configured_connection_identity_is_refused_without_new_source_calls(self):
        for value in ['', ' whitespace ', 'newline\n', 1]:
            with self.assertRaises(ValueError):
                WorkbenchSessions('http://127.0.0.1:1234', engineering.PROJECT, engineering.CTX,
                                  ontobase_connection_id=value, factory=ObjectAuthority)


if __name__ == '__main__':
    unittest.main()
