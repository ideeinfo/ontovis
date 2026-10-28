"""Shared, project-scoped model evidence for recommendations and Canvas links."""
from __future__ import annotations

import json
import re

from .analysis_drafts import require


def configuration_references(library, version, project):
    """Capture revisions and adopters once when a model is added to a Canvas."""
    if library is None:return []
    with library.connect() as db:
        if not db.execute("select 1 from sqlite_master where name='equipment_configurations'").fetchone():return []
        rows=db.execute('''select c.id,c.head_revision from equipment_configurations c
            join equipment_configuration_revisions r on r.revision=c.head_revision
            where c.project_code=? and exists(select 1 from json_each(r.snapshot,'$.models') m
                where json_extract(m.value,'$.modelVersionId')=?) order by c.id''',(project,version)).fetchall()
        return [{'configurationId':cid,'configurationRevision':revision,'equipmentEntityUids':[
            row[0] for row in db.execute('select equipment_uid from equipment_configuration_assignments where configuration_id=? order by equipment_uid',(cid,))]}
            for cid,revision in rows]


def frozen_configuration_bindings(reader,library,version,references):
    result=[]
    require(library is not None or not references,'ANALYSIS_SOURCE_UNAVAILABLE',404)
    if not references:return result
    with library.connect() as db:
        for ref in references:
            row=db.execute('''select r.snapshot from equipment_configuration_revisions r
                join equipment_configurations c on c.id=r.configuration_id
                where c.project_code=? and c.id=? and r.revision=?''',
                (reader.reader.project_code,ref['configurationId'],ref['configurationRevision'])).fetchone()
            require(row is not None,'ANALYSIS_SOURCE_UNAVAILABLE',404)
            snapshot=json.loads(row[0]);model=next((m for m in snapshot['models'] if m['modelVersionId']==version),None)
            require(model is not None,'ANALYSIS_SOURCE_UNAVAILABLE',404)
            mappings=list(model['mappings'])
            if snapshot.get('rootDefinition'):mappings.append({**snapshot['rootDefinition'],'componentKeys':[],'wholeModel':True})
            for mapping in mappings:
                if not mapping['componentKeys'] and not mapping.get('wholeModel'):continue
                for equipment in ref['equipmentEntityUids'] or [None]:
                    result.append({'entityUid':mapping['objectRef']['entityUid'],'modelVersionId':version,
                        'componentKeys':mapping['componentKeys'],'wholeModel':bool(mapping.get('wholeModel')),
                        'sceneState':'active','sceneId':None,'sceneRevision':None,'equipmentEntityUid':equipment,
                        'configurationId':ref['configurationId'],'configurationRevision':ref['configurationRevision']})
    return result


def object_names(item):
    """Names are candidate hints only; they never establish object identity."""
    names = set()
    for identifier in item.get('identifiers', []):
        if identifier.get('role') != 'primary':
            continue
        value = identifier.get('value', '')
        if not isinstance(value, str) or not value:
            continue
        names.add(value)
        # An RDS location aspect can match a cabinet label in schematic geometry.
        location = re.search(r'\+([^=+\-]+)$', value)
        if location:
            names.add(location[1])
        if len(names) >= 16:
            break
    return sorted(names)[:16]


def component_name_index(components):
    result = {}
    for row in components:
        if row.get('componentKey') and row.get('displayName'):
            result.setdefault(row['displayName'], set()).add(row['componentKey'])
    return result


def candidate_components(item, components, *, by_name=None):
    index = component_name_index(components) if by_name is None else by_name
    return sorted({key for name in object_names(item) for key in index.get(name, ())})


