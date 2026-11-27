"""Bounded, resumable delivery of the immutable simulated source journal."""
from __future__ import annotations

import json
import re
from threading import Event, Lock
import time

from .analysis_drafts import digest, require
from . import simulated_faults

ACCESS_SECONDS = 5
CURSOR_SECONDS = 600
MAX_CONNECTIONS = 8
MAX_PER_SESSION = 2
PATH = '/api/workbench/analysis-sessions/simulation/stream'


def event_bytes(event, data, cursor=None):
    prefix = f'event: {event}\n' + (f'id: {cursor}\n' if cursor else '')
    return (prefix + 'data: ' + json.dumps(data, ensure_ascii=False, allow_nan=False,
                                          separators=(',', ':')) + '\n\n').encode('utf-8')


class SimulationStreams:
    def __init__(self, *, clock=time.time, monotonic=time.monotonic):
        self.clock, self.monotonic = clock, monotonic
        self.lock, self.stopped, self.owners = Lock(), Event(), {}

    def subscribe(self, owner, project, body, revision, guard, authorize):
        require(type(body) is dict and set(body) in (
            {'datasetId', 'datasetRevision', 'fromSecond'}, {'datasetId', 'datasetRevision', 'cursor'}))
        detail = simulated_faults.detail(project, {key: body[key] for key in ('datasetId', 'datasetRevision')})
        journal = digest({'schema': 'simulated-stream:1', 'detail': detail})
        now = int(self.clock() * 1000)
        initial = 'cursor' not in body
        if initial:
            second = body['fromSecond']
            require(type(second) is int and 0 <= second <= 180)
            anchor = now - second * 1000
        else:
            value = body['cursor']
            require(type(value) is str and len(value) <= 128, 'STREAM_CURSOR_INVALID')
            match = re.fullmatch(r's1:([a-f0-9]{64}):([0-9]{13}):([0-9]{1,3})', value)
            require(match is not None, 'STREAM_CURSOR_INVALID')
            require(match[1] == journal, 'STREAM_SOURCE_CHANGED', 409)
            anchor, second = int(match[2]), int(match[3])
            require(0 <= second <= 180 and 0 <= now - anchor <= CURSOR_SECONDS * 1000
                    and second <= min(180, (now - anchor) // 1000), 'STREAM_CURSOR_EXPIRED', 409)
        guard()
        with self.lock:
            require(not self.stopped.is_set(), 'SERVICE_BUSY', 503)
            require(sum(self.owners.values()) < MAX_CONNECTIONS
                    and self.owners.get(owner, 0) < MAX_PER_SESSION, 'STREAM_LIMIT_EXCEEDED', 429)
            self.owners[owner] = self.owners.get(owner, 0) + 1
        return Subscription(self, owner, detail, journal, anchor, second, initial, revision, guard, authorize)

    def close(self):
        self.stopped.set()


class Subscription:
    def __init__(self, feed, owner, detail, journal, anchor, second, initial, revision, guard, authorize):
        self.feed, self.owner, self.detail = feed, owner, detail
        self.journal, self.anchor, self.second = journal, anchor, second
        self.initial, self.revision, self.guard, self.authorize = initial, revision, guard, authorize
        self.closed = False
        self.last_access = feed.monotonic()

    def close(self):
        with self.feed.lock:
            if not self.closed:
                count = self.feed.owners[self.owner] - 1
                if count: self.feed.owners[self.owner] = count
                else: del self.feed.owners[self.owner]
                self.closed = True

    def cursor(self, second):
        return f's1:{self.journal}:{self.anchor}:{second}'

    def check(self):
        self.guard()
        if self.feed.monotonic() - self.last_access >= ACCESS_SECONDS:
            self.authorize()
            self.last_access = self.feed.monotonic()
        self.guard()

    def payload(self, second):
        return {'sequence': second, 'datasetId': self.detail['dataset']['datasetId'],
                'datasetRevision': self.detail['dataset']['datasetRevision'],
                'epoch': simulated_faults.EPOCH, 'journalRevision': self.journal,
                'sourceTime': simulated_faults.stamp(second, self.detail['dataset']['timeFrom']),
                'deliveredAt': int(self.feed.clock() * 1000),
                'sourceWatermark': min(180, max(0, int((self.feed.clock() * 1000 - self.anchor) // 1000))),
                'sessionRevision': self.revision}

    def frames(self):
        try:
            self.check()
            yield event_bytes('ready', {'dataset': self.detail['dataset'], 'journalRevision': self.journal,
                'sourceMode': 'simulated_stream', 'sessionRevision': self.revision,
                'accessCheckSeconds': ACCESS_SECONDS, 'staleAfterSeconds': 5})
            if self.initial:
                self.check()
                value = self.payload(self.second)
                value['detail'] = {'dataset': self.detail['dataset'],
                    'alarms': [row for row in self.detail['alarms'] if row['sequence'] <= self.second],
                    'trends': [{**{key: row[key] for key in ('metricId', 'unit', 'timeFrom', 'timeTo')},
                                'samples': row['samples'][:self.second + 1]} for row in self.detail['trends']]}
                yield event_bytes('snapshot', value, self.cursor(self.second))
            while not self.closed and not self.feed.stopped.is_set() and self.second < 180:
                self.check()
                watermark = min(180, int((self.feed.clock() * 1000 - self.anchor) // 1000))
                if watermark <= self.second:
                    self.feed.stopped.wait(.1)
                    continue
                # No producer queue: after a slow write the immutable journal
                # supplies only the next record, including all intervening gaps.
                self.second += 1
                value = self.payload(self.second)
                value['samples'] = [{**row['samples'][self.second], 'metricId': row['metricId'],
                                     'unit': row['unit']} for row in self.detail['trends']]
                value['alarms'] = [row for row in self.detail['alarms'] if row['sequence'] == self.second]
                self.check()
                yield event_bytes('sample', value, self.cursor(self.second))
            if self.second == 180 and not self.closed and not self.feed.stopped.is_set():
                self.check()
                yield event_bytes('complete', self.payload(self.second))
        finally:
            self.close()
