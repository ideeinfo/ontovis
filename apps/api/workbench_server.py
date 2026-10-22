#!/usr/bin/env python3
"""ONTOVis first workbench slice: one configured installation, current evidence.

No spatial-demo assets, OntoBase business writes or arbitrary proxy.
"""
from __future__ import annotations
import argparse
import hashlib
import json
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
from apps.api.model_validation import MAX_BYTES
from apps.api.scene_library import SceneLibrary, MAX_SCENE_BYTES, MAX_INSTANCES, MAX_COORDINATE_M
from apps.api.terrain_library import TerrainLibrary, MAX_VERSIONS as MAX_TERRAIN_VERSIONS, MAX_TOTAL_BYTES as MAX_TERRAIN_TOTAL_BYTES
from apps.api.terrain_validation import MAX_BYTES as MAX_TERRAIN_BYTES, MAX_PIXELS as MAX_TERRAIN_PIXELS, MAX_TRIANGLES as MAX_TERRAIN_TRIANGLES


class WorkbenchSessions(UserSessions):
    def __init__(self, base_url, project_code, installation_context_id, *, model_root=None, library_root=None, terrain_python=None, **kwargs):
        super().__init__(base_url, project_code, **kwargs)
        self.context_id = str(UUID(installation_context_id))
        self.prefix = '/api/v1/projects/' + quote(project_code, safe='')
        self.context_path = self.prefix + '/installations/' + self.context_id
        self.model = ModelAsset(Path(model_root), project_code, self.context_id) if model_root else None
        self.library = ModelLibrary(Path(library_root),project_code,self.context_id) if library_root else None
        self.scenes = SceneLibrary(self.library) if self.library else None
        self.terrains = TerrainLibrary(self.library, python_executable=terrain_python) if self.library and terrain_python else None

    def scene_access(self, authority):
        """Read project permission without requiring the legacy default installation."""
        access = authority.request('GET', self.access_path)
        if (access.get('projectCode') != self.project_code
                or not {'objects.read','objects.resolve','installations.read','hierarchy.read'}.issubset(access.get('capabilities', []))
                or not isinstance(access.get('accessRevision'), str) or not access['accessRevision']):
            raise PreviewError(403, 'FORBIDDEN')
        return access

    def terrain_authorization(self, sid, payload, *, writing):
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
                        raise PreviewError(403, 'SCENE_WRITE_FORBIDDEN')
                    if access['accessRevision'] != baseline['accessRevision']:
                        raise PreviewError(409, 'ACCESS_CHANGED')
                    self.guard(sid, row)
                except PreviewError as error:
                    if error.status == 401:
                        self.invalidate(sid, row)
                    raise

            authorize()
            if self.terrains is None:
                raise PreviewError(503, 'PROCESSING_UNAVAILABLE')
            return row, authorize, baseline, authority.username
        except PreviewError as error:
            if error.status == 401:
                self.invalidate(sid, row)
            raise

    def terrain_response(self, value, row, access):
        value['sessionRevision'] = row.revision
        value['capabilities'] = {'scope': 'private_geotiff_processing', 'canRead': True,
            'canUpload': access.get('role') == 'admin', 'canCancel': access.get('role') == 'admin',
            'sceneTerrainPlacement': False}
        value['limits'] = {'maxUploadBytes': MAX_TERRAIN_BYTES, 'maxMetadataHeaderBytes': 8192,
            'maxMetadataJsonBytes': 6144, 'maxJsonBytes': 16384, 'maxPixels': MAX_TERRAIN_PIXELS,
            'maxTriangles': MAX_TERRAIN_TRIANGLES, 'maxVersions': MAX_TERRAIN_VERSIONS,
            'maxLibraryBytes': MAX_TERRAIN_TOTAL_BYTES, 'maxPendingJobs': self.terrains.max_queue,
            'processingTimeoutSeconds': self.terrains.timeout}
        return value

    def terrain_upload(self, sid, payload, stream, length):
        row, authorize, access, actor = self.terrain_authorization(sid, payload, writing=True)
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
        if path == '/api/workbench/terrains/job' and set(body) == {'jobId'}:
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

    def scene_request(self, sid, path, payload):
        with self.lock:
            row = self.current(sid, authenticated=True, touch=True)
            if payload.get('expectedSessionRevision') != row.revision:
                raise PreviewError(409, 'SESSION_CHANGED')
            authority = row.authority
        body = {key: value for key, value in payload.items() if key != 'expectedSessionRevision'}
        if self.scenes is None or self.library is None:
            raise PreviewError(503, 'MODEL_UNAVAILABLE')
        writing = path in ('/api/workbench/scenes/create', '/api/workbench/scenes/save')
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

            fixed_shas = {}

            def validate_resources(snapshot):
                for identifier in sorted({item['modelVersionId'] for item in snapshot['instances']}):
                    try:
                        version = self.library.version(identifier)
                        if identifier in fixed_shas and fixed_shas[identifier] != version['sha256']:
                            raise PreviewError(409, 'RESOURCE_CHANGED')
                        self.library.content(version)
                        fixed_shas[identifier] = version['sha256']
                    except PreviewError as error:
                        if error.code == 'MODEL_CHANGED':
                            raise PreviewError(409, 'RESOURCE_CHANGED') from None
                        if error.code == 'MODEL_NOT_FOUND':
                            raise PreviewError(404, 'NOT_FOUND_OR_FORBIDDEN') from None
                        raise

            def validate_engineering(snapshot, reviewed, changes):
                if reviewed or changes or any(item['rootBinding'] is not None or item['componentBindings']
                                               for item in snapshot['instances']):
                    raise PreviewError(422, 'SCENE_SCOPE_UNSUPPORTED')

            if path == '/api/workbench/scenes' and set(body).issubset({'q','cursor','limit'}):
                value = self.scenes.listing(authority.username, authorize,
                    access_revision=baseline['accessRevision'], **body)
            elif path == '/api/workbench/scenes/create':
                value = self.scenes.create(body, authority.username, authorize, validate_resources, validate_engineering)
            elif path == '/api/workbench/scenes/open' and set(body) in ({'sceneId'}, {'sceneId','sceneRevision'}):
                value = self.scenes.open(body['sceneId'], authority.username, authorize, body.get('sceneRevision'))
                fixed_shas.update({item['modelVersionId']: item['sha256'] for item in value['resourceRefs']})
                validate_resources(value['snapshot'])
                authorize()
            elif path == '/api/workbench/scenes/head' and set(body) == {'sceneId','viewingRevision'}:
                value = self.scenes.head(body['sceneId'], body['viewingRevision'], authority.username, authorize)
            elif path == '/api/workbench/scenes/save':
                value = self.scenes.save(body, authority.username, authorize, validate_resources, validate_engineering)
            else:
                raise PreviewError(422, 'INVALID_REQUEST')
            self.guard(sid, row)
            value['sessionRevision'] = row.revision
            value['capabilities'] = {**self.scenes.capabilities(), 'scope': 'local_plane_unbound',
                'localPlaneUnbound': True, 'canRead': True, 'canWrite': current_access.get('role') == 'admin',
                'existingUploadedModelVersionsOnly': True}
            value['limits'] = {'maxSaveJsonBytes': MAX_SCENE_BYTES, 'maxReadJsonBytes': 16384,
                'maxInstances': MAX_INSTANCES, 'maxComponentBindings': 0, 'maxNameCharacters': 200,
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
            revision = self.library.listing()['libraryRevision']
            self.guard(sid,row)
            return {'item':value, 'libraryRevision':revision, 'sessionRevision':row.revision}
        finally:
            if path: path.unlink(missing_ok=True)
            self.library.slots.release()

    def save_binding(self, sid, payload):
        row,context,authorize,authority = self.writer(sid,payload)
        body = {key:value for key,value in payload.items() if key!='expectedSessionRevision'}
        uid = body.get('entityUid')
        if not isinstance(uid,str) or uid not in {item['entityUid'] for item in self.model.value['bindings']}: raise PreviewError(422,'INVALID_CABINET')
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
        value = self.library.version(identifier)
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
                  'canEditBindings':authority.request('GET',self.access_path).get('role')=='admin'}
        result['viewRevision'] = hashlib.sha256(json.dumps([result,context['hierarchyRevision']],sort_keys=True).encode()).hexdigest()
        return result

    def context(self, authority):
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
                value = self.library.listing()
                value['hasCurrentModel'] = self.model is not None
                access = authority.request('GET',self.access_path)
                value['canUpload'] = access.get('role')=='admin' and context.get('purpose')=='demonstration' and context.get('engineeringUseAllowed') is False
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
    parser.add_argument('--project-code', required=True)
    parser.add_argument('--installation-context-id', required=True)
    parser.add_argument('--source', default='http://127.0.0.1:18001')
    parser.add_argument('--origin', default='https://vis.ontobase.ai')
    parser.add_argument('--port', type=int, default=18084)
    parser.add_argument('--development', action='store_true')
    parser.add_argument('--model-root', type=Path)
    parser.add_argument('--library-root', type=Path)
    parser.add_argument('--terrain-python', type=Path)
    args = parser.parse_args()
    sessions = WorkbenchSessions(args.source, args.project_code, args.installation_context_id, model_root=args.model_root, library_root=args.library_root, terrain_python=args.terrain_python)
    server = ThreadingHTTPServer(('127.0.0.1', args.port), handler_type(sessions, args.origin, development=args.development))
    print('ONTOVis evidence workbench ready', flush=True)
    try:
        server.serve_forever()
    finally:
        server.server_close()
        if sessions.terrains:
            sessions.terrains.close()


if __name__ == '__main__': main()
