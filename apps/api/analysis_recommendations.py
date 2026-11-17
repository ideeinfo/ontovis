"""Relation-first, bounded reads for the existing analysis material picker."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time

from . import analysis_drafts as d
from .analysis_source_reader import selected
from .authority import PreviewError

PRIORITY = {'field_record':0, 'same_event':0, 'selected_object':0,
    'object_association':10, 'shared_definition':10, 'binding':10,
    'fault_evidence':20, 'simulation_mapping':20, 'same_object_fault':20,
    'descendant':30, 'shared_photos':30, 'model_applicable':40, 'same_fault':40,
    'historical_binding':50, 'simulation_rule':60, 'name_candidate':70, 'catalogue_search':90}
RELATED_SECTIONS = ('materials','drawings','photos','documents','device_materials')
PLANS = {
    'materials':(('field',),('drawings','photos'),('fault',),('child_drawings','shared_photos'),('applicable',)),
    'drawings':(('drawings',),('child_drawings',)),
    'photos':(('field',),('photos',),('shared_photos',),('applicable',)),
    'documents':(('fault',),('applicable',),('catalogue',)),
    'device_materials':(('applicable',),),
}
PAGE_SIZE = 12
MAX_PAGE_READS = 8
CURSOR_SECONDS = 300


def recommendation(kind, title, selector, reason, *, relevance='catalogue_search', asset_key=None, **extra):
    d.require(relevance in PRIORITY)
    value={'key':d.digest([kind,selector]), 'kind':kind, 'title':title[:120], 'selector':selector,
        'reason':reason, 'relevance':relevance, 'relevancePriority':PRIORITY[relevance], **extra}
    if asset_key:value['assetKey']=asset_key
    return value


def cursor_secret(reader, supplied):
    if supplied is not None:
        d.require(type(supplied) is bytes and len(supplied)>=32)
        return supplied
    # Direct in-process callers keep their own private key. HTTP always supplies
    # the existing service key and binds the cursor to the current login revision.
    key=getattr(reader,'_recommendation_cursor_key',None)
    if type(key) is not bytes:
        key=secrets.token_bytes(32);reader._recommendation_cursor_key=key
    return key


def scope_digest(reader, body, session_revision, selection=None):
    return d.digest({'actor':getattr(reader,'actor',''),'connection':getattr(reader.reader,'connection_id',''),
        'project':reader.reader.project_code,'session':session_revision,'entry':body['entry'],
        'section':body.get('section','objects'),'q':body.get('q',''),'selection':selection})


def encode_cursor(key, scope, state, expires=None):
    value={'version':1,'scope':scope,'expires':expires or int(time.time())+CURSOR_SECONDS,'state':state}
    raw=base64.urlsafe_b64encode(json.dumps(value,sort_keys=True,separators=(',',':')).encode()).decode().rstrip('=')
    token='rec1.'+raw+'.'+hmac.new(key,raw.encode(),'sha256').hexdigest()
    d.require(len(token)<=12288,'ANALYSIS_RECOMMENDATIONS_LIMIT',409)
    return token


def decode_cursor(token, key, scope):
    d.require(type(token) is str and len(token)<=12288,'ANALYSIS_RECOMMENDATIONS_CHANGED',409)
    try:
        prefix,raw,signature=token.split('.')
        d.require(prefix=='rec1' and hmac.compare_digest(signature,hmac.new(key,raw.encode(),'sha256').hexdigest()),
            'ANALYSIS_RECOMMENDATIONS_CHANGED',409)
        value=json.loads(base64.urlsafe_b64decode(raw+'='*(-len(raw)%4)))
    except (ValueError,UnicodeError,TypeError):
        raise PreviewError(409,'ANALYSIS_RECOMMENDATIONS_CHANGED') from None
    d.require(type(value) is dict and set(value)=={'version','scope','expires','state'}
        and value['version']==1 and value['scope']==scope,'ANALYSIS_RECOMMENDATIONS_CHANGED',409)
    d.require(type(value['expires']) is int and int(time.time())<value['expires']<=int(time.time())+CURSOR_SECONDS,
        'ANALYSIS_RECOMMENDATIONS_EXPIRED',409)
    return value['state'],value['expires']


def _matches(item, query):
    return not query or query in ' '.join(str(item.get(k,'')) for k in ('title','identifier','reason','reasonEn')).casefold()


def _document(item, reason, reason_en, relevance):
    if not item.get('contentVersionId'):return None
    doc=d.identifier(item.get('documentId'));version=d.identifier(item['contentVersionId'])
    kind='photo' if item['kind']=='photo' else 'document'
    selector={'documentId':doc,'contentVersionId':version}
    selector.update({'sourceType':'project_document'} if kind=='photo' else {'pageNumber':1})
    return recommendation(kind,item['title'],selector,reason,reasonEn=reason_en,relevance=relevance,
        asset_key=kind+':'+doc+':'+version+('' if kind=='photo' else ':1'),availability=item['availability'])


def _photos(reader, chosen, purpose, memo):
    cache='photos:'+purpose
    if cache in memo:return memo[cache]
    selection=selected(chosen)
    if purpose=='field_record' and selection['installationContextId'] is None:
        memo[cache]=[];return []
    rows=reader.photos.resolve({**selection,**({'photoPurpose':purpose} if purpose=='field_record' else {})})['items']
    result=[]
    for row in rows:
        basis='field_record' if purpose=='field_record' else 'shared_definition' if row.get('sourceRelation')=='template_definition' else 'object_association'
        selector={k:selection[k] for k in ('entityUid','expectedEntityRevision')}|{'evidenceRef':row['evidenceRef']}
        if purpose=='field_record':selector['photoPurpose']=purpose
        if row.get('sourceRevision'):selector['expectedSourceRevision']=row['sourceRevision']
        reason='当前设备的现场照片' if purpose=='field_record' else '共享定义的对象定位照片' if basis=='shared_definition' else '当前对象的定位照片'
        key='photo:'+str(row.get('documentId'))+':'+str(row.get('contentVersionId')) if row.get('documentId') and row.get('contentVersionId') else None
        if row.get('selector'):
            value=recommendation('photo',row['title'],selector,reason,relevance=basis,asset_key=key,preview=row,
                reasonEn='Field photo of this equipment.' if purpose=='field_record' else 'Located photo linked to this object or its retained shared definition.',
                availability='available' if row.get('displayAvailability','available') in ('available','not_checked') else 'unavailable')
        else:
            value=_document({**row,'kind':'photo','availability':'available' if row.get('contentAvailability')=='available' else 'unavailable'},
                reason+' · 整图','Whole photo linked to this object; no region is asserted.',basis)
            if value is None:continue
        result.append(value)
    # One fixed photo is suggested once. Prefer its original device region to
    # a label region, keeping the source selector intact.
    result.sort(key=lambda x:(x.get('availability')!='available',
        (x.get('preview') or {}).get('selector',{}).get('regionKind')!='device_region',x['key']))
    memo[cache]=result
    return result


def _source_page(reader, chosen, dataset, section, name, cursor, query, memo):
    selection=selected(chosen) if chosen else None
    if name in ('photos','field'):
        return (_photos(reader,chosen,'field_record' if name=='field' else 'object_location',memo) if chosen else []),None
    if name=='drawings':
        if not chosen:return [],None
        from .scene_evidence import SceneEvidenceReader
        rows=SceneEvidenceReader(reader.reader).resolve(selection)['items'];result=[]
        for row in rows:
            if row['availability']!='available':continue
            selector={k:selection[k] for k in ('entityUid','expectedEntityRevision')}|{'evidenceRef':row['evidenceRef']}
            if row.get('sourceRevision'):selector['expectedSourceRevision']=row['sourceRevision']
            basis='shared_definition' if row.get('sourceRelation')=='template_definition' else 'object_association'
            result.append(recommendation('drawing',row['title'],selector,'当前对象已有的图纸关联',
                relevance=basis,reasonEn='Drawing linked to this object or its retained shared definition.',preview=row))
        return result,None
    if name=='child_drawings':
        if not chosen:return [],None
        from .related_drawings import RelatedDrawingsReader
        value=RelatedDrawingsReader(reader.reader).resolve({**selection,'includeDescendants':True,'limit':12,'cursor':cursor})
        result=[]
        for row in value['items']:
            if any(x['relation'] in ('self','shared_definition') for x in row['matchedObjects']):continue
            if row['availability']!='available':continue
            selector={'drawingUid':row['drawingUid'],'expectedContentSha256':row['contentSha256']}
            result.append(recommendation('drawing',row['title'],selector,'已登记下级对象关联的图纸 · 整页',
                reasonEn='Drawing linked to registered descendants; whole page.',relevance='descendant',
                asset_key='drawing:'+row['drawingUid']+':'+row['contentSha256']))
        return result,value['nextCursor']
    if name=='shared_photos':
        if not chosen:return [],None
        value=reader.reader._request('POST',reader.reader.prefix+'/equipment/shared-photos/query',{**selection,'limit':12,'cursor':cursor})
        d.require(value.get('projectCode')==reader.reader.project_code and type(value.get('items')) is list
            and len(value['items'])<=12,'SOURCE_CHANGED',409)
        result=[]
        for row in value['items']:
            d.require(type(row) is dict and row.get('availability') in ('available','unavailable'),'SOURCE_CHANGED',409)
            value_row=_document({**row,'kind':'photo'},'本对象及下级的共享照片 · 整图',
                'Shared photo of this object or its registered members; whole image.','shared_photos')
            if value_row is not None:result.append(value_row)
        return result,value.get('nextCursor')
    if name=='fault':
        if not dataset:return [],None
        from .analysis_preview import fault_documents
        return [recommendation('document',row['title'],row['selector'],row['reason'],relevance='fault_evidence',
            asset_key='document:'+row['selector']['documentId']+':'+row['selector']['contentVersionId']+':'+str(row['selector']['pageNumber']),
            reasonEn='Published knowledge matches the current fault code and cites this fixed manual page.')
            for row in fault_documents(reader,dataset['faultCode'])],None
    if name=='applicable':
        if not chosen or selection['installationContextId'] is None:return [],None
        from .equipment_reader import EquipmentReader
        value=EquipmentReader(reader.reader).material_devices({**selection,'limit':12,'cursor':cursor});result=[]
        for row in value['items']:
            if section=='photos' and row['kind']!='photo' or section=='documents' and row['kind']!='pdf':continue
            item=_document(row,'当前设备型号及角色的适用资料',
                'Applicable to the selected equipment through its source-resolved model and role.','model_applicable')
            if item is not None:result.append(item)
        return result,value['nextCursor']
    if name=='catalogue':
        if not query and (chosen or dataset):return [],None
        from urllib.parse import urlencode
        params={'q':query,'status':'active','limit':12}
        if cursor is not None:params['cursor']=cursor
        value=reader.reader._request('GET',reader.reader.prefix+'/documents?'+urlencode(params));result=[]
        for row in value['items']:
            if row.get('kind')=='photo' or row.get('preview_kind')!='pdf':continue
            item=_document({'documentId':row['id'],'contentVersionId':row.get('current_version_id'),'title':row['name'],
                'kind':'pdf','availability':'available' if not row.get('preview_error') and row.get('current_version_id') else 'unavailable'},
                '项目文档名称检索','Project document name search; applicability needs review.','catalogue_search')
            if item is not None:result.append(item)
        return result,value.get('next_cursor')
    raise PreviewError(422,'INVALID_REQUEST')


def related_recommendations(reader, body, dataset, chosen, *, cursor_key=None, session_revision=''):
    section=body['section'];groups=PLANS[section];names={n for g in groups for n in g}
    query=body.get('q','');d.require(type(query) is str and len(query)<=200)
    if section=='device_materials' and (not chosen or selected(chosen)['installationContextId'] is None):
        return {'items':[],'nextOffset':None,'nextCursor':None,'gaps':['请先选择具体设备安装对象；共享工程定义不代替单台设备。'],'dataset':dataset,'order':'relevance'}
    if section!='documents' and not chosen:
        return {'items':[],'nextOffset':None,'nextCursor':None,'gaps':['先选择工程对象或故障，再查看关联资料。'],'dataset':dataset,'order':'relevance'}
    d.require(body.get('offset',0)==0,'ANALYSIS_RECOMMENDATIONS_CHANGED',409)
    key=cursor_secret(reader,cursor_key);scope=scope_digest(reader,body,session_revision,selected(chosen) if chosen else None)
    if body.get('cursor') is not None:
        state,expires=decode_cursor(body['cursor'],key,scope)
    else:state,expires={'phase':0,'turn':0,'positions':{}},int(time.time())+CURSOR_SECONDS
    d.require(type(state) is dict and set(state)=={'phase','turn','positions'} and type(state['phase']) is int
        and 0<=state['phase']<=len(groups) and type(state['turn']) is int and 0<=state['turn']<3
        and type(state['positions']) is dict and set(state['positions'])<=names,'ANALYSIS_RECOMMENDATIONS_CHANGED',409)
    positions=state['positions'];rows=[];seen={};gaps=[];cache={};memo={};reads=0;counts={}
    authorize=getattr(reader,'authorize',lambda:None);authorize()

    def head(name):
        nonlocal reads
        position=positions.setdefault(name,{'cursor':None,'index':0,'digest':None,'next':None})
        d.require(type(position) is dict,'ANALYSIS_RECOMMENDATIONS_CHANGED',409)
        if position=={'done':True}:return None
        d.require(set(position)=={'cursor','index','digest','next'} and type(position['index']) is int
            and 0<=position['index']<=20,'ANALYSIS_RECOMMENDATIONS_CHANGED',409)
        for k in ('cursor','next'):
            d.require(position[k] is None or type(position[k]) is str and len(position[k])<=8192,'ANALYSIS_RECOMMENDATIONS_CHANGED',409)
        while True:
            if name not in cache:
                if reads>=MAX_PAGE_READS or counts.get(name,0)>=2:return None
                reads+=1;counts[name]=counts.get(name,0)+1
                try:items,following=_source_page(reader,chosen,dataset,section,name,position['cursor'],query,memo)
                except PreviewError as error:
                    if error.status in (401,403,409,410,422):raise
                    gaps.append(name+': '+error.code);positions[name]={'done':True};return None
                d.require(following is None or type(following) is str and 0<len(following)<=8192,'SOURCE_CHANGED',409)
                d.require(following is None or following!=position['cursor'],'SOURCE_CHANGED',409)
                identifiers={x.get('value','').casefold() for x in (chosen or {}).get('item',{}).get('identifiers',[])
                    if x.get('role')=='primary' and type(x.get('value')) is str}
                items=[row for row in items if _matches(row,'' if query.casefold() in identifiers else query.casefold())]
                digest=d.digest([items,bool(following)])
                d.require(position['digest'] is None or position['digest']==digest,'ANALYSIS_RECOMMENDATIONS_CHANGED',409)
                if position['digest'] is None:position.update(digest=digest,next=following)
                cache[name]=items
            items=cache[name]
            d.require(position['index']<=len(items),'ANALYSIS_RECOMMENDATIONS_CHANGED',409)
            if position['index']<len(items):return items[position['index']]
            if position['next'] is None:
                positions[name]={'done':True};return None
            position.update(cursor=position['next'],index=0,digest=None,next=None);cache.pop(name,None)

    while len(rows)<PAGE_SIZE and state['phase']<len(groups):
        group=groups[state['phase']];picked=False
        for step in range(len(group)):
            turn=(state['turn']+step)%len(group);name=group[turn];item=head(name)
            if item is None:continue
            positions[name]['index']+=1;state['turn']=(turn+1)%len(group);picked=True
            identity=item.get('assetKey',item['key'])
            if identity not in seen:seen[identity]=len(rows);rows.append(item)
            elif rows[seen[identity]].get('availability')=='unavailable' and item.get('availability')!='unavailable':
                rows[seen[identity]]=item
            break
        if not picked:
            if all(positions.get(name)=={'done':True} for name in group):state.update(phase=state['phase']+1,turn=0)
            else:break
    authorize()
    following=encode_cursor(key,scope,state,expires) if state['phase']<len(groups) else None
    return {'items':sorted(rows,key=lambda row:row['relevancePriority']),'nextOffset':None,'nextCursor':following,'gaps':list(dict.fromkeys(gaps)),
        'dataset':dataset,'order':'relevance'}
