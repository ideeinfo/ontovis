"""Immutable replay delivery, resume watermarks and bounded authorization leases."""
import json
import unittest
from unittest.mock import patch

from apps.api.authority import PreviewError
from apps.api import simulated_faults as sim
from apps.api.simulation_stream import SimulationStreams, event_bytes
from tests import test_project_workspaces as projects


def decode(frame):
    lines = frame.decode().splitlines()
    return {'event': next(line[7:] for line in lines if line.startswith('event: ')),
            'id': next((line[4:] for line in lines if line.startswith('id: ')), None),
            'data': json.loads(next(line[6:] for line in lines if line.startswith('data: ')))}


class SimulationStreamTests(unittest.TestCase):
    def setUp(self):
        self.now = 1793232000.0
        self.feed = SimulationStreams(clock=lambda: self.now, monotonic=lambda: self.now)
        self.addCleanup(self.feed.close)
        item = sim.identity('13001')
        self.body = {key: item[key] for key in ('datasetId', 'datasetRevision')}
        self.guards, self.authorizations = 0, 0

    def guard(self): self.guards += 1
    def authorize(self): self.authorizations += 1

    def open(self, *, owner='one', **body):
        value = self.feed.subscribe(owner, 'Demo-PDS', {**self.body, **body}, 'revision', self.guard, self.authorize)
        self.addCleanup(value.close)
        return value

    def test_full_journal_preserves_original_event_revisions_times_and_quality(self):
        subscription = self.open(fromSecond=0)
        frames = subscription.frames()
        self.assertEqual(decode(next(frames))['event'], 'ready')
        first = decode(next(frames)); self.assertEqual(first['event'], 'snapshot')
        self.assertEqual(first['data']['detail']['alarms'], [])
        self.assertEqual(len(first['data']['detail']['trends'][0]['samples']), 1)
        values = []
        for second in range(1, 181):
            self.now += 1
            value = decode(next(frames)); values.append(value)
            self.assertEqual(value['data']['sequence'], second)
            self.assertTrue(value['id'].endswith(':'+str(second)))
            self.assertLessEqual(len(event_bytes('sample', value['data'], value['id'])), 8000)
        self.assertEqual([v['data']['alarms'][0]['sourceRevision'] for v in values if v['data']['alarms']], ['1', '2'])
        gap = values[89]['data']['samples']
        self.assertTrue(all(p['quality'] == 'bad' and p['value'] is None for p in gap))
        self.assertEqual(values[149]['data']['alarms'][0]['state'], 'cleared')
        self.assertEqual(decode(next(frames))['event'], 'complete')
        self.assertRaises(StopIteration, next, frames)
        self.assertEqual(self.feed.owners, {})
        self.assertGreaterEqual(self.authorizations, 36)

    def test_resume_backfills_each_missing_second_including_bad_quality_before_live(self):
        subscription = self.open(fromSecond=87)
        frames = subscription.frames(); next(frames)
        cursor = decode(next(frames))['id']
        frames.close(); self.now += 6
        resumed = self.open(cursor=cursor); frames = resumed.frames()
        self.assertEqual(decode(next(frames))['event'], 'ready')
        for second in range(88, 94):
            value = decode(next(frames))
            self.assertEqual(value['data']['sequence'], second)
            self.assertEqual(value['data']['sourceWatermark'], 93)
            if second == 90: self.assertIsNone(value['data']['samples'][0]['value'])
        frames.close()

    def test_resume_journal_survives_new_delivery_process_without_saving_business_rows(self):
        original = self.open(fromSecond=149); frames = original.frames(); next(frames)
        cursor = decode(next(frames))['id']; frames.close(); self.now += 2
        other = SimulationStreams(clock=lambda: self.now, monotonic=lambda: self.now)
        value = other.subscribe('new-login', 'Demo-PDS', {**self.body, 'cursor': cursor}, 'new-revision', self.guard, self.authorize)
        stream = value.frames(); next(stream)
        restored = decode(next(stream))
        self.assertEqual(restored['data']['sequence'], 150)
        self.assertEqual(restored['data']['alarms'][0]['state'], 'cleared')
        self.assertEqual(restored['data']['sessionRevision'], 'new-revision')
        stream.close(); other.close()

    def test_invalid_extra_noninteger_position_and_cursor_combinations_are_rejected(self):
        for body in ({'fromSecond': True}, {'fromSecond': .1}, {'fromSecond': -1}, {'fromSecond': 181},
                     {'fromSecond': 0, 'extra': 'arbitrary'}, {'fromSecond': 0, 'cursor': 'x'}, {'cursor': 'x'}, {}):
            with self.subTest(body=body), self.assertRaises(PreviewError): self.open(**body)
        self.assertEqual(self.feed.owners, {})

    def test_cursor_cannot_skip_ahead_expire_or_cross_source_revision(self):
        subscription = self.open(fromSecond=60)
        cursor = subscription.cursor(60)
        for bad in (subscription.cursor(181), subscription.cursor(61), cursor.replace(subscription.journal, '0'*64)):
            with self.subTest(cursor=bad), self.assertRaises(PreviewError): self.open(cursor=bad)
        self.now += 601
        with self.assertRaises(PreviewError) as error: self.open(cursor=cursor)
        self.assertEqual(error.exception.code, 'STREAM_CURSOR_EXPIRED')

    def test_changed_dataset_and_other_project_fail_before_allocating_a_slot(self):
        with self.assertRaises(PreviewError): self.open(fromSecond=0, datasetRevision='changed')
        with self.assertRaises(PreviewError):
            self.feed.subscribe('one', 'B', {**self.body, 'fromSecond': 0}, 'r', self.guard, self.authorize)
        self.assertEqual(self.feed.owners, {})

    def test_session_and_global_connection_limits_release_idempotently(self):
        one = self.open(fromSecond=0); two = self.open(fromSecond=0)
        with self.assertRaises(PreviewError) as error: self.open(fromSecond=0)
        self.assertEqual((error.exception.status, error.exception.code), (429, 'STREAM_LIMIT_EXCEEDED'))
        one.close(); one.close(); self.assertEqual(self.feed.owners['one'], 1)
        for i in range(7): self.open(owner=str(i), fromSecond=0)
        with self.assertRaises(PreviewError): self.open(owner='ninth', fromSecond=0)
        two.close(); self.open(owner='replacement', fromSecond=0)

    def test_local_logout_and_source_revoke_stop_before_next_record(self):
        subscription = self.open(fromSecond=60); frames = subscription.frames(); next(frames); next(frames)
        self.now += 1
        with patch.object(subscription, 'guard', side_effect=PreviewError(401, 'SESSION_EXPIRED')):
            with self.assertRaises(PreviewError): next(frames)
        self.assertEqual(self.feed.owners, {})
        subscription = self.open(fromSecond=60); frames = subscription.frames(); next(frames); next(frames)
        self.now += 5
        with patch.object(subscription, 'authorize', side_effect=PreviewError(403, 'FORBIDDEN')):
            with self.assertRaises(PreviewError): next(frames)
        self.assertEqual(self.feed.owners, {})

    def test_slow_reader_uses_fixed_journal_not_a_growing_producer_queue(self):
        subscription = self.open(fromSecond=60); frames = subscription.frames(); next(frames); next(frames)
        self.now += 90
        self.assertEqual(decode(next(frames))['data']['sequence'], 61)
        self.assertEqual(len(subscription.detail['trends'][0]['samples']), 181)
        self.assertFalse(hasattr(subscription, 'queue'))
        frames.close()

    def test_server_shutdown_releases_active_and_unstarted_streams(self):
        subscription = self.open(fromSecond=60); frames = subscription.frames(); next(frames); next(frames)
        self.feed.close(); self.assertRaises(StopIteration, next, frames)
        self.assertEqual(self.feed.owners, {})
        with self.assertRaises(PreviewError): self.open(fromSecond=0)


