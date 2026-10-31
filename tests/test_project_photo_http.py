"""A photo click makes one protected source read, without workspace gates."""
from http.server import ThreadingHTTPServer
from pathlib import Path
import tempfile
from threading import Event, Thread
import unittest
from unittest.mock import patch
from urllib.parse import unquote

from apps.api.authority import PreviewError
from apps.api.project_sessions import ProjectSessions
from apps.api.session_http import handler_type
from tests.test_project_workspaces import ProjectsAuthority
from tests.test_scene_photos import PhotoAuthority
from tests import test_scene_http as transport
from tests import test_project_model_http as models

ROOT = '/api/workbench/objects/photos/'


class Source(ProjectsAuthority):
    def __init__(self, url):
        super().__init__(url); self.photos = PhotoAuthority(); self.grants = 0
        self.after = None

    def check(self, path):
        code = unquote(path.split('/')[4])
        if code not in self.permissions[self.username]: raise PreviewError(403, 'FORBIDDEN')
        if code != 'Demo-PDS': raise PreviewError(404, 'NOT_FOUND_OR_FORBIDDEN')

    def request(self, method, path, body=None):
        if path.endswith('/access'): self.grants += 1
        if '/object-evidence/photos/' not in path: return super().request(method, path, body)
        self.check(path)
        result = self.photos.request(method, path, body)
        if self.after: self.after()
        self.check(path)
        return result

    def photo(self, path, body, digest):
        self.check(path)
        result = self.photos.photo(path, body, digest)
        if self.after: self.after()
        self.check(path)
        return result


class ProjectPhotoHttpTests(unittest.TestCase):
    request = models.ProjectModelHttpTests.request
    login = transport.SceneHttpTests.login
    account = transport.SceneHttpTests.account

    def setUp(self):
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        root = Path(temp.name).resolve()
        for key, value in [('projects', {'Demo-PDS': 'Synthetic', 'B': 'Other'}),
                           ('permissions', {'member': {'Demo-PDS': 'member', 'B': 'member'}})]:
            context = patch.object(Source, key, value); context.start(); self.addCleanup(context.stop)
        self.sessions = ProjectSessions('http://127.0.0.1:1234', library_root=root/'shared',
                                       workspace_root=root/'projects', factory=Source)
        self.addCleanup(self.sessions.close)
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), handler_type(self.sessions, transport.ORIGIN, development=True))
        thread = Thread(target=self.server.serve_forever, daemon=True); thread.start()
        self.addCleanup(self.server.server_close); self.addCleanup(thread.join); self.addCleanup(self.server.shutdown)
        self.admin = self.login('member')

    def body(self, content=False):
        item = self.account().photos.objects['definition']
        body = {'entityUid': 'definition', 'expectedEntityRevision': item['entityRevision'],
                'installationContextId': None, 'expectedHierarchyRevision': None}
        if content:
            row = self.account().photos.metadata(body)['items'][0]
            body.update(evidenceRef=row['evidenceRef'], expectedSourceRevision=row['sourceRevision'],
                expectedContentVersionId=row['contentVersionId'], expectedSourceSha256=row['sourceSha256'],
                expectedDisplayRevision=row['selector']['displayRevision'])
        return {**body, 'projectRef': {'ontobaseConnectionId': 'ontobase-primary', 'projectCode': 'Demo-PDS'}}

    def test_one_source_read_no_grant_roundtrip_or_workspace_required(self):
        source = self.account(); source.grants = 0; source.photos.calls.clear()
        status, value, _ = self.request(ROOT+'resolve', self.body())
        self.assertEqual(status, 200, value)
        self.assertEqual(len(value['items']), 1)
        self.assertEqual(self.request(ROOT+'content', self.body(True))[0], 200)
        self.assertEqual(source.grants, 0)
        self.assertEqual([path.rsplit('/', 1)[-1] for _, path, _ in source.photos.calls], ['resolve', 'content'])
        self.assertIsNone(self.sessions.registry.lookup('Demo-PDS'))

    def test_source_project_permissions_fixed_version_and_transport_gates_still_apply(self):
        body = self.body(True)
        self.assertEqual(self.request(ROOT+'content', body, client=False)[0], 401)
        self.assertEqual(self.request(ROOT+'content', body, headers={'Origin': 'https://wrong.invalid'})[0], 403)
        self.assertEqual(self.request(ROOT+'content', {**body, 'expectedSessionRevision': 'old'})[0], 409)
        for ref in ({'ontobaseConnectionId': 'wrong', 'projectCode': 'Demo-PDS'},
                    {'ontobaseConnectionId': 'ontobase-primary', 'projectCode': 'B'}):
            self.assertEqual(self.request(ROOT+'content', {**body, 'projectRef': ref})[0], 404)
        self.assertEqual(self.request(ROOT+'content', {**body, 'expectedContentVersionId': 'wrong'})[0], 409)
        self.assertEqual(self.request(ROOT+'content', {**body, 'source': 'https://wrong.invalid'})[0], 422)
        self.account().after = lambda: Source.permissions['member'].pop('Demo-PDS')
        self.assertEqual(self.request(ROOT+'content', body)[0], 403)

    def test_logout_while_source_reads_discards_the_late_photo(self):
        entered, release = Event(), Event()
        self.account().after = lambda: (entered.set(), release.wait(3))
        results = []; body = self.body(True)
        thread = Thread(target=lambda: results.append(self.request(ROOT+'content', body)))
        thread.start()
        try:
            self.assertTrue(entered.wait(2))
            sid = self.admin['cookie'].split('=', 1)[1]
            with self.sessions.lock: self.sessions.rows.pop(sid)
        finally: release.set(); thread.join(3)
        self.assertEqual(results[0][0], 401)
        self.assertNotIn('content', results[0][1])

    def test_source_expiry_invalidates_only_the_reading_session(self):
        other = self.login('member')
        body = self.body(True)
        def expired(*_args): raise PreviewError(401, 'SESSION_EXPIRED')
        self.account().photo = expired
        status, value, _ = self.request(ROOT+'content', body)
        self.assertEqual((status, value['code']), (401, 'SESSION_EXPIRED'))
        self.assertNotIn(self.admin['cookie'].split('=', 1)[1], self.sessions.rows)
        self.assertIn(other['cookie'].split('=', 1)[1], self.sessions.rows)


if __name__ == '__main__': unittest.main()
