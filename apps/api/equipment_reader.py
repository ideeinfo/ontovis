"""Bounded current-user reads of the source equipment library."""
from urllib.parse import urlencode

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
            result[uid]={'item':item,'context':context,'children':children}
        _require(set(result)==set(uids))
        return result
