"""Current protected drawing reads for an explicitly selected project object.

The caller owns the current-user session and project guard. Geometry, scene
bindings and ancestor hosts do not choose the source object or confer access.
"""
from __future__ import annotations

import hashlib

from .authority import PreviewError
from .scene_engineering import SceneEngineeringReader

MAX_REFERENCES=20
MAX_IMAGE_BYTES=20*1024*1024
SELECTION_FIELDS={'entityUid','installationContextId','expectedEntityRevision','expectedHierarchyRevision'}
CONTENT_FIELDS={'evidenceRef','expectedSourceRevision','expectedContentSha256'}


def _require(value,code='SOURCE_UNAVAILABLE',status=502):
    if not value:raise PreviewError(status,code)


def _text(value,limit=512,*,request=False,multiline=False):
    _require(isinstance(value,str) and 0<len(value)<=limit and value.strip()
             and all(ord(character)>=32 or multiline and character in '\n\r\t' for character in value),
             'INVALID_REQUEST' if request else 'SOURCE_UNAVAILABLE',422 if request else 502)
    return value


def _sha(value,*,request=False):
    _require(isinstance(value,str) and len(value)==64 and all(character in '0123456789abcdef' for character in value),
             'INVALID_REQUEST' if request else 'SOURCE_UNAVAILABLE',422 if request else 502)
    return value


class SceneEvidenceReader:
    def __init__(self,engineering_reader:SceneEngineeringReader):
        _require(isinstance(engineering_reader,SceneEngineeringReader),'INVALID_REQUEST',422)
        _require(callable(getattr(engineering_reader.authority,'image',None)),'INVALID_REQUEST',422)
        self.reader=engineering_reader

    def _selection(self,payload,*,content=False):
        fields=SELECTION_FIELDS|CONTENT_FIELDS if content else SELECTION_FIELDS
        _require(type(payload) is dict and set(payload)==fields,'INVALID_REQUEST',422)
        body={key:payload[key] for key in SELECTION_FIELDS}
        _text(body['entityUid'],request=True);_text(body['expectedEntityRevision'],200,request=True)
        _require((body['installationContextId'] is None)==(body['expectedHierarchyRevision'] is None),'INVALID_REQUEST',422)
        if body['expectedHierarchyRevision'] is not None:_text(body['expectedHierarchyRevision'],200,request=True)
        if content:
            _text(payload['evidenceRef'],request=True)
            _sha(payload['expectedSourceRevision'],request=True);_sha(payload['expectedContentSha256'],request=True)
        return body

    def _selected(self,body):
        # An incomplete parent path remains readable. No bindingEligible or
        # root/ancestor test can replace the selected object's own identity.
        return self.reader.detail(body['installationContextId'],body['entityUid'],body['expectedHierarchyRevision'],
                                  expected_entity_revision=body['expectedEntityRevision'])

    def _unchanged(self,body,selected):
        current=self._selected(body)
        _require(current['item']==selected['item'] and current['context']==selected['context'],
                 'ENGINEERING_CHANGED',409)
        self.reader.authorize()

    def _metadata(self,value,body,selected):
        _require(type(value) is dict and value.get('entityUid')==body['entityUid']
                 and value.get('entityRevision')==body['expectedEntityRevision']
                 and value.get('installationContextId')==body['installationContextId']
                 and value.get('hierarchyRevision')==body['expectedHierarchyRevision'],
                 'ENGINEERING_CHANGED',409)
        _require(value.get('complete') is True and value.get('versionMode')=='current_content_snapshot')
        rows=value.get('items');_require(type(rows) is list)
        _require(len(rows)<=MAX_REFERENCES,'EVIDENCE_SCOPE_LIMIT',413)
        result=[];seen=set()
        for row in rows:
            _require(type(row) is dict)
            ref=_text(row.get('evidenceRef'));_require(ref not in seen);seen.add(ref)
            relation=row.get('sourceRelation');source=_text(row.get('sourceEntityUid'))
            source_revision=_text(row.get('sourceEntityRevision'),200)
            template=row.get('sourceTemplateRevision')
            if relation=='direct':
                _require(source==body['entityUid'] and source_revision==body['expectedEntityRevision'] and template is None,
                         'SOURCE_CHANGED',409)
            else:
                _require(relation=='template_definition')
                _require(source==selected['item']['sourceTemplateEntityUid'] and _text(template,200)==source_revision,
                         'SOURCE_DEFINITION_CHANGED',409)
            availability=row.get('availability');_require(availability in ('available','missing'))
            digest=row.get('contentSha256')
            if availability=='available':_sha(digest)
            else:_require(digest is None)
            _require(row.get('versionMode')=='current_content_snapshot' and row.get('precision')=='page'
                     and row.get('region') is None and row.get('mediaType')=='application/pdf')
            page=row.get('pageNumber')
            _require(page is None or type(page) is int and 0<=page<=2**31-1)
            result.append({'evidenceRef':ref,'sourceRelation':relation,'sourceEntityUid':source,
                'sourceEntityRevision':source_revision,'sourceTemplateRevision':template,
                'sourceRevision':_sha(row.get('sourceRevision')),'recordDigest':_sha(row.get('recordDigest')),
                'contentSha256':digest,'title':_text(row.get('title'),2000,multiline=True),'pageNumber':page,
                'availability':availability,'versionMode':'current_content_snapshot','precision':'page','region':None})
        return {'items':result,'complete':True}

    def resolve(self,payload:dict)->dict:
        body=self._selection(payload);selected=self._selected(body)
        value=self.reader._request('POST',self.reader.prefix+'/object-evidence/resolve',body)
        result=self._metadata(value,body,selected)
        self._unchanged(body,selected)
        return result

    def content(self,payload:dict)->dict:
        body=self._selection(payload,content=True);selected=self._selected(body)
        request={**body,**{key:payload[key] for key in CONTENT_FIELDS},'representation':'image'}
        self.reader.authorize()
        # OntoBase re-resolves the exact reference, object/source revisions and
        # PDF hash before reading, then checks access again after rendering.
        # Authority.image also verifies PNG media type and the source hash
        # header. Re-listing here would hash every associated PDF needlessly.
        image=self.reader.authority.image(self.reader.prefix+'/object-evidence/content',request)
        _require(type(image) is bytes and 0<len(image)<=MAX_IMAGE_BYTES and image.startswith(b'\x89PNG\r\n\x1a\n'))
        self._unchanged(body,selected)
        return {'content':image,'mediaType':'image/png','sourceContentSha256':payload['expectedContentSha256'],
                'imageSha256':hashlib.sha256(image).hexdigest()}
