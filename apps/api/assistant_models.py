"""Project model routing and encrypted credentials in the existing paired store."""
from __future__ import annotations
import copy
import hashlib
import hmac
import json
import os
import stat
from .assistant_store import require, identifier, encoded, digest, now
from .authority import PreviewError
from .llm_providers import PROVIDERS, TASKS, endpoint, model_id, api_key


class AssistantModels:
    def __init__(self, library, connection_id):
        self.library,self.connection_id=library,connection_id
        with library.connect() as db:
            db.executescript('''
            create table if not exists assistant_model_configs (
              connection_id text not null,project_code text not null,revision integer not null,
              config_json text not null,actor text not null,updated_at text not null,
              primary key(connection_id,project_code));
            create table if not exists assistant_model_config_requests (
              connection_id text not null,project_code text not null,actor text not null,request_id text not null,
              fingerprint text not null,result_json text not null,
              primary key(connection_id,project_code,actor,request_id));
            create table if not exists assistant_model_config_events (
              connection_id text not null,project_code text not null,revision integer not null,
              actor text not null,created_at text not null,change_json text not null,
              primary key(connection_id,project_code,revision));
            ''')

    def _key(self, create=False):
        from cryptography.fernet import Fernet
        path=self.library.root/'llm-credentials.key'
        if create:
            try:
                fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
                with os.fdopen(fd,'wb') as file:file.write(Fernet.generate_key());file.flush();os.fsync(file.fileno())
            except FileExistsError:pass
        try:
            fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
            with os.fdopen(fd,'rb') as file:
                info=os.fstat(file.fileno())
                require(stat.S_ISREG(info.st_mode) and info.st_nlink==1 and stat.S_IMODE(info.st_mode)==0o600,'LLM_KEY_STORE_UNAVAILABLE',409)
                key=file.read(45)
            require(len(key)==44,'LLM_KEY_STORE_UNAVAILABLE',409);Fernet(key);return key
        except (OSError,ValueError):raise PreviewError(409,'LLM_KEY_STORE_UNAVAILABLE') from None

    def _seal(self, project, provider, key):
        from cryptography.fernet import Fernet
        raw=encoded({'connection':self.connection_id,'project':project,'provider':provider,'key':api_key(key)})
        return Fernet(self._key(True)).encrypt(raw.encode()).decode()

    def _secret(self, project, provider, token):
        from cryptography.fernet import Fernet,InvalidToken
        try:
            value=json.loads(Fernet(self._key()).decrypt(token.encode()))
            require(type(value) is dict and set(value)=={'connection','project','provider','key'}
                and (value['connection'],value['project'],value['provider'])==(self.connection_id,project,provider),'LLM_KEY_STORE_UNAVAILABLE',409)
            return api_key(value['key'])
        except (InvalidToken,ValueError,TypeError,AttributeError):raise PreviewError(409,'LLM_KEY_STORE_UNAVAILABLE') from None

    def read(self, project, db=None):
        if db is None:
            with self.library.connect() as current:return self.read(project,current)
        row=db.execute('select * from assistant_model_configs where connection_id=? and project_code=?',(self.connection_id,project)).fetchone()
        if row:
            config=json.loads(row['config_json'])
            for task in config['tasks'].values():
                if 'execution' not in task:
                    task['execution']='ontobase' if config['providers'][task['provider']]['mode']=='inherited' else 'ontovis'
                if task['execution']=='ontobase':
                    task.pop('provider',None);task.pop('modelId',None)
            for provider in config['providers'].values():provider['mode']='managed'
            return {'revision':row['revision'],'updatedAt':row['updated_at'],'config':config}
        return {'revision':0,'updatedAt':None,'config':{
            'providers':{name:{'baseUrl':p['baseUrl'],'mode':'managed','credential':None} for name,p in PROVIDERS.items()},
            'tasks':{name:{'execution':'ontobase','enabled':True} for name in TASKS}}}

    @staticmethod
    def public(value):
        return {'revision':value['revision'],'updatedAt':value['updatedAt'],
            'providers':[{ 'id':name,'name':PROVIDERS[name]['name'],'baseUrl':p['baseUrl'],'mode':p['mode'],
                'keyConfigured':bool(p['credential'])} for name in PROVIDERS for p in (value['config']['providers'][name],)],
            'tasks':[{ 'id':name,'nameZh':TASKS[name][0],'nameEn':TASKS[name][1],**value['config']['tasks'][name]} for name in TASKS]}

    def save(self, project, actor, body, authorize):
        require(type(body) is dict and set(body)=={'requestId','expectedRevision','expectedAccessRevision','change'})
        identifier(body['requestId']);require(type(body['expectedRevision']) is int and 0<=body['expectedRevision']<10000)
        change=body['change'];require(type(change) is dict and change.get('kind') in ('provider','task'))
        if change['kind']=='provider':
            require(set(change)=={'kind','provider','baseUrl','mode','keyAction','apiKey'})
            provider=change['provider'];url=endpoint(provider,change['baseUrl'])
            require(change['mode']=='managed','LLM_CONFIGURATION_CHANGED',409)
            require(change['keyAction'] in ('keep','replace','clear'))
            if change['keyAction']=='replace':api_key(change['apiKey'])
            else:require(change['apiKey'] is None)
        else:
            require('execution' in change,'LLM_CONFIGURATION_CHANGED',409)
            require(change['execution'] in ('ontobase','ontovis'))
            fields={'kind','taskId','execution','enabled'}
            require(set(change)==(fields if change['execution']=='ontobase' else fields|{'provider','modelId'}))
            require(type(change['taskId']) is str and change['taskId'] in TASKS and type(change['enabled']) is bool)
            if change['execution']=='ontovis':
                require(type(change['provider']) is str and change['provider'] in PROVIDERS and type(change['modelId']) is str)
                if change['modelId']:model_id(change['modelId'])
        # The request fingerprint contains no plaintext key, even in audit rows.
        def fingerprint():
            cleaned=copy.deepcopy(body)
            if cleaned['change'].get('apiKey'):
                cleaned['change']['apiKey']=hmac.new(self._key(),change['apiKey'].encode(),'sha256').hexdigest()
            return digest(cleaned)
        authorize()
        with self.library.connect() as db:
            db.execute('begin immediate')
            previous=db.execute('select fingerprint,result_json from assistant_model_config_requests where connection_id=? and project_code=? and actor=? and request_id=?',
                (self.connection_id,project,actor,body['requestId'])).fetchone()
            if previous:
                require(previous['fingerprint']==fingerprint(),'ASSISTANT_REQUEST_CONFLICT',409);authorize();return json.loads(previous['result_json'])
            current=self.read(project,db);require(current['revision']==body['expectedRevision'],'LLM_CONFIGURATION_CHANGED',409)
            config=current['config'];audit={k:v for k,v in change.items() if k!='apiKey'}
            if change['kind']=='provider':
                old=config['providers'][provider]
                require(change['keyAction']!='keep' or not old['credential'] or old['baseUrl']==url,'LLM_NEW_ENDPOINT_KEY_REQUIRED')
                secret=old['credential'] if change['keyAction']=='keep' else None
                if change['keyAction']=='replace':secret=self._seal(project,provider,change['apiKey'])
                config['providers'][provider]={'baseUrl':url,'mode':change['mode'],'credential':secret}
            else:
                if change['execution']=='ontovis' and change['enabled']:
                    p=config['providers'][change['provider']]
                    model_id(change['modelId']);require(bool(p['credential']),'LLM_KEY_REQUIRED')
                config['tasks'][change['taskId']]={k:change[k] for k in change if k not in ('kind','taskId')}
            stamp=now();revision=current['revision']+1
            result=self.public({'revision':revision,'updatedAt':stamp,'config':config})
            require(db.execute('select count(*) from assistant_model_config_events where connection_id=? and project_code=?',(self.connection_id,project)).fetchone()[0]<10000,'LLM_CONFIGURATION_LIMIT',413)
            db.execute('insert into assistant_model_configs values(?,?,?,?,?,?) on conflict(connection_id,project_code) do update set revision=excluded.revision,config_json=excluded.config_json,actor=excluded.actor,updated_at=excluded.updated_at',
                (self.connection_id,project,revision,encoded(config),actor,stamp))
            db.execute('insert into assistant_model_config_events values(?,?,?,?,?,?)',(self.connection_id,project,revision,actor,stamp,encoded(audit)))
            db.execute('insert into assistant_model_config_requests values(?,?,?,?,?,?)',(self.connection_id,project,actor,body['requestId'],fingerprint(),encoded(result)))
            authorize();return result

    def profile(self, project, task_id, inherited):
        require(type(task_id) is str and task_id in TASKS,'LLM_TASK_INVALID')
        value=self.read(project);task=value['config']['tasks'][task_id];execution=task['execution']
        base=execution=='ontobase';source=inherited() if base else {}
        p=None if base else value['config']['providers'][task['provider']]
        rev=source.get('serviceRevision') if value['revision']==0 and task_id=='analysis' else digest([
            value['revision'],task_id,task,None if base else p['baseUrl'],execution,source.get('serviceRevision')])
        ready=task['enabled'] and (source.get('enabled') is True if base else bool(p['credential']) and bool(task['modelId']))
        runnable=ready and (source.get('canRun') is True if base else True)
        return {'taskId':task_id,'execution':execution,'provider':source.get('provider') if base else task['provider'],
            'modelId':source.get('modelId') if base else task['modelId'],
            'baseUrl':None if base else p['baseUrl'],'enabled':ready,'canRun':runnable,'serviceRef':'ontovis-task-model-v1',
            'serviceRevision':rev,'configurationRevision':value['revision'],'sourceServiceRevision':source.get('serviceRevision'),
            'accessRevision':source.get('accessRevision'),'purpose':'ontovis_analysis',
            'reason':None if ready else 'LLM_TASK_DISABLED' if not task['enabled'] else source.get('reason','ASSISTANT_SERVICE_UNAVAILABLE') if base else 'LLM_MODEL_REQUIRED' if p['credential'] else 'LLM_KEY_REQUIRED'}

    def credentials(self, project, provider, base_url=None, transient=None, *, expected_revision=None):
        require(type(provider) is str and provider in PROVIDERS)
        value=self.read(project)
        require(expected_revision is None or value['revision']==expected_revision,'LLM_CONFIGURATION_CHANGED',409)
        p=value['config']['providers'][provider]
        url=endpoint(provider,base_url or p['baseUrl'])
        if transient:return url,api_key(transient)
        require(url==p['baseUrl'],'LLM_NEW_ENDPOINT_KEY_REQUIRED')
        require(p['credential'] is not None,'LLM_KEY_REQUIRED')
        return url,self._secret(project,provider,p['credential'])


def validate_backup_credentials(db, root):
    """No schema creation or writes during offline backup verification."""
    if not db.execute("select 1 from sqlite_master where name='assistant_model_configs'").fetchone():return
    from types import SimpleNamespace
    store=object.__new__(AssistantModels);store.library=SimpleNamespace(root=root)
    for connection,project,raw in db.execute('select connection_id,project_code,config_json from assistant_model_configs'):
        store.connection_id=connection;value=json.loads(raw)
        for provider,p in value['providers'].items():
            endpoint(provider,p['baseUrl'])
            if p['credential']:store._secret(project,provider,p['credential'])