class ProjectSimulationStreamTests(unittest.TestCase):
    def setUp(self):
        self.fixture = projects.ProjectWorkspaceTests(); self.fixture.setUp(); self.addCleanup(self.fixture.doCleanups)
        self.sessions = self.fixture.sessions
        self.now = 1793232000.0
        self.sessions.simulation_streams.clock = lambda: self.now
        self.sessions.simulation_streams.monotonic = lambda: self.now
        patcher = patch.dict(projects.ProjectsAuthority.projects, {'Demo-PDS': 'Synthetic demo'})
        patcher.start(); self.addCleanup(patcher.stop)
        patcher = patch.dict(projects.ProjectsAuthority.permissions['member'], {'Demo-PDS': 'viewer'})
        patcher.start(); self.addCleanup(patcher.stop)
        item = sim.identity('13001')
        self.body = self.fixture.payload('Demo-PDS', **{key: item[key] for key in ('datasetId', 'datasetRevision')}, fromSecond=60)

    def test_readonly_stream_does_not_create_workspace_analysis_or_touch_user_activity(self):
        touched = self.sessions.current(self.fixture.sid).touched
        with patch('apps.api.analysis_drafts.AnalysisDrafts', side_effect=AssertionError('Unrelated analysis database')):
            stream = self.sessions.simulation_stream(self.fixture.sid, self.body)
            frames = stream.frames(); next(frames); next(frames); frames.close()
        self.assertEqual(self.sessions.current(self.fixture.sid).touched, touched)
        self.assertIsNone(self.sessions.registry.lookup('Demo-PDS'))

    def test_member_revocation_is_rechecked_on_long_lived_connection(self):
        stream = self.sessions.simulation_stream(self.fixture.sid, self.body)
        frames = stream.frames(); next(frames); next(frames)
        del projects.ProjectsAuthority.permissions['member']['Demo-PDS']; self.now += 5
        with self.assertRaises(PreviewError) as error: next(frames)
        self.assertEqual(error.exception.status, 403)
        self.assertEqual(self.sessions.simulation_streams.owners, {})

    def test_anonymous_stale_revision_logout_and_cross_project_are_rejected(self):
        for sid, body in ((None, self.body), (self.fixture.sid, {**self.body, 'expectedSessionRevision': 'old'}),
                          (self.fixture.sid, {**self.body, 'projectRef': {'ontobaseConnectionId':'other','projectCode':'Demo-PDS'}})):
            with self.subTest(sid=sid), self.assertRaises(PreviewError): self.sessions.simulation_stream(sid, body)
        stream = self.sessions.simulation_stream(self.fixture.sid, self.body)
        frames = stream.frames(); next(frames)
        self.sessions.logout(self.fixture.sid, self.fixture.revision)
        with self.assertRaises(PreviewError): next(frames)
        self.assertEqual(self.sessions.simulation_streams.owners, {})
