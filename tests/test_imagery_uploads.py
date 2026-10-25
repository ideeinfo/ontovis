"""Resumable private reception against real files, SQLite and bounded GIS import."""
import hashlib
import io
import json
import os
import signal
import subprocess
import sys
import time
import unittest
from unittest.mock import patch
from uuid import uuid4

import tests.test_imagery_library as fixtures
from apps.api.authority import PreviewError
from apps.api.imagery_library import ImageryLibrary
from apps.api.imagery_uploads import CHUNK_BYTES, ImageryUploads
from apps.api.model_library import ModelLibrary


class ImageryUploadTests(unittest.TestCase):
    def setUp(self):
        fixtures.ImageryLibraryTests.setUp(self)
        self.transfers = self.images.uploads
        self.actor = 'synthetic-admin'
        self.payload = fixtures.metadata()
        self.sha = hashlib.sha256(self.data).hexdigest()

    def start(self, **changes):
        values = dict(payload=self.payload, sha256=self.sha, size=len(self.data), actor=self.actor, authorize=lambda: None)
        values.update(changes)
        return self.transfers.start(**values)

    def chunk(self, row, data, *, offset=None, revision=None, fingerprint=None, actor=None, guard=lambda: None):
        return self.transfers.chunk(io.BytesIO(data), len(data), {
            'uploadId': row['uploadId'], 'offset': row['receivedBytes'] if offset is None else offset,
            'expectedUploadRevision': revision or row['uploadRevision'],
            'expectedChunkSha256': fingerprint or hashlib.sha256(data).hexdigest()}, actor or self.actor, guard)

    def status(self, row, actor=None):
        return self.transfers.status(row['uploadId'], actor or self.actor, lambda: None)

    def complete(self, row):
        return self.transfers.complete(row['uploadId'], row['uploadRevision'], self.actor, lambda: None)

    def expect(self, code, callback):
        fixtures.ImageryLibraryTests.expect(self, code, callback)

    def count(self, table):
        with self.models.connect() as db:
            return db.execute('select count(*) from ' + table).fetchone()[0]

    def test_real_file_two_segments_publish_once_and_existing_request_skips_transfer(self):
        row = self.start()
        row = self.chunk(row, self.data[:100])
        row = self.chunk(row, self.data[100:])
        value = self.complete(row)
        self.assertEqual(value['state'], 'completed')
        self.assertEqual(value['sha256'], self.sha)
        self.assertEqual(self.complete(row)['imageryVersionId'], value['imageryVersionId'])
        self.assertEqual(self.start()['imageryVersionId'], value['imageryVersionId'])
        self.assertEqual(self.transfers.cancel(row['uploadId'], row['uploadRevision'], self.actor, lambda: None)['state'], 'completed')
        self.assertEqual((self.count('imagery_versions'), self.count('imagery_requests'), self.count('imagery_audit')), (1, 1, 1))
        self.assertFalse((self.transfers.root / row['uploadId'] / 'source.part').exists())
        self.expect('REQUEST_CONFLICT', lambda: self.start(size=len(self.data) + 1))

    def test_lost_chunk_reply_replays_exact_range_without_mutating_receipt(self):
        initial = self.start()
        current = self.chunk(initial, self.data[:100])
        folder = self.transfers.root / initial['uploadId']
        before = {name: ((folder / name).read_bytes(), (folder / name).stat().st_mtime_ns)
                  for name in ('state.json', 'source.part')}
        repeated = self.chunk(initial, self.data[:100])
        self.assertEqual(repeated, current)
        for name, expected in before.items():
            self.assertEqual(((folder / name).read_bytes(), (folder / name).stat().st_mtime_ns), expected)
        self.expect('REQUEST_CONFLICT', lambda: self.chunk(initial, b'x' * 100))

    def test_changed_offset_revision_or_chunk_hash_never_advances_receipt(self):
        row = self.start()
        self.expect('IMAGERY_UPLOAD_CHANGED', lambda: self.chunk(row, b'abc', offset=1))
        self.expect('IMAGERY_UPLOAD_CHANGED', lambda: self.chunk(row, b'abc', revision=str(uuid4())))
        self.expect('IMAGERY_CHUNK_CHANGED', lambda: self.chunk(row, b'abc', fingerprint='0' * 64))
        self.assertEqual(self.status(row)['receivedBytes'], 0)
        self.assertEqual(self.count('imagery_versions'), 0)

    def test_start_reuses_only_the_same_actor_request_metadata_hash_and_length(self):
        row = self.start()
        self.assertEqual(self.start(), row)
        for change in ({'size': len(self.data) + 1}, {'sha256': '0' * 64},
                       {'payload': {**self.payload, 'sourceNote': 'different'}}):
            with self.subTest(change=change):
                self.expect('REQUEST_CONFLICT', lambda: self.start(**change))
        self.assertEqual(len(list(self.transfers.root.iterdir())), 1)

    def test_restart_keeps_confirmed_bytes_and_rechecks_a_new_authorization(self):
        row = self.chunk(self.start(), self.data[:100])
        self.images = ImageryLibrary(self.models, python_executable=sys.executable)
        self.transfers = self.images.uploads
        self.assertEqual(self.status(row)['receivedBytes'], 100)
        calls = []
        row = self.chunk(row, self.data[100:], guard=lambda: calls.append('current-guard'))
        self.assertGreaterEqual(len(calls), 3)
        self.assertEqual(self.complete(row)['state'], 'completed')

    def test_receipt_write_failure_keeps_tail_unconfirmed_and_retry_rewrites_it(self):
        row = self.start()
        with patch.object(self.transfers, 'save', side_effect=OSError('synthetic disk failure')):
            self.expect('IMAGERY_STORAGE_UNAVAILABLE', lambda: self.chunk(row, self.data[:100]))
        self.assertEqual(self.status(row)['receivedBytes'], 0)
        row = self.chunk(row, self.data[:100])
        row = self.chunk(row, self.data[100:])
        self.assertEqual(self.complete(row)['sha256'], self.sha)

    def test_sigkill_after_file_fsync_does_not_promote_unacknowledged_bytes(self):
        row=self.start()
        payload={'uploadId':row['uploadId'],'offset':0,'expectedUploadRevision':row['uploadRevision'],
                 'expectedChunkSha256':hashlib.sha256(self.data[:100]).hexdigest()}
        script='''import io,json,os,signal,sys
from pathlib import Path
from types import SimpleNamespace
from apps.api.imagery_uploads import ImageryUploads
receiver=ImageryUploads(SimpleNamespace(root=Path(sys.argv[1])))
receiver.save=lambda *_: os.kill(os.getpid(),signal.SIGKILL)
receiver.chunk(io.BytesIO(bytes.fromhex(sys.argv[3])),100,json.loads(sys.argv[2]),'synthetic-admin',lambda:None)
'''
        process=subprocess.run([sys.executable,'-c',script,str(self.images.root),json.dumps(payload),self.data[:100].hex()],
                               stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=10)
        self.assertEqual(process.returncode,-signal.SIGKILL)
        self.transfers=ImageryLibrary(self.models,python_executable=sys.executable).uploads
        self.assertEqual(self.status(row)['receivedBytes'],0)
        row=self.chunk(row,self.data)
        self.assertEqual(self.complete(row)['sha256'],self.sha)

    def test_receipt_budget_is_checked_before_publishing_the_receiving_directory(self):
        payload={**self.payload,'sourceNote':'字'*2000,'licenseNote':'字'*2000,'qualityNote':'字'*2000}
        self.expect('IMAGERY_LIMIT_EXCEEDED',lambda:self.start(payload=payload))
        self.assertFalse(self.transfers.root.exists())

    def test_read_only_listing_does_not_create_a_receiving_directory(self):
        self.assertEqual(self.transfers.listing(self.actor, lambda: None), [])
        self.assertFalse(self.transfers.root.exists())

    def test_network_read_interruption_is_not_reported_as_storage_failure(self):
        row = self.start()
        for failure in (TimeoutError(), ConnectionResetError()):
            with self.subTest(failure=type(failure).__name__):
                stream = io.BytesIO(self.data)
                with patch.object(stream, 'read', side_effect=failure):
                    self.expect('SOURCE_UNAVAILABLE', lambda: self.transfers.chunk(stream, len(self.data), {
                        'uploadId': row['uploadId'], 'offset': 0, 'expectedUploadRevision': row['uploadRevision'],
                        'expectedChunkSha256': self.sha}, self.actor, lambda: None))
                self.assertEqual(self.status(row)['receivedBytes'], 0)

    def test_earlier_large_unconfirmed_tail_is_rewritten_after_limit_reduction(self):
        data = b'x' * (256 * 1024 + 1)
        row = self.start(size=len(data), sha256=hashlib.sha256(data).hexdigest())
        source = self.transfers.root / row['uploadId'] / 'source.part'
        source.write_bytes(b'z' * (256 * 1024))
        self.assertEqual(self.status(row)['receivedBytes'], 0)
        row = self.chunk(row, data[:CHUNK_BYTES])
        self.assertEqual(row['receivedBytes'], CHUNK_BYTES)
        self.assertEqual(source.read_bytes(), data[:CHUNK_BYTES])

    def test_authority_revoked_after_bytes_before_receipt_leaves_offset_unconfirmed(self):
        row = self.start()
        calls = []
        def guard():
            calls.append(1)
            if len(calls) == 3: raise PreviewError(403, 'FORBIDDEN')
        self.expect('FORBIDDEN', lambda: self.chunk(row, self.data[:100], guard=guard))
        self.assertEqual(self.status(row)['receivedBytes'], 0)
        self.assertEqual(self.count('imagery_versions'), 0)
        self.assertEqual(self.chunk(row, self.data[:100])['receivedBytes'], 100)

    def test_other_actor_and_other_project_cannot_read_write_finish_or_cancel(self):
        row = self.start()
        actions = [lambda: self.status(row, 'other'), lambda: self.chunk(row, b'x', actor='other'),
                   lambda: self.transfers.complete(row['uploadId'], row['uploadRevision'], 'other', lambda: None),
                   lambda: self.transfers.cancel(row['uploadId'], row['uploadRevision'], 'other', lambda: None)]
        for action in actions: self.expect('NOT_FOUND_OR_FORBIDDEN', action)
        self.assertEqual(self.transfers.listing('other', lambda: None), [])
        other = ModelLibrary(self.root / 'other', 'other-project', str(uuid4()))
        receiver = ImageryLibrary(other, python_executable=sys.executable).uploads
        self.expect('NOT_FOUND_OR_FORBIDDEN', lambda: receiver.status(row['uploadId'], self.actor, lambda: None))

    def test_global_pending_budget_and_expiry_do_not_delete_any_version(self):
        first = self.start()
        self.start(payload=fixtures.metadata())
        self.expect('IMAGERY_BUSY', lambda: self.start(payload=fixtures.metadata()))
        with patch('apps.api.imagery_uploads.time.time', return_value=first['expiresAt'] + 2):
            self.expect('IMAGERY_UPLOAD_EXPIRED', lambda: self.status(first))
            self.assertEqual(self.transfers.listing(self.actor, lambda: None), [])
            self.assertEqual(self.start(payload=fixtures.metadata())['receivedBytes'], 0)
        self.assertEqual(self.count('imagery_versions'), 0)

    def test_cancel_requires_current_revision_and_only_removes_unpublished_copy(self):
        row = self.start()
        self.expect('IMAGERY_UPLOAD_CHANGED', lambda: self.transfers.cancel(row['uploadId'], str(uuid4()), self.actor, lambda: None))
        result = self.transfers.cancel(row['uploadId'], row['uploadRevision'], self.actor, lambda: None)
        self.assertEqual(result['state'], 'cancelled')
        self.assertFalse((self.transfers.root / row['uploadId']).exists())
        self.assertEqual(self.count('imagery_versions'), 0)

    def test_short_stream_boolean_offset_and_chunk_limit_do_not_commit(self):
        row = self.start()
        payload = {'uploadId': row['uploadId'], 'offset': 0, 'expectedUploadRevision': row['uploadRevision'],
                   'expectedChunkSha256': hashlib.sha256(b'ab').hexdigest()}
        self.expect('UNSUPPORTED_IMAGERY', lambda: self.transfers.chunk(io.BytesIO(b'a'), 2, payload, self.actor, lambda: None))
        self.expect('INVALID_REQUEST', lambda: self.transfers.chunk(io.BytesIO(b'ab'), 2, {**payload, 'offset': False}, self.actor, lambda: None))
        self.expect('INVALID_REQUEST', lambda: self.transfers.chunk(io.BytesIO(), CHUNK_BYTES + 1, payload, self.actor, lambda: None))
        self.assertEqual(self.status(row)['receivedBytes'], 0)

    def test_incomplete_and_wrong_full_fingerprint_never_publish(self):
        row = self.start(sha256='0' * 64)
        self.expect('IMAGERY_UPLOAD_INCOMPLETE', lambda: self.complete(row))
        row = self.chunk(row, self.data)
        self.expect('IMAGERY_CHUNK_CHANGED', lambda: self.complete(row))
        self.assertEqual(self.count('imagery_versions'), 0)

    def test_source_tampering_short_file_symlink_and_hardlink_are_refused(self):
        row = self.chunk(self.start(), self.data[:100])
        source = self.transfers.root / row['uploadId'] / 'source.part'
        source.write_bytes(b'')
        self.expect('RESOURCE_CHANGED', lambda: self.status(row))
        source.unlink()
        target = self.root / 'unrelated'; target.write_bytes(b'x' * 100)
        source.symlink_to(target)
        self.expect('RESOURCE_CHANGED', lambda: self.status(row))
        self.assertEqual(target.read_bytes(), b'x' * 100)
        source.unlink(); os.link(target, source)
        self.expect('RESOURCE_CHANGED', lambda: self.status(row))

    def test_unknown_entry_is_preserved_and_blocks_cleanup(self):
        row = self.start()
        extra = self.transfers.root / row['uploadId'] / 'unrelated.txt'; extra.write_text('preserve')
        self.expect('RESOURCE_CHANGED', lambda: self.transfers.cancel(row['uploadId'], row['uploadRevision'], self.actor, lambda: None))
        self.assertEqual(extra.read_text(), 'preserve')

    def test_interrupted_initial_receipt_never_leaves_visible_broken_upload(self):
        with patch.object(self.transfers, 'save', side_effect=OSError('synthetic receipt failure')):
            self.expect('IMAGERY_STORAGE_UNAVAILABLE', self.start)
        self.assertEqual(list(self.transfers.root.iterdir()), [])
        self.assertEqual(list((self.images.root / 'temporary').iterdir()), [])
        self.assertEqual(self.start()['receivedBytes'], 0)

    def test_commit_succeeds_then_receipt_failure_recovers_same_version_after_restart(self):
        row = self.chunk(self.start(), self.data)
        with patch.object(self.transfers, 'save', side_effect=OSError('synthetic receipt failure after commit')):
            self.expect('IMAGERY_STORAGE_UNAVAILABLE', lambda: self.complete(row))
        self.transfers = ImageryLibrary(self.models, python_executable=sys.executable).uploads
        value = self.status(row)
        self.assertEqual(value['state'], 'completed')
        self.assertEqual(self.start()['imageryVersionId'], value['imageryVersionId'])
        self.assertEqual(self.complete(row)['imageryVersionId'], value['imageryVersionId'])
        self.assertEqual((self.count('imagery_versions'), self.count('imagery_audit')), (1, 1))

    def test_private_receipt_contains_no_reusable_authorization_or_local_path(self):
        row = self.start()
        state = json.loads((self.transfers.root / row['uploadId'] / 'state.json').read_text())
        self.assertEqual(set(state), {'schemaVersion', 'uploadId', 'actor', 'metadata', 'sha256', 'bytes',
                                     'receivedBytes', 'uploadRevision', 'expiresAt', 'state'})
        self.assertNotIn(str(self.root), json.dumps(state))
        self.assertEqual(stat_mode(self.transfers.root / row['uploadId'] / 'state.json'), 0o600)


def stat_mode(path):
    return path.stat().st_mode & 0o777


if __name__ == '__main__': unittest.main()
