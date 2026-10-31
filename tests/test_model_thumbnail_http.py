"""Normal HTTP boundaries; synthetic authority and PNG renderer, real private store."""
import hashlib
import time
import unittest
from uuid import uuid4

from apps.api.model_thumbnails import ModelThumbnails
from tests import test_project_model_http as http_fixture
from tests.test_model_thumbnails import png


class ModelThumbnailHttpTests(unittest.TestCase):
    def setUp(self):
        self.fixture = http_fixture.ProjectModelHttpTests(); self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.engine = ModelThumbnails(self.fixture.sessions.project_models, lambda content, work: png())
        self.fixture.sessions.thumbnails = self.engine
        self.addCleanup(self.engine.close)

    def ref(self, version):
        return {'modelVersionId': version['modelVersionId'], 'expectedContentRevision': version['contentRevision'], 'expectedSha256': version['sha256']}

    def status(self, version, **options):
        return self.fixture.request('/api/workbench/resources/model/thumbnail', self.ref(version), **options)

    def ready(self, version):
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            status, result, _ = self.status(version)
            self.assertEqual(status, 200, result)
            if result['thumbnail']['state'] == 'ready': return result['thumbnail']
            time.sleep(.01)
        self.fail('Thumbnail did not become ready')

    def test_upload_automatically_creates_thumbnail_and_catalog_exposes_it(self):
        version = self.fixture.new_version()
        self.assertIn(version['thumbnail']['state'], ('queued', 'processing', 'ready'))
        self.ready(version)
        status, catalog, _ = self.fixture.listing()
        self.assertEqual(status, 200); self.assertTrue(catalog['capabilities']['canGenerateThumbnails'])
        self.assertEqual(catalog['items'][0]['versions'][0]['thumbnail']['state'], 'ready')
        with self.engine.library.connect() as db:
            self.assertEqual(db.execute('select count(*) from versions').fetchone()[0], 1)
            self.assertEqual(db.execute('select count(*) from project_model_versions').fetchone()[0], 1)

    def test_reader_can_fetch_private_png_but_cannot_schedule_a_write(self):
        version = self.fixture.new_version(); ready = self.ready(version)
        member = self.fixture.login('fixture-reader'); self.fixture.authority(member).role = 'reader'
        body = {**self.ref(version), 'expectedThumbnailRevision': ready['thumbnailRevision'], 'expectedImageSha256': ready['imageSha256']}
        status, content, headers = self.fixture.request('/api/workbench/resources/model/thumbnail/content', body, client=member)
        self.assertEqual(status, 200); self.assertEqual(content, png())
        self.assertEqual(headers['Content-Type'], 'image/png'); self.assertEqual(headers['Cache-Control'], 'no-store')
        self.assertEqual(headers['X-Content-SHA256'], hashlib.sha256(content).hexdigest())
        self.assertEqual(headers['X-Session-Revision'], member['revision'])
        body = {**self.ref(version), 'expectedThumbnailRevision': ready['thumbnailRevision'], 'clientRequestId': str(uuid4())}
        status, error, _ = self.fixture.request('/api/workbench/resources/model/thumbnail/ensure', body, client=member)
        self.assertEqual((status, error['code']), (403, 'MODEL_WRITE_FORBIDDEN'))
        self.assertFalse(self.status(version, client=member)[1]['capabilities']['canGenerateThumbnails'])

    def test_anonymous_logged_out_and_revoked_project_cannot_read_images(self):
        version = self.fixture.new_version(); ready = self.ready(version)
        body = {**self.ref(version), 'expectedThumbnailRevision': ready['thumbnailRevision'], 'expectedImageSha256': ready['imageSha256']}
        self.assertEqual(self.fixture.request('/api/workbench/resources/model/thumbnail/content', body, client=False)[0], 401)
        member = self.fixture.login('another-reader'); self.fixture.authority(member).allowed = False
        self.assertEqual(self.fixture.request('/api/workbench/resources/model/thumbnail/content', body, client=member)[0], 403)
        self.fixture.request('/api/session/logout')
        self.assertEqual(self.fixture.request('/api/workbench/resources/model/thumbnail/content', body)[0], 401)

    def test_exact_source_revision_and_thumbnail_revision_are_required(self):
        version = self.fixture.new_version(); ready = self.ready(version)
        for changes in [{'expectedContentRevision': 'stale'}, {'expectedSha256': '0' * 64}, {'expectedThumbnailRevision': 'stale'}, {'expectedImageSha256': '0' * 64}]:
            body = {**self.ref(version), 'expectedThumbnailRevision': ready['thumbnailRevision'], 'expectedImageSha256': ready['imageSha256'], **changes}
            self.assertEqual(self.fixture.request('/api/workbench/resources/model/thumbnail/content', body)[0], 409)
        body = {**self.ref(version), 'expectedThumbnailRevision': ready['thumbnailRevision'], 'expectedImageSha256': ready['imageSha256'], 'path': '/etc/passwd'}
        self.assertEqual(self.fixture.request('/api/workbench/resources/model/thumbnail/content', body)[0], 422)

    def test_thumbnail_requests_do_not_change_geometry_catalog_or_scene_heads(self):
        version = self.fixture.new_version(); ready = self.ready(version)
        before = self.fixture.listing()[1]['libraryRevision']
        body = {**self.ref(version), 'expectedThumbnailRevision': ready['thumbnailRevision'], 'clientRequestId': str(uuid4())}
        for _ in range(2): self.assertEqual(self.fixture.request('/api/workbench/resources/model/thumbnail/ensure', body)[0], 200)
        self.assertEqual(self.fixture.listing()[1]['libraryRevision'], before)
        with self.engine.library.connect() as db:
            self.assertEqual(db.execute('select count(*) from versions').fetchone()[0], 1)
            self.assertEqual(db.execute('select count(*) from scenes').fetchone()[0], 0)
            self.assertEqual(db.execute('select count(*) from scene_revisions').fetchone()[0], 0)
