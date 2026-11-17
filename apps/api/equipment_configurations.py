"""Project-owned geometry mappings; current equipment adoption belongs to OntoBase."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from uuid import UUID, uuid4

from .authority import PreviewError
from .scene_bindings import validate_ref


def require(ok, code='INVALID_REQUEST', status=422):
    if not ok:
        raise PreviewError(status, code)


def identifier(value):
    try:
        require(isinstance(value, str) and str(UUID(value)) == value)
    except (ValueError, TypeError, AttributeError):
        raise PreviewError(422, 'INVALID_REQUEST') from None
    return value


def text(value, limit=200):
    require(isinstance(value, str) and 0 < len(value.strip()) <= limit and value == value.strip()
            and all(ord(c) >= 32 for c in value))
    return value


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


class EquipmentConfigurations:
    def __init__(self, library, connection_id, project_code):
        self.library = library
        self.scope = {'connection_id': connection_id, 'project_code': project_code}
        with library.connect() as db:
            db.executescript('''
                create table if not exists equipment_configurations (
                    id text primary key, project_code text not null, head_revision text not null);
                create table if not exists equipment_configuration_revisions (
                    revision text primary key, configuration_id text not null references equipment_configurations(id),
                    snapshot text not null, actor text not null, saved_at text not null);
                create table if not exists equipment_configuration_assignments (
                    equipment_uid text primary key, configuration_id text not null references equipment_configurations(id),
                    assignment_revision text not null);
                create table if not exists equipment_configuration_adoptions (
                    revision text primary key, configuration_id text not null references equipment_configurations(id),
                    equipment_uids text not null, actor text not null, saved_at text not null);
                create table if not exists equipment_configuration_requests (
                    actor text not null, request_id text not null, payload_sha text not null, result text not null,
                    primary key(actor,request_id));
                create table if not exists scene_equipment_configuration_uses (
                    scene_revision text not null references scene_revisions(revision), instance_id text not null,
                    configuration_id text not null references equipment_configurations(id),
                    configuration_revision text not null references equipment_configuration_revisions(revision),
                    equipment_uid text not null, primary key(scene_revision,instance_id));
                create trigger if not exists equipment_configuration_history_no_update
                    before update on equipment_configuration_revisions begin select raise(abort,'immutable equipment configuration'); end;
                create trigger if not exists equipment_configuration_history_no_delete
                    before delete on equipment_configuration_revisions begin select raise(abort,'immutable equipment configuration'); end;
                create trigger if not exists equipment_adoption_history_no_update
                    before update on equipment_configuration_adoptions begin select raise(abort,'immutable equipment adoption'); end;
                create trigger if not exists equipment_adoption_history_no_delete
                    before delete on equipment_configuration_adoptions begin select raise(abort,'immutable equipment adoption'); end;
            ''')
            if 'project_application_revision_id' not in {r['name'] for r in db.execute('pragma table_info(equipment_configurations)')}:
                db.execute('alter table equipment_configurations add column project_application_revision_id text')
            db.execute('create unique index if not exists equipment_configuration_source_application on equipment_configurations(project_code,project_application_revision_id) where project_application_revision_id is not null')

    def _ref(self, ref):
        return validate_ref(ref, **self.scope)

    def for_equipment(self, uid, equipment=None):
        adoption=(equipment([uid])[uid].get('adoption') if equipment else None)
        with self.library.connect() as db:
            if adoption:
                row=db.execute('''select c.id,c.head_revision,r.snapshot from equipment_configurations c
                    join equipment_configuration_revisions r on r.revision=c.head_revision
                    where c.project_code=? and c.project_application_revision_id=?''',
                    (self.scope['project_code'],adoption['applicationRevisionId'])).fetchone()
                if row:
                    return {'configurationId':row['id'],'configurationRevision':row['head_revision'],'snapshot':json.loads(row['snapshot'])}
            row=db.execute('''select c.id,c.head_revision,r.snapshot from equipment_configuration_assignments a
                join equipment_configurations c on c.id=a.configuration_id
                join equipment_configuration_revisions r on r.revision=c.head_revision
                where a.equipment_uid=? and c.project_application_revision_id is null''',(uid,)).fetchone()
        return {'configurationId':row['id'],'configurationRevision':row['head_revision'],'snapshot':json.loads(row['snapshot'])} if row else None

    def validate(self, snapshot, objects, model_components):
        require(type(snapshot) is dict and set(snapshot) == {'displayName', 'objectKind', 'rootDefinition', 'models'})
        value = {'displayName': text(snapshot['displayName']), 'objectKind': text(snapshot['objectKind'], 80),
                 'rootDefinition': None, 'models': []}
        root = snapshot['rootDefinition']
        if root is not None:
            require(type(root) is dict and set(root) == {'objectRef', 'expectedEntityRevision'})
            ref = self._ref(root['objectRef']); selected = objects(ref['entityUid'])
            require(selected['item']['installationContextId'] is None, 'DEFINITION_REQUIRED', 409)
            require(selected['item']['objectKind'] == value['objectKind'], 'OBJECT_KIND_MISMATCH', 409)
            require(selected['item']['entityRevision'] == root['expectedEntityRevision'], 'ENGINEERING_CHANGED', 409)
            value['rootDefinition'] = deepcopy(root)
        require(type(snapshot['models']) is list and 0 < len(snapshot['models']) <= 20)
        versions = set()
        for entry in snapshot['models']:
            require(type(entry) is dict and set(entry) == {'modelVersionId', 'mappings'})
            version = identifier(entry['modelVersionId']); require(version not in versions)
            versions.add(version)
            components = model_components(version)
            available = {row['componentKey'] for row in components}
            require(type(entry['mappings']) is list and len(entry['mappings']) <= 500)
            mappings, uids, used = [], set(), set()
            for mapping in entry['mappings']:
                require(type(mapping) is dict and set(mapping) == {'objectRef', 'expectedEntityRevision', 'componentKeys'})
                ref = self._ref(mapping['objectRef']); uid = ref['entityUid']
                require(uid not in uids); uids.add(uid)
                keys = mapping['componentKeys']
                require(type(keys) is list and len(keys) <= 500 and all(type(k) is str for k in keys))
                require(len(set(keys)) == len(keys) and not used.intersection(keys), 'COMPONENT_ALREADY_MAPPED', 409)
                require(set(keys) <= available, 'COMPONENT_MISSING', 409); used.update(keys)
                item = objects(uid)['item']
                require(item['installationContextId'] is None, 'DEFINITION_REQUIRED', 409)
                require(item['entityRevision'] == mapping['expectedEntityRevision'], 'ENGINEERING_CHANGED', 409)
                mappings.append({**deepcopy(mapping), 'componentKeys': sorted(keys)})
            value['models'].append({'modelVersionId': version, 'mappings': sorted(mappings, key=lambda m:m['objectRef']['entityUid'])})
        value['models'].sort(key=lambda m:m['modelVersionId'])
        return value

    def source_snapshot(self, snapshot, application):
        require(type(snapshot) is dict and set(snapshot)=={'projectApplicationRef','models'},'SOURCE_APPLICATION_REQUIRED',409)
        ref=snapshot['projectApplicationRef']
        require(type(ref) is dict and set(ref)=={'applicationId','applicationRevisionId','specificationRevisionId'})
        expected={'applicationId':application['applicationId'],'applicationRevisionId':application['revisionId'],
                  'specificationRevisionId':application['snapshot']['specificationRevisionId']}
        require(ref==expected and application['projectCode']==self.scope['project_code'],'SOURCE_APPLICATION_MISMATCH',409)
        source=application['snapshot']; root=source.get('rootDefinition')
        allowed={r['entityUid']:r['expectedEntityRevision'] for r in ([root] if root else [])+source['mappings']}
        require(type(snapshot['models']) is list)
        for model in snapshot['models']:
            require(type(model) is dict and type(model.get('mappings')) is list)
            for mapping in model['mappings']:
                require(type(mapping) is dict and type(mapping.get('objectRef')) is dict)
                require(allowed.get(mapping['objectRef'].get('entityUid'))==mapping.get('expectedEntityRevision')
                        and mapping.get('expectedEntityRevision') is not None,'DEFINITION_NOT_IN_APPLICATION',409)
        return {'displayName':source['name'],'objectKind':application['specification']['objectKind'],
                'rootDefinition':None if root is None else {'objectRef':{'ontobaseConnectionId':self.scope['connection_id'],
                    'projectCode':self.scope['project_code'],'entityUid':root['entityUid']},'expectedEntityRevision':root['expectedEntityRevision']},
                'models':snapshot['models']}

    def catalogue(self, authorize):
        authorize()
        with self.library.connect() as db:
            rows = db.execute('''select c.id,c.head_revision,r.snapshot,r.saved_at,
                case when c.project_application_revision_id is null then
                  (select count(*) from equipment_configuration_assignments a where a.configuration_id=c.id)
                  else null end as equipment_count
                from equipment_configurations c join equipment_configuration_revisions r on r.revision=c.head_revision
                where c.project_code=? order by r.saved_at,c.id''', (self.scope['project_code'],)).fetchall()
            assignments = [dict(row) for row in db.execute('select * from equipment_configuration_assignments order by equipment_uid')]
        authorize()
        return {'items': [{'configurationId': row['id'], 'configurationRevision': row['head_revision'],
            'snapshot': json.loads(row['snapshot']), 'savedAt': row['saved_at'], 'equipmentCount': row['equipment_count']} for row in rows],
            'assignments': assignments}

    def detail(self, configuration_id, revision, authorize):
        identifier(configuration_id);authorize()
        with self.library.connect() as db:
            config=db.execute('select head_revision from equipment_configurations where id=? and project_code=?',(configuration_id,self.scope['project_code'])).fetchone()
            require(config is not None,'NOT_FOUND_OR_FORBIDDEN',404)
            row=db.execute('select * from equipment_configuration_revisions where configuration_id=? and revision=?',
                           (configuration_id,revision or config[0])).fetchone()
            require(row is not None,'NOT_FOUND_OR_FORBIDDEN',404)
        authorize()
        return {'configurationId':configuration_id,'configurationRevision':row['revision'],'snapshot':json.loads(row['snapshot']),'savedAt':row['saved_at']}

    def resolve_scene(self, opened, equipment, authorize):
        """Compose a read projection. Never persist per-device copies of mappings."""
        authorize();current=opened['sceneRevision']==opened['headRevision']
        with self.library.connect() as db:
            if current:
                rows=db.execute('''select a.equipment_uid,c.id,c.head_revision,r.snapshot
                    from equipment_configuration_assignments a join equipment_configurations c on c.id=a.configuration_id
                    join equipment_configuration_revisions r on r.revision=c.head_revision''').fetchall()
            else:
                rows=db.execute('''select u.equipment_uid,u.configuration_id as id,u.configuration_revision as head_revision,r.snapshot
                    from scene_equipment_configuration_uses u join equipment_configuration_revisions r on r.revision=u.configuration_revision
                    where u.scene_revision=?''',(opened['sceneRevision'],)).fetchall()
            application_rows=db.execute('''select c.id,c.head_revision,c.project_application_revision_id,r.snapshot
                from equipment_configurations c join equipment_configuration_revisions r on r.revision=c.head_revision
                where c.project_code=? and c.project_application_revision_id is not null''',(self.scope['project_code'],)).fetchall() if current else []
        by_uid={row['equipment_uid']:row for row in rows if not current or not json.loads(row['snapshot']).get('projectApplicationRef')}
        roots=sorted({i['rootBinding']['objectRef']['entityUid'] for i in opened['snapshot']['instances'] if i.get('rootBinding')
                      and (current or i['rootBinding']['objectRef']['entityUid'] in by_uid)})
        if not roots:return deepcopy(opened),[]
        known={}
        for offset in range(0,len(roots),50):known.update(equipment(roots[offset:offset+50]))
        by_application={r['project_application_revision_id']:r for r in application_rows}
        if current:
            for uid,source in known.items():
                adoption=source.get('adoption')
                if adoption and adoption['applicationRevisionId'] in by_application:
                    by_uid[uid]=by_application[adoption['applicationRevisionId']]
        value=deepcopy(opened);uses=[];expectations=value['validation'].setdefault('engineeringExpectations',[])
        expected_uids={x['ref']['entityUid'] for x in expectations}
        for instance in value['snapshot']['instances']:
            root=(instance.get('rootBinding') or {}).get('objectRef')
            if not root or root['entityUid'] not in by_uid:continue
            row=by_uid[root['entityUid']];profile=json.loads(row['snapshot'])
            model=next((m for m in profile['models'] if m['modelVersionId']==instance['modelVersionId']),None)
            if model is None:continue
            source=known[root['entityUid']];ctx=source['context'];children={}
            for item in source['children']:
                if item.get('sourceTemplateEntityUid'):children.setdefault(item['sourceTemplateEntityUid'],[]).append(item)
            occupied={k for b in instance['componentBindings'] for k in b['componentKeys']}
            bound_uids={b['objectRef']['entityUid'] for b in instance['componentBindings']}
            definitions=([dict(deepcopy(profile['rootDefinition']),componentKeys=[])] if profile.get('rootDefinition') else []);conflicts=[]
            for mapping in model['mappings']:
                uid=mapping['objectRef']['entityUid'];candidates=children.get(uid,[])
                definitions.append(deepcopy(mapping))
                if not mapping['componentKeys']:continue
                if len(candidates)!=1:continue
                item=candidates[0]
                if item['entityUid'] in bound_uids or occupied.intersection(mapping['componentKeys']):
                    existing=next((b for b in instance['componentBindings'] if b['objectRef']['entityUid']==item['entityUid']),None)
                    if not existing or sorted(existing['componentKeys'])!=sorted(mapping['componentKeys']):conflicts.append(uid)
                    continue
                ref={**mapping['objectRef'],'entityUid':item['entityUid']}
                instance['componentBindings'].append({'objectRef':ref,'componentKeys':mapping['componentKeys']})
                occupied.update(mapping['componentKeys']);bound_uids.add(item['entityUid'])
                if item['entityUid'] not in expected_uids:
                    expectations.append({'ref':ref,'expectedEntityRevision':item['entityRevision'],
                        'installationContextId':ctx['installationContextId'],'expectedHierarchyRevision':ctx['hierarchyRevision']})
                    expected_uids.add(item['entityUid'])
            uses.append({'sceneModelInstanceId':instance['sceneModelInstanceId'],'equipmentEntityUid':root['entityUid'],
                'configurationId':row['id'],'configurationRevision':row['head_revision'],
                'displayName':profile['displayName'],'definitionMappings':definitions,'conflicts':conflicts,
                'equipmentTargets':{uid:items[0]['entityUid'] for uid,items in children.items() if len(items)==1}})
        authorize();return value,uses

    def _prior(self, db, actor, body):
        request = identifier(body['clientRequestId'])
        digest = hashlib.sha256(encoded(body).encode()).hexdigest()
        row = db.execute('select payload_sha,result from equipment_configuration_requests where actor=? and request_id=?', (actor,request)).fetchone()
        require(row is None or row['payload_sha'] == digest, 'IDEMPOTENCY_CONFLICT', 409)
        return request, digest, json.loads(row['result']) if row else None

    @staticmethod
    def _finish(db, actor, request, digest, result):
        db.execute('insert into equipment_configuration_requests values(?,?,?,?)',(actor,request,digest,encoded(result)))
        return result

    def save(self, body, actor, authorize, objects, model_components, application=None):
        require(type(body) is dict and set(body) == {'configurationId','expectedConfigurationRevision','snapshot','clientRequestId'})
        cid = identifier(body['configurationId']); authorize()
        with self.library.connect() as db:
            db.execute('begin immediate')
            request, digest, prior = self._prior(db, actor, body)
            if prior is not None:
                authorize(); return prior
            old = db.execute('select head_revision from equipment_configurations where id=? and project_code=?', (cid,self.scope['project_code'])).fetchone()
            require((old['head_revision'] if old else None) == body['expectedConfigurationRevision'], 'REVISION_CONFLICT', 409)
            source_ref=deepcopy(body['snapshot'].get('projectApplicationRef')) if type(body['snapshot']) is dict else None
            snapshot = self.validate(self.source_snapshot(body['snapshot'],application) if application else body['snapshot'], objects, model_components)
            if application:
                snapshot['projectApplicationRef']=source_ref
                duplicate=db.execute('select id from equipment_configurations where project_code=? and project_application_revision_id=? and id<>?',
                    (self.scope['project_code'],source_ref['applicationRevisionId'],cid)).fetchone()
                require(duplicate is None,'APPLICATION_BINDING_EXISTS',409)
            # Existing adopted model versions cannot silently lose their mapping.
            if old:
                previous = json.loads(db.execute('select snapshot from equipment_configuration_revisions where revision=?',(old['head_revision'],)).fetchone()[0])
                require(not previous.get('projectApplicationRef') or previous['projectApplicationRef']==source_ref,'SOURCE_APPLICATION_MISMATCH',409)
                # First attachment is a continuation: original geometry mappings must remain reviewable.
                if source_ref and not previous.get('projectApplicationRef'):
                    for model in previous['models']:
                        new=next((m for m in snapshot['models'] if m['modelVersionId']==model['modelVersionId']),None)
                        require(new is not None and all(m in new['mappings'] for m in model['mappings']),'LEGACY_MAPPING_CHANGED',409)
                require({x['modelVersionId'] for x in previous['models']} <= {x['modelVersionId'] for x in snapshot['models']}, 'MODEL_MAPPING_IN_USE', 409)
            revision = 'equipment-config:' + str(uuid4()); now = datetime.now(timezone.utc).isoformat()
            if not old:
                db.execute('insert into equipment_configurations(id,project_code,head_revision) values(?,?,?)',(cid,self.scope['project_code'],revision))
            db.execute('insert into equipment_configuration_revisions values(?,?,?,?,?)',(revision,cid,encoded(snapshot),actor,now))
            db.execute('update equipment_configurations set head_revision=? where id=?',(revision,cid))
            if source_ref:db.execute('update equipment_configurations set project_application_revision_id=? where id=?',(source_ref['applicationRevisionId'],cid))
            count = db.execute('select count(*) from equipment_configuration_assignments where configuration_id=?',(cid,)).fetchone()[0]
            authorize()
            return self._finish(db,actor,request,digest,{'configurationId':cid,'configurationRevision':revision,'snapshot':snapshot,
                'equipmentCount':None if source_ref else count,'savedAt':now})

    def assign(self, body, actor, authorize, equipment):
        require(type(body) is dict and set(body) == {'configurationId','expectedConfigurationRevision','equipment','clientRequestId'})
        cid = identifier(body['configurationId']); rows = body['equipment']
        require(type(rows) is list and 0 < len(rows) <= 50)
        require(all(type(r) is dict and set(r)=={'entityUid','expectedEntityRevision','expectedHierarchyRevision','expectedAssignmentRevision'} for r in rows))
        uids=[text(r['entityUid'],512) for r in rows];require(len(set(uids))==len(uids))
        authorize()
        with self.library.connect() as db:
            db.execute('begin immediate')
            request,digest,prior=self._prior(db,actor,body)
            if prior is not None:
                authorize();return prior
            config=db.execute('select r.snapshot,c.head_revision from equipment_configurations c join equipment_configuration_revisions r on r.revision=c.head_revision where c.id=?',(cid,)).fetchone()
            require(config is not None,'NOT_FOUND_OR_FORBIDDEN',404)
            require(config['head_revision']==body['expectedConfigurationRevision'],'REVISION_CONFLICT',409)
            snapshot=json.loads(config['snapshot']);current=equipment(uids)
            for row in rows:
                value=current[row['entityUid']];item,context=value['item'],value['context']
                require(item.get('equipmentState','active')=='active' and context['rootEntityUid']==row['entityUid'], 'ROOT_EQUIPMENT_REQUIRED',409)
                require(item['objectKind']==snapshot['objectKind'],'OBJECT_KIND_MISMATCH',409)
                require(item['entityRevision']==row['expectedEntityRevision'] and context['hierarchyRevision']==row['expectedHierarchyRevision'],'ENGINEERING_CHANGED',409)
                old=db.execute('select assignment_revision from equipment_configuration_assignments where equipment_uid=?',(row['entityUid'],)).fetchone()
                require((old[0] if old else None)==row['expectedAssignmentRevision'],'REVISION_CONFLICT',409)
            revision='equipment-adoption:'+str(uuid4());now=datetime.now(timezone.utc).isoformat()
            for uid in uids:
                db.execute('insert into equipment_configuration_assignments values(?,?,?) on conflict(equipment_uid) do update set configuration_id=excluded.configuration_id,assignment_revision=excluded.assignment_revision',(uid,cid,revision))
            db.execute('insert into equipment_configuration_adoptions values(?,?,?,?,?)',(revision,cid,encoded(sorted(uids)),actor,now))
            authorize()
            return self._finish(db,actor,request,digest,{'configurationId':cid,'configurationRevision':config['head_revision'],
                'assignmentRevision':revision,'equipmentUids':sorted(uids)})
