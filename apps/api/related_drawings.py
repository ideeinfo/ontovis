"""Parent-anchored reads of authoritative, deduplicated related drawings."""
import hashlib
from .scene_evidence import SceneEvidenceReader,SELECTION_FIELDS,_require,_sha,_text


class RelatedDrawingsReader:
    def __init__(self,reader):
        self.reader=reader;self.evidence=SceneEvidenceReader(reader)

    def selection(self,payload,content=False):
        extra={'includeDescendants','drawingUid','expectedSourceRevision','expectedContentSha256'} if content else {'includeDescendants','limit','cursor'}
        required=SELECTION_FIELDS|({'includeDescendants','drawingUid','expectedSourceRevision','expectedContentSha256'} if content else {'includeDescendants','limit'})
        _require(type(payload) is dict and required<=set(payload)<=SELECTION_FIELDS|extra,'INVALID_REQUEST',422)
        body=self.evidence._selection({key:payload[key] for key in SELECTION_FIELDS})
        _require(type(payload['includeDescendants']) is bool,'INVALID_REQUEST',422)
        if content:
            _text(payload['drawingUid'],request=True);_sha(payload['expectedSourceRevision'],request=True);_sha(payload['expectedContentSha256'],request=True)
        else:
            _require(type(payload['limit']) is int and 1<=payload['limit']<=20,'INVALID_REQUEST',422)
            if payload.get('cursor') is not None:_text(payload['cursor'],8192,request=True)
        return body

    def resolve(self,payload):
        body=self.selection(payload);selected=self.evidence._selected(body)
        value=self.reader._request('POST',self.reader.prefix+'/object-evidence/related',payload)
        _require(type(value) is dict and value.get('entityUid')==body['entityUid'] and value.get('entityRevision')==body['expectedEntityRevision']
            and value.get('installationContextId')==body['installationContextId'] and value.get('hierarchyRevision')==body['expectedHierarchyRevision']
            and value.get('includeDescendants') is payload['includeDescendants'],'ENGINEERING_CHANGED',409)
        _require(value.get('scopeComplete') is True and type(value.get('total')) is int and 0<=value['total']<=5000)
        _sha(value.get('snapshotRevision'));items=value.get('items');_require(type(items) is list and len(items)<=payload['limit'])
        seen=set();result=[]
        for row in items:
            _require(type(row) is dict);uid=_text(row.get('drawingUid'));_require(uid not in seen);seen.add(uid)
            _text(row.get('title'),2000,multiline=True);_sha(row.get('sourceRevision'))
            _require(row.get('availability') in ('available','missing') and row.get('precision')=='page' and row.get('region') is None)
            _require(row.get('drawingNumber') is None or type(row.get('drawingNumber')) is str)
            _require(row.get('pageNumber') is None or type(row.get('pageNumber')) is int and row['pageNumber']>=0)
            if row['availability']=='available':_sha(row.get('contentSha256'))
            else:_require(row.get('contentSha256') is None)
            matches=row.get('matchedObjects');_require(type(matches) is list and 0<len(matches)<=2000);clean=[];matched=set()
            for item in matches:
                _require(type(item) is dict)
                for key in ('entityUid','entityRevision','displayName','viaEntityUid','viaName'):_text(item.get(key),2000,multiline=key in ('displayName','viaName'))
                _require(item.get('relation') in ('self','shared_definition','installation_descendant','definition_descendant'))
                _require(payload['includeDescendants'] or item['relation'] in ('self','shared_definition'))
                token=(item['entityUid'],item['relation'],item['viaEntityUid']);_require(token not in matched);matched.add(token)
                if item['relation']=='self':_require(item['entityUid']==body['entityUid'] and item['entityRevision']==body['expectedEntityRevision'])
                clean.append({key:item[key] for key in ('entityUid','entityRevision','displayName','relation','viaEntityUid','viaName')})
            result.append({**{key:row[key] for key in ('drawingUid','title','drawingNumber','pageNumber','sourceRevision','contentSha256','availability','precision','region')},'matchedObjects':clean})
        cursor=value.get('nextCursor');_require(cursor is None or type(cursor) is str and 0<len(cursor)<=8192)
        self.evidence._unchanged(body,selected)
        _require(value['total']>=len(result) and (cursor is None or bool(result)))
        return {**{key:value[key] for key in ('total','nextCursor','snapshotRevision','scopeComplete','includeDescendants')},'items':result}

    def content(self,payload):
        body=self.selection(payload,True);selected=self.evidence._selected(body)
        self.reader.authorize()
        data=self.reader.authority.image(self.reader.prefix+'/object-evidence/related/content',{**payload,'representation':'image'})
        _require(type(data) is bytes and 0<len(data)<=20*1024*1024 and data.startswith(b'\x89PNG\r\n\x1a\n'))
        self.evidence._unchanged(body,selected)
        return {'content':data,'mediaType':'image/png','sourceContentSha256':payload['expectedContentSha256'],'imageSha256':hashlib.sha256(data).hexdigest()}
