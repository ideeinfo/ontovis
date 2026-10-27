"""Owner-scoped analysis storage; schema changes are explicit and offline."""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import hmac
import json
import math
from threading import RLock
from uuid import UUID, uuid4

from .authority import PreviewError

SCHEMA = 'ontovis_analysis_v1'
FORMAT_V1 = 'ontovis-analysis-drafts-v1'
FORMAT = 'ontovis-analysis-sources-v2'
FORMAT_V3 = 'ontovis-analysis-lifecycle-v3'
MAX_BYTES = 256 * 1024
MAX_STORE_BYTES = 8 * 1024 * 1024
MAX_STORE_REVISIONS = 10000
WRITE_LOCK = int.from_bytes(hashlib.sha256((SCHEMA+'-draft-writes').encode()).digest()[:8], 'big', signed=True)
COLUMNS = {
    'store_meta': ('id', 'schema_version', 'connection_id', 'store_id'),
    'analysis_sessions': ('session_id', 'connection_id', 'project_code', 'owner_id', 'title', 'status',
                          'head_revision', 'created_at', 'updated_at'),
    'analysis_revisions': ('session_id', 'revision', 'snapshot_json', 'content_sha256', 'actor_id',
                           'operation', 'restored_from', 'created_at'),
    'analysis_requests': ('connection_id', 'project_code', 'actor_id', 'request_id', 'fingerprint',
                          'result_json', 'created_at'),
}
V1_COLUMNS = dict(COLUMNS)
COLUMNS['analysis_evidence_refs'] = ('evidence_ref_id', 'session_id', 'request_id', 'request_fingerprint',
    'source_kind', 'descriptor_json', 'descriptor_sha256', 'actor_id', 'created_at')
EVIDENCE_DDL = f'''
create table {SCHEMA}.analysis_evidence_refs (
 evidence_ref_id uuid primary key, session_id uuid not null references {SCHEMA}.analysis_sessions(session_id),
 request_id uuid not null, request_fingerprint text not null check(length(request_fingerprint)=64),
 source_kind text not null check(source_kind in ('object','drawing','document','photo','model','work_order','alarm','trend')),
 descriptor_json text not null check(octet_length(descriptor_json)<=16384),
 descriptor_sha256 text not null check(length(descriptor_sha256)=64),
 actor_id uuid not null, created_at text not null, unique(session_id,request_id));
create trigger immutable_analysis_evidence before update or delete on {SCHEMA}.analysis_evidence_refs
 for each row execute function {SCHEMA}.immutable_record();
'''
DDL_V1 = f'''
create schema {SCHEMA};
create table {SCHEMA}.store_meta (
 id integer primary key check(id=1), schema_version integer not null check(schema_version=1),
 connection_id text not null unique, store_id uuid not null unique);
create table {SCHEMA}.analysis_sessions (
 session_id uuid primary key, connection_id text not null references {SCHEMA}.store_meta(connection_id),
 project_code text not null, owner_id uuid not null, title text not null, status text not null
 check(status in ('analyzing','awaiting_field_check','awaiting_expert_review')),
 head_revision integer not null check(head_revision between 1 and 1000), created_at text not null, updated_at text not null);
create index analysis_scope_owner on {SCHEMA}.analysis_sessions(connection_id,project_code,owner_id);
create table {SCHEMA}.analysis_revisions (
 session_id uuid not null references {SCHEMA}.analysis_sessions(session_id), revision integer not null check(revision between 1 and 1000),
 snapshot_json text not null check(octet_length(snapshot_json)<=262144), content_sha256 text not null check(length(content_sha256)=64),
 actor_id uuid not null, operation text not null check(operation in ('create','save','restore')),
 restored_from integer, created_at text not null, primary key(session_id,revision),
 check((operation='restore' and restored_from is not null and restored_from>=1 and restored_from<revision) or (operation<>'restore' and restored_from is null)));
alter table {SCHEMA}.analysis_sessions add constraint analysis_head_exists
 foreign key(session_id,head_revision) references {SCHEMA}.analysis_revisions(session_id,revision) deferrable initially deferred;
create table {SCHEMA}.analysis_requests (
 connection_id text not null, project_code text not null, actor_id uuid not null, request_id uuid not null,
 fingerprint text not null check(length(fingerprint)=64), result_json text not null check(octet_length(result_json)<=2048),
 created_at text not null, primary key(connection_id,project_code,actor_id,request_id));
create function {SCHEMA}.immutable_record() returns trigger language plpgsql as $$
begin raise exception 'ANALYSIS_HISTORY_IMMUTABLE'; end $$;
create trigger immutable_analysis_revisions before update or delete on {SCHEMA}.analysis_revisions
 for each row execute function {SCHEMA}.immutable_record();
create trigger immutable_analysis_requests before update or delete on {SCHEMA}.analysis_requests
 for each row execute function {SCHEMA}.immutable_record();
create trigger immutable_analysis_meta before update or delete on {SCHEMA}.store_meta
 for each row execute function {SCHEMA}.immutable_record();
create function {SCHEMA}.fixed_owner() returns trigger language plpgsql as $$
begin
 if new.session_id<>old.session_id or new.connection_id<>old.connection_id or new.project_code<>old.project_code
 or new.owner_id<>old.owner_id or new.created_at<>old.created_at or new.head_revision<>old.head_revision+1 then
 raise exception 'ANALYSIS_IDENTITY_IMMUTABLE'; end if;
 return new;
end $$;
create trigger analysis_fixed_owner before update on {SCHEMA}.analysis_sessions
 for each row execute function {SCHEMA}.fixed_owner();
'''
CANVAS_INDEX_DDL = f'''create index if not exists analysis_fault_context on {SCHEMA}.analysis_revisions
 ((snapshot_json::jsonb #>> '{{context,sourceConnectionId}}'),(snapshot_json::jsonb #>> '{{context,faultCode}}'),session_id,revision)
 where snapshot_json::jsonb->>'schemaVersion'='2';'''
