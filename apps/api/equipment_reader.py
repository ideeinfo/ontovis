"""Bounded current-user reads of the source equipment library."""
from urllib.parse import quote, urlencode
import re
from uuid import UUID

from .scene_engineering import _object, _require, _text, _argument, _context_id


class EquipmentReader:
    def __init__(self, reader):
        self.reader = reader

    def catalogue(self, body):
        _require(type(body) is dict and set(body) <= {'q','cursor','limit','rootsOnly'}, 'INVALID_REQUEST',422)
        query={'q':body.get('q',''),'limit':body.get('limit',50),'rootsOnly':str(body.get('rootsOnly',True)).lower()}
        _require(type(query['q']) is str and len(query['q'])<=200 and type(query['limit']) is int
                 and 1<=query['limit']<=100 and type(body.get('rootsOnly',True)) is bool,'INVALID_REQUEST',422)
        if body.get('cursor') is not None:
            query['cursor']=_text(body['cursor'],8192)
        value=self.reader._request('GET',self.reader.prefix+'/equipment?'+urlencode(query))
        _require(value.get('projectCode')==self.reader.project_code and type(value.get('items')) is list
                 and len(value['items'])<=query['limit'])
        items=[_object(item) for item in value['items']]
        _require(all(item['objectScope']=='installation' and item['equipmentState']=='active' for item in items))
        return {key:value.get(key) for key in ('projectCode','nextCursor','snapshotRevision')}|{'items':items}

    def resolve(self, uids):
        _require(type(uids) is list and 0<len(uids)<=50 and len(set(uids))==len(uids),'INVALID_REQUEST',422)
        for uid in uids:_text(uid)
        value=self.reader._request('POST',self.reader.prefix+'/equipment/resolve',{'entityUids':uids})
        _require(value.get('projectCode')==self.reader.project_code and type(value.get('items')) is list)
        result={}
        for row in value['items']:
            _require(type(row) is dict and type(row.get('context')) is dict and type(row.get('children')) is list)
            item=_object(row['item']);ctx=row['context'];uid=item['entityUid']
            _require(uid in uids and uid not in result and item['objectScope']=='installation')
            cid=_context_id(ctx.get('installationContextId'))
            _require(ctx.get('projectCode')==self.reader.project_code and item['installationContextId']==cid
                     and ctx.get('purpose') in ('demonstration','engineering') and type(ctx.get('rootEntityUid')) is str)
            _require(_text(ctx.get('hierarchyRevision')).startswith(cid+':'))
            context={k:ctx[k] for k in ('installationContextId','projectCode','displayName','purpose','basis','rootEntityUid','hierarchyRevision','engineeringUseAllowed')}
            children=[_object(x) for x in row['children']]
            _require(len(children)<=2000 and len({x['entityUid'] for x in children})==len(children)
                     and all(x['installationContextId']==cid and x['equipmentState']=='active' for x in children))
            adoption=row.get('adoption')
            if adoption is not None:
                _require(type(adoption) is dict)
                for key in ('adoptionId','applicationId','applicationRevisionId','specificationRevisionId'):
                    self.identifier(adoption.get(key))
            result[uid]={'item':item,'context':context,'children':children,
                         'adoption':adoption,'attributes':row.get('attributes'),'model':self.model(row.get('model'))}
        _require(set(result)==set(uids))
        return result

    @staticmethod
    def identifier(value):
        try:
            _require(type(value) is str and str(UUID(value))==value,'INVALID_REQUEST',422)
        except (TypeError,ValueError,AttributeError):
            _require(False,'INVALID_REQUEST',422)
        return value

    def applications(self, body):
        _require(set(body)<={'offset','limit'},'INVALID_REQUEST',422)
        offset,limit=body.get('offset',0),body.get('limit',50)
        _require(type(offset) is int and offset>=0 and type(limit) is int and 1<=limit<=50,'INVALID_REQUEST',422)
        return self.reader._request('GET',self.reader.prefix+'/equipment-applications?'+urlencode({'offset':offset,'limit':limit}))

    def application(self, revision):
        revision=self.identifier(revision)
        value=self.reader._request('GET',self.reader.prefix+'/equipment-applications/revisions/'+revision)
        _require(value.get('projectCode')==self.reader.project_code and value.get('revisionId')==revision)
        _require(type(value.get('snapshot')) is dict and type(value.get('specification')) is dict)
        self.identifier(value.get('applicationId'))
        self.identifier(value['snapshot'].get('specificationRevisionId'))
        return value

    def application_equipment(self, revision):
        """Capture a bounded adopter set, rejecting changes between source pages."""
        revision=self.identifier(revision);items=[];offset=0;snapshot=None
        while True:
            query={'limit':100,'offset':offset}
            if snapshot is not None:query['expectedSnapshotRevision']=snapshot
            page=self.reader._request('GET',self.reader.prefix+'/equipment-applications/revisions/'+revision+'/equipment?'+urlencode(query))
            _require(page.get('projectCode')==self.reader.project_code and page.get('applicationRevisionId')==revision)
            _require(type(page.get('total')) is int and 0<=page['total']<=500,'ANALYSIS_SOURCE_LIMIT',409)
            rows=page.get('items');_require(type(rows) is list and len(rows)<=100)
            current=_text(page.get('snapshotRevision'),200)
            _require(snapshot is None or snapshot==current,'SNAPSHOT_CHANGED',409);snapshot=current
            for row in rows:
                _text(row.get('entityUid'));self.identifier(row.get('adoptionId'))
            items.extend(row['entityUid'] for row in rows)
            next_offset=page.get('nextOffset')
            if next_offset is None:
                _require(len(items)==page['total'] and len(set(items))==len(items))
                return items
            _require(next_offset==offset+100 and len(rows)==100)
            offset=next_offset

    def application_detail(self, revision):
        application=self.application(revision)
        spec_id=application['snapshot']['specificationRevisionId']
        specification=self.reader._request('GET','/api/v1/equipment-catalog/specification-revisions/'+spec_id)
        _require(specification.get('revisionId')==spec_id)
        snapshot=specification['snapshot']
        template=self.reader._request('GET','/api/v1/equipment-catalog/template-revisions/'+self.identifier(snapshot['templateRevisionId'])+
            '/effective?'+urlencode({'code':snapshot['classificationRef']['code']}))
        refs=([application['snapshot']['rootDefinition']] if application['snapshot'].get('rootDefinition') else [])+application['snapshot']['mappings']
        uids=sorted({r['entityUid'] for r in refs});objects=[]
        for offset in range(0,len(uids),50):objects.extend(self.reader._resolve(uids[offset:offset+50]).values())
        return {'application':application,'specification':specification,'template':template,'objects':objects}

    @classmethod
    def model(cls, value):
        if value is None:return None
        _require(type(value) is dict)
        for key in ('specificationId','revisionId','headRevisionId','templateRevisionId'):cls.identifier(value.get(key))
        for key in ('name','code','objectKind','nature','status'):_text(value.get(key),200)
        _require(type(value.get('revision')) is int and value['revision']>=1)
        _require(type(value.get('classificationRef')) is dict)
        return {key:value.get(key) for key in ('specificationId','revisionId','headRevisionId','templateRevisionId',
            'name','code','objectKind','nature','status','manufacturer','classificationRef','revision','rowVersion','roleCount','knownValueCount')}

    @staticmethod
    def material_roles(value):
        _require(type(value) is list and len(value)<=1000)
        result=[]
        for role in value:
            _require(type(role) is dict and role.get('kind') in ('model','root','role'))
            key=_text(role.get('value'),80)
            _require(key==role['kind'] if role['kind']!='role' else bool(re.fullmatch(r'role:[A-Za-z][A-Za-z0-9_.:-]*',key)))
            name=role.get('name')
            if name is not None:_text(name,2000)
            result.append(dict(value=key,kind=role['kind'],name=name))
        _require(len({r['value'] for r in result})==len(result))
        return result

    @staticmethod
    def material_items(value, limit, *, candidates=False):
        _require(type(value) is dict and type(value.get('items')) is list and len(value['items'])<=limit)
        items=[]
        for row in value['items']:
            _require(type(row) is dict)
            EquipmentReader.identifier(row.get('documentId'));EquipmentReader.identifier(row.get('contentVersionId'))
            _text(row.get('title'),1000)
            _require(row.get('kind') in ('pdf','photo') and row.get('availability') in ('available','unavailable','field_record'))
            _require(type(row.get('versionNumber')) is int and row['versionNumber']>=1)
            _require(row.get('pageCount') is None or type(row['pageCount']) is int and row['pageCount']>=0)
            item={key:row.get(key) for key in ('documentId','contentVersionId','title','kind','documentKind','versionNumber','pageCount','availability')}
            if candidates:
                _require(type(row.get('selected')) is bool);item['selected']=row['selected']
            else:
                for key in ('scopes','origins'):
                    _require(type(row.get(key)) is list and len(row[key])<=1000 and all(type(x) is str and len(x)<=100 for x in row[key]))
                    item[key]=row[key]
            items.append(item)
        cursor=value.get('nextCursor')
        _require(cursor is None or type(cursor) is str and 0<len(cursor)<=8192)
        _require(len({(x['documentId'],x['contentVersionId']) for x in items})==len(items))
        return {'items':items,'nextCursor':cursor}

    def material_catalogue(self, body, *, candidates=False):
        allowed={'specificationId','scope','kind','cursor','limit'}|({'revision','q'} if candidates else set())
        _require(type(body) is dict and {'specificationId'}<=set(body)<=allowed,'INVALID_REQUEST',422)
        spec=self.identifier(body['specificationId']);limit=body.get('limit',20)
        scope=body.get('scope','model' if candidates else '');kind=body.get('kind','')
        _require(type(limit) is int and 1<=limit<=100 and kind in ('','pdf','photo') and type(scope) is str
            and len(scope)<=80 and (scope in ('','model','root') or re.fullmatch(r'role:[A-Za-z][A-Za-z0-9_.:-]*',scope)), 'INVALID_REQUEST',422)
        query={'scope':scope,'kind':kind,'limit':limit}
        if body.get('cursor') is not None:query['cursor']=_argument(body['cursor'],8192)
        if candidates:
            revision=body.get('revision');q=body.get('q','')
            _require(type(revision) is int and 0<=revision<=2147483647 and type(q) is str and len(q)<=200,'INVALID_REQUEST',422)
            query.update(revision=revision,q=q)
        value=self.reader._request('GET',self.reader.prefix+'/equipment-materials/models/'+spec+('/candidates' if candidates else '')+'?'+urlencode(query))
        result=self.material_items(value,limit,candidates=candidates)
        if not candidates:
            model=self.model(value.get('model'));_require(model is not None and model['specificationId']==spec)
            roles=self.material_roles(value.get('roles'))
            _require(not scope or scope in {r['value'] for r in roles},'INVALID_REQUEST',422)
            _require(type(value.get('revision')) is int and value['revision']>=0 and type(value.get('total')) is int and value['total']>=0)
            _require(type(value.get('canManage')) is bool)
            result.update(model=model,roles=roles,revision=value['revision'],total=value['total'],canManage=value['canManage'])
        return result

    def material_devices(self, body):
        fields={'entityUid','expectedEntityRevision','installationContextId','expectedHierarchyRevision'}
        _require(type(body) is dict and fields<=set(body)<=fields|{'cursor','limit'},'INVALID_REQUEST',422)
        for key in ('entityUid','expectedEntityRevision','expectedHierarchyRevision'):_argument(body.get(key),512 if key=='entityUid' else 200)
        _context_id(body.get('installationContextId'),request=True)
        limit=body.get('limit',20);_require(type(limit) is int and 1<=limit<=100,'INVALID_REQUEST',422)
        if body.get('cursor') is not None:_argument(body['cursor'],8192)
        value=self.reader._request('POST',self.reader.prefix+'/equipment-materials/devices/resolve',{**body,'limit':limit})
        result=self.material_items(value,limit)
        result.update(model=self.model(value.get('model')),role=value.get('role'),roles=self.material_roles(value.get('roles',[])),revision=value.get('revision',0),canManage=value.get('canManage',False))
        _require(result['role'] is None or result['role'] in {r['value'] for r in result['roles'] if r['kind'] in ('root','role')})
        _require(type(result['revision']) is int and result['revision']>=0 and type(result['canManage']) is bool)
        return result

    def attribute_form(self, body):
        _require(type(body) is dict and set(body)=={'entityUid'},'INVALID_REQUEST',422);uid=_argument(body['entityUid'])
        value=self.reader._request('GET',self.reader.prefix+'/equipment/'+quote(uid,safe='')+'/attribute-form')
        _require(type(value.get('device')) is dict and value['device'].get('entityUid')==uid)
        _require(type(value.get('fields')) is list and len(value['fields'])<=1000 and type(value.get('values')) is list
            and type(value.get('available')) is bool)
        return {key:value.get(key) for key in ('device','rowVersion','canManage','available','reason','fields','values','scope','contextDigest')}|{'model':self.model(value.get('model'))}
