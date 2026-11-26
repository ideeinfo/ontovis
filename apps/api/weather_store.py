"""Project forecast configuration and a bounded, shared MET response cache."""
from __future__ import annotations
import json
import math
import re
import time
from threading import Lock
from urllib.parse import urlsplit
from uuid import uuid4
from .assistant_store import require, identifier, encoded, digest
from . import weather_source as source

DEFAULT = dict(enabled=False, provider='met_no', contact='https://github.com/ideeinfo/ontovis', refreshMinutes=180)


def validate_config(value):
    require(type(value) is dict and set(value) - {'points'} == set(DEFAULT))
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
    result = {k: value[k] for k in DEFAULT}
    if 'points' in value:
        points = value['points']
        require(type(points) is list and len(points) <= 50)
        ids = []
        for point in points:
            require(type(point) is dict and set(point) == {'sceneId', 'label', 'latitude', 'longitude'})
            identifier(point['sceneId']); ids.append(point['sceneId'])
            require(type(point['label']) is str and 0 < len(point['label'].strip()) <= 80
                    and not any(ord(c) < 32 for c in point['label']))
            for key, high in [('latitude', 90), ('longitude', 180)]:
                number = point[key]
                require(type(number) in (int, float) and math.isfinite(number) and -high <= number <= high)
        require(len(set(ids)) == len(ids))
        result['points'] = points
    return result


class WeatherStore:
    def __init__(self, library, connection_id, *, clock=time.time, fetcher=None):
        self.library, self.connection_id, self.clock = library, connection_id, clock
        self.fetcher = fetcher or source.fetch
        self.lock, self.last_attempt = Lock(), float('-inf')
        with library.connect() as db:
            db.execute('''create table if not exists weather_cache (
                cache_key text primary key, payload text, fetched_at real, checked_at real not null,
                retry_at real not null, modified text, error text)''')

    def _record(self, db, project):
        scope = (self.connection_id, project)
        tables = {row[0] for row in db.execute("""select name from sqlite_master where type='table'
            and name in ('weather_settings','weather_config_revisions')""")}
        if 'weather_settings' in tables:
            row = db.execute('''select config,config_token,saved_at from weather_settings
                where connection_id=? and project_code=?''', scope).fetchone()
            if row is not None:
                return dict(row)
        if 'weather_config_revisions' in tables:
            # Adopt the last legacy settings at the next authorized save. Reads leave the database as found.
            row = db.execute('''select config,revision,saved_at from weather_config_revisions
                where connection_id=? and project_code=? order by revision desc limit 1''', scope).fetchone()
            if row is not None:
                return dict(config=row['config'], saved_at=row['saved_at'], legacy=True,
                            config_token=digest([*scope, row['revision'], row['config'], row['saved_at']]))
        return None

    @staticmethod
    def _view(row):
        if row is None: return dict(configToken=None, config=dict(DEFAULT), savedAt=None)
        saved = json.loads(row['config'])
        legacy = None if 'points' not in saved else [point['sceneId'] for point in validate_config(saved)['points']]
        return dict(configToken=row['config_token'], config={**DEFAULT, **{k: saved[k] for k in DEFAULT if k in saved}},
                    savedAt=row['saved_at'], **({'legacySceneIds': legacy} if legacy is not None else {}))

    def config(self, project):
        with self.library.connect() as db:
            return self._view(self._record(db, project))

    def save(self, project, body, authorize):
        expected = body['expectedConfigToken']
        require(expected is None or type(expected) is str and re.fullmatch(r'(?:[0-9a-f]{32}|[0-9a-f]{64})', expected))
        config = encoded(validate_config(body['config']))
        authorize()
        with self.library.connect() as db:
            db.execute('begin immediate')
            current = self._record(db, project)
            if current and not current.get('legacy') and current['config'] == config:
                authorize()
                return self._view(current)
            require((current['config_token'] if current else None) == expected, 'WEATHER_CONFIG_CHANGED', 409)
            result = dict(config=config, config_token=uuid4().hex, saved_at=source.iso(self.clock()))
            authorize()
            db.execute('''create table if not exists weather_settings (
                connection_id text not null, project_code text not null, config text not null,
                config_token text not null, saved_at text not null, primary key(connection_id,project_code))''')
            db.execute('''insert into weather_settings(connection_id,project_code,config,config_token,saved_at)
                values(?,?,?,?,?) on conflict(connection_id,project_code) do update set
                config=excluded.config, config_token=excluded.config_token, saved_at=excluded.saved_at''',
                (self.connection_id, project, config, result['config_token'], result['saved_at']))
            authorize()
            return self._view(result)

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