DDL = DDL_V1.replace('schema_version=1', 'schema_version=2') + EVIDENCE_DDL + CANVAS_INDEX_DDL
V3_COLUMNS = {**COLUMNS, 'analysis_lifecycle_events': ('session_id', 'lifecycle_revision', 'state',
    'analysis_revision', 'actor_id', 'request_id', 'created_at')}
LIFECYCLE_DDL = f'''
create table {SCHEMA}.analysis_lifecycle_events (
 session_id uuid not null references {SCHEMA}.analysis_sessions(session_id),
 lifecycle_revision integer not null check(lifecycle_revision between 1 and 1000),
 state text not null check(state in ('active','trashed')),
 analysis_revision integer not null, actor_id uuid not null, request_id uuid not null, created_at text not null,
 primary key(session_id,lifecycle_revision), unique(session_id,request_id),
 foreign key(session_id,analysis_revision) references {SCHEMA}.analysis_revisions(session_id,revision));
create trigger immutable_analysis_lifecycle before update or delete on {SCHEMA}.analysis_lifecycle_events
 for each row execute function {SCHEMA}.immutable_record();
'''
DDL_V3 = DDL.replace('schema_version=2', 'schema_version=3') + LIFECYCLE_DDL


def columns_for(version):
    return {1: V1_COLUMNS, 2: COLUMNS, 3: V3_COLUMNS}[version]


def require(condition, code='INVALID_REQUEST', status=422):
    if not condition:
        raise PreviewError(status, code)


def text(value, limit=120):
    require(type(value) is str and bool(value.strip()) and value == value.strip() and len(value) <= limit)
    require('\x00' not in value)
    try:
        value.encode('utf-8')
    except UnicodeError:
        raise PreviewError(422, 'INVALID_REQUEST') from None
    return value


def identifier(value):
    try:
        require(type(value) is str and str(UUID(value)) == value)
    except (ValueError, TypeError, AttributeError):
        raise PreviewError(422, 'INVALID_REQUEST') from None
    return value


