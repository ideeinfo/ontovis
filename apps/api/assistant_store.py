"""Project policy history and owner-scoped assistant receipts in the paired library."""
from __future__ import annotations
from datetime import datetime, timezone
import hashlib
import json
from uuid import UUID, uuid4
from .authority import PreviewError

KINDS = ('object','alarm','trend','drawing','photo','model','document','work_order')
SERVICE = 'ontobase-qwen-ontovis-v1'
DEFAULT = dict(enabled=False, serviceRef=SERVICE, allowedKinds=list(KINDS), reads=8, parallel=2, seconds=120)
ACTIVE = ('reading','model','validating','cancel_requested')

def require(value, code='INVALID_REQUEST', status=422):
    if not value: raise PreviewError(status, code)

def identifier(value):
    try: require(type(value) is str and str(UUID(value)) == value)
    except (ValueError, TypeError, AttributeError): raise PreviewError(422,'INVALID_REQUEST') from None
    return value

def encoded(value): return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)
def digest(value): return hashlib.sha256(encoded(value).encode()).hexdigest()
def now(): return datetime.now(timezone.utc).isoformat().replace('+00:00','Z')

def validate_policy(value):
    require(type(value) is dict and set(value) == set(DEFAULT))
    require(type(value['enabled']) is bool and value['serviceRef'] == SERVICE)
    require(type(value['allowedKinds']) is list and 1 <= len(value['allowedKinds']) <= 8
            and all(type(v) is str and v in KINDS for v in value['allowedKinds'])
            and len(set(value['allowedKinds'])) == len(value['allowedKinds']))
    for key, high in [('reads',8),('parallel',2),('seconds',120)]:
        require(type(value[key]) is int and (10 if key == 'seconds' else 1) <= value[key] <= high)
    return {**value, 'allowedKinds': sorted(value['allowedKinds'])}


