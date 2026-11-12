"""Current drawings retain the selected identity through explicit HTTP reads."""
import hashlib
from http.server import ThreadingHTTPServer
from threading import Thread
import unittest

from apps.api.session_http import handler_type
from apps.api.workbench_server import WorkbenchSessions
import tests.test_scene_engineering as engineering
import tests.test_scene_engineering_http as object_http
import tests.test_scene_evidence as evidence
import tests.test_project_model_http as transport

ROOT = '/api/workbench/objects/evidence/'


class EvidenceHttpAuthority(object_http.ObjectAuthority):
    def __init__(self, base):
        super().__init__(base)
        self.engineering = evidence.EvidenceAuthority()

    def image(self, path, body):
        return self.engineering.image(path, body)


class SceneEvidenceHttpTests(unittest.TestCase):
    request = transport.ProjectModelHttpTests.request
    login = object_http.SceneEngineeringHttpTests.login
    account = object_http.SceneEngineeringHttpTests.account
    expect = object_http.SceneEngineeringHttpTests.expect

    def setUp(self):
        self.sessions = WorkbenchSessions('http://127.0.0.1:1234', engineering.PROJECT, engineering.CTX,
            factory=EvidenceHttpAuthority, ontobase_connection_id=engineering.CONNECTION)
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), handler_type(self.sessions, object_http.scene_http.ORIGIN, development=True))
        self.thread = Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.thread.join)
        self.addCleanup(self.server.shutdown)
        self.admin = self.login('synthetic-admin')

    def selection(self, uid=evidence.OTHER_CHILD):
        item = self.account().engineering.objects[uid]
        context = item['installationContextId']
        return {'entityUid': uid, 'installationContextId': context, 'expectedEntityRevision': item['entityRevision'],
                'expectedHierarchyRevision': self.account().engineering.contexts[context]['hierarchyRevision'] if context else None}

    def content_body(self, uid=evidence.OTHER_CHILD):
        body = self.selection(uid)
        source = self.account().engineering.metadata(body)
        return {**body, 'evidenceRef': source['evidenceRef'], 'expectedSourceRevision': source['sourceRevision'],
                'expectedContentSha256': source['contentSha256']}

    def test_other_installation_child_reads_own_template_drawing_and_private_png(self):
        status, value, _ = self.request(ROOT + 'resolve', self.selection())
        self.assertEqual(status, 200, value)
        self.assertEqual(value['items'][0]['sourceEntityUid'], 'synthetic-shared-definition')
        self.assertEqual(value['items'][0]['sourceRelation'], 'template_definition')
        status, data, headers = self.request(ROOT + 'content', self.content_body())
        self.assertEqual(status, 200, data)
        self.assertEqual(data, evidence.PNG)
        self.assertEqual(headers['Content-Type'], 'image/png')
        self.assertEqual(headers['Cache-Control'], 'no-store')
        self.assertEqual(headers['X-Session-Revision'], self.admin['revision'])
        self.assertEqual(headers['X-Content-SHA256'], hashlib.sha256(data).hexdigest())
        self.assertNotEqual(headers['X-Content-SHA256'], self.content_body()['expectedContentSha256'])
        calls = [body for _, path, body in self.account().engineering.calls if '/object-evidence/' in path]
        self.assertTrue(all(body['entityUid'] == evidence.OTHER_CHILD and body['installationContextId'] == engineering.OTHER_CTX for body in calls))
        self.assertNotIn('privateServerPath', str(value))
        self.assertNotIn('https://', str(value))

    def test_definition_and_incomplete_hierarchy_do_not_require_geometry_location(self):
        for uid in ('definition', evidence.OTHER_CHILD):
            if uid == evidence.OTHER_CHILD:
                self.account().engineering.parents.pop(uid)
            self.assertEqual(self.request(ROOT + 'resolve', self.selection(uid))[0], 200)
            self.assertEqual(self.request(ROOT + 'content', self.content_body(uid))[0], 200)
        self.assertIsNone(self.sessions.library)

    def test_old_source_and_content_conditions_reject_stale_preview(self):
        body = self.content_body()
        self.account().engineering.pdf = b'changed synthetic current source'
        self.expect(self.request(ROOT + 'content', body), 409, 'CONTENT_CHANGED')
        self.expect(self.request(ROOT + 'content', {**self.content_body(), 'expectedSourceRevision': 'f' * 64}), 409, 'SOURCE_CHANGED')

    def test_wrong_context_or_ancestor_host_cannot_replace_selected_object(self):
        selected = self.selection()
        self.expect(self.request(ROOT + 'resolve', {**selected, 'installationContextId': engineering.CTX}), 403, 'NOT_FOUND_OR_FORBIDDEN')
        self.expect(self.request(ROOT + 'resolve', {**selected, 'hostEntityUid': engineering.OTHER_ROOT}), 422, 'INVALID_REQUEST')
        self.assertFalse(any('/object-evidence/' in path for _, path, _ in self.account().engineering.calls))

    def test_unauthenticated_and_late_revocation_return_no_image(self):
        body = self.content_body()
        self.expect(self.request(ROOT + 'content', body, client=False), 401, 'SESSION_EXPIRED')
        account = self.account()
        account.engineering.image_after = lambda *_: setattr(account, 'allowed', False)
        self.expect(self.request(ROOT + 'content', body), 403, 'FORBIDDEN')

    def test_changed_grant_after_source_lookup_discards_evidence_list(self):
        account = self.account()
        account.engineering.evidence_after = lambda *_: setattr(account, 'grant', 'grant:changed')
        self.expect(self.request(ROOT + 'resolve', self.selection()), 409, 'ACCESS_CHANGED')

    def test_raw_source_project_and_unknown_output_fields_are_rejected(self):
        for fields in ({'representation': 'pdf'}, {'projectCode': 'other'}, {'url': 'http://arbitrary.invalid'}):
            self.expect(self.request(ROOT + 'content', {**self.content_body(), **fields}), 422, 'INVALID_REQUEST')
        self.assertEqual(self.account().engineering.calls, [])


if __name__ == '__main__':
    unittest.main()
