"""Thumbnail identity, authorization, cache lifetime and bounded PNG processing."""
import copy
import hashlib
import io
from pathlib import Path
import struct
import tempfile
from threading import Event, Thread
import time
import unittest
from uuid import uuid4
import zlib

from apps.api.authority import PreviewError
from apps.api.model_library import ModelLibrary
from apps.api.project_model_library import ProjectModelLibrary
from apps.api.model_thumbnails import ModelThumbnails, png_info, MAX_PNG_BYTES
from tests.test_model_upload import glb
from tests.test_project_model_library import Guard, CONTEXT


def png(color=(90, 125, 105, 255)):
    def chunk(kind, data):
        return struct.pack('>I', len(data)) + kind + data + struct.pack('>I', zlib.crc32(kind + data) & 0xffffffff)
    pixels = (b'\0' + bytes(color) * 256) * 256
    return b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', 256, 256, 8, 6, 0, 0, 0)) + chunk(b'IDAT', zlib.compress(pixels)) + chunk(b'IEND', b'')


class ModelThumbnailTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory(); self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.library = ModelLibrary(self.root / 'private', 'fixture-project', CONTEXT)
        self.models = ProjectModelLibrary(self.library)
        self.guard = Guard(); self.calls = []
        data = glb(self.root / 'input.glb').read_bytes()
        self.version = self.models.upload(io.BytesIO(data), len(data), self.metadata(), 'fixture-admin', self.guard)
        self.engine = self.new_engine()

    def metadata(self):
        return {'expectedLibraryRevision': self.library.listing()['libraryRevision'], 'clientRequestId': str(uuid4()),
                'displayName': 'Synthetic thumbnail input', 'purpose': 'equipment', 'sourceNote': 'Synthetic test geometry', 'rightsDeclared': True}

    def render(self, content, work):
        self.calls.append(hashlib.sha256(content).hexdigest())
        return png()

    def new_engine(self, renderer=None, start_worker=False):
        value = ModelThumbnails(self.models, renderer or self.render, start_worker=start_worker)
        self.addCleanup(value.close)
        return value

    def reference(self, version=None):
        v = version or self.version
        return {'modelVersionId': v['modelVersionId'], 'expectedContentRevision': v['contentRevision'], 'expectedSha256': v['sha256']}

    def body(self, version=None, **changes):
        return {**self.reference(version), 'expectedThumbnailRevision': None, 'clientRequestId': str(uuid4()), **changes}

    def ensure(self, body=None): return self.engine.ensure(body or self.body(), 'fixture-admin', self.guard)

    def complete(self, body=None):
        body = body or self.body(); self.ensure(body)
        self.engine.pending.pop(self.version['sha256'], None)
        self.engine._process(self.version['sha256'], body, self.guard)
        return self.engine.describe(self.version['sha256'])

    def current_counts(self):
        with self.library.connect() as db:
            return tuple(db.execute('select count(*) from ' + t).fetchone()[0] for t in ('versions', 'project_model_versions', 'project_model_audit'))

    def test_generation_does_not_create_model_versions_or_change_source_and_library_revision(self):
        before = self.current_counts(), self.library.listing()['libraryRevision'], self.models._content(self.version)
        ready = self.complete()
        self.assertEqual(ready['state'], 'ready'); self.assertEqual((ready['width'], ready['height']), (256, 256))
        self.assertEqual(before, (self.current_counts(), self.library.listing()['libraryRevision'], self.models._content(self.version)))
        self.assertEqual(self.calls, [self.version['sha256']])
        body = {**self.reference(), 'expectedThumbnailRevision': ready['thumbnailRevision'], 'expectedImageSha256': ready['imageSha256']}
        self.assertEqual(self.engine.content(body, self.guard)['content'], png())

    def test_same_geometry_calibration_reuses_the_thumbnail(self):
        self.complete()
        calibrated = self.models.calibrate({'modelVersionId': self.version['modelVersionId'],
            'expectedContentRevision': self.version['contentRevision'], 'expectedLibraryRevision': self.library.listing()['libraryRevision'],
            'calibration': {'unit': 'm', 'axes': 'Y_UP_RIGHT_HANDED', 'basePoint': [0, 0, 0], 'forward': [0, 0, 1]},
            'clientRequestId': str(uuid4())}, 'fixture-admin', self.guard)
        value = self.engine.automatic(calibrated, 'fixture-admin', self.guard)
        self.assertEqual(value['state'], 'ready'); self.assertFalse(self.engine.pending); self.assertEqual(len(self.calls), 1)
        with self.library.connect() as db: self.assertEqual(db.execute('select count(*) from model_thumbnails').fetchone()[0], 1)

    def test_idempotent_replay_does_not_queue_twice_and_changed_payload_is_rejected(self):
        body = self.body(); first = self.ensure(body)
        self.assertEqual(self.ensure(body), first); self.assertEqual(len(self.engine.pending), 1)
        with self.assertRaises(PreviewError) as error: self.ensure({**body, 'expectedThumbnailRevision': 'different'})
        self.assertEqual(error.exception.code, 'REQUEST_CONFLICT')

    def test_parallel_requests_for_one_geometry_share_one_job(self):
        results = []; errors = []
        def request():
            try: results.append(self.ensure())
            except Exception as error: errors.append(error)
        threads = [Thread(target=request) for _ in range(4)]
        for thread in threads: thread.start()
        for thread in threads: thread.join(4)
        self.assertEqual(errors, []); self.assertEqual(len(results), 4)
        self.assertEqual(len({result['thumbnailRevision'] for result in results}), 1)
        self.assertEqual(len(self.engine.pending), 1)

    def test_denied_or_changed_source_cannot_schedule_or_publish(self):
        self.guard.allowed = False
        with self.assertRaises(PreviewError): self.ensure()
        self.guard.allowed = True
        with self.assertRaises(PreviewError) as error: self.ensure(self.body(expectedSha256='0' * 64))
        self.assertEqual(error.exception.code, 'RESOURCE_CHANGED')
        self.assertEqual(self.engine.describe(self.version['sha256'])['state'], 'missing')
        self.assertFalse(self.engine.pending)

    def test_revocation_during_render_never_publishes_a_private_image(self):
        body = self.body(); self.ensure(body)
        def revoke(content, work): self.guard.allowed = False; return png()
        self.engine.renderer = revoke
        with self.assertRaises(PreviewError): self.engine._process(self.version['sha256'], body, self.guard)
        self.assertFalse(list((self.engine.root / 'files').iterdir()))
        self.assertFalse(list((self.engine.root / 'temporary').iterdir()))

    def test_changed_processing_revision_rolls_back_output_publication(self):
        body = self.body(); self.ensure(body)
        def change(content, work):
            with self.library.connect() as db: db.execute("update model_thumbnails set revision='unexpected' where source_sha256=?", (self.version['sha256'],))
            return png()
        self.engine.renderer = change
        with self.assertRaises(PreviewError) as error: self.engine._process(self.version['sha256'], body, self.guard)
        self.assertEqual(error.exception.code, 'RESOURCE_CHANGED')
        self.assertFalse(list((self.engine.root / 'files').iterdir()))

    def test_worker_failure_is_retryable_with_a_current_thumbnail_revision(self):
        self.engine.close()
        def fail(content, work): raise PreviewError(503, 'THUMBNAIL_RENDER_FAILED')
        self.engine = self.new_engine(fail, start_worker=True)
        body = self.body(); self.ensure(body)
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            failed = self.engine.describe(self.version['sha256'])
            if failed['state'] == 'failed': break
            time.sleep(.01)
        self.assertEqual(failed['state'], 'failed')
        self.assertEqual(self.ensure(body)['state'], 'failed')
        with self.assertRaises(PreviewError): self.ensure(self.body())
        self.engine.renderer = self.render
        self.ensure(self.body(expectedThumbnailRevision=failed['thumbnailRevision']))
        while time.monotonic() < deadline:
            ready = self.engine.describe(self.version['sha256'])
            if ready['state'] == 'ready': break
            time.sleep(.01)
        self.assertEqual(ready['state'], 'ready')

    def test_restart_marks_unfinished_jobs_and_does_not_adopt_orphan_images(self):
        self.ensure(); self.engine.close()
        orphan = self.engine.root / 'files' / (self.version['sha256'] + '.png'); orphan.write_bytes(png())
        self.engine = self.new_engine()
        self.assertEqual(self.engine.describe(self.version['sha256'])['state'], 'failed')
        self.assertFalse(orphan.exists()); self.assertFalse(self.engine.pending)

    def test_private_read_rejects_wrong_revision_wrong_digest_tampering_and_symlink(self):
        ready = self.complete()
        body = {**self.reference(), 'expectedThumbnailRevision': ready['thumbnailRevision'], 'expectedImageSha256': ready['imageSha256']}
        for change in ({'expectedImageSha256': '0' * 64}, {'expectedThumbnailRevision': 'stale'}):
            with self.assertRaises(PreviewError): self.engine.content({**body, **change}, self.guard)
        target = self.engine.root / 'files' / (self.version['sha256'] + '.png'); target.write_bytes(png((0, 0, 0, 255)))
        with self.assertRaises(PreviewError) as error: self.engine.content(body, self.guard)
        self.assertEqual(error.exception.status, 409)
        target.unlink(); other = self.root / 'other.png'; other.write_bytes(png()); target.symlink_to(other)
        with self.assertRaises(PreviewError): self.engine.content(body, self.guard)
        self.guard.allowed = False
        with self.assertRaises(PreviewError): self.engine.content(body, self.guard)

    def test_png_validation_rejects_wrong_dimensions_crc_trailing_bytes_oversize_and_active_formats(self):
        self.assertEqual(png_info(png())['width'], 256)
        for data in [png()[:-1], png() + b'extra', b'<svg onload="alert(1)"/>', b'\xff\xd8jpeg',
                     png()[:20] + b'changed' + png()[27:], b'\x89PNG\r\n\x1a\n' + b'x' * MAX_PNG_BYTES]:
            with self.subTest(size=len(data)), self.assertRaises(PreviewError): png_info(data)

    def test_malformed_renderer_output_is_not_published(self):
        body = self.body(); self.ensure(body); self.engine.renderer = lambda content, work: b'<svg>fake</svg>'
        with self.assertRaises(PreviewError): self.engine._process(self.version['sha256'], body, self.guard)
        self.assertFalse(list((self.engine.root / 'files').iterdir()))
