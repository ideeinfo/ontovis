"""Project forecast configuration and a bounded, shared MET response cache."""
from __future__ import annotations
import json
import math
import re
import time
from threading import Lock
from urllib.parse import urlsplit
from .assistant_store import require, identifier, encoded, digest
from . import weather_source as source

DEFAULT = dict(enabled=False, provider='met_no', contact='https://github.com/ideeinfo/ontovis', refreshMinutes=180, points=[])


def validate_config(value):
    require(type(value) is dict and set(value) == set(DEFAULT))
    require(type(value['enabled']) is bool and value['provider'] == 'met_no')
    require(type(value['refreshMinutes']) is int and value['refreshMinutes'] in (180, 360, 720))
    contact = value['contact']
    require(type(contact) is str and 5 <= len(contact) <= 200 and contact.isascii()
            and not re.search(r'[\s\x00-\x1f\x7f]', contact))
    try: target = urlsplit(contact)
    except ValueError:
        require(False)
    require(bool(re.fullmatch(r'[^@/]+@[^@/]+\.[^@/]+', contact)) or
            (target.scheme == 'https' and bool(target.hostname) and not target.username and not target.password))
    points = value['points']; require(type(points) is list and len(points) <= 50)
    result = []
    for point in points:
        require(type(point) is dict and set(point) == {'sceneId', 'label', 'latitude', 'longitude'})
        identifier(point['sceneId'])
        require(type(point['label']) is str and 0 < len(point['label'].strip()) <= 80
                and not any(ord(c) < 32 for c in point['label']))
        normalized = dict(point, label=point['label'].strip())
        for key, high in [('latitude', 90), ('longitude', 180)]:
            number = point[key]
            require(type(number) in (float, int) and math.isfinite(number) and -high <= number <= high)
            normalized[key] = math.trunc(number * 10000) / 10000
        result.append(normalized)
    require(len({p['sceneId'] for p in result}) == len(result))
    require(not value['enabled'] or bool(result))
    return {**value, 'points': sorted(result, key=lambda p: p['sceneId'])}


class WeatherStore:
    def __init__(self, library, connection_id, *, clock=time.time, fetcher=None):
        self.library, self.connection_id, self.clock = library, connection_id, clock
        self.fetcher = fetcher or source.fetch
        self.lock, self.last_attempt = Lock(), float('-inf')
        with library.connect() as db:
            db.executescript('''
            create table if not exists weather_config_revisions (
                connection_id text not null, project_code text not null, revision integer not null,
                config text not null, actor text not null, saved_at text not null,
                primary key(connection_id,project_code,revision));
            create table if not exists weather_config_requests (
                connection_id text not null, project_code text not null, actor text not null,
                request_id text not null, fingerprint text not null, result text not null,
                primary key(connection_id,project_code,actor,request_id));
            create table if not exists weather_cache (
                cache_key text primary key, payload text, fetched_at real, checked_at real not null,
                retry_at real not null, modified text, error text);
            ''')

    def config(self, project, db=None):
        if db is None:
            with self.library.connect() as current: return self.config(project, current)
        row = db.execute('''select * from weather_config_revisions where connection_id=? and project_code=?
                            order by revision desc limit 1''', (self.connection_id, project)).fetchone()
        return dict(revision=row['revision'], config=json.loads(row['config']), savedAt=row['saved_at']) if row else dict(revision=0, config={**DEFAULT, 'points': []}, savedAt=None)

    def save(self, project, actor, body, authorize):
        identifier(body['requestId']); require(type(body['expectedRevision']) is int and 0 <= body['expectedRevision'] < 1000)
        config = validate_config(body['config']); fingerprint = digest(body); authorize()
        with self.library.connect() as db:
            db.execute('begin immediate')
            prior = db.execute('''select * from weather_config_requests where connection_id=? and project_code=?
                                and actor=? and request_id=?''', (self.connection_id, project, actor, body['requestId'])).fetchone()
            if prior:
                require(prior['fingerprint'] == fingerprint, 'REQUEST_ID_REUSED', 409); authorize()
                return json.loads(prior['result'])
            current = self.config(project, db)
            require(current['revision'] == body['expectedRevision'], 'WEATHER_CONFIG_CHANGED', 409)
            result = dict(revision=current['revision'] + 1, config=config, savedAt=source.iso(self.clock()))
            authorize()
            db.execute('insert into weather_config_revisions values(?,?,?,?,?,?)',
                       (self.connection_id, project, result['revision'], encoded(config), actor, result['savedAt']))
            db.execute('insert into weather_config_requests values(?,?,?,?,?,?)',
                       (self.connection_id, project, actor, body['requestId'], fingerprint, encoded(result)))
            authorize()
            return result

    def current(self, config, point, authorize):
        key = digest([point['latitude'], point['longitude']])
        if not self.lock.acquire(timeout=12): return dict(status='unavailable', error='WEATHER_BUSY', source=source.SOURCE, point=point)
        try:
            authorize(); now = self.clock()
            with self.library.connect() as db:
                record = db.execute('select * from weather_cache where cache_key=?', (key,)).fetchone()
            row = dict(record) if record else dict(payload=None, fetched_at=None, checked_at=0, retry_at=0, modified=None, error=None)
            due = max(row['retry_at'], row['checked_at'] + config['refreshMinutes'] * 60 if not row['error'] else 0)
            if now >= due:
                if now < self.last_attempt + 1:
                    return dict(status='unavailable', error='WEATHER_BUSY', source=source.SOURCE, point=point)
                self.last_attempt = now
                try:
                    status, value, headers = self.fetcher(point, config['contact'], row['modified'] if row['payload'] else None)
                    if status == 200:
                        source.validate_document(value, point)
                        row.update(payload=encoded(value), fetched_at=now)
                    elif status != 304 or not row['payload']: raise source.WeatherFailure('WEATHER_INVALID_DATA')
                    modified = headers.get('last-modified')
                    if modified and len(modified) <= 100 and '\r' not in modified and '\n' not in modified:
                        row['modified'] = modified
                    row.update(checked_at=now, retry_at=max(now + 10800, source.http_time(headers.get('expires'), now)), error=None)
                except source.WeatherFailure as error:
                    row.update(checked_at=now, retry_at=now + error.retry, error=error.code)
                authorize()
                with self.library.connect() as db:
                    db.execute('''insert or replace into weather_cache values(?,?,?,?,?,?,?)''',
                               (key, row['payload'], row['fetched_at'], row['checked_at'], row['retry_at'], row['modified'], row['error']))
                    db.execute('''delete from weather_cache where cache_key in
                        (select cache_key from weather_cache order by checked_at desc limit -1 offset 128)''')
            authorize()
            current = source.forecast(json.loads(row['payload']), self.clock()) if row['payload'] else None
            status = 'available' if current and current['usable'] and not row['error'] else 'stale' if current else 'unavailable'
            return dict(status=status, error=row['error'] or (None if status == 'available' else 'WEATHER_OUTDATED'),
                        forecast=current, point=point, source=source.SOURCE,
                        fetchedAt=source.iso(row['fetched_at']) if row['fetched_at'] is not None else None,
                        nextFetchAt=source.iso(max(row['retry_at'], row['checked_at'] + config['refreshMinutes'] * 60 if not row['error'] else 0)))
        finally: self.lock.release()
