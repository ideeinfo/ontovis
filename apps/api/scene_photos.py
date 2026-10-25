"""Fixed photo regions on the selected object's retained source reference."""
from __future__ import annotations

from copy import deepcopy
import math

from .authority import PreviewError
from .scene_evidence import SceneEvidenceReader, SELECTION_FIELDS, _require, _sha, _text

PHOTO_FIELDS = {'evidenceRef', 'expectedSourceRevision', 'expectedContentVersionId', 'expectedSourceSha256',
                'expectedDisplayRevision'}


def selector(value):
    if value is None:
        return None
    _require(type(value) is dict)
    kind = value.get('kind')
    expected = {'kind', 'renditionId', 'displayRevision', 'regionKind', 'coordinateSpace'}
    _require(kind in ('image_bbox', 'spherical_region'))
    _require(set(value) == expected | ({'bbox'} if kind == 'image_bbox' else {'sphericalRegion'}))
    _text(value['renditionId']); _sha(value['displayRevision'])
    _require(value['regionKind'] in ('label_region', 'device_region'))
    if kind == 'image_bbox':
        _require(value['coordinateSpace'] == 'oriented_display_normalized')
        box = value['bbox']
        _require(type(box) is dict and set(box) == {'x', 'y', 'width', 'height'})
        _require(all(type(v) in (int, float) and math.isfinite(v) and 0 <= v <= 1 for v in box.values()))
        _require(box['width'] > 0 and box['height'] > 0
                 and box['x'] + box['width'] <= 1 + 1e-9 and box['y'] + box['height'] <= 1 + 1e-9)
    else:
        _require(value['coordinateSpace'] == 'spherical_degrees' and type(value['sphericalRegion']) is dict)
        region = value['sphericalRegion']
        _require(set(region) == {'yaw_start_deg', 'yaw_span_deg', 'pitch_min_deg', 'pitch_max_deg', 'view'})
        view = region['view']
        _require(type(view) is dict and set(view) == {'yaw_deg', 'pitch_deg', 'hfov_deg'})
        numbers = [region[key] for key in region if key != 'view'] + list(view.values())
        _require(all(type(number) in (int, float) and math.isfinite(number) for number in numbers))
        _require(-180 <= region['yaw_start_deg'] < 180 and 0 < region['yaw_span_deg'] <= 360
                 and -90 <= region['pitch_min_deg'] < region['pitch_max_deg'] <= 90
                 and -180 <= view['yaw_deg'] < 180 and -90 <= view['pitch_deg'] <= 90 and 35 <= view['hfov_deg'] <= 120)
    return deepcopy(value)


class ScenePhotoReader(SceneEvidenceReader):
    def __init__(self, reader):
        self.reader = reader

    def _photo_metadata(self, value, body):
        _require(type(value) is dict and value.get('entityUid') == body['entityUid']
                 and value.get('entityRevision') == body['expectedEntityRevision']
                 and value.get('installationContextId') == body['installationContextId']
                 and value.get('hierarchyRevision') == body['expectedHierarchyRevision'], 'ENGINEERING_CHANGED', 409)
        _require(value.get('complete') is True and value.get('versionMode') == 'fixed_content_version'
                 and value.get('scope') == 'stored_object_photo_locations')
        rows = value.get('items')
        _require(type(rows) is list and len(rows) <= 20)
        result, seen = [], set()
        for row in rows:
            _require(type(row) is dict)
            ref = _text(row.get('evidenceRef'))
            _require(ref.startswith('photo:') and ref not in seen)
            seen.add(ref)
            relation = row.get('sourceRelation')
            if relation == 'direct':
                _require(row.get('sourceEntityUid') == body['entityUid']
                         and row.get('sourceEntityRevision') == body['expectedEntityRevision']
                         and row.get('sourceTemplateRevision') is None, 'SOURCE_CHANGED', 409)
            else:
                _require(relation == 'template_definition'
                         and row.get('sourceTemplateRevision') == row.get('sourceEntityRevision'), 'SOURCE_CHANGED', 409)
                _text(row.get('sourceEntityUid')); _text(row.get('sourceEntityRevision'), 200)
            _require(row.get('engineeringConfirmation') is False
                     and row.get('verificationState') == 'association_record_only'
                     and row.get('applicabilityState') == 'recorded_unverified'
                     and row.get('versionMode') == 'fixed_content_version')
            basis = row.get('associationIdentityBasis', 'not_reported')
            _require(basis in ('formal_uid', 'accepted_primary', 'formal_drawing_primary_needs_review', 'not_reported'))
            item = {key: row.get(key) for key in ('evidenceRef', 'sourceRevision', 'sourceRelation', 'sourceEntityUid',
                'sourceEntityRevision', 'documentId', 'contentVersionId', 'title', 'sourceSha256', 'versionNumber',
                'newerVersionAvailable', 'documentStatus', 'unavailableReason', 'anchorUnavailableReason',
                'displayAvailability', 'contentAvailability', 'engineeringConfirmation', 'versionMode')}
            _sha(item['sourceRevision']); _text(item['title'], 2000, multiline=True)
            _text(item['contentVersionId']); _text(item['documentId'])
            if item['sourceSha256'] is not None: _sha(item['sourceSha256'])
            _require(type(item['newerVersionAvailable']) is bool)
            item['selector'] = selector(row.get('selector'))
            item['associationIdentityBasis'] = basis
            _require((item['selector'] is None) == (row.get('anchorAppliesTo') is None))
            if item['selector'] is not None:
                _require(row.get('anchorAppliesTo') == 'display_rendition')
            result.append(item)
        return {'items': result, 'complete': True, 'versionMode': 'fixed_content_version'}

    def _resolve_selected(self, body):
        try:
            value = self.reader._request('POST', self.reader.prefix + '/object-evidence/photos/resolve', body)
        except PreviewError as error:
            if error.status == 404:
                raise PreviewError(503, 'PHOTO_SOURCE_UNAVAILABLE') from None
            raise
        return self._photo_metadata(value, body)

    def resolve(self, payload):
        body = self._selection(payload)
        return self._resolve_selected(body)

    def content(self, payload):
        _require(type(payload) is dict and set(payload) == SELECTION_FIELDS | PHOTO_FIELDS, 'INVALID_REQUEST', 422)
        body = self._selection({key: payload[key] for key in SELECTION_FIELDS})
        _text(payload['evidenceRef'], request=True); _text(payload['expectedContentVersionId'], request=True)
        for key in ('expectedSourceRevision', 'expectedSourceSha256', 'expectedDisplayRevision'):
            _sha(payload[key], request=True)
        # The fixed source endpoint owns membership, association, version and
        # read-after-change checks. Do not repeat its queries in the proxy.
        request = {**body, **{key: payload[key] for key in PHOTO_FIELDS if key != 'expectedDisplayRevision'},
                   'representation': 'display'}
        self.reader.authorize()
        result = self.reader.authority.photo(self.reader.prefix + '/object-evidence/photos/content', request,
                                             payload['expectedDisplayRevision'])
        self.reader.authorize()
        return result
