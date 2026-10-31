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
            create table if not exists assistant_conversations (
                id text primary key,connection_id text not null,project_code text not null,owner text not null,
                analysis_id text not null,analysis_revision integer not null,title text not null,
                head_run_id text,version integer not null,created_at text not null,updated_at text not null);
            create index if not exists assistant_conversation_scope on assistant_conversations
                (connection_id,project_code,owner,analysis_id,analysis_revision,updated_at);
            create table if not exists assistant_conversation_turns (
                conversation_id text not null references assistant_conversations(id),turn_no integer not null,
                run_id text not null unique references assistant_runs(id),parent_run_id text,
                primary key(conversation_id,turn_no));
            create trigger if not exists assistant_policy_immutable_update before update on assistant_policy_revisions
                begin select raise(abort,'immutable assistant policy'); end;
            create trigger if not exists assistant_policy_immutable_delete before delete on assistant_policy_revisions
                begin select raise(abort,'immutable assistant policy'); end;
            ''')
            # Adopt legacy single-turn receipts without editing their original inputs or answers.
            for old in db.execute('''select r.* from assistant_runs r left join assistant_conversation_turns t on t.run_id=r.id
                where t.run_id is null and r.connection_id=? order by r.created_at limit 500''',(connection_id,)).fetchall():
                title=json.loads(old['input_json']).get('question','历史分析')[:80]
                db.execute('insert into assistant_conversations values(?,?,?,?,?,?,?,?,?,?,?)',
                    (old['id'],connection_id,old['project_code'],old['owner'],old['analysis_id'],old['analysis_revision'],
                     title,old['id'],1,old['created_at'],old['updated_at']))
                db.execute('insert into assistant_conversation_turns values(?,?,?,?)',(old['id'],1,old['id'],None))
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
        return self.with_conversation(dict(row))

    def by_request(self, project, owner, request_id):
        identifier(request_id)
        with self.library.connect() as db:
            row=db.execute('select * from assistant_runs where connection_id=? and project_code=? and owner=? and request_id=?',
                (self.connection_id,project,owner,request_id)).fetchone()
        require(row is not None,'NOT_FOUND_OR_FORBIDDEN',404);return self.with_conversation(dict(row))

    def with_conversation(self,row,db=None):
        if db is None:
            with self.library.connect() as current:return self.with_conversation(row,current)
        turn=db.execute('select conversation_id,turn_no,parent_run_id from assistant_conversation_turns where run_id=?',(row['id'],)).fetchone()
        return {**row,**(dict(turn) if turn else {})}

    def conversations(self,project,owner,analysis,revision):
        identifier(analysis);require(type(revision) is int and 1<=revision<=1000)
        with self.library.connect() as db:
            rows=db.execute('''select * from assistant_conversations where connection_id=? and project_code=? and owner=?
                and analysis_id=? and analysis_revision=? order by updated_at desc,id desc limit 20''',
                (self.connection_id,project,owner,analysis,revision)).fetchall()
        return [self.conversation_public(dict(r)) for r in rows]

    @staticmethod
    def conversation_public(row):
        return dict(conversationId=row['id'],title=row['title'],version=row['version'],headRunId=row['head_run_id'],
                    analysisSessionId=row['analysis_id'],analysisRevision=row['analysis_revision'],updatedAt=row['updated_at'])

    def conversation(self,project,owner,conversation_id,before=None):
        identifier(conversation_id)
        require(before is None or type(before) is int and 1<=before<=501)
        with self.library.connect() as db:
            head=db.execute('select * from assistant_conversations where id=? and connection_id=? and project_code=? and owner=?',
                (conversation_id,self.connection_id,project,owner)).fetchone()
            require(head is not None,'NOT_FOUND_OR_FORBIDDEN',404)
            rows=db.execute('''select r.*,t.conversation_id,t.turn_no,t.parent_run_id from assistant_conversation_turns t
                join assistant_runs r on r.id=t.run_id where t.conversation_id=? and t.turn_no<? order by t.turn_no desc limit 4''',
                (conversation_id,before or 501)).fetchall()
        return self.conversation_public(dict(head)),list(reversed([dict(r) for r in rows]))

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
                require(prior['fingerprint']==fingerprint,'ASSISTANT_REQUEST_CONFLICT',409);return self.with_conversation(dict(prior),db),False
            require(db.execute('select count(*) from assistant_runs').fetchone()[0]<500,'ASSISTANT_STORE_LIMIT',413)
            run_id=str(uuid4())
            conversation=body.get('conversationId');expected=body.get('expectedConversationVersion',0);parent=body.get('parentRunId')
            require(type(expected) is int and 0<=expected<500)
            if conversation is None:
                require(expected==0 and parent is None,'ASSISTANT_CONVERSATION_CHANGED',409)
                conversation=str(uuid4())
                db.execute('insert into assistant_conversations values(?,?,?,?,?,?,?,?,?,?,?)',
                    (conversation,self.connection_id,project,owner,body['analysisSessionId'],body['expectedAnalysisRevision'],
                     body['question'].strip()[:80],None,0,stamp,stamp))
            else:
                identifier(conversation);identifier(parent)
                head=db.execute('select * from assistant_conversations where id=? and connection_id=? and project_code=? and owner=?',
                    (conversation,self.connection_id,project,owner)).fetchone()
                require(head is not None,'NOT_FOUND_OR_FORBIDDEN',404)
                require(head['analysis_id']==body['analysisSessionId'] and head['analysis_revision']==body['expectedAnalysisRevision']
                    and head['version']==expected and head['head_run_id']==parent,'ASSISTANT_CONVERSATION_CHANGED',409)
                previous=db.execute('select state from assistant_runs where id=?',(parent,)).fetchone()
                require(previous is not None and previous['state'] not in ACTIVE,'ASSISTANT_BUSY',409)
            db.execute('insert into assistant_runs values(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                (run_id,self.connection_id,project,owner,body['requestId'],fingerprint,body['analysisSessionId'],body['expectedAnalysisRevision'],
                 policy_revision,service_revision,'reading',1,stamp,stamp,encoded(body),'[]','[]',None,None))
            db.execute('insert into assistant_conversation_turns values(?,?,?,?)',(conversation,expected+1,run_id,parent))
            db.execute('update assistant_conversations set head_run_id=?,version=?,updated_at=? where id=?',
                (run_id,expected+1,stamp,conversation))
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
            'question':json.loads(row['input_json']).get('question',''),
            'conversationId':row.get('conversation_id'),'conversationVersion':row.get('turn_no',0),'parentRunId':row.get('parent_run_id'),
            'analysisSessionId':row['analysis_id'],'analysisRevision':row['analysis_revision'],'policyRevision':row['policy_revision'],
            'progress':[] if hide else json.loads(row['progress_json']),'sources':[] if hide else json.loads(row['sources_json']),
            'result':None if hide or row['result_json'] is None else json.loads(row['result_json']),'error':row['error_code']}
