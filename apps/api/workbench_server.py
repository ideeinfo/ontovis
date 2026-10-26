#!/usr/bin/env python3
"""ONTOVis first workbench slice: one configured installation, current evidence.

No spatial-demo assets, OntoBase business writes or arbitrary proxy.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from http.server import ThreadingHTTPServer
from pathlib import Path
import sys
import tempfile
from urllib.parse import quote, urlencode
from uuid import UUID

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from apps.api.authority import Authority, PreviewError
from apps.api.user_sessions import UserSessions
from apps.api.session_http import handler_type
from apps.api.model_assets import ModelAsset
from apps.api.model_library import ModelLibrary
from apps.api.project_model_library import ProjectModelLibrary
from apps.api.model_resource_metadata import ModelResourceMetadata, MAX_METADATA_BYTES, MAX_METADATA_REQUEST_BYTES
from apps.api.model_thumbnails import ModelThumbnails, ThumbnailRenderer, MAX_PNG_BYTES
from apps.api.model_validation import MAX_BYTES
from apps.api.model_inspection import ModelInspection
from apps.api.scene_library import SceneLibrary, MAX_SCENE_BYTES, MAX_INSTANCES, MAX_COORDINATE_M, MAX_COMPONENT_BINDINGS
from apps.api.terrain_library import TerrainLibrary, MAX_VERSIONS as MAX_TERRAIN_VERSIONS, MAX_TOTAL_BYTES as MAX_TERRAIN_TOTAL_BYTES
from apps.api.terrain_validation import MAX_BYTES as MAX_TERRAIN_BYTES, MAX_PIXELS as MAX_TERRAIN_PIXELS, MAX_TRIANGLES as MAX_TERRAIN_TRIANGLES
from apps.api.scene_geometry_process import SceneGeometryProcess
from apps.api.scene_engineering import SceneEngineeringReader
from apps.api.scene_photos import ScenePhotoReader
from apps.api.scene_evidence import SceneEvidenceReader
from apps.api.scene_engineering_validation import SceneEngineeringValidator
from apps.api.scene_bindings import validate_ref
from apps.api.scene_location import SceneLocationResolver
from apps.api.legacy_scene_registry import LegacySceneRegistry
from apps.api.legacy_scene_sources import LegacySceneSources
from apps.api.imagery_library import ImageryLibrary, MAX_BYTES as MAX_IMAGERY_BYTES, MAX_VERSIONS as MAX_IMAGERY_VERSIONS, MAX_TOTAL_BYTES as MAX_IMAGERY_TOTAL_BYTES
from apps.api.public_geodata import PublicGeoData
from apps.api.storage_lease import storage_lease, StorageInUse


class WorkbenchSessions(UserSessions):
    def __init__(self, base_url, project_code, installation_context_id, *, model_root=None, library_root=None, terrain_python=None,
                 terrain_max_upload_bytes=MAX_TERRAIN_BYTES, ontobase_connection_id='ontobase-primary',
                 thumbnail_renderer=None, thumbnail_node=None, thumbnail_browser=None, **kwargs):
        if type(terrain_max_upload_bytes) is not int or not 8 <= terrain_max_upload_bytes <= MAX_TERRAIN_BYTES:
            raise ValueError('Invalid configured terrain upload limit')
        if any(value is not None for value in (thumbnail_renderer, thumbnail_node, thumbnail_browser)) and not all(
                value is not None for value in (thumbnail_renderer, thumbnail_node, thumbnail_browser)):
            raise ValueError('Configure thumbnail renderer, Node and browser together')
        super().__init__(base_url, project_code, **kwargs)
        self.terrain_max_upload_bytes = terrain_max_upload_bytes
        if (not isinstance(ontobase_connection_id, str) or not 0 < len(ontobase_connection_id) <= 200
                or ontobase_connection_id != ontobase_connection_id.strip()
                or any(ord(character) < 32 for character in ontobase_connection_id)):
            raise ValueError('Invalid configured OntoBase connection identity')
        self.ontobase_connection_id = ontobase_connection_id
        self.context_id = str(UUID(installation_context_id)) if installation_context_id else None
        self.prefix = '/api/v1/projects/' + quote(project_code, safe='')
        self.context_path = self.prefix + '/installations/' + self.context_id if self.context_id else None
        self.model = ModelAsset(Path(model_root), project_code, self.context_id) if model_root else None
        self.library = ModelLibrary(Path(library_root),project_code,self.context_id) if library_root else None
        self.project_models = ProjectModelLibrary(self.library) if self.library else None
        self.model_inspection = ModelInspection(self.project_models) if self.project_models else None
        self.model_metadata = ModelResourceMetadata(self.project_models) if self.project_models else None
        self.thumbnails = ModelThumbnails(self.project_models,
            ThumbnailRenderer(thumbnail_renderer, thumbnail_node, thumbnail_browser)) if self.project_models and thumbnail_renderer else None
        self.scenes = SceneLibrary(self.library, model_identity=self.project_models.content_identity) if self.library else None
        self.legacy_registry = LegacySceneRegistry(self.library) if self.library else None
        self.terrains = TerrainLibrary(self.library, python_executable=terrain_python) if self.library and terrain_python else None
        self.imagery = ImageryLibrary(self.library, python_executable=terrain_python) if self.library and terrain_python else None
        self.public_geodata = PublicGeoData(self.library, self.terrains, self.imagery) if self.terrains and self.imagery else None
        self.geometry = SceneGeometryProcess(self.library, python_executable=terrain_python,
            terrain_root=self.terrains.root / 'versions') if self.terrains else None

    def scene_access(self, authority):
        """Read project permission without requiring the legacy default installation."""
        access = authority.request('GET', self.access_path)
        if (access.get('projectCode') != self.project_code
                or not {'objects.read','objects.resolve','installations.read','hierarchy.read'}.issubset(access.get('capabilities', []))
                or not isinstance(access.get('accessRevision'), str) or not access['accessRevision']):
            raise PreviewError(403, 'FORBIDDEN')
        return access

    def project_authorization(self, sid, payload, *, writing, write_code='SCENE_WRITE_FORBIDDEN'):
        with self.lock:
            row = self.current(sid, authenticated=True, touch=True)
            if payload.get('expectedSessionRevision') != row.revision:
                raise PreviewError(409, 'SESSION_CHANGED')
            authority = row.authority
        try:
            baseline = self.scene_access(authority)

            def authorize():
                try:
                    self.guard(sid, row)
                    access = self.scene_access(authority)
                    if writing and access.get('role') != 'admin':
                        raise PreviewError(403, write_code)
                    if access['accessRevision'] != baseline['accessRevision']:
                        raise PreviewError(409, 'ACCESS_CHANGED')
                    self.guard(sid, row)
                except PreviewError as error:
                    if error.status == 401:
                        self.invalidate(sid, row)
                    raise

            authorize()
            return row, authorize, baseline, authority.username
        except PreviewError as error:
            if error.status == 401:
                self.invalidate(sid, row)
            raise

    def terrain_authorization(self, sid, payload, *, writing):
        result = self.project_authorization(sid, payload, writing=writing)
        if self.terrains is None:
            raise PreviewError(503, 'PROCESSING_UNAVAILABLE')
        return result

    def legacy_migration_request(self, sid, path, payload):
        prefix = '/api/workbench/scenes/legacy-migration/'
        action = path.removeprefix(prefix)
        if not path.startswith(prefix) or action not in ('sources', 'check', 'activate', 'entry'):
            raise PreviewError(422, 'INVALID_REQUEST')
        row, authorize, access, actor = self.project_authorization(sid, payload,
            writing=action != 'entry', write_code='LEGACY_MIGRATION_FORBIDDEN')
        if self.legacy_registry is None:
            raise PreviewError(503, 'LEGACY_REGISTRY_UNAVAILABLE')
        with self.lock:
            self.guard(sid, row)
            authority = row.authority
        body = {key: value for key, value in payload.items() if key != 'expectedSessionRevision'}
        try:
            if action == 'entry':
                value = self.legacy_registry.entry(body, actor, authorize)
                if value['available']:
                    entry = value['entry']
                    # Resolve only the registered current target through normal
                    # project resource and current engineering read boundaries.
                    self.scene_request(sid, '/api/workbench/scenes/open', {
                        'expectedSessionRevision': row.revision, 'sceneId': entry['sceneId'],
                        'sceneRevision': entry['sceneRevision']})
            else:
                reader = SceneEngineeringReader(authority, self.ontobase_connection_id, self.project_code,
                    lambda: self.guard(sid, row))
                sources = LegacySceneSources(self.library, self.model, reader)
                def authorize_sources():
                    authorize()
                    sources.assert_unchanged()
                    self.guard(sid, row)
                if action == 'sources':
                    if body: raise PreviewError(422, 'INVALID_REQUEST')
                    value = sources.inventory()
                    authorize_sources()
                else:
                    method = self.legacy_registry.check if action == 'check' else self.legacy_registry.activate
                    value = method(body, actor, authorize_sources, sources, access_revision=access['accessRevision'])
                # The registry has just completed its full authorization and
                # final local source check. Do not reopen a network race here.
            if action == 'entry': authorize()
            else: self.guard(sid, row)
            return {**value, 'sessionRevision': row.revision}
        except PreviewError as error:
            if error.status == 401:
                self.invalidate(sid, row)
            raise

    def scene_object_request(self, sid, path, payload):
        row, authorize, access, _ = self.project_authorization(sid, payload, writing=False)
        with self.lock:
            self.guard(sid, row)
            authority = row.authority
        # Fixed source APIs check current project membership on every request.
        # Full grant checks bracket the operation; inner checks keep logout prompt.
        try:
            body = {key: value for key, value in payload.items() if key != 'expectedSessionRevision'}
            reader = SceneEngineeringReader(authority, self.ontobase_connection_id, self.project_code, lambda: self.guard(sid, row))
            if path == '/api/workbench/objects/context':
                if not {'entityUid'} <= set(body) <= {'entityUid', 'expectedEntityRevision'}:
                    raise PreviewError(422, 'INVALID_REQUEST')
                value = reader.context_for_object(body['entityUid'], body.get('expectedEntityRevision'))
            elif path == '/api/workbench/objects/detail':
                fields = {'installationContextId', 'entityUid', 'expectedHierarchyRevision'}
                if not fields <= set(body) <= fields | {'expectedEntityRevision'}:
                    raise PreviewError(422, 'INVALID_REQUEST')
                value = reader.detail(body['installationContextId'], body['entityUid'], body['expectedHierarchyRevision'],
                                      expected_entity_revision=body.get('expectedEntityRevision'))
            elif path == '/api/workbench/objects/children':
                fields = {'installationContextId', 'entityUid', 'expectedHierarchyRevision'}
                if not fields <= set(body) <= fields | {'cursor'}:
                    raise PreviewError(422, 'INVALID_REQUEST')
                value = reader.children(body['installationContextId'], body['entityUid'], body['expectedHierarchyRevision'],
                                        cursor=body.get('cursor'))
            elif path == '/api/workbench/objects/evidence/resolve':
                value = SceneEvidenceReader(reader).resolve(body)
            elif path == '/api/workbench/objects/evidence/content':
                value = SceneEvidenceReader(reader).content(body)
            elif path == '/api/workbench/objects/photos/resolve':
                value = ScenePhotoReader(reader).resolve(body)
            elif path == '/api/workbench/objects/photos/content':
                value = ScenePhotoReader(reader).content(body)
            else:
                raise PreviewError(422, 'INVALID_REQUEST')
            authorize()
            return {**value, 'sessionRevision': row.revision, 'projectName': access.get('projectName', self.project_code)}
        except PreviewError as error:
            if error.status == 401:
                self.invalidate(sid, row)
            raise

    def resource_response(self, value, row, access):
        if self.thumbnails is not None: self.thumbnails.attach(value)
        value['sessionRevision'] = row.revision
        value['capabilities'] = {'scope': getattr(self, 'model_scope', 'project_static_glb_resources'), 'canRead': True,
            'canUpload': access.get('role') == 'admin', 'canCalibrate': access.get('role') == 'admin',
            'canWriteMetadata': access.get('role') == 'admin',
            'canGenerateThumbnails': self.thumbnails is not None and access.get('role') == 'admin',
            'calibrationRequiredForGeographicPlacement': True, 'automaticLegacyAdoption': False}
        limits = ProjectModelLibrary.capabilities()
        value['limits'] = {key: limits[key] for key in ('maxUploadBytes', 'maxVersions', 'maxLibraryBytes')}
        value['limits'].update({'maxMetadataHeaderBytes': 8192,
            'maxMetadataJsonBytes': 6144, 'maxJsonBytes': 16384,
            'maxResourceMetadataBytes': MAX_METADATA_BYTES, 'maxResourceMetadataRequestBytes': MAX_METADATA_REQUEST_BYTES,
            'maxThumbnailBytes': MAX_PNG_BYTES})
        return value

    def resource_authorization(self, sid, payload, *, writing, read_capabilities=True):
        if hasattr(self, 'model_authorization'):
            return self.model_authorization(sid, payload, writing=writing, read_capabilities=read_capabilities)
        return self.project_authorization(sid, payload, writing=writing, write_code='MODEL_WRITE_FORBIDDEN')

    def resource_upload(self, sid, payload, stream, length):
        row, authorize, access, actor = self.resource_authorization(sid, payload, writing=True)
        if self.project_models is None:
            raise PreviewError(503, 'MODEL_UNAVAILABLE')
        metadata = {key: value for key, value in payload.items() if key != 'expectedSessionRevision'}
        value = self.project_models.upload(stream, length, metadata, actor, authorize)
        if self.thumbnails is not None: self.thumbnails.automatic(value, actor, authorize)
        authorize()
        return self.resource_response(value, row, access)

    def resource_request(self, sid, path, payload):
        writing = path in ('/api/workbench/resources/model/calibrate', '/api/workbench/resources/model/import-existing',
                           '/api/workbench/resources/model/preserve-legacy-display',
                           '/api/workbench/resources/model/metadata/save', '/api/workbench/resources/model/thumbnail/ensure')
        row, authorize, access, actor = self.resource_authorization(sid, payload,
            writing=writing, read_capabilities=not path.endswith('/content'))
        if self.project_models is None or self.scenes is None:
            raise PreviewError(503, 'MODEL_UNAVAILABLE')
        body = {key: value for key, value in payload.items() if key != 'expectedSessionRevision'}
        if path == '/api/workbench/resources/models' and set(body).issubset(
                {'q', 'purpose', 'cursor', 'expectedLibraryRevision', 'limit'}):
            options = dict(body)
            if 'expectedLibraryRevision' in options:
                options['expected_library_revision'] = options.pop('expectedLibraryRevision')
            value = self.project_models.listing(actor, authorize,
                access_revision=access['accessRevision'], **options)
        elif path == '/api/workbench/resources/models/legacy' and not body:
            value = self.project_models.legacy_candidates(authorize)
        elif path == '/api/workbench/resources/model' and set(body) == {'modelAssetId', 'modelVersionId'}:
            value = self.project_models.model(body['modelAssetId'], body['modelVersionId'], authorize)
        elif path == '/api/workbench/resources/model/metadata':
            value = self.model_metadata.read(body, authorize)
        elif path == '/api/workbench/resources/model/inspection':
            value = self.model_inspection.read(body, authorize)
        elif path == '/api/workbench/resources/model/metadata/save':
            value = self.model_metadata.save(body, actor, authorize)
        elif path in ('/api/workbench/resources/model/thumbnail', '/api/workbench/resources/model/thumbnail/ensure',
                      '/api/workbench/resources/model/thumbnail/content'):
            if self.thumbnails is None: raise PreviewError(503, 'THUMBNAIL_UNAVAILABLE')
            if path.endswith('/content'):
                value = self.thumbnails.content(body, authorize)
                authorize()
                return {**value, 'sessionRevision': row.revision}
            value = {'thumbnail': self.thumbnails.ensure(body, actor, authorize) if path.endswith('/ensure')
                     else self.thumbnails.status(body, authorize)}
        elif path == '/api/workbench/resources/model/content' and set(body) == {
                'modelVersionId', 'expectedContentRevision', 'expectedSha256'}:
            fingerprint = body['expectedSha256']
            if (not isinstance(fingerprint, str) or len(fingerprint) != 64
                    or any(character not in '0123456789abcdef' for character in fingerprint)):
                raise PreviewError(422, 'INVALID_REQUEST')
            content = self.project_models.content(body['modelVersionId'],
                body['expectedContentRevision'], fingerprint, authorize)
            authorize()
            return {'content': content, 'sha256': fingerprint, 'sessionRevision': row.revision}
        elif path == '/api/workbench/resources/model/import-existing':
            value = self.project_models.import_existing(body, actor, authorize)
            if self.thumbnails is not None: self.thumbnails.automatic(value, actor, authorize)
        elif path == '/api/workbench/resources/model/calibrate':
            value = self.project_models.calibrate(body, actor, authorize)
            if self.thumbnails is not None: self.thumbnails.automatic(value, actor, authorize)
        elif path == '/api/workbench/resources/model/preserve-legacy-display':
            value = self.project_models.preserve_legacy_display(body, actor, authorize)
            if self.thumbnails is not None: self.thumbnails.automatic(value, actor, authorize)
        elif path == '/api/workbench/resources/uses' and {'resourceKind', 'versionId'} <= set(body) and set(body).issubset(
                {'resourceKind', 'versionId', 'scope', 'cursor', 'limit'}):
            if body['resourceKind'] != 'model':
                raise PreviewError(422, 'SCENE_SCOPE_UNSUPPORTED')
            value = self.scenes.uses(body['versionId'], actor, authorize,
                access_revision=access['accessRevision'],
                **{key: value for key, value in body.items() if key in ('scope', 'cursor', 'limit')})
        else:
            raise PreviewError(422, 'INVALID_REQUEST')
        authorize()
        return self.resource_response(value, row, access)

    def terrain_response(self, value, row, access):
        value['sessionRevision'] = row.revision
        value['capabilities'] = {'scope': 'private_geotiff_processing', 'canRead': True,
            'canUpload': access.get('role') == 'admin', 'canCancel': access.get('role') == 'admin',
            'sceneTerrainPlacement': self.geometry is not None}
        value['limits'] = {'maxUploadBytes': self.terrain_max_upload_bytes, 'maxMetadataHeaderBytes': 8192,
            'maxMetadataJsonBytes': 6144, 'maxJsonBytes': 16384, 'maxPixels': MAX_TERRAIN_PIXELS,
            'maxTriangles': MAX_TERRAIN_TRIANGLES, 'maxVersions': MAX_TERRAIN_VERSIONS,
            'maxLibraryBytes': MAX_TERRAIN_TOTAL_BYTES, 'maxPendingJobs': self.terrains.max_queue,
            'processingTimeoutSeconds': self.terrains.timeout}
        return value

    def terrain_upload(self, sid, payload, stream, length):
        row, authorize, access, actor = self.terrain_authorization(sid, payload, writing=True)
        if type(length) is not int or not 8 <= length <= self.terrain_max_upload_bytes:
            raise PreviewError(413, 'TERRAIN_LIMIT_EXCEEDED')
        metadata = {key: value for key, value in payload.items() if key != 'expectedSessionRevision'}
        # The worker retains this real-session guard in memory only. Never hold
        # the session mutex across terrain calls: the worker invokes the guard.
        value = self.terrains.upload(stream, length, metadata, actor, authorize)
        authorize()
        return self.terrain_response(value, row, access)

    def terrain_request(self, sid, path, payload):
        writing = path == '/api/workbench/terrains/job/cancel'
        row, authorize, access, actor = self.terrain_authorization(sid, payload, writing=writing)
        body = {key: value for key, value in payload.items() if key != 'expectedSessionRevision'}
        if path == '/api/workbench/terrains' and set(body).issubset({'q', 'cursor', 'limit'}):
            value = self.terrains.listing(actor, authorize, access_revision=access['accessRevision'], **body)
        elif path == '/api/workbench/terrains/job' and set(body) == {'jobId'}:
            value = self.terrains.job(body['jobId'], authorize)
        elif writing and set(body) == {'jobId', 'expectedJobRevision', 'clientRequestId'}:
            value = self.terrains.cancel(body['jobId'], body['expectedJobRevision'],
                actor, authorize, body['clientRequestId'])
        elif path == '/api/workbench/terrains/version' and set(body) == {'terrainVersionId'}:
            value = self.terrains.version(body['terrainVersionId'], authorize)
        elif path == '/api/workbench/terrains/content' and set(body) == {'terrainVersionId', 'artifactId', 'expectedSha256'}:
            fingerprint = body['expectedSha256']
            if (not isinstance(fingerprint, str) or len(fingerprint) != 64
                    or any(character not in '0123456789abcdef' for character in fingerprint)):
                raise PreviewError(422, 'INVALID_REQUEST')
            content = self.terrains.content(body['terrainVersionId'], body['artifactId'], fingerprint, authorize)
            authorize()
            return {'content': content, 'sha256': fingerprint, 'sessionRevision': row.revision}
        else:
            raise PreviewError(422, 'INVALID_REQUEST')
        authorize()
        return self.terrain_response(value, row, access)

    def imagery_response(self, value, row, access):
        from .imagery_uploads import CHUNK_BYTES, MAX_PENDING, TTL_SECONDS
        return {**value, 'sessionRevision': row.revision,
                'capabilities': {'scope':'private_overview_imagery', 'canRead':True, 'canUpload':access.get('role') == 'admin'},
                'limits': {'maxUploadBytes':MAX_IMAGERY_BYTES, 'maxSide':4096,
                           'maxVersions':MAX_IMAGERY_VERSIONS, 'maxLibraryBytes':MAX_IMAGERY_TOTAL_BYTES,
                           'maxChunkBytes':CHUNK_BYTES, 'maxPendingUploads':MAX_PENDING, 'uploadTtlSeconds':TTL_SECONDS}}

    def imagery_chunk(self, sid, payload, stream, length):
        row, authorize, access, actor = self.project_authorization(sid, payload, writing=True, write_code='IMAGERY_WRITE_FORBIDDEN')
        if self.imagery is None: raise PreviewError(503, 'PROCESSING_UNAVAILABLE')
        body = {key:value for key,value in payload.items() if key != 'expectedSessionRevision'}
        return self.imagery_response(self.imagery.uploads.chunk(stream, length, body, actor, authorize), row, access)

    def imagery_upload(self, sid, payload, stream, length):
        row, authorize, access, actor = self.project_authorization(sid, payload, writing=True, write_code='IMAGERY_WRITE_FORBIDDEN')
        if self.imagery is None: raise PreviewError(503, 'PROCESSING_UNAVAILABLE')
        value = self.imagery.upload(stream, length, {key:value for key,value in payload.items() if key != 'expectedSessionRevision'}, actor, authorize)
        return self.imagery_response(value, row, access)

    def imagery_request(self, sid, path, payload):
        writing = path in ('/api/workbench/imagery/uploads/start', '/api/workbench/imagery/uploads/complete', '/api/workbench/imagery/uploads/cancel')
        row, authorize, access, actor = self.project_authorization(sid, payload, writing=writing, write_code='IMAGERY_WRITE_FORBIDDEN')
        if self.imagery is None: raise PreviewError(503, 'PROCESSING_UNAVAILABLE')
        body = {key:value for key,value in payload.items() if key != 'expectedSessionRevision'}
        if path == '/api/workbench/imagery' and set(body) <= {'q'}:
            value = self.imagery.listing(authorize, **body)
            value['uploads'] = self.imagery.uploads.listing(actor, authorize)
        elif path == '/api/workbench/imagery/uploads/start' and set(body) == {'metadata', 'expectedSourceSha256', 'bytes'}:
            value = self.imagery.uploads.start(body['metadata'], body['expectedSourceSha256'], body['bytes'], actor, authorize)
        elif path == '/api/workbench/imagery/uploads/status' and set(body) == {'uploadId'}:
            value = self.imagery.uploads.status(body['uploadId'], actor, authorize)
        elif path in ('/api/workbench/imagery/uploads/complete', '/api/workbench/imagery/uploads/cancel') and set(body) == {'uploadId', 'expectedUploadRevision'}:
            action = self.imagery.uploads.complete if path.endswith('/complete') else self.imagery.uploads.cancel
            value = action(body['uploadId'], body['expectedUploadRevision'], actor, authorize)
        elif path == '/api/workbench/imagery/upload-result' and set(body) == {'metadata', 'expectedSourceSha256'}:
            value = self.imagery.upload_result(body['metadata'], body['expectedSourceSha256'],
                                               actor, authorize)
        elif path == '/api/workbench/imagery/version' and set(body) == {'imageryVersionId'}:
            value = self.imagery.version(body['imageryVersionId'], authorize)
        elif path == '/api/workbench/imagery/content' and set(body) == {'imageryVersionId','expectedContentRevision','expectedSha256'}:
            fingerprint = body['expectedSha256']
            if not isinstance(fingerprint,str) or len(fingerprint) != 64 or any(c not in '0123456789abcdef' for c in fingerprint):
                raise PreviewError(422, 'INVALID_REQUEST')
            content = self.imagery.content(body['imageryVersionId'], body['expectedContentRevision'], fingerprint, authorize)
            return {'content':content, 'sha256':fingerprint, 'sessionRevision':row.revision}
        else: raise PreviewError(422, 'INVALID_REQUEST')
        authorize()
        return self.imagery_response(value, row, access)

    def public_geodata_request(self, sid, path, payload):
        action = path.removeprefix('/api/workbench/public-geodata/')
        if action not in ('start', 'job', 'cancel'):
            raise PreviewError(422, 'INVALID_REQUEST')
        row, authorize, access, actor = self.project_authorization(sid, payload,
            writing=action in ('start', 'cancel'), write_code='SCENE_WRITE_FORBIDDEN')
        if self.public_geodata is None:
            raise PreviewError(503, 'PROCESSING_UNAVAILABLE')
        body = {key: value for key, value in payload.items() if key != 'expectedSessionRevision'}
        if action == 'start':
            result = self.public_geodata.start(body, actor, authorize)
        elif action == 'job' and set(body) <= {'jobId'}:
            result = self.public_geodata.job(body.get('jobId'), actor, authorize)
        elif action == 'cancel' and set(body) == {'jobId', 'expectedJobRevision'}:
            result = self.public_geodata.cancel(body['jobId'], body['expectedJobRevision'], actor, authorize)
        else:
            raise PreviewError(422, 'INVALID_REQUEST')
        authorize()
        return {**result, 'sessionRevision': row.revision, 'capabilities': {'canAcquire': access.get('role') == 'admin'}}

    def scene_request(self, sid, path, payload):
        with self.lock:
            row = self.current(sid, authenticated=True, touch=True)
            if payload.get('expectedSessionRevision') != row.revision:
                raise PreviewError(409, 'SESSION_CHANGED')
            authority = row.authority
        body = {key: value for key, value in payload.items() if key != 'expectedSessionRevision'}
        if self.scenes is None or self.library is None:
            raise PreviewError(503, 'MODEL_UNAVAILABLE')
        writing = path in ('/api/workbench/scenes/create', '/api/workbench/scenes/save',
                           '/api/workbench/scenes/delete', '/api/workbench/scenes/restore')
        try:
            baseline = self.scene_access(authority)
            current_access = baseline

            def authorize():
                nonlocal current_access
                self.guard(sid, row)
                current_access = self.scene_access(authority)
                if writing and current_access.get('role') != 'admin':
                    raise PreviewError(403, 'SCENE_WRITE_FORBIDDEN')
                if current_access['accessRevision'] != baseline['accessRevision']:
                    raise PreviewError(409, 'ACCESS_CHANGED')
                self.guard(sid, row)

            fixed_models = {}
            fixed_terrains = {}

            def validate_resources(snapshot):
                for identifier in sorted({item['modelVersionId'] for item in snapshot['instances']}):
                    try:
                        identity = self.project_models.content_identity(identifier)
                        content_identity = (identity['sha256'], identity['contentRevision'])
                        if identifier in fixed_models and fixed_models[identifier] != content_identity:
                            raise PreviewError(409, 'RESOURCE_CHANGED')
                        if identity['isProjectResource']:
                            if identity['calibrationState'] == 'legacy_display' and snapshot['coordinateFrame']['mode'] != 'local_plane':
                                raise PreviewError(409, 'MODEL_GEOGRAPHIC_CALIBRATION_REQUIRED')
                            if not identity['canPlace']:
                                raise PreviewError(409, 'MODEL_CALIBRATION_REQUIRED')
                            self.project_models.content(identifier, identity['contentRevision'], identity['sha256'], authorize)
                        else:
                            if snapshot['coordinateFrame']['mode'] != 'local_plane':
                                raise PreviewError(409, 'MODEL_CALIBRATION_REQUIRED')
                            self.project_models.library.content(self.project_models.library.version(identifier))
                        fixed_models[identifier] = content_identity
                    except PreviewError as error:
                        if error.code == 'MODEL_CHANGED':
                            raise PreviewError(409, 'RESOURCE_CHANGED') from None
                        if error.code == 'MODEL_NOT_FOUND':
                            raise PreviewError(404, 'NOT_FOUND_OR_FORBIDDEN') from None
                        raise
                terrains = []
                if snapshot['terrain'] is not None:
                    if self.terrains is None:
                        raise PreviewError(503, 'PROCESSING_UNAVAILABLE')
                    version = self.terrains.version(snapshot['terrain']['terrainVersionId'], authorize)
                    if version['contentRevision'] != snapshot['terrain']['expectedContentRevision']:
                        raise PreviewError(409, 'RESOURCE_CHANGED')
                    identity = {'terrainVersionId': version['terrainVersionId'],
                        'contentRevision': version['contentRevision'], 'sha256': version['sha256'],
                        'reportSha256': version['expectedReportSha256']}
                    if version['terrainVersionId'] in fixed_terrains and fixed_terrains[version['terrainVersionId']] != identity:
                        raise PreviewError(409, 'RESOURCE_CHANGED')
                    fixed_terrains[version['terrainVersionId']] = identity
                    terrains.append(identity)
                if snapshot.get('imagery') is not None:
                    if self.imagery is None or snapshot['terrain'] is None:
                        raise PreviewError(503, 'PROCESSING_UNAVAILABLE')
                    self.imagery.validate_scene(snapshot['imagery'], version, authorize)
                return {'terrains': terrains}

            def validate_engineering(snapshot, reviewed, changes):
                if reviewed or changes or any(item['rootBinding'] is not None or item['componentBindings']
                                               for item in snapshot['instances']):
                    raise PreviewError(422, 'SCENE_SCOPE_UNSUPPORTED')

            def geometry_result(snapshot, *, expected_frame=None, preview=False, anchor=None, candidate=None):
                if self.geometry is None:
                    raise PreviewError(503, 'PROCESSING_UNAVAILABLE')
                terrain_id = candidate if candidate is not None else snapshot['terrain']['terrainVersionId']
                terrain = self.terrains.version(terrain_id, authorize)
                manifest = {'terrainVersionId': terrain['terrainVersionId'], 'contentRevision': terrain['contentRevision'],
                    'sha256': terrain['sha256'], 'reportSha256': terrain['expectedReportSha256']}
                request = {'kind': 'anchor' if anchor is not None else 'validate',
                    'snapshot': snapshot, 'trustedTerrains': [manifest]}
                if anchor is not None:
                    request.update(candidateTerrainVersionId=candidate, anchor=anchor)
                else:
                    request.update(expectedFrame=expected_frame, resampleGround=preview)
                return self.geometry.process(request, authorize)

            def preview_geometry(snapshot, *, expected_frame=None):
                return geometry_result(snapshot, expected_frame=expected_frame, preview=True)

            def validate_geometry(snapshot, *, expected_frame=None):
                return geometry_result(snapshot, expected_frame=expected_frame)

            def preview_anchor(snapshot, candidate, anchor):
                return geometry_result(snapshot, candidate=candidate, anchor=anchor)

            def model_details(identifier):
                identity = self.project_models.content_identity(identifier)
                if not identity['isProjectResource']:
                    raise PreviewError(409, 'MODEL_CALIBRATION_REQUIRED')
                value = self.project_models.model(identity['modelAssetId'], identifier, authorize)
                expected = (identity['sha256'], identity['contentRevision'])
                if identifier in fixed_models and fixed_models[identifier] != expected:
                    raise PreviewError(409, 'RESOURCE_CHANGED')
                fixed_models[identifier] = expected
                return value

            reader = SceneEngineeringReader(authority, self.ontobase_connection_id, self.project_code,
                lambda: self.guard(sid, row))
            engineering_check = SceneEngineeringValidator(reader,
                lambda identifier: model_details(identifier)['components'],
                self.ontobase_connection_id, self.project_code)

            def terrain_replacement(snapshot, candidate, strategy):
                if self.geometry is None or self.terrains is None:
                    raise PreviewError(503, 'PROCESSING_UNAVAILABLE')
                manifests = []
                for identifier in sorted({snapshot['terrain']['terrainVersionId'], candidate}):
                    version = self.terrains.version(identifier, authorize)
                    identity = {'terrainVersionId': identifier, 'contentRevision': version['contentRevision'],
                        'sha256': version['sha256'], 'reportSha256': version['expectedReportSha256']}
                    if identifier in fixed_terrains and fixed_terrains[identifier] != identity:
                        raise PreviewError(409, 'RESOURCE_CHANGED')
                    fixed_terrains[identifier] = identity
                    manifests.append(identity)
                return self.geometry.process({'kind': 'terrain_replacement', 'snapshot': snapshot,
                    'candidateTerrainVersionId': candidate, 'strategy': strategy, 'trustedTerrains': manifests}, authorize)

            if path == '/api/workbench/scenes' and set(body).issubset({'q','cursor','limit','state'}):
                value = self.scenes.listing(authority.username, authorize,
                    access_revision=baseline['accessRevision'], **body)
            elif path == '/api/workbench/scenes/create':
                value = self.scenes.create(body, authority.username, authorize, validate_resources, validate_engineering,
                    engineering_check=engineering_check)
            elif path == '/api/workbench/scenes/open' and set(body) in ({'sceneId'}, {'sceneId','sceneRevision'}):
                value = self.scenes.open(body['sceneId'], authority.username, authorize, body.get('sceneRevision'),
                    engineering_check=engineering_check)
                fixed_models.update({item['modelVersionId']: (item['sha256'], item['contentRevision']) for item in value['resourceRefs']})
                fixed_terrains.update({item['terrainVersionId']: item for item in value.get('terrainRefs', [])})
                validate_resources(value['snapshot'])
                authorize()
            elif path == '/api/workbench/scenes/locate' and {'sceneId', 'sceneRevision', 'selectedObjectRef', 'contextEpoch'} <= set(body) <= {
                    'sceneId', 'sceneRevision', 'selectedObjectRef', 'contextEpoch', 'representationChoice'}:
                if (not isinstance(body['sceneRevision'], str) or not body['sceneRevision']
                        or 'representationChoice' in body and type(body['representationChoice']) is not dict):
                    raise PreviewError(422, 'INVALID_REQUEST')
                selected_ref = validate_ref(body['selectedObjectRef'],
                    connection_id=self.ontobase_connection_id, project_code=self.project_code)
                opened = self.scenes.open(body['sceneId'], authority.username, authorize, body['sceneRevision'],
                    engineering_check=engineering_check)
                fixed_models.update({item['modelVersionId']: (item['sha256'], item['contentRevision']) for item in opened['resourceRefs']})
                fixed_terrains.update({item['terrainVersionId']: item for item in opened.get('terrainRefs', [])})
                validate_resources(opened['snapshot'])
                selected = reader.context_for_object(selected_ref['entityUid'])
                value = SceneLocationResolver(model_details).resolve(opened, selected, body['contextEpoch'],
                    body.get('representationChoice'))
                authorize()
            elif path == '/api/workbench/scenes/head' and set(body) == {'sceneId','viewingRevision'}:
                value = self.scenes.head(body['sceneId'], body['viewingRevision'], authority.username, authorize)
            elif path == '/api/workbench/scenes/save':
                value = self.scenes.save(body, authority.username, authorize, validate_resources, validate_engineering,
                    validate_geometry=validate_geometry if self.geometry is not None else None,
                    access_revision=baseline['accessRevision'],
                    terrain_replacement=terrain_replacement, model_details=model_details, engineering_check=engineering_check)
            elif path in ('/api/workbench/scenes/delete', '/api/workbench/scenes/restore'):
                value = self.scenes.lifecycle(body, authority.username, authorize, action=path.rsplit('/', 1)[1])
            elif path == '/api/workbench/scenes/check':
                value = self.scenes.check(body, authority.username, authorize, validate_resources, validate_engineering,
                    preview_geometry if self.geometry is not None else None,
                    preview_anchor if self.geometry is not None else None,
                    access_revision=baseline['accessRevision'], engineering_check=engineering_check)
            elif path == '/api/workbench/scenes/replacement-check':
                value = self.scenes.replacement_check(body, authority.username, authorize,
                    validate_resources, validate_engineering,
                    preview_geometry if self.geometry is not None else None,
                    terrain_replacement if self.geometry is not None else None,
                    model_details, access_revision=baseline['accessRevision'], engineering_check=engineering_check)
            else:
                raise PreviewError(422, 'INVALID_REQUEST')
            self.guard(sid, row)
            value['sessionRevision'] = row.revision
            value['projectName'] = current_access.get('projectName', self.project_code)
            value['capabilities'] = {**self.scenes.capabilities(geographic=self.geometry is not None, engineering=True),
                'scope': 'project_scenes',
                'localPlaneUnbound': True, 'canRead': True, 'canWrite': current_access.get('role') == 'admin',
                'existingUploadedModelVersionsOnly': True, 'projectModelResources': True,
                'canPreflightGeographic': self.geometry is not None}
            value['limits'] = {'maxSaveJsonBytes': MAX_SCENE_BYTES, 'maxReadJsonBytes': 16384,
                'maxCheckJsonBytes': MAX_SCENE_BYTES,
                'maxInstances': MAX_INSTANCES, 'maxComponentBindings': MAX_COMPONENT_BINDINGS, 'maxNameCharacters': 200,
                'maxLocalCoordinateM': MAX_COORDINATE_M}
            return value
        except PreviewError as error:
            if error.status == 401:
                self.invalidate(sid, row)
            raise

    def writer(self, sid, payload):
        with self.lock:
            row = self.current(sid, authenticated=True, touch=True)
            if payload.get('expectedSessionRevision') != row.revision: raise PreviewError(409,'SESSION_CHANGED')
            authority = row.authority
        if self.library is None or self.model is None: raise PreviewError(503,'MODEL_UNAVAILABLE')
        self.access(authority)
        access = authority.request('GET',self.access_path)
        context = self.context(authority)
        if access.get('role')!='admin': raise PreviewError(403,'MODEL_WRITE_FORBIDDEN')
        if context.get('purpose')!='demonstration' or context.get('engineeringUseAllowed') is not False:
            raise PreviewError(409,'MODEL_SCOPE_CHANGED')
        if not self.library.legacy_writable(): raise PreviewError(409, 'LEGACY_MODEL_READ_ONLY')
        def authorize():
            self.guard(sid,row)
            current = authority.request('GET',self.access_path)
            if current.get('role')!='admin': raise PreviewError(403,'MODEL_WRITE_FORBIDDEN')
            if current.get('accessRevision')!=access['accessRevision']: raise PreviewError(409,'ACCESS_CHANGED')
            if self.context(authority)!=context: raise PreviewError(409,'REVISION_CONFLICT')
            self.guard(sid,row)
        self.guard(sid,row)
        return row,context,authorize,authority

    def upload(self, sid, payload, stream, length):
        ModelLibrary.upload_metadata(payload)
        if not 24 <= length <= MAX_BYTES: raise PreviewError(413,'MODEL_LIMIT_EXCEEDED')
        row,context,authorize,authority = self.writer(sid,payload)
        if not self.library.slots.acquire(blocking=False): raise PreviewError(429,'MODEL_BUSY')
        path = None
        try:
            with tempfile.NamedTemporaryFile(dir=self.library.root/'temporary',prefix='upload-',suffix='.glb',delete=False) as file:
                path = Path(file.name); remaining = length
                while remaining:
                    chunk = stream.read(min(65536,remaining))
                    if not chunk: raise PreviewError(422,'INVALID_MODEL')
                    file.write(chunk); remaining -= len(chunk)
            result = self.library.process(path)
            # Existing, explicitly labelled proxies apply only to this exact artifact.
            if result['sha256']==self.model.value['sha256']:
                for row_binding in self.model.value['bindings']:
                    if row_binding['geometryQuality']=='proxy_schematic':
                        result['components'].append({'componentKey':'proxy:'+row_binding['componentKey'],
                            'displayName':row_binding['componentKey'], 'nodeIndices':[], 'keyStability':'version_local',
                            'geometryQuality':'proxy_schematic', 'bounds':row_binding['bounds']})
            self.guard(sid,row)
            value = self.library.save_upload(path,payload,authority.username,result,authorize)
            if self.thumbnails is not None:
                value['thumbnail'] = self.thumbnails.automatic(value, authority.username, authorize)
            revision = self.library.listing()['libraryRevision']
            self.guard(sid,row)
            return {'item':value, 'libraryRevision':revision, 'sessionRevision':row.revision}
        finally:
            try:
                if path: path.unlink(missing_ok=True)
            except OSError:
                raise PreviewError(503, 'MODEL_STORAGE_UNAVAILABLE') from None
            finally:
                self.library.slots.release()

    def save_binding(self, sid, payload):
        row,context,authorize,authority = self.writer(sid,payload)
        body = {key:value for key,value in payload.items() if key!='expectedSessionRevision'}
        uid = body.get('entityUid')
        if not isinstance(uid,str) or uid not in {item['entityUid'] for item in self.model.value['bindings']}: raise PreviewError(422,'INVALID_CABINET')
        self.library.version(body.get('modelVersionId'), legacy_only=True)
        def verify():
            authorize()
            item = self.object(authority,uid)
            ancestors = authority.request('GET',self.context_path+'/ancestors?'+urlencode({'entityUid':uid}))
            if (body.get('expectedHierarchyRevision')!=context['hierarchyRevision']
                    or item['entityRevision']!=body.get('expectedEntityRevision') or item.get('objectKind')!='cabinet'
                    or ancestors.get('hierarchyRevision')!=context['hierarchyRevision'] or ancestors.get('completeness')!='complete'
                    or not any(p.get('object',{}).get('entityUid')==context['rootEntityUid'] for p in ancestors.get('path',[]))):
                raise PreviewError(409,'MODEL_BINDING_CHANGED')
        self.guard(sid,row)
        self.library.bind(body,authority.username,verify)
        revision = self.library.version(body['modelVersionId'])['modelRevision']
        self.guard(sid,row)
        return {'modelRevision':revision, 'sessionRevision':row.revision}

    def library_model(self, authority, context, identifier):
        if self.library is None: raise PreviewError(503,'MODEL_UNAVAILABLE')
        value = self.library.version(identifier, legacy_only=True)
        if context.get('purpose')!='demonstration' or context.get('engineeringUseAllowed') is not False: raise PreviewError(409,'MODEL_SCOPE_CHANGED')
        components = {item['componentKey']:item for item in value['components']}
        bindings,warnings = [],[]
        for record in value['bindings']:
            try:
                item = self.object(authority,record['entity_uid'])
                ancestors = authority.request('GET',self.context_path+'/ancestors?'+urlencode({'entityUid':item['entityUid']}))
                if (item['entityRevision']!=record['entity_revision'] or item.get('objectKind')!='cabinet'
                        or record['hierarchy_revision']!=context['hierarchyRevision']
                        or ancestors.get('hierarchyRevision')!=context['hierarchyRevision'] or ancestors.get('completeness')!='complete'
                        or not any(p.get('object',{}).get('entityUid')==context['rootEntityUid'] for p in ancestors.get('path',[]))):
                    raise PreviewError(409,'MODEL_BINDING_CHANGED')
                comp = components[record['component_key']]
                bindings.append({'entityUid':item['entityUid'],'entityRevision':item['entityRevision'],
                    **{key:comp[key] for key in ('componentKey','displayName','geometryQuality','bounds')}})
            except PreviewError as error:
                if error.status!=409: raise
                warnings.append({'entityUid':record['entity_uid'],'code':'MODEL_BINDING_CHANGED'})
        result = {'modelVersionId':value['versionId'],'modelRevision':value['modelRevision'],
                  'displayName':value['displayName'],'sha256':value['sha256'], 'rootEntityUid':context['rootEntityUid'],
                  'bindingStatus':'demonstration_draft','engineeringUseAllowed':False,
                  'components':value['components'],'bindings':bindings,'bindingWarnings':warnings,
                  'canEditBindings':authority.request('GET',self.access_path).get('role')=='admin' and self.library.legacy_writable()}
        result['viewRevision'] = hashlib.sha256(json.dumps([result,context['hierarchyRevision']],sort_keys=True).encode()).hexdigest()
        return result

    def context(self, authority):
        if self.context_path is None:
            raise PreviewError(404, 'LEGACY_SCENE_ENTRY_UNAVAILABLE')
        item = authority.request('GET', self.context_path)['item']
        if item.get('projectCode') != self.project_code or item.get('installationContextId') != self.context_id:
            raise PreviewError(502, 'SOURCE_UNAVAILABLE')
        return item

    def object(self, authority, uid, *, project_catalog=False):
        if not isinstance(uid, str) or not 0 < len(uid) <= 512:
            raise PreviewError(422, 'INVALID_REQUEST')
        query = {'entityUids':[uid]}
        if not project_catalog: query['installationContextId'] = self.context_id
        result = authority.request('POST', self.prefix + '/objects/resolve', query)['items'][0]
        item = result.get('object')
        if result.get('resolution') != 'exact' or not item:
            raise PreviewError(409 if item else 403, 'IDENTITY_CHANGED' if item else 'NOT_FOUND_OR_FORBIDDEN')
        if item.get('entityUid') != uid or item.get('installationContextId') not in ((None, self.context_id) if project_catalog else (self.context_id,)):
            raise PreviewError(403, 'NOT_FOUND_OR_FORBIDDEN')
        if item.get('lifecycle') != 'active':
            raise PreviewError(409, 'IDENTITY_CHANGED')
        return item

    def read(self, sid, path, payload):
        with self.lock:
            row = self.current(sid, authenticated=True, touch=True)
            authority = row.authority
            if payload.get('expectedSessionRevision') != row.revision:
                raise PreviewError(409, 'SESSION_CHANGED')
        body = {key:value for key,value in payload.items() if key != 'expectedSessionRevision'}
        try:
            access_revision = self.access(authority)
            context = None if path == '/api/workbench/catalog' else self.context(authority)
            if path == '/api/workbench/context' and not body:
                root = self.object(authority, context['rootEntityUid']) if context['rootEntityUid'] else None
                children = authority.request('GET', self.context_path + '/children?' + urlencode(
                    {'parentEntityUid':root['entityUid'], 'limit':50})) if root else None
                if children and children.get('hierarchyRevision') != context['hierarchyRevision']:
                    raise PreviewError(409, 'REVISION_CONFLICT')
                access = authority.request('GET', self.access_path)
                value = {'context':context, 'root':root, 'children':children,
                         'projectName':access.get('projectName', self.project_code)}
            elif path == '/api/workbench/catalog' and set(body).issubset({'q','cursor','scope','groupBy','categoryKey','expectedSnapshotRevision'}):
                q, cursor = body.get('q',''), body.get('cursor')
                if (not isinstance(q, str) or len(q) > 200 or cursor is not None
                        and (not isinstance(cursor, str) or not 0 < len(cursor) <= 8192)):
                    raise PreviewError(422, 'INVALID_REQUEST')
                params = {'q':q, 'limit':50}
                if body.get('scope','project') not in ('equipment','project'):
                    raise PreviewError(422, 'INVALID_REQUEST')
                if body.get('scope') == 'equipment': params['installationContextId'] = self.context_id
                if 'groupBy' in body:
                    if body['groupBy'] != 'classification': raise PreviewError(422, 'INVALID_REQUEST')
                    params['groupBy'] = body['groupBy']
                if 'categoryKey' in body:
                    if body.get('groupBy') != 'classification' or not isinstance(body['categoryKey'], str) or not 0 < len(body['categoryKey']) <= 2048:
                        raise PreviewError(422, 'INVALID_REQUEST')
                    params['categoryKey'] = body['categoryKey']
                if 'expectedSnapshotRevision' in body and (not isinstance(body['expectedSnapshotRevision'], str) or not 0 < len(body['expectedSnapshotRevision']) <= 128):
                    raise PreviewError(422, 'INVALID_REQUEST')
                if cursor: params['cursor'] = cursor
                value = authority.request('GET', self.prefix + '/objects?' + urlencode(params))
                if body.get('expectedSnapshotRevision') and value.get('snapshotRevision') != body['expectedSnapshotRevision']:
                    raise PreviewError(409, 'SNAPSHOT_EXPIRED')
            elif path == '/api/workbench/children' and set(body).issubset({'parentEntityUid','cursor','expectedHierarchyRevision'}) and 'parentEntityUid' in body:
                self.object(authority, body['parentEntityUid'])
                if body.get('expectedHierarchyRevision') != context['hierarchyRevision']:
                    raise PreviewError(409, 'REVISION_CONFLICT')
                if body.get('cursor') is not None and (not isinstance(body['cursor'], str) or len(body['cursor']) > 8192):
                    raise PreviewError(422, 'INVALID_REQUEST')
                params = {'parentEntityUid':body['parentEntityUid'], 'limit':50}
                if body.get('cursor'): params['cursor'] = body['cursor']
                value = authority.request('GET', self.context_path + '/children?' + urlencode(params))
                if value.get('hierarchyRevision') != context['hierarchyRevision']:
                    raise PreviewError(409, 'REVISION_CONFLICT')
            elif path == '/api/workbench/object' and set(body) in ({'entityUid','expectedHierarchyRevision'}, {'entityUid','expectedHierarchyRevision','scope'}):
                if body.get('scope','equipment') not in ('equipment','project'):
                    raise PreviewError(422, 'INVALID_REQUEST')
                if body['expectedHierarchyRevision'] != context['hierarchyRevision']:
                    raise PreviewError(409, 'REVISION_CONFLICT')
                item = self.object(authority, body['entityUid'], project_catalog=body.get('scope') == 'project')
                ancestors = {'path':[], 'completeness':'not_applicable'}
                if item.get('installationContextId'):
                    ancestors = authority.request('GET', self.context_path + '/ancestors?' + urlencode({'entityUid':body['entityUid']}))
                    if ancestors.get('hierarchyRevision') != context['hierarchyRevision']:
                        raise PreviewError(409, 'REVISION_CONFLICT')
                value = {'item':item, 'ancestors':ancestors}
            elif path == '/api/workbench/models' and not body:
                if self.library is None: raise PreviewError(503,'MODEL_UNAVAILABLE')
                value = self.library.listing(legacy_only=True)
                value['hasCurrentModel'] = self.model is not None
                access = authority.request('GET',self.access_path)
                value['canUpload'] = access.get('role')=='admin' and context.get('purpose')=='demonstration' and context.get('engineeringUseAllowed') is False and self.library.legacy_writable()
            elif path in ('/api/workbench/model','/api/workbench/model/content') and 'modelVersionId' in body:
                allowed = {'modelVersionId','expectedModelSha256','expectedModelRevision','expectedViewRevision'} if path.endswith('/content') else {'modelVersionId'}
                if set(body)!=allowed: raise PreviewError(422,'INVALID_REQUEST')
                metadata = self.library_model(authority,context,body['modelVersionId'])
                value = metadata
                if path.endswith('/content'):
                    if (metadata['sha256']!=body['expectedModelSha256'] or metadata['modelRevision']!=body['expectedModelRevision'] or metadata['viewRevision']!=body['expectedViewRevision']): raise PreviewError(409,'MODEL_CHANGED')
                    value = {'content':self.library.content(self.library.version(body['modelVersionId'])), 'mediaType':'model/gltf-binary'}
            elif path in ('/api/workbench/model','/api/workbench/model/content'):
                if self.model is None: raise PreviewError(503, 'MODEL_UNAVAILABLE')
                if set(body) != ({'expectedModelSha256'} if path.endswith('/content') else set()):
                    raise PreviewError(422, 'INVALID_REQUEST')
                if body and body['expectedModelSha256'] != self.model.value['sha256']:
                    raise PreviewError(409, 'MODEL_CHANGED')
                items = authority.request('POST', self.prefix + '/objects/resolve', {
                    'entityUids':[row['entityUid'] for row in self.model.value['bindings']],
                    'installationContextId':self.context_id})['items']
                value = self.model.metadata(items, context)
                if path.endswith('/content'):
                    value = {'content':self.model.content(), 'mediaType':'model/gltf-binary'}
            elif path in ('/api/workbench/evidence/resolve','/api/workbench/evidence/content'):
                allowed = {'entityUid','installationContextId','expectedEntityRevision','expectedHierarchyRevision'}
                if path.endswith('/content'): allowed |= {'evidenceRef','expectedSourceRevision','expectedContentSha256'}
                if set(body) != allowed or body['installationContextId'] not in (None, self.context_id):
                    raise PreviewError(422, 'INVALID_REQUEST')
                if body['installationContextId'] is None:
                    if body['expectedHierarchyRevision'] is not None:
                        raise PreviewError(422, 'INVALID_REQUEST')
                elif body['expectedHierarchyRevision'] != context['hierarchyRevision']:
                    raise PreviewError(409, 'REVISION_CONFLICT')
                route = self.prefix + '/object-evidence/' + path.rsplit('/',1)[1]
                value = ({'content':authority.image(route, {**body,'representation':'image'})}
                         if path.endswith('/content') else authority.request('POST', route, body))
            else:
                raise PreviewError(422, 'INVALID_REQUEST')
            self.guard(sid, row)
            if self.access(authority) != access_revision:
                raise PreviewError(409, 'ACCESS_CHANGED')
            if context is not None and self.context(authority)['hierarchyRevision'] != context['hierarchyRevision']:
                raise PreviewError(409, 'REVISION_CONFLICT')
            if path == '/api/workbench/model/content':
                if 'modelVersionId' in body:
                    if self.library_model(authority,context,body['modelVersionId'])['viewRevision']!=body['expectedViewRevision']: raise PreviewError(409,'MODEL_CHANGED')
                else:
                    items = authority.request('POST', self.prefix + '/objects/resolve', {
                        'entityUids':[item['entityUid'] for item in self.model.value['bindings']],
                        'installationContextId':self.context_id})['items']
                    self.model.metadata(items, context)
            self.guard(sid, row)
            value['sessionRevision'] = row.revision
            return value
        except PreviewError as error:
            if error.status == 401: self.invalidate(sid, row)
            raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project-code')
    parser.add_argument('--installation-context-id')
    parser.add_argument('--workspace-root', type=Path)
    parser.add_argument('--registry-backend', choices=('sqlite', 'postgres'), default='sqlite')
    parser.add_argument('--ontobase-connection-id', default='ontobase-primary')
    parser.add_argument('--source', default='http://127.0.0.1:18001')
    parser.add_argument('--origin', default='https://vis.ontobase.ai')
    parser.add_argument('--port', type=int, default=18084)
    parser.add_argument('--development', action='store_true')
    parser.add_argument('--model-root', type=Path)
    parser.add_argument('--library-root', type=Path)
    parser.add_argument('--terrain-python', type=Path)
    parser.add_argument('--terrain-max-upload-bytes', type=int, default=MAX_TERRAIN_BYTES)
    parser.add_argument('--thumbnail-renderer', type=Path)
    parser.add_argument('--thumbnail-node', type=Path)
    parser.add_argument('--thumbnail-browser', type=Path)
    args = parser.parse_args()
    if args.library_root is None:
        parser.error('--library-root is required')
    from apps.api.project_sessions import ProjectSessions
    workspace_root = args.workspace_root or args.library_root.parent / 'workbench-projects'
    try:
        with storage_lease((args.library_root, workspace_root), create=True):
            sessions = ProjectSessions(args.source, args.project_code, args.installation_context_id, model_root=args.model_root,
                workspace_root=workspace_root,
                registry_backend=args.registry_backend, registry_database_url=os.environ.get('ONTOVIS_REGISTRY_DSN'),
                analysis_store_id=os.environ.get('ONTOVIS_ANALYSIS_STORE_ID'),
                library_root=args.library_root, terrain_python=args.terrain_python, terrain_max_upload_bytes=args.terrain_max_upload_bytes,
                ontobase_connection_id=args.ontobase_connection_id, thumbnail_renderer=args.thumbnail_renderer,
                thumbnail_node=args.thumbnail_node, thumbnail_browser=args.thumbnail_browser)
            try:
                server = ThreadingHTTPServer(('127.0.0.1', args.port), handler_type(sessions, args.origin, development=args.development))
                print('ONTOVis evidence workbench ready', flush=True)
                try:
                    server.serve_forever()
                finally:
                    server.server_close()
            finally:
                sessions.close()
    except StorageInUse:
        parser.exit(2, 'STORAGE_IN_USE: this SQLite runtime permits one service process per private store.\n')
    except PreviewError as error:
        parser.exit(2, error.code + '\n')


if __name__ == '__main__': main()