def canonical(value):
    try:
        encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)
        encoded.encode('utf-8')
        return encoded
    except (ValueError, TypeError, RecursionError, UnicodeError):
        raise PreviewError(422, 'INVALID_REQUEST') from None


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def number(value, low, high):
    return type(value) in (int, float) and math.isfinite(value) and low <= value <= high


def utc(value):
    require(type(value) is str and len(value) in (20, 24) and value.endswith('Z'))
    try:
        parsed = datetime.fromisoformat(value[:-1] + '+00:00')
    except ValueError:
        raise PreviewError(422, 'INVALID_REQUEST') from None
    canonical_time = parsed.isoformat(timespec='milliseconds' if len(value) == 24 else 'seconds').replace('+00:00', 'Z')
    require(canonical_time == value)
    return parsed


def validate_snapshot(value, connection_id, project_code):
    """V1 notes remain immutable; V2 sources are checked against owned handles on write."""
    if type(value) is dict and value.get('schemaVersion') == 2:
        from .analysis_canvas import validate_canvas
        return validate_canvas(value, connection_id, project_code)
    text(connection_id); text(project_code)
    require(type(value) is dict and set(value) == {'schemaVersion', 'ontobaseConnectionId', 'projectCode',
        'title', 'status', 'context', 'cards', 'relations', 'viewport'})
    require(type(value['schemaVersion']) is int and value['schemaVersion'] == 1)
    require((value['ontobaseConnectionId'], value['projectCode']) == (connection_id, project_code),
            'ANALYSIS_SCOPE_MISMATCH', 404)
    text(value['title'])
    require(value['status'] in ('analyzing', 'awaiting_field_check', 'awaiting_expert_review'),
            'ANALYSIS_REVIEW_NOT_CONFIGURED', 409)
    context = value['context']
    require(type(context) is dict and set(context) == {'objectIds', 'timeFrom', 'timeTo', 'timezone'})
    require(type(context['objectIds']) is list and not context['objectIds'], 'ANALYSIS_SOURCE_NOT_CONNECTED', 409)
    require(context['timezone'] in ('UTC', 'Asia/Shanghai') and utc(context['timeFrom']) < utc(context['timeTo']))
    view = value['viewport']
    require(type(view) is dict and set(view) == {'x', 'y', 'zoom'} and number(view['x'], -50000, 50000)
            and number(view['y'], -50000, 50000) and number(view['zoom'], .25, 1.5))
    cards, relations = value['cards'], value['relations']
    require(type(cards) is list and len(cards) <= 50 and type(relations) is list and len(relations) <= 100,
            'ANALYSIS_SIZE_LIMIT', 413)
    ids = set()
    for card in cards:
        require(type(card) is dict)
        require(card.get('kind') == 'analysis' and 'source' not in card, 'ANALYSIS_SOURCE_NOT_CONNECTED', 409)
        require(set(card) == {'id', 'kind', 'title', 'x', 'y', 'width', 'height', 'pinned', 'note'})
        key = text(card['id'], 100); text(card['title'])
        require(key not in ids); ids.add(key)
        require(number(card['x'], -20000, 20000) and number(card['y'], -20000, 20000)
                and number(card['width'], 240, 720) and number(card['height'], 176, 960)
                and type(card['pinned']) is bool and type(card['note']) is str and len(card['note']) <= 4000
                and '\x00' not in card['note'])
    keys, edges = set(), set()
    for relation in relations:
        require(type(relation) is dict and set(relation) == {'id', 'from', 'to', 'kind', 'origin', 'reason'})
        key = text(relation['id'], 100)
        require(relation['origin'] == 'manual' and relation['kind'] in ('reference', 'hypothesis', 'supports', 'contradicts'),
                'ANALYSIS_SOURCE_NOT_CONNECTED', 409)
        require(type(relation['from']) is str and type(relation['to']) is str and relation['from'] in ids
                and relation['to'] in ids and relation['from'] != relation['to'])
        edge = (relation['from'], relation['to'], relation['kind'])
        require(key not in keys and edge not in edges); keys.add(key); edges.add(edge)
        text(relation['reason'], 1000)
    raw = canonical(value)
    require(len(raw.encode()) <= MAX_BYTES, 'ANALYSIS_SIZE_LIMIT', 413)
    return raw