class AssistantStore:
    def __init__(self, library, connection_id):
        self.library, self.connection_id = library, connection_id
        with library.connect() as db:
            db.executescript('''
            create table if not exists assistant_policy_heads (
                connection_id text not null, project_code text not null, revision integer not null,
                primary key(connection_id,project_code));
            create table if not exists assistant_policy_revisions (
                connection_id text not null, project_code text not null, revision integer not null,
                policy text not null, actor text not null, created_at text not null, operation text not null,
                restored_from integer, primary key(connection_id,project_code,revision));
            create table if not exists assistant_policy_requests (
                connection_id text not null, project_code text not null, actor text not null,
                request_id text not null, fingerprint text not null, result text not null,
                primary key(connection_id,project_code,actor,request_id));
            create table if not exists assistant_runs (
                id text primary key, connection_id text not null, project_code text not null, owner text not null,
                request_id text not null, fingerprint text not null, analysis_id text not null, analysis_revision integer not null,
                policy_revision integer not null, service_revision text not null, state text not null, version integer not null,
                created_at text not null, updated_at text not null, input_json text not null, sources_json text not null,
                progress_json text not null, result_json text, error_code text,
                unique(connection_id,project_code,owner,request_id));
            create trigger if not exists assistant_policy_immutable_update before update on assistant_policy_revisions
                begin select raise(abort,'immutable assistant policy'); end;
            create trigger if not exists assistant_policy_immutable_delete before delete on assistant_policy_revisions
                begin select raise(abort,'immutable assistant policy'); end;
            ''')
            # An uncertain request is never automatically sent to the provider again.
            db.execute("update assistant_runs set state='interrupted',version=version+1,updated_at=?,error_code='ASSISTANT_INTERRUPTED' where connection_id=? and state in ('reading','model','validating','cancel_requested')", (now(),connection_id))

    def policy(self, project, db=None):
        if db is None:
            with self.library.connect() as current: return self.policy(project,current)
        row = db.execute('''select r.* from assistant_policy_heads h join assistant_policy_revisions r
            using(connection_id,project_code,revision) where h.connection_id=? and h.project_code=?''',(self.connection_id,project)).fetchone()
        return {'revision':row['revision'],'policy':json.loads(row['policy']),'savedAt':row['created_at']} if row else {'revision':0,'policy':dict(DEFAULT),'savedAt':None}

    def history(self, project):
        with self.library.connect() as db:
            return [{'revision':r['revision'],'savedAt':r['created_at'],'operation':r['operation'],'restoredFrom':r['restored_from'],
                     'policy':json.loads(r['policy'])} for r in db.execute('''select * from assistant_policy_revisions
                where connection_id=? and project_code=? order by revision desc limit 50''',(self.connection_id,project))]

    def publish(self, project, actor, body, authorize):
        identifier(body['requestId']);require(type(body['expectedRevision']) is int and 0 <= body['expectedRevision'] < 1000)
        rollback = 'restoreRevision' in body
        policy = None if rollback else validate_policy(body['policy'])
        if rollback: require(type(body['restoreRevision']) is int and 1 <= body['restoreRevision'] <= body['expectedRevision'])
        fingerprint=digest(body);authorize()
        with self.library.connect() as db:
            db.execute('begin immediate')
            prior=db.execute('''select fingerprint,result from assistant_policy_requests where connection_id=? and project_code=? and actor=? and request_id=?''',
                (self.connection_id,project,actor,body['requestId'])).fetchone()
            if prior:
                require(prior['fingerprint']==fingerprint,'ASSISTANT_REQUEST_CONFLICT',409);authorize();return json.loads(prior['result'])
            current=self.policy(project,db);require(current['revision']==body['expectedRevision'],'ASSISTANT_POLICY_CHANGED',409)
            if rollback:
                row=db.execute('''select policy from assistant_policy_revisions where connection_id=? and project_code=? and revision=?''',
                    (self.connection_id,project,body['restoreRevision'])).fetchone()
                require(row is not None,'NOT_FOUND_OR_FORBIDDEN',404);policy=validate_policy(json.loads(row['policy']))
            version=current['revision']+1;stamp=now()
            db.execute('insert into assistant_policy_revisions values(?,?,?,?,?,?,?,?)',
                (self.connection_id,project,version,encoded(policy),actor,stamp,'rollback' if rollback else 'publish',body.get('restoreRevision')))
            db.execute('insert into assistant_policy_heads values(?,?,?) on conflict(connection_id,project_code) do update set revision=excluded.revision',
                (self.connection_id,project,version))
            result={'revision':version,'policy':policy,'savedAt':stamp}
            db.execute('insert into assistant_policy_requests values(?,?,?,?,?,?)',(self.connection_id,project,actor,body['requestId'],fingerprint,encoded(result)))
            authorize();return result

    def run(self, project, owner, run_id):
        identifier(run_id)
        with self.library.connect() as db:
            row=db.execute('select * from assistant_runs where id=? and connection_id=? and project_code=? and owner=?',
                (run_id,self.connection_id,project,owner)).fetchone()
        require(row is not None,'NOT_FOUND_OR_FORBIDDEN',404)
        return dict(row)

    def by_request(self, project, owner, request_id):
        identifier(request_id)
        with self.library.connect() as db:
            row=db.execute('select * from assistant_runs where connection_id=? and project_code=? and owner=? and request_id=?',
                (self.connection_id,project,owner,request_id)).fetchone()
        require(row is not None,'NOT_FOUND_OR_FORBIDDEN',404);return dict(row)

    def cancel(self, project, owner, run_id, expected_version):
        require(type(expected_version) is int and expected_version>=1)
        with self.library.connect() as db:
            db.execute('begin immediate')
            row=db.execute('select state,version from assistant_runs where id=? and connection_id=? and project_code=? and owner=?',
                (identifier(run_id),self.connection_id,project,owner)).fetchone()
            require(row is not None,'NOT_FOUND_OR_FORBIDDEN',404)
            if row['state'] in ACTIVE:
                require(row['version']==expected_version,'ASSISTANT_RUN_CHANGED',409)
                db.execute("update assistant_runs set state='cancel_requested',version=version+1,updated_at=? where id=?",(now(),run_id))
        return self.run(project,owner,run_id)

    def begin(self, project, owner, body, policy_revision, service_revision):
        identifier(body['requestId']);identifier(body['analysisSessionId'])
        stamp=now();fingerprint=digest(body)
        with self.library.connect() as db:
            db.execute('begin immediate')
            prior=db.execute('select * from assistant_runs where connection_id=? and project_code=? and owner=? and request_id=?',
                (self.connection_id,project,owner,body['requestId'])).fetchone()
            if prior:
                require(prior['fingerprint']==fingerprint,'ASSISTANT_REQUEST_CONFLICT',409);return dict(prior),False
            require(db.execute('select count(*) from assistant_runs').fetchone()[0]<500,'ASSISTANT_STORE_LIMIT',413)
            run_id=str(uuid4())
            db.execute('insert into assistant_runs values(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                (run_id,self.connection_id,project,owner,body['requestId'],fingerprint,body['analysisSessionId'],body['expectedAnalysisRevision'],
                 policy_revision,service_revision,'reading',1,stamp,stamp,encoded(body),'[]','[]',None,None))
        return self.run(project,owner,run_id),True

    def update(self, run_id, state, *, progress=None, sources=None, result=None, error=None):
        with self.library.connect() as db:
            db.execute('''update assistant_runs set state=?,version=version+1,updated_at=?,
                progress_json=coalesce(?,progress_json),sources_json=coalesce(?,sources_json),result_json=coalesce(?,result_json),error_code=? where id=?''',
                (state,now(),None if progress is None else encoded(progress),None if sources is None else encoded(sources),
                 None if result is None else encoded(result),error,run_id))

    @staticmethod
    def public(row, *, hide=False):
        return {'runId':row['id'],'state':row['state'],'version':row['version'],'createdAt':row['created_at'],'updatedAt':row['updated_at'],
            'analysisSessionId':row['analysis_id'],'analysisRevision':row['analysis_revision'],'policyRevision':row['policy_revision'],
            'progress':[] if hide else json.loads(row['progress_json']),'sources':[] if hide else json.loads(row['sources_json']),
            'result':None if hide or row['result_json'] is None else json.loads(row['result_json']),'error':row['error_code']}