def scene_bindings(reader, library, *, model_versions=None, entity_uid=None):
    if library is None:
        return [], False
    shared, shared_truncated = shared_configuration_bindings(reader,library,model_versions=model_versions,entity_uid=entity_uid)
    conditions, params = ['s.project_code=?'], [reader.reader.project_code]
    if model_versions is not None:
        versions = sorted(set(model_versions))
        if not versions:
            return [], False
        require(len(versions) <= 50)
        conditions.append('exists(select 1 from scene_resource_uses u where u.revision=s.head_revision and u.model_version_id in ('+
                          ','.join('?' for _ in versions)+'))')
        params += versions
    if entity_uid is not None:
        conditions.append('''exists(select 1 from json_each(r.snapshot,'$.instances') i where
            json_extract(i.value,'$.rootBinding.objectRef.entityUid')=? or exists(
            select 1 from json_each(i.value,'$.componentBindings') b where json_extract(b.value,'$.objectRef.entityUid')=?))''')
        params += [entity_uid, entity_uid]
    with library.connect() as db:
        rows = db.execute('''select s.id,s.head_revision,r.snapshot,v.validation,coalesce(l.state,'active')
            from scenes s join scene_revisions r on r.revision=s.head_revision
            left join scene_spatial_validations v on v.revision=s.head_revision
            left join scene_lifecycle l on l.scene_id=s.id where '''+' and '.join(conditions)+'''
            order by case when coalesce(l.state,'active')='active' then 0 else 1 end,s.id limit 101''', params).fetchall()
    matches, seen = list(shared), {(row['entityUid'],row['modelVersionId'],tuple(sorted(row['componentKeys']))) for row in shared}
    for scene_id, revision, raw, validation_raw, state in rows[:100]:
        snapshot = json.loads(raw); validation = json.loads(validation_raw) if validation_raw else {}
        for instance in snapshot['instances']:
            if model_versions is not None and instance['modelVersionId'] not in versions:
                continue
            bindings = list(instance.get('componentBindings', []))
            if instance.get('rootBinding'):
                bindings.append({**instance['rootBinding'], 'componentKeys': [], 'wholeModel': True})
            for binding in bindings:
                bound = binding['objectRef']
                if (bound.get('projectCode'), bound.get('ontobaseConnectionId')) != (reader.reader.project_code, reader.reader.connection_id):
                    continue
                if entity_uid is not None and bound['entityUid'] != entity_uid:
                    continue
                if any(issue.get('blocking') and issue.get('sceneModelInstanceId') == instance['sceneModelInstanceId']
                       and issue.get('objectRef') == bound for issue in validation.get('bindingIssues', [])):
                    continue
                key = (bound['entityUid'], instance['modelVersionId'], tuple(sorted(binding['componentKeys'])))
                if key in seen:
                    continue
                seen.add(key)
                matches.append({'entityUid': bound['entityUid'], 'modelVersionId': instance['modelVersionId'],
                    'componentKeys': binding['componentKeys'], 'wholeModel': bool(binding.get('wholeModel')),
                    'sceneId': scene_id, 'sceneRevision': revision, 'sceneState': state})
                if len(matches) >= 200:
                    return matches, True
    return matches, len(rows) > 100 or shared_truncated


def shared_configuration_bindings(reader,library,*,model_versions=None,entity_uid=None,equipment_uid=None):
    """Saved project mappings provide model evidence without per-scene copies."""
    with library.connect() as db:
        if not db.execute("select 1 from sqlite_master where name='equipment_configuration_assignments'").fetchone():
            return [],False
        conditions=["s.project_code=?","coalesce(l.state,'active')='active'"]
        params=[reader.reader.project_code]
        if entity_uid is not None:
            conditions.append("json_extract(b.value,'$.objectRef.entityUid')=?");params.append(entity_uid)
        if equipment_uid is not None:
            conditions.append('a.equipment_uid=?');params.append(equipment_uid)
        if model_versions is not None:
            versions=sorted(set(model_versions))
            if not versions:return [],False
            conditions.append("json_extract(m.value,'$.modelVersionId') in ("+','.join('?' for _ in versions)+')');params.extend(versions)
        rows=db.execute('''select s.id,s.head_revision,a.equipment_uid,c.id,c.head_revision,
            json_extract(m.value,'$.modelVersionId'),b.value from scenes s
            join scene_revisions r on r.revision=s.head_revision
            join json_each(r.snapshot,'$.instances') i
            join equipment_configuration_assignments a on a.equipment_uid=json_extract(i.value,'$.rootBinding.objectRef.entityUid')
            join equipment_configurations c on c.id=a.configuration_id
            join equipment_configuration_revisions cr on cr.revision=c.head_revision
            join json_each(cr.snapshot,'$.models') m on json_extract(m.value,'$.modelVersionId')=json_extract(i.value,'$.modelVersionId')
            join json_each(m.value,'$.mappings') b
            left join scene_lifecycle l on l.scene_id=s.id where '''+' and '.join(conditions)+''' order by s.id,a.equipment_uid limit 201''',params).fetchall()
    result=[]
    for scene,revision,equipment,cid,config_revision,version,raw in rows[:200]:
        mapping=json.loads(raw)
        if not mapping['componentKeys']:continue
        ref=mapping['objectRef']
        if (ref.get('ontobaseConnectionId'),ref.get('projectCode'))!=(reader.reader.connection_id,reader.reader.project_code):continue
        result.append({'entityUid':ref['entityUid'],'modelVersionId':version,'componentKeys':mapping['componentKeys'],'wholeModel':False,
            'sceneId':scene,'sceneRevision':revision,'sceneState':'active','equipmentEntityUid':equipment,
            'configurationId':cid,'configurationRevision':config_revision,'expectedEntityRevision':mapping['expectedEntityRevision']})
    return result,len(rows)>200


