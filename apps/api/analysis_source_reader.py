"""Concrete existing object, drawing, photo, model and rehearsal readers."""
from __future__ import annotations

from urllib.parse import urlencode

from . import analysis_drafts as draft
from .analysis_evidence import SELECTION, PHOTO, DRAWING, validate_descriptor
from .authority import PreviewError
from .scene_evidence import SceneEvidenceReader
from .scene_photos import ScenePhotoReader
from . import simulated_faults as simulated


def selected(value):
    context = value.get('context')
    return {'entityUid': value['item']['entityUid'], 'expectedEntityRevision': value['item']['entityRevision'],
            'installationContextId': context['installationContextId'] if context else None,
            'expectedHierarchyRevision': context['hierarchyRevision'] if context else None}


def matches_project_identifier(item, identifier, project_code):
    return any(value.get('value') == identifier and value.get('role') == 'primary'
        and value.get('status') in ('accepted', 'needs_review') and value.get('scheme') in ('RDS', 'electrical_tag')
        and value.get('scopeType') == 'project' and value.get('scopeKey') == project_code
        for value in item.get('identifiers', []))


class AnalysisSourceReader:
    def __init__(self, reader, models, orders, authorize, actor, *, scene_library=None):
        self.reader, self.models, self.orders, self.authorize, self.actor = reader, models, orders, authorize, actor
        self.photos = ScenePhotoReader(reader)
        self.scene_library = scene_library

    def _selection(self, selector, extra=()):
        draft.require(type(selector) is dict and set(selector) == {'entityUid', 'expectedEntityRevision', *extra})
        draft.text(selector['entityUid'], 512); draft.text(selector['expectedEntityRevision'], 200)
        return selected(self.reader.context_for_object(selector['entityUid'], selector['expectedEntityRevision']))

    def resolve(self, kind, selector):
        self.authorize()
        if kind == 'object':
            value = self._selection(selector)
        elif kind == 'drawing' and 'drawingUid' in selector:
            validate_descriptor(kind, selector)
            from .analysis_preview import drawing_bytes
            drawing_bytes(self, selector)
            value = dict(selector)
        elif kind in ('drawing', 'photo'):
            photo_scope = ('photoPurpose',) if kind == 'photo' and 'photoPurpose' in selector else ()
            body = self._selection(selector, ('evidenceRef', *photo_scope))
            if photo_scope: body['photoPurpose'] = selector['photoPurpose']
            draft.text(selector['evidenceRef'], 512)
            rows = (self.photos if kind == 'photo' else SceneEvidenceReader(self.reader)).resolve(body)['items']
            row = next((item for item in rows if item['evidenceRef'] == selector['evidenceRef']), None)
            draft.require(row is not None, 'ANALYSIS_SOURCE_UNAVAILABLE', 404)
            if kind == 'drawing':
                draft.require(row['availability'] == 'available', 'ANALYSIS_SOURCE_UNAVAILABLE', 404)
                value = {**body, 'evidenceRef': row['evidenceRef'], 'expectedSourceRevision': row['sourceRevision'],
                         'expectedContentSha256': row['contentSha256']}
            else:
                draft.require(row['selector'] is not None and row['displayAvailability'] in ('available', 'not_checked'), 'PHOTO_REGION_UNAVAILABLE', 409)
                value = {**body, 'evidenceRef': row['evidenceRef'], 'expectedSourceRevision': row['sourceRevision'],
                    'expectedContentVersionId': row['contentVersionId'], 'expectedSourceSha256': row['sourceSha256'],
                    'expectedDisplayRevision': row['selector']['displayRevision']}
        elif kind == 'model':
            draft.require(set(selector) == {'modelAssetId', 'modelVersionId', 'expectedContentRevision', 'expectedSha256'})
            row = self.models.model(selector['modelAssetId'], selector['modelVersionId'], self.authorize)
            draft.require(row['assetState'] == 'active', 'MODEL_DELETED', 410)
            draft.require(row['contentRevision'] == selector['expectedContentRevision'] and row['sha256'] == selector['expectedSha256'], 'RESOURCE_CHANGED', 409)
            value = {key: row[key] for key in ('modelAssetId', 'modelVersionId', 'contentRevision', 'sha256')}
            if self.scene_library is not None:
                from .analysis_model_links import configuration_references
                value['configurationRefs']=configuration_references(self.scene_library,value['modelVersionId'],self.reader.project_code)
        elif kind == 'work_order':
            value = self.orders.capture(selector, self.actor, self.authorize)
        elif kind in ('alarm', 'trend'):
            fields = {'datasetId', 'datasetRevision', 'eventId'} if kind == 'alarm' else {'datasetId', 'datasetRevision', 'metricId', 'timeFrom', 'timeTo'}
            draft.require(set(selector) == fields)
            value = dict(selector)
            self.read(kind, value)
        elif kind == 'document':
            value = dict(selector)
            self.read(kind, value)
            if 'knowledgeReleaseId' in value:
                from .analysis_preview import node_evidence
                evidence = node_evidence(self, value)
                draft.require(any(row['selector'].get('page') == value['pageNumber'] for row in evidence['items']), 'KNOWLEDGE_PAGE_MISMATCH', 409)
        else:
            raise PreviewError(503, 'ANALYSIS_SOURCE_NOT_CONNECTED')
        validate_descriptor(kind, value); self.authorize()
        return value

    def read(self, kind, descriptor):
        validate_descriptor(kind, descriptor); self.authorize()
        if kind == 'object':
            value = self.reader.detail(descriptor['installationContextId'], descriptor['entityUid'],
                descriptor['expectedHierarchyRevision'], expected_entity_revision=descriptor['expectedEntityRevision'])
        elif kind == 'drawing' and 'drawingUid' in descriptor:
            from .analysis_preview import drawing_identity
            drawing, _ = drawing_identity(self, descriptor)
            value = {'title': drawing.get('drawing_name') or drawing['drawing_uid'], 'drawingUid': drawing['drawing_uid'],
                     'pageNumber': drawing.get('source_page_number'), 'contentSha256': descriptor['expectedContentSha256']}
        elif kind in ('drawing', 'photo'):
            body = {key: descriptor[key] for key in SELECTION}
            if kind == 'photo' and 'photoPurpose' in descriptor: body['photoPurpose'] = descriptor['photoPurpose']
            rows = (self.photos if kind == 'photo' else SceneEvidenceReader(self.reader)).resolve(body)['items']
            value = next((row for row in rows if row['evidenceRef'] == descriptor['evidenceRef']), None)
            draft.require(value is not None, 'ANALYSIS_SOURCE_UNAVAILABLE', 404)
            if kind == 'drawing':
                draft.require(value['sourceRevision'] == descriptor['expectedSourceRevision'] and value['contentSha256'] == descriptor['expectedContentSha256'], 'SOURCE_CHANGED', 409)
            else:
                draft.require(value['sourceRevision'] == descriptor['expectedSourceRevision'] and value['contentVersionId'] == descriptor['expectedContentVersionId']
                    and value['sourceSha256'] == descriptor['expectedSourceSha256'] and value['selector'] is not None
                    and value['selector']['displayRevision'] == descriptor['expectedDisplayRevision'], 'SOURCE_CHANGED', 409)
        elif kind == 'model':
            value = self.models.model(descriptor['modelAssetId'], descriptor['modelVersionId'], self.authorize)
            draft.require(value['contentRevision'] == descriptor['contentRevision'] and value['sha256'] == descriptor['sha256'], 'RESOURCE_CHANGED', 409)
            if 'configurationRefs' in descriptor:
                from .analysis_model_links import frozen_configuration_bindings
                frozen_configuration_bindings(self,self.scene_library,descriptor['modelVersionId'],descriptor['configurationRefs'])
        elif kind == 'work_order':
            value = self.orders.fixed_snapshot(descriptor)
        elif kind == 'document':
            prefix = self.reader.prefix + '/documents/' + descriptor['documentId']
            document = self.reader._request('GET', prefix)['item']
            draft.require(document['status'] != 'recycled', 'ANALYSIS_SOURCE_UNAVAILABLE', 410)
            version = self.reader._request('GET', prefix + '/versions/' + descriptor['contentVersionId'])['item']
            draft.require(version['source_sha256'] == descriptor['sourceSha256'], 'SOURCE_CHANGED', 409)
            draft.require(version['preview_kind'] == 'pdf' and 1 <= descriptor['pageNumber'] <= (version.get('page_count') or 0), 'ANALYSIS_DOCUMENT_PAGE_UNAVAILABLE', 409)
            value = {'title': document['name'], 'documentId': descriptor['documentId'], 'contentVersionId': descriptor['contentVersionId'],
                'pageNumber': descriptor['pageNumber'], 'pageCount': version['page_count'], 'versionNumber': version['version_number'],
                'sourceSha256': version['source_sha256'], 'mediaType': 'application/pdf', 'kind': document['kind'],
                'newerVersionAvailable': document['current_version_id'] != descriptor['contentVersionId']}
            navigation = self.reader._request('GET',prefix+'/versions/'+descriptor['contentVersionId']+'/navigation')
            value['outline'] = [{'title':row['title'],'page':row['page']}
                for row in navigation.get('outline',[])[:200]
                if isinstance(row.get('page'),int) and 1 <= row['page'] <= version['page_count']]
            value.update({key: descriptor[key] for key in ('knowledgeReleaseId', 'knowledgeNodeId') if key in descriptor})
        elif kind in ('alarm', 'trend'):
            simulated.catalogue(self.reader.project_code)
            dataset = simulated.dataset(descriptor['datasetId'], descriptor['datasetRevision'])
            if kind == 'alarm':
                value = simulated.alarms(descriptor['datasetId'], descriptor['datasetRevision'])
                draft.require(value['items'][0]['sourceEventId'] == descriptor['eventId'], 'SIMULATION_EVENT_UNAVAILABLE', 404)
            else:
                value = simulated.trend(descriptor['datasetId'], descriptor['metricId'], descriptor['timeFrom'], descriptor['timeTo'], descriptor['datasetRevision'])
            # Rehearsal data remains readable when a separate engineering source
            # is missing. Its object/photo cards perform their own protected reads.
            value = {**value, 'mappingKind': 'simulated_reference'}
        else:
            raise PreviewError(503, 'ANALYSIS_SOURCE_NOT_CONNECTED')
        self.authorize(); return value

    def content(self, kind, descriptor):
        validate_descriptor(kind, descriptor); self.authorize()
        if kind == 'photo':
            return self.photos.content(descriptor)
        if kind == 'drawing':
            if 'drawingUid' in descriptor:
                from .analysis_preview import drawing_bytes
                from .analysis_media import drawing_image
                return drawing_image(drawing_bytes(self, descriptor))
            value = SceneEvidenceReader(self.reader).content(descriptor)
            return {'content': value['content'], 'mediaType': 'image/png', 'sha256': value['imageSha256']}
        if kind == 'model':
            content = self.models.content(descriptor['modelVersionId'], descriptor['contentRevision'], descriptor['sha256'], self.authorize)
            return {'content': content, 'mediaType': 'model/gltf-binary', 'sha256': descriptor['sha256']}
        if kind == 'document':
            self.read(kind, descriptor)
            path = self.reader.prefix + '/documents/' + descriptor['documentId'] + '/content?' + urlencode({
                'version_id': descriptor['contentVersionId'], 'page': descriptor['pageNumber'], 'rendition': 'display'})
            value = self.reader.authority.document_page(path)
            self.authorize()
            return value
        raise PreviewError(422, 'ANALYSIS_SOURCE_CONTENT_UNSUPPORTED')

    def _rds(self, rds):
        value = self.reader._request('GET', self.reader.prefix+'/objects?'+urlencode({'primaryIdentifier': rds, 'limit': 50}))
        draft.require(value.get('projectCode') == self.reader.project_code and type(value.get('items')) is list, 'SOURCE_UNAVAILABLE', 502)
        def matches(item):
            return matches_project_identifier(item, rds, self.reader.project_code)
        rows = [row for row in value['items'] if matches(row)]
        draft.require(value.get('nextCursor') is None and len(rows) == 1, 'DIAGNOSTIC_OBJECT_UNRESOLVED', 409)
        result = self.reader.context_for_object(rows[0]['entityUid'], rows[0]['entityRevision'])
        draft.require(matches(result['item']), 'ENGINEERING_CHANGED', 409)
        return result

    def qualify(self, code):
        simulated.catalogue(self.reader.project_code)
        profile = simulated.identity(code); gaps = []; components = []; cabinet = None; photo = None; drawing = None; photo_target = None
        try:
            cabinet = self._rds('=WEC+'+profile['cabinet'])
            item = cabinet['item']
            draft.require(item['objectScope'] == 'definition' and item['objectKind'] == 'cabinet' and item['installationContextId'] is None, 'CABINET_MEMBERSHIP_UNRESOLVED', 409)
            from .demo_faults import diagnosis
            for node in diagnosis(code)['nodes']:
                if node['kind'] != 'component': continue
                channel = simulated.PROFILES[code].get('channel')
                is_channel = channel is not None and node['rds'] == channel['rds']
                child = self._rds(channel['moduleRds'] if is_channel else node['rds'])
                draft.require(child['item'].get('definitionParentEntityUid') == item['entityUid'], 'CABINET_MEMBERSHIP_UNRESOLVED', 409)
                components.append({'rds': node['rds'], 'selection': selected(child),
                    'referenceKind': 'module_channel' if is_channel else 'engineering_object',
                    **({'channelAddress': channel['address'], 'moduleRds': channel['moduleRds'],
                        'channelIdentityConfirmed': False} if is_channel else {})})
            seen = set()
            for target in [components[0]['selection'], selected(cabinet), *(part['selection'] for part in components[1:])]:
                if target['entityUid'] in seen: continue
                seen.add(target['entityUid'])
                rows = self.photos.resolve(target)['items']
                photo = next((row for row in rows if row['displayAvailability'] in ('available', 'not_checked') and row['selector'] is not None), None)
                if photo is not None: photo_target = target; break
            draft.require(photo is not None, 'PHOTO_REGION_UNAVAILABLE', 409)
            evidence = SceneEvidenceReader(self.reader).resolve(components[0]['selection'])['items']
            drawing = next((row for row in evidence if row['availability'] == 'available'), None)
            draft.require(drawing is not None, 'ANALYSIS_SOURCE_UNAVAILABLE', 404)
        except PreviewError as error:
            if error.status in (401, 403): raise
            gaps.append(error.code)
        self.authorize()
        return {'dataset': profile, 'eligible': not gaps, 'gaps': gaps,
            'components': components, 'cabinet': selected(cabinet) if cabinet else None,
            'photo': photo, 'photoTarget': photo_target, 'drawing': drawing,
            'locationGranularity': 'source_label' if photo_target and cabinet and photo_target['entityUid'] != cabinet['item']['entityUid'] else 'cabinet',
            'contentVerification': 'on_protected_read', 'wholeFaultDiagnosisComplete': False,
            'engineeringConfirmation': False, 'sourceKind': 'simulated'}