class AnalysisConnection:
    def __init__(self, database_url):
        require(type(database_url) is str and bool(database_url), 'ANALYSIS_DATABASE_REQUIRED', 503)
        try:
            import psycopg
        except ImportError:
            raise PreviewError(503, 'ANALYSIS_DRIVER_REQUIRED') from None
        self.driver, self.db, self.lock = psycopg, None, RLock()
        try:
            self.db = psycopg.connect(database_url, connect_timeout=5, autocommit=True)
            name = self.db.execute('select current_database()').fetchone()[0]
            require(name.startswith('ontovis_'), 'ANALYSIS_DEDICATED_DATABASE_REQUIRED', 409)
            self.db.execute("set statement_timeout='15s'")
            self.db.execute("set lock_timeout='5s'")
        except BaseException as error:
            self.close()
            if isinstance(error, psycopg.Error):
                raise PreviewError(503, 'ANALYSIS_DATABASE_UNAVAILABLE') from None
            raise

    @contextmanager
    def transaction(self, readonly=False):
        with self.lock:
            require(self.db is not None and not self.db.closed, 'ANALYSIS_CONNECTION_CLOSED', 503)
            try:
                with self.db.transaction(), self.db.cursor() as cursor:
                    if readonly:
                        cursor.execute('set transaction isolation level repeatable read, read only')
                    yield cursor
            except self.driver.Error as error:
                code = 'ANALYSIS_BUSY' if error.sqlstate in ('55P03', '57014', '40001') else 'ANALYSIS_DATABASE_UNAVAILABLE'
                raise PreviewError(503, code) from None

    def close(self):
        if self.db is not None:
            self.db.close()


def profile(cursor):
    cursor.execute('select table_name,column_name from information_schema.columns where table_schema=%s order by table_name,ordinal_position', (SCHEMA,))
    actual = {}
    for table, column in cursor.fetchall():
        actual.setdefault(table, []).append(column)
    version = next((v for v in (1, 2, 3) if actual == {name: list(columns) for name, columns in columns_for(v).items()}), None)
    require(version is not None, 'ANALYSIS_PROFILE_CHANGED', 409)
    cursor.execute(f'select schema_version from {SCHEMA}.store_meta where id=1')
    row = cursor.fetchone()
    require(row and row[0] == version, 'ANALYSIS_PROFILE_CHANGED', 409)
    return version


def provision(database_url, connection_id, *, version=2):
    text(connection_id)
    require(type(version) is int and version in (1, 2, 3))
    connection = AnalysisConnection(database_url)
    try:
        with connection.transaction() as cursor:
            cursor.execute('select to_regnamespace(%s)', (SCHEMA,))
            require(cursor.fetchone()[0] is None, 'ANALYSIS_TARGET_OCCUPIED', 409)
            cursor.execute({1: DDL_V1, 2: DDL, 3: DDL_V3}[version])
            store_id = str(uuid4())
            cursor.execute(f'insert into {SCHEMA}.store_meta values(1,%s,%s,%s)', (version, connection_id, store_id))
            profile(cursor)
        return {'storeId': store_id, 'connectionId': connection_id, 'schemaVersion': version}
    finally:
        connection.close()


