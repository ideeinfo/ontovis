"""Project model routing and encrypted credentials in the existing paired store."""
from __future__ import annotations
import copy
import json
import os
import stat
from .assistant_store import require, identifier, encoded, digest, now
from .authority import PreviewError
from .llm_providers import PROVIDERS, TASKS, FOCUS, endpoint, model_id, api_key


TOOLS=('selected_sources','engineering_neighborhood','manual_fault_lookup')

def defaults(task):
    return dict(enabled=True,connectionId=None,modelId='',timeoutSeconds=50,concurrency=2,
        reasoningEffort='default',goal=FOCUS[task],focus='',readLimit=8,readParallel=2,tools=list(TOOLS))


def validate_settings(value):
    require(type(value) is dict and set(value)==set(defaults('analysis')))
    require(type(value['enabled']) is bool)
    if value['connectionId'] is not None:identifier(value['connectionId']);model_id(value['modelId'])
    else:require(value['modelId']=='','LLM_MODEL_REQUIRED')
    for key,lo,hi in [('timeoutSeconds',10,50),('concurrency',1,2),('readLimit',1,8),('readParallel',1,2)]:
        require(type(value[key]) is int and lo<=value[key]<=hi,'LLM_SETTINGS_INVALID')
    require(type(value['reasoningEffort']) is str and 0<len(value['reasoningEffort'])<=32)
    for key in ('goal','focus'):
        require(type(value[key]) is str and len(value[key])<=2000 and '\0' not in value[key],'LLM_SETTINGS_INVALID')
    require(bool(value['goal'].strip()),'LLM_SETTINGS_INVALID')
    require(type(value['tools']) is list and all(type(t) is str for t in value['tools']) and len(set(value['tools']))==len(value['tools'])
        and set(value['tools'])<=set(TOOLS) and 'selected_sources' in value['tools'],'ASSISTANT_TOOL_NOT_ALLOWED')
    return copy.deepcopy(value)


def source_configuration(task_id, settings):
    return {'taskId':task_id,**{key:settings[key] for key in ('connectionId','modelId','timeoutSeconds','reasoningEffort','goal','focus')}}


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
    def settings(config, task_id):
        saved=config.get('capabilities',{}).get(task_id)
        if saved is not None:return copy.deepcopy(saved)
        old=config['tasks'][task_id]
        return {**defaults(task_id),'enabled':old['enabled'] and old['execution']=='ontobase'}

    @staticmethod
    def public(value):
        config=value['config']
        return {'schemaVersion':2,'revision':value['revision'],'updatedAt':value['updatedAt'],
            'defaults':{task:defaults(task) for task in TASKS},
            'tasks':[{'id':task,'nameZh':TASKS[task][0],'nameEn':TASKS[task][1],
                **AssistantModels.settings(config,task),
                'configured':task in config.get('capabilities',{}),
                'legacyNeedsReview':task not in config.get('capabilities',{}) and config['tasks'][task]['execution']=='ontovis'} for task in TASKS]}

    def save(self, project, actor, body, authorize, validate_source):
        require(type(body) is dict and set(body)=={'requestId','expectedRevision','expectedAccessRevision','change'})
        identifier(body['requestId']);require(type(body['expectedRevision']) is int and 0<=body['expectedRevision']<10000)
        change=body['change']
        require(type(change) is dict and set(change)=={'kind','taskId','settings','expectedConnectionVersion'} and change['kind']=='capability')
        require(type(change['taskId']) is str and change['taskId'] in TASKS,'LLM_TASK_INVALID')
        task=validate_settings(change['settings'])
        require(change['expectedConnectionVersion'] is None or type(change['expectedConnectionVersion']) is int and change['expectedConnectionVersion']>=1)
        fingerprint=digest(body)
        authorize()
        with self.library.connect() as db:
            db.execute('begin immediate')
            previous=db.execute('select fingerprint,result_json from assistant_model_config_requests where connection_id=? and project_code=? and actor=? and request_id=?',
                (self.connection_id,project,actor,body['requestId'])).fetchone()
            if previous:
                require(previous['fingerprint']==fingerprint,'ASSISTANT_REQUEST_CONFLICT',409);authorize();return json.loads(previous['result_json'])
            current=self.read(project,db);require(current['revision']==body['expectedRevision'],'LLM_CONFIGURATION_CHANGED',409)
            # Source authorization and connection versions are checked before committing.
            if task['enabled']:validate_source(source_configuration(change['taskId'],task),change['expectedConnectionVersion'])
            config=current['config'];config.setdefault('capabilities',{})[change['taskId']]=task
            stamp=now();revision=current['revision']+1
            result=self.public({'revision':revision,'updatedAt':stamp,'config':config})
            require(db.execute('select count(*) from assistant_model_config_events where connection_id=? and project_code=?',(self.connection_id,project)).fetchone()[0]<10000,'LLM_CONFIGURATION_LIMIT',413)
            db.execute('insert into assistant_model_configs values(?,?,?,?,?,?) on conflict(connection_id,project_code) do update set revision=excluded.revision,config_json=excluded.config_json,actor=excluded.actor,updated_at=excluded.updated_at',
                (self.connection_id,project,revision,encoded(config),actor,stamp))
            db.execute('insert into assistant_model_config_events values(?,?,?,?,?,?)',(self.connection_id,project,revision,actor,stamp,encoded(change)))
            db.execute('insert into assistant_model_config_requests values(?,?,?,?,?,?)',(self.connection_id,project,actor,body['requestId'],fingerprint,encoded(result)))
            authorize();return result

    def profile(self, project, task_id, inherited):
        require(type(task_id) is str and task_id in TASKS,'LLM_TASK_INVALID')
        value=self.read(project);config=value['config'];task=self.settings(config,task_id)
        configured=task_id in config.get('capabilities',{})
        source=inherited(source_configuration(task_id,task) if configured else None)
        old=config['tasks'][task_id]
        if not configured and old['execution']=='ontovis':
            source={'enabled':False,'canRun':False,'reason':'LLM_CONNECTION_REVIEW_REQUIRED'}
        if not configured:
            revision=source.get('serviceRevision') if value['revision']==0 and task_id=='analysis' else digest([
                value['revision'],task_id,old,None,'ontobase',source.get('serviceRevision')])
        else:revision=digest([value['revision'],task_id,task,source.get('serviceRevision')])
        ready=task['enabled'] and source.get('enabled') is True
        return {'taskId':task_id,'execution':'ontobase','provider':source.get('provider'),'modelId':source.get('modelId'),
            'enabled':ready,'canRun':ready and source.get('canRun') is True,'serviceRef':'ontovis-task-model-v1',
            'serviceRevision':revision,'configurationRevision':value['revision'],'sourceServiceRevision':source.get('serviceRevision'),
            'accessRevision':source.get('accessRevision'),'purpose':'ontovis_analysis','configuration':source_configuration(task_id,task) if configured else None,
            'settings':task,'reasoningOptions':source.get('reasoningOptions',['default']),'reason':None if ready else source.get('reason') or ('LLM_TASK_DISABLED' if not task['enabled'] else 'ASSISTANT_SERVICE_UNAVAILABLE')}


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