def recommend_models(reader, chosen, library, *, offset=0, query=''):
    """Prefer exact saved bindings, then history, then explicit name candidates."""
    require(type(query) is str and len(query) <= 200)
    item = chosen['item']; names = object_names(item)
    bindings, truncated = scene_bindings(reader, library, entity_uid=item['entityUid'])
    source_uid=item.get('sourceTemplateEntityUid') or item.get('definitionParentEntityUid')
    if source_uid:
        root_uid=(chosen.get('context') or {}).get('rootEntityUid')
        inherited,more=shared_configuration_bindings(reader,library,entity_uid=source_uid,equipment_uid=root_uid)
        bindings.extend({**row,'entityUid':item['entityUid'],'hostDefinitionEntityUid':source_uid} for row in inherited)
        truncated=truncated or more
    active = sorted({row['modelVersionId'] for row in bindings if row['sceneState'] == 'active'})
    historic = sorted({row['modelVersionId'] for row in bindings if row['sceneState'] != 'active'} - set(active))
    versions = active + historic
    if not names and not versions:
        return [], None, ['当前对象未登记模型绑定，也没有可匹配的主标识。']
    marks = lambda values: ','.join('?' for _ in values) or 'null'
    bound = f'p.version_id in ({marks(versions)})'
    candidate = f'''(not exists(select 1 from project_model_versions p2 join versions v2 on v2.id=p2.version_id
        where p2.asset_id=a.id and (v2.created_at>v.created_at or v2.created_at=v.created_at and v2.id>v.id))
        and exists(select 1 from json_each(v.components) c where json_extract(c.value,'$.displayName') in ({marks(names)})))'''
    with reader.models.library.connect() as db:
        rows = db.execute(f'''select a.name,p.asset_id,p.version_id,p.content_revision,v.sha256,v.components
            from project_model_assets a join project_model_versions p on p.asset_id=a.id join versions v on v.id=p.version_id
            left join project_model_lifecycle l on l.asset_id=a.id where a.project_code=? and coalesce(l.state,'active')='active'
            and ({bound} or {candidate}) and (?='' or instr(lower(a.name),lower(?))>0)
            order by case when p.version_id in ({marks(active)}) then 0 when p.version_id in ({marks(historic)}) then 1 else 2 end,a.name,p.version_id
            limit 13 offset ?''', [reader.models.project_code, *versions, *names, query, query, *active, *historic, offset]).fetchall()
    result, gaps = [], []
    for title, asset, version, revision, sha, raw in rows[:12]:
        components = json.loads(raw); keys = {row.get('componentKey') for row in components}
        matching = [row for row in bindings if row['modelVersionId'] == version and set(row['componentKeys']) <= keys]
        current = next((row for row in matching if row['sceneState'] == 'active'), None)
        history = next((row for row in matching if row['sceneState'] != 'active'), None)
        if current:
            match_type, reason = 'binding', ('项目设备采用已有共享型号配置；通过共享对象或所属柜体映射定位' if current.get('configurationId') else
                '当前工程对象在有效场景中已有模型绑定；使用该绑定的固定模型版本')
        elif history:
            match_type, reason = 'historical_binding', '当前对象仅在回收站场景中有历史绑定，不能当作有效绑定'
        elif candidate_components(item, components):
            match_type, reason = 'name_candidate', '构件名与所选对象的主标识匹配；仅为名称候选，尚无当前对象的有效绑定'
        else:
            gaps.append('部分场景绑定的构件已不在该固定模型中，未作为绑定推荐。'); continue
        result.append({'title': title, 'selector': {'modelAssetId': asset, 'modelVersionId': version,
            'expectedContentRevision': revision, 'expectedSha256': sha}, 'reason': reason, 'matchType': match_type})
    if truncated:
        gaps.append('场景绑定超过首批读取范围，当前推荐仅覆盖首批。')
    return result, offset+12 if len(rows) > 12 else None, list(dict.fromkeys(gaps))