class AnalysisDrafts:
    def __init__(self, database_url, connection_id, project_code, *, clock=None):
        self.connection_id, self.project_code = text(connection_id), text(project_code)
        self.clock = clock or (lambda: datetime.now(timezone.utc).isoformat(timespec='milliseconds').replace('+00:00', 'Z'))
        self.connection = AnalysisConnection(database_url)
        try:
            with self.connection.transaction(readonly=True) as cursor:
                self.schema_version = profile(cursor)
                cursor.execute(f'select connection_id,store_id::text from {SCHEMA}.store_meta where id=1')
                row = cursor.fetchone()
                require(row and row[0] == self.connection_id, 'ANALYSIS_STORE_SCOPE_MISMATCH', 409)
                self.store_id = row[1]
        except BaseException:
            self.close(); raise

    def close(self):
        self.connection.close()

    def lifecycle(self, cursor, session_id):
        if self.schema_version < 3:
            return {'lifecycle': 'active', 'lifecycleRevision': 0}
        cursor.execute(f'''select state,lifecycle_revision from {SCHEMA}.analysis_lifecycle_events
            where session_id=%s order by lifecycle_revision desc limit 1''', (session_id,))
        row = cursor.fetchone()
        return {'lifecycle': row[0], 'lifecycleRevision': row[1]} if row else {'lifecycle': 'active', 'lifecycleRevision': 0}

    def _session(self, cursor, session_id, actor_id, *, lock=False, active=False):
        identifier(session_id); identifier(actor_id)
        cursor.execute(f'''select head_revision,title,status,created_at,updated_at from {SCHEMA}.analysis_sessions
            where session_id=%s and connection_id=%s and project_code=%s and owner_id=%s''' + (' for update' if lock else ''),
            (session_id, self.connection_id, self.project_code, actor_id))
        row = cursor.fetchone()
        require(row, 'NOT_FOUND_OR_FORBIDDEN', 404)
        if active:
            require(self.lifecycle(cursor, session_id)['lifecycle'] == 'active', 'ANALYSIS_TRASHED', 409)
        return row

    def _revision(self, cursor, session_id, revision):
        require(type(revision) is int and 1 <= revision <= 1000)
        cursor.execute(f'select snapshot_json,content_sha256,operation,restored_from,created_at from {SCHEMA}.analysis_revisions where session_id=%s and revision=%s', (session_id, revision))
        row = cursor.fetchone()
        require(row, 'NOT_FOUND_OR_FORBIDDEN', 404)
        try:
            snapshot = json.loads(row[0])
            raw = validate_snapshot(snapshot, self.connection_id, self.project_code)
            require(raw == row[0] and hashlib.sha256(raw.encode()).hexdigest() == row[1])
        except (ValueError, PreviewError):
            raise PreviewError(409, 'ANALYSIS_STORAGE_INVALID') from None
        return snapshot, row

    def detail(self, actor_id, session_id, authorize, *, revision=None):
        authorize()
        with self.connection.transaction(readonly=True) as cursor:
            head = self._session(cursor, session_id, actor_id)[0]
            version = head if revision is None else revision
            snapshot, row = self._revision(cursor, session_id, version)
            authorize()
            return {'analysisSessionId': session_id, 'analysisRevision': version, 'headRevision': head,
                    'contentSha256': row[1], 'snapshot': snapshot, 'operation': row[2], 'restoredFromRevision': row[3],
                    **self.lifecycle(cursor, session_id)}

    def history(self, actor_id, session_id, authorize, *, before=None, limit=25):
        require(type(limit) is int and 1 <= limit <= 50)
        require(before is None or type(before) is int and 1 <= before <= 1001)
        authorize()
        with self.connection.transaction(readonly=True) as cursor:
            head = self._session(cursor, session_id, actor_id)[0]
            cursor.execute(f'''select revision,content_sha256,operation,restored_from,created_at from {SCHEMA}.analysis_revisions
                where session_id=%s and revision<%s order by revision desc limit %s''', (session_id, before or head+1, limit+1))
            rows = cursor.fetchall(); more = len(rows) > limit; rows = rows[:limit]
            authorize()
            return {'headRevision': head, 'items': [{'revision':r[0], 'contentSha256':r[1], 'operation':r[2],
                    'restoredFromRevision':r[3], 'createdAt':r[4]} for r in rows],
                    'nextBeforeRevision': rows[-1][0] if more else None}

    def listing(self, actor_id, body, authorize, *, cursor_key, session_revision):
        identifier(actor_id)
        require(type(body) is dict and set(body) <= {'q', 'status', 'limit', 'cursor', 'lifecycle'})
        lifecycle = body.get('lifecycle', 'active')
        require(lifecycle in ('active', 'trashed'))
        query, status, limit = body.get('q', ''), body.get('status', ''), body.get('limit', 25)
        require(type(query) is str and len(query) <= 200 and type(limit) is int and 1 <= limit <= 50)
        require(status in ('', 'analyzing', 'awaiting_field_check', 'awaiting_expert_review'))
        authorize()
        with self.connection.transaction(readonly=True) as cursor:
            projection = (f'''left join lateral (select state,lifecycle_revision,created_at as changed_at
                from {SCHEMA}.analysis_lifecycle_events where session_id=s.session_id order by lifecycle_revision desc limit 1) l on true'''
                if self.schema_version >= 3 else "left join (select 'active'::text as state,0 as lifecycle_revision,null::text as changed_at) l on true")
            cursor.execute(f'''select s.session_id::text,s.title,s.status,s.head_revision,s.created_at,s.updated_at,
                coalesce(l.state,'active'),coalesce(l.lifecycle_revision,0),coalesce(l.changed_at,s.updated_at)
                from {SCHEMA}.analysis_sessions s {projection}
                where s.connection_id=%s and s.project_code=%s and s.owner_id=%s
                and coalesce(l.state,'active')=%s order by coalesce(l.changed_at,s.updated_at) desc,s.session_id limit 1001''',
                (self.connection_id, self.project_code, actor_id, lifecycle))
            rows = cursor.fetchall()
            require(len(rows) <= 1000, 'ANALYSIS_STORAGE_INVALID', 409)
            items = [{'analysisSessionId': r[0], 'title': r[1], 'status': r[2], 'analysisRevision': r[3],
                      'createdAt': r[4], 'updatedAt': r[5], 'lifecycle': r[6], 'lifecycleRevision': r[7], 'lifecycleChangedAt': r[8]} for r in rows
                     if (not status or r[2] == status) and query.strip().casefold() in r[1].casefold()]
            revision = digest([self.store_id, self.connection_id, self.project_code, actor_id,
                               session_revision, query, status, lifecycle, limit, items])
            start = 0
            token = body.get('cursor')
            if token is not None:
                require(type(token) is str and len(token) <= 200)
                try:
                    offset, previous, signature = token.split('.')
                    unsigned = offset + '.' + previous
                    require(hmac.compare_digest(signature, hmac.new(cursor_key, unsigned.encode(), 'sha256').hexdigest()))
                    require(previous == revision, 'ANALYSIS_LIST_CHANGED', 409)
                    start = int(offset)
                    require(str(start) == offset and 0 <= start <= len(items))
                except (ValueError, TypeError):
                    raise PreviewError(422, 'INVALID_REQUEST') from None
            following = None
            if start + limit < len(items):
                unsigned = str(start + limit) + '.' + revision
                following = unsigned + '.' + hmac.new(cursor_key, unsigned.encode(), 'sha256').hexdigest()
            authorize()
            return {'items': items[start:start+limit], 'total': len(items), 'nextCursor': following,
                    'snapshotRevision': revision}

    def write(self, actor_id, project_role, action, body, authorize):
        """actor/role and authorize must come from the server session, never JSON."""
        identifier(actor_id); authorize()
        require(project_role == 'admin', 'ANALYSIS_WRITE_FORBIDDEN', 403)
        require(type(body) is dict and action in ('create', 'save', 'restore'))
        allowed = {'requestId', 'snapshot'} if action == 'create' else {'requestId', 'analysisSessionId', 'expectedAnalysisRevision', 'snapshot' if action == 'save' else 'restoreRevision'}
        require(set(body) == allowed)
        request_id = identifier(body['requestId'])
        raw = validate_snapshot(body['snapshot'], self.connection_id, self.project_code) if action != 'restore' else None
        fingerprint = digest({'action': action, 'body': body})
        timestamp = self.clock(); utc(timestamp)
        scope = (self.connection_id, self.project_code, actor_id, request_id)
        with self.connection.transaction() as cursor:
            key = int.from_bytes(hashlib.sha256(canonical(scope).encode()).digest()[:8], 'big', signed=True)
            cursor.execute('select pg_advisory_xact_lock(%s)', (key,))
            cursor.execute(f'select fingerprint,result_json from {SCHEMA}.analysis_requests where connection_id=%s and project_code=%s and actor_id=%s and request_id=%s', scope)
            replay = cursor.fetchone()
            if replay:
                require(replay[0] == fingerprint, 'ANALYSIS_REQUEST_CONFLICT', 409)
                result = json.loads(replay[1]); self._session(cursor, result['analysisSessionId'], actor_id, active=True)
                authorize(); return result
            # Keep the bounded draft store exportable. Candidate writes serialize
            # this quota check; this is not a multi-process throughput claim.
            cursor.execute('select pg_advisory_xact_lock(%s)', (WRITE_LOCK,))
            restored_from = None
            if action == 'create':
                project_key = int.from_bytes(hashlib.sha256(canonical(scope[:2]).encode()).digest()[:8], 'big', signed=True)
                cursor.execute('select pg_advisory_xact_lock(%s)', (project_key,))
                cursor.execute(f'select count(*) from {SCHEMA}.analysis_sessions where connection_id=%s and project_code=%s', scope[:2])
                require(cursor.fetchone()[0] < 1000, 'ANALYSIS_SESSION_LIMIT', 413)
                session_id, revision = str(uuid4()), 1
            else:
                session_id = identifier(body['analysisSessionId'])
                current = self._session(cursor, session_id, actor_id, lock=True, active=True)[0]
                require(type(body['expectedAnalysisRevision']) is int and current == body['expectedAnalysisRevision'], 'ANALYSIS_CHANGED', 409)
                require(current < 1000, 'ANALYSIS_REVISION_LIMIT', 413)
                revision = current + 1
                if action == 'restore':
                    restored_from = body['restoreRevision']
                    _, stored = self._revision(cursor, session_id, restored_from)
                    raw = stored[0]
            snapshot = json.loads(raw)
            if snapshot.get('schemaVersion') == 2:
                from .analysis_canvas import validate_handles
                validate_handles(cursor, session_id, snapshot, self.schema_version)
            sha = hashlib.sha256(raw.encode()).hexdigest()
            cursor.execute(f'select count(*),coalesce(sum(octet_length(snapshot_json)),0) from {SCHEMA}.analysis_revisions')
            count, used = cursor.fetchone()
            require(count < MAX_STORE_REVISIONS and used + len(raw.encode()) <= MAX_STORE_BYTES,
                    'ANALYSIS_STORE_LIMIT', 413)
            if action == 'create':
                cursor.execute(f'insert into {SCHEMA}.analysis_sessions values(%s,%s,%s,%s,%s,%s,%s,%s,%s)',
                    (session_id, self.connection_id, self.project_code, actor_id, snapshot['title'], snapshot['status'], revision, timestamp, timestamp))
            cursor.execute(f'insert into {SCHEMA}.analysis_revisions values(%s,%s,%s,%s,%s,%s,%s,%s)',
                (session_id, revision, raw, sha, actor_id, action, restored_from, timestamp))
            if action != 'create':
                cursor.execute(f'update {SCHEMA}.analysis_sessions set head_revision=%s,title=%s,status=%s,updated_at=%s where session_id=%s',
                    (revision, snapshot['title'], snapshot['status'], timestamp, session_id))
            result = {'analysisSessionId': session_id, 'analysisRevision': revision, 'contentSha256': sha,
                      'operation': action, 'restoredFromRevision': restored_from}
            cursor.execute(f'select count(*) from {SCHEMA}.analysis_requests')
            require(cursor.fetchone()[0]<MAX_STORE_REVISIONS,'ANALYSIS_STORE_LIMIT',413)
            cursor.execute(f'insert into {SCHEMA}.analysis_requests values(%s,%s,%s,%s,%s,%s,%s)',
                (*scope, fingerprint, canonical(result), timestamp))
            authorize()
            return result
