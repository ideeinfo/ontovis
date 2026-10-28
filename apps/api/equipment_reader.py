"""Bounded current-user reads of the source equipment library."""
from urllib.parse import urlencode
from uuid import UUID

from .scene_engineering import _object, _require, _text, _context_id


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
                         'adoption':adoption,'attributes':row.get('attributes')}
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
