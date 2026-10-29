"""Explicit project dispatch over the existing per-user and per-project services."""
from __future__ import annotations

import hashlib
import hmac
import json
from pathlib import Path
import secrets
from threading import BoundedSemaphore, Lock
from urllib.parse import quote

from .authority import PreviewError
from .project_workspaces import ProjectWorkspaces, text
from .user_sessions import UserSessions
from .workbench_server import WorkbenchSessions
from .scene_library import SceneLibrary, MAX_SCENE_BYTES, MAX_INSTANCES, MAX_COMPONENT_BINDINGS, MAX_COORDINATE_M
from .project_model_library import ProjectModelLibrary
from .shared_models import SharedModelAccess
from .work_orders import WorkOrders, require as order_require
from .demo_faults import DEMO_PROJECT
from .scene_engineering import SceneEngineeringReader
from .scene_photos import ScenePhotoReader
from .simulation_stream import SimulationStreams


METHODS = ('scene_request', 'scene_object_request', 'equipment_request', 'resource_request', 'resource_upload',
           'terrain_request', 'terrain_upload', 'imagery_request', 'imagery_upload', 'imagery_chunk',
           'public_geodata_request', 'legacy_migration_request', 'read', 'upload', 'save_binding')


class ProjectSessions(UserSessions):
    def __init__(self, base_url, project_code=None, installation_context_id=None, *, library_root,
                 workspace_root=None, model_root=None, ontobase_connection_id='ontobase-primary',
                 registry_backend='sqlite', registry_database_url=None, analysis_store_id=None, **kwargs):
        if analysis_store_id is not None and registry_backend != 'postgres':
            raise PreviewError(409, 'ANALYSIS_POSTGRES_REQUIRED')
        identity_options = {key: kwargs.pop(key) for key in ('clock', 'factory') if key in kwargs}
        super().__init__(base_url, project_code or '', **identity_options)
        self.connection_id = text(ontobase_connection_id)
        self.options = kwargs
        self.model_root = model_root
        registry_type = ProjectWorkspaces
        registry_options = {}
        if registry_backend == 'postgres':
            from .postgres_project_workspaces import PostgresProjectWorkspaces
            registry_type = PostgresProjectWorkspaces
            registry_options['database_url'] = registry_database_url
            registry_options['model_root'] = model_root
        elif registry_backend != 'sqlite':
            raise ValueError('REGISTRY_BACKEND_UNSUPPORTED')
        self.registry = registry_type(workspace_root or Path(library_root).parent / 'workbench-projects',
            self.connection_id, legacy_root=library_root, legacy_project=project_code,
            legacy_context=installation_context_id, **registry_options)
        self.services = {}
        self.readers = {}
        self.analysis_store_id, self.analysis_database_url = analysis_store_id, registry_database_url
        # Leave room for the registry and a side-by-side acceptance service in
        # the dedicated account's connection budget. No cross-user grant cache.
        self.analysis_slots = BoundedSemaphore(2)
        self.simulation_streams = SimulationStreams()
        try:
            if registry_backend == 'postgres':
                from .analysis_drafts import SCHEMA, identifier, profile, require
                with self.registry.connection.transaction(readonly=True) as cursor:
                    cursor.execute('select to_regnamespace(%s)', (SCHEMA,))
                    exists = cursor.fetchone()[0] is not None
                    require(exists == (analysis_store_id is not None), 'ANALYSIS_CONFIGURATION_REQUIRED', 409)
                    if exists:
                        identifier(analysis_store_id); profile(cursor)
                        cursor.execute(f'select store_id::text,connection_id from {SCHEMA}.store_meta where id=1')
                        require(cursor.fetchone() == (analysis_store_id, self.connection_id), 'ANALYSIS_STORE_SCOPE_MISMATCH', 409)
            self._initialize_services(project_code, installation_context_id, library_root, model_root)
        except BaseException:
            self.close()
            raise

    def _initialize_services(self, project_code, installation_context_id, library_root, model_root):
        self.cursor_key = secrets.token_bytes(32)
        self.upload_slots, self.geometry_slots = BoundedSemaphore(1), BoundedSemaphore(1)
        self.terrain_slots, self.thumbnail_slots, self.fetch_slots = BoundedSemaphore(1), BoundedSemaphore(1), BoundedSemaphore(1)
        self.imagery_lock=Lock()
        # Keep existing model IDs/files in place. The configured library is now
        # the connection-wide resource store, not a project chosen by a request.
        self.shared = WorkbenchSessions(self.base_url, project_code or '__shared_models__', installation_context_id,
            library_root=library_root, model_root=model_root, ontobase_connection_id=self.connection_id, **self.options)
        self._delegate(self.shared)
        with self.shared.library.connect() as db:
            db.execute('''create table if not exists shared_model_scope (
                id integer primary key check(id=1), connection_id text not null, scope_version integer not null)''')
            db.execute('insert or ignore into shared_model_scope values(1,?,1)', (self.connection_id,))
            if tuple(db.execute('select connection_id,scope_version from shared_model_scope where id=1').fetchone()) != (self.connection_id, 1):
                raise ValueError('Shared models belong to a different source connection')
        self.shared_access = SharedModelAccess(self)
        self.registry.ensure_shared_model_store()
        self.shared.model_authorization = self.shared_access.authorize
        self.shared.model_scope = 'shared_static_glb_resources'
        self.shared.scenes.use_shared_models(lambda identifier, db=None: self.shared.project_models.content_identity(identifier), self.connection_id,
                        model_lock=self.shared.project_models.lifecycle_lock)
        if project_code and self.registry.lookup(project_code):
            self._workspace(self.registry.lookup(project_code))

    def access(self, authority):
        # Login/inspect already validate /auth/me. Project access is checked per request.
        return 'authenticated_identity'

    def _session(self, sid, payload):
        row = self.current(sid, authenticated=True, touch=True)
        if payload.get('expectedSessionRevision') != row.revision:
            raise PreviewError(409, 'SESSION_CHANGED')
        return row

    def _ref(self, value):
        if value is None:
            raise PreviewError(422, 'PROJECT_REQUIRED')
        if type(value) is not dict or set(value) != {'ontobaseConnectionId', 'projectCode'}:
            raise PreviewError(422, 'INVALID_REQUEST')
        if text(value['ontobaseConnectionId']) != self.connection_id:
            raise PreviewError(404, 'PROJECT_SCOPE_MISMATCH')
        return text(value['projectCode'])

    def _access(self, sid, row, code):
        try:
            value = row.authority.request('GET', '/api/v1/projects/' + quote(code, safe='') + '/access')
            if (value.get('projectCode') != code or not isinstance(value.get('accessRevision'), str)
                    or not value['accessRevision'] or not {'objects.read', 'objects.resolve',
                    'installations.read', 'hierarchy.read'}.issubset(value.get('capabilities', []))):
                raise PreviewError(403, 'FORBIDDEN')
            self.guard(sid, row)
            return value
        except PreviewError as error:
            if error.status == 401:
                self.invalidate(sid, row)
            raise

    def projects_request(self, sid, path, payload):
        row = self._session(sid, payload)
        body = {k: v for k, v in payload.items() if k != 'expectedSessionRevision'}
        if path.endswith('/projects/access') and set(body) == {'projectRef'}:
            code = self._ref(body['projectRef'])
            value = self._access(sid, row, code)
            return {**value, **self.registry.summary(code), 'projectRef': body['projectRef'], 'sessionRevision': row.revision}
        if path != '/api/workbench/projects' or not set(body) <= {'q', 'cursor', 'limit'}:
            raise PreviewError(422, 'INVALID_REQUEST')
        query, limit = body.get('q', ''), body.get('limit', 50)
        if not isinstance(query, str) or len(query) > 200 or type(limit) is not int or not 1 <= limit <= 100:
            raise PreviewError(422, 'INVALID_REQUEST')
        try:
            source = row.authority.request('GET', '/api/v1/projects')
            if type(source.get('items')) is not list:
                raise PreviewError(502, 'SOURCE_UNAVAILABLE')
            items, codes = [], set()
            for item in source['items']:
                code = text(item['project_code'])
                name = text(item['project_name'])
                if code in codes or item.get('status') != 'active':
                    raise PreviewError(502, 'SOURCE_UNAVAILABLE')
                codes.add(code)
                if query.strip().casefold() not in (name + ' ' + code).casefold():
                    continue
                items.append({'projectRef': {'ontobaseConnectionId': self.connection_id, 'projectCode': code},
                    'displayName': name, 'sourceDescription': item.get('description') or '', 'status': 'active',
                    **self.registry.summary(code)})
            items.sort(key=lambda item: (item['displayName'], item['projectRef']['projectCode']))
            revision = hashlib.sha256(json.dumps([row.authority.username, row.revision, query, limit, items],
                sort_keys=True, ensure_ascii=False).encode()).hexdigest()
            start = 0
            cursor = body.get('cursor')
            if cursor is not None:
                if not isinstance(cursor, str):
                    raise PreviewError(422, 'INVALID_REQUEST')
                try:
                    start_text, prior_revision, signature = cursor.split('.')
                    unsigned = start_text + '.' + prior_revision
                    if not hmac.compare_digest(signature, hmac.new(self.cursor_key, unsigned.encode(), 'sha256').hexdigest()):
                        raise ValueError()
                    start = int(start_text)
                    if start < 0 or prior_revision != revision:
                        raise PreviewError(409, 'SNAPSHOT_EXPIRED')
                except (ValueError, TypeError):
                    raise PreviewError(422, 'INVALID_REQUEST') from None
            following = None
            if start + limit < len(items):
                unsigned = str(start + limit) + '.' + revision
                following = unsigned + '.' + hmac.new(self.cursor_key, unsigned.encode(), 'sha256').hexdigest()
            self.guard(sid, row)
            return {'items': items[start:start + limit], 'nextCursor': following, 'snapshotRevision': revision,
                    'ontobaseConnectionId': self.connection_id, 'sessionRevision': row.revision}
        except PreviewError as error:
            if error.status == 401:
                self.invalidate(sid, row)
            raise
        except (KeyError, TypeError, ValueError):
            raise PreviewError(502, 'SOURCE_UNAVAILABLE') from None

    def _workspace(self, workspace):
        with self.registry.lock:
            key = workspace['workspace_id']
            if workspace['state'] == 'blocked':
                raise PreviewError(409, 'WORKSPACE_SCOPE_INVALID')
            if key in self.services:
                return self.services[key]
            try:
                self.registry.validate_existing(workspace)
            except PreviewError:
                self.registry.mark(workspace, 'blocked', 'scope_mismatch')
                raise
            service = self.shared if self.registry.path(workspace) == self.shared.library.root else WorkbenchSessions(
                self.base_url, workspace['project_code'], workspace['legacy_context_id'],
                library_root=self.registry.path(workspace), ontobase_connection_id=self.connection_id, **self.options)
            try:
                self.registry.bind(workspace, service.library)
                if service is not self.shared:
                    with service.library.connect() as db:
                        if db.execute('select 1 from versions limit 1').fetchone():
                            raise PreviewError(409, 'SHARED_MODEL_MIGRATION_REQUIRED')
                    service.project_models = self.shared.project_models
                    service.scenes.use_shared_models(
                        lambda identifier, db=None: self.shared.project_models.content_identity(identifier), self.connection_id,
                        model_lock=self.shared.project_models.lifecycle_lock)
            except PreviewError:
                self.registry.mark(workspace, 'blocked', 'scope_mismatch')
                self._close(service)
                raise
            self._delegate(service)
            self.services[key] = service
            return service

    def _delegate(self, service):
        service.lock = self.lock
        service.current, service.guard, service.invalidate = self.current, self.guard, self.invalidate
        service.library.slots = self.upload_slots
        if service.geometry: service.geometry.slots = self.geometry_slots
        if service.terrains: service.terrains.process_budget = self.terrain_slots
        if service.thumbnails: service.thumbnails.renderer.process_budget = self.thumbnail_slots
        if service.public_geodata: service.public_geodata.fetch_budget = self.fetch_slots
        if service.imagery: service.imagery.lock = self.imagery_lock

    def _empty(self, path, row, access, payload):
        body = {k: v for k, v in payload.items() if k != 'expectedSessionRevision'}
        allowed = {'/api/workbench/scenes': {'q', 'cursor', 'limit', 'state'},
            '/api/workbench/resources/models': {'q', 'purpose', 'cursor', 'limit', 'expectedLibraryRevision'},
            '/api/workbench/resources/models/legacy': set(), '/api/workbench/terrains': {'q', 'cursor', 'limit'},
            '/api/workbench/imagery': {'q'}, '/api/workbench/scenes/legacy-migration/entry': {'sourceKind', 'sourceKey'}}
        if path in allowed:
            if (not set(body) <= allowed[path] or not isinstance(body.get('q', ''), str)
                    or len(body.get('q', '')) > 200 or type(body.get('limit', 50)) is not int
                    or not 1 <= body.get('limit', 50) <= 100):
                raise PreviewError(422, 'INVALID_REQUEST')
            if body.get('cursor') is not None:
                raise PreviewError(409, 'SNAPSHOT_EXPIRED')
        can_write = access.get('role') == 'admin'
        if path == '/api/workbench/scenes':
            if payload.get('state', 'active') not in ('active', 'deleted'):
                raise PreviewError(422, 'INVALID_REQUEST')
            return {'items': [], 'nextCursor': None, 'snapshotRevision': 'scenes:empty',
                'capabilities': {**SceneLibrary.capabilities(geographic=bool(self.options.get('terrain_python')), engineering=True),
                    'scope': 'project_scenes', 'canRead': True, 'canWrite': can_write, 'sceneInfoWriteVersion': 1,
                    'sceneLifecycleWriteVersion': 1},
                'limits': {'maxInstances': MAX_INSTANCES, 'maxComponentBindings': MAX_COMPONENT_BINDINGS,
                    'maxSaveJsonBytes': MAX_SCENE_BYTES, 'maxCheckJsonBytes': MAX_SCENE_BYTES,
                    'maxReadJsonBytes': 16384, 'maxNameCharacters': 200, 'maxLocalCoordinateM': MAX_COORDINATE_M}}
        if path in ('/api/workbench/resources/models', '/api/workbench/resources/models/legacy'):
            limits = ProjectModelLibrary.capabilities()
            return {'items': [], 'libraryRevision': 'library:0', 'nextCursor': None,
                    'capabilities': {'canRead': True, 'canUpload': can_write, 'canCalibrate': can_write},
                    'limits': limits}
        if path == '/api/workbench/imagery':
            from .imagery_library import MAX_BYTES, MAX_VERSIONS, MAX_TOTAL_BYTES
            from .imagery_uploads import CHUNK_BYTES, MAX_PENDING, TTL_SECONDS
            return {'items': [], 'uploads': [], 'capabilities': {'scope': 'private_overview_imagery', 'canRead': True, 'canUpload': can_write},
                'limits': {'maxUploadBytes': MAX_BYTES, 'maxSide': 4096, 'maxVersions': MAX_VERSIONS,
                           'maxLibraryBytes': MAX_TOTAL_BYTES, 'maxChunkBytes': CHUNK_BYTES,
                           'maxPendingUploads': MAX_PENDING, 'uploadTtlSeconds': TTL_SECONDS}}
        if path == '/api/workbench/terrains':
            return {'items': [], 'nextCursor': None, 'snapshotRevision': 'resources:empty',
                'capabilities': {'canRead': True, 'canUpload': can_write},
                'limits': {'maxUploadBytes': self.options.get('terrain_max_upload_bytes', 100000000)}}
        if path.endswith('/legacy-migration/entry'):
            return {'available': False, 'entry': None}
        raise PreviewError(404, 'NOT_FOUND_OR_FORBIDDEN')

    def _call(self, method, sid, path, payload, *args):
        if path.startswith('/api/demo/'):
            raise PreviewError(410, 'DEMO_REMOVED')
        row = self._session(sid, payload)
        if method in ('resource_request', 'resource_upload') and (path != '/api/workbench/resources/uses' or 'projectRef' not in payload):
            clean = {k: v for k, v in payload.items() if k != 'projectRef'}
            if 'projectRef' in payload:
                self._ref(payload['projectRef'])
            if path == '/api/workbench/resources/uses':
                return self.shared_access.uses(sid, clean)
            return (self.shared.resource_request(sid, path, clean) if method == 'resource_request'
                    else self.shared.resource_upload(sid, clean, *args))
        code = self._ref(payload.get('projectRef'))
        if method == 'scene_object_request' and path in (
                '/api/workbench/objects/photos/resolve', '/api/workbench/objects/photos/content'):
            body = {k: v for k, v in payload.items() if k not in ('projectRef', 'expectedSessionRevision')}
            # OntoBase checks the current project grant and fixed association
            # inside this one protected read, including its final recheck.
            reader = ScenePhotoReader(SceneEngineeringReader(row.authority, self.connection_id, code,
                lambda: self.guard(sid, row)))
            try:
                value = reader.content(body) if path.endswith('/content') else reader.resolve(body)
                self.guard(sid, row)
                return {**value, 'sessionRevision': row.revision,
                        'projectRef': {'ontobaseConnectionId': self.connection_id, 'projectCode': code}}
            except PreviewError as error:
                if error.status == 401: self.invalidate(sid, row)
                raise
        access = self._access(sid, row, code)
        clean = {k: v for k, v in payload.items() if k != 'projectRef'}
        writing = method.endswith('upload') or method == 'imagery_chunk' or path == '/api/workbench/imagery/uploads/complete' or path.endswith(('/create', '/save', '/calibrate', '/import-existing',
            '/preserve-legacy-display', '/ensure', '/binding', '/cancel', '/start', '/activate', '/delete', '/restore', '/assign', '/associate'))
        if writing and access.get('role') != 'admin':
            raise PreviewError(403, 'SCENE_WRITE_FORBIDDEN' if '/scenes' in path or '/terrains' in path or '/public-geodata/' in path
                               else 'IMAGERY_WRITE_FORBIDDEN' if '/imagery' in path else 'MODEL_WRITE_FORBIDDEN')
        workspace = self.registry.lookup(code)
        if workspace is None and writing and path not in ('/api/workbench/imagery/uploads/chunk',
                '/api/workbench/imagery/uploads/complete', '/api/workbench/imagery/uploads/cancel',
                '/api/workbench/scenes/delete', '/api/workbench/scenes/restore'):
            workspace = self.registry.prepare(code)
        if method == 'scene_object_request' or path == '/api/workbench/catalog' or method=='equipment_request' and workspace is None:
            if code not in self.readers:
                service = WorkbenchSessions(self.base_url, code, None, ontobase_connection_id=self.connection_id)
                service.lock = self.lock
                service.current, service.guard, service.invalidate = self.current, self.guard, self.invalidate
                self.readers[code] = service
            if 'sceneId' in clean:
                if workspace is None:
                    raise PreviewError(404, 'NOT_FOUND_OR_FORBIDDEN')
                with self._workspace(workspace).library.connect() as db:
                    self._workspace(workspace).scenes._scope(db, clean.pop('sceneId'))
            value = getattr(self.readers[code], method)(sid, path, clean)
        elif workspace is None:
            value = self._empty(path, row, access, clean)
        else:
            service = self._workspace(workspace)
            value = getattr(service, method)(sid, path, clean, *args) if method.endswith('request') or method == 'read' else getattr(service, method)(sid, clean, *args)
        if self._access(sid, row, code)['accessRevision'] != access['accessRevision']:
            raise PreviewError(409, 'ACCESS_CHANGED')
        if workspace and value.get('sceneId'):
            with self._workspace(workspace).library.connect() as db:
                first = db.execute('select saved_at from scene_revisions where scene_id=? order by saved_at,revision limit 1',
                                   (value['sceneId'],)).fetchone()
                if first:
                    value['createdAt'] = first[0]
        return {**value, 'projectRef': {'ontobaseConnectionId': self.connection_id, 'projectCode': code},
                'workspaceId': workspace['workspace_id'] if workspace else None,
                'projectName': access.get('projectName', code), 'sessionRevision': row.revision}

    @staticmethod
    def _close(service):
        for name in ('public_geodata', 'terrains', 'thumbnails'):
            item = getattr(service, name, None)
            if item:
                item.close()

    def close(self):
        self.simulation_streams.close()
        try:
            for service in {getattr(self, 'shared', None), *self.services.values(), *self.readers.values()}:
                if service is not None:
                    self._close(service)
        finally:
            self.registry.close()

    def _demo_order_targets(self, reader):
        model = self.shared.model.value if self.shared.model else None
        order_require(model and model.get('projectCode') == DEMO_PROJECT, 'DEMO_TARGETS_UNAVAILABLE', 409)
        bindings = {item['componentKey']: item for item in model['bindings'] if item['componentKey'] in ('CN', 'CN1')}
        order_require(set(bindings) == {'CN', 'CN1'}, 'DEMO_TARGETS_UNAVAILABLE', 409)
        targets = {}
        for key, binding in bindings.items():
            value = reader.context_for_object(binding['entityUid'], binding['entityRevision'])
            order_require(value['context'] and value['context']['purpose'] == 'demonstration'
                and value['context']['engineeringUseAllowed'] is False
                and value['context']['installationContextId'] == model['installationContextId'],
                'DEMO_TARGETS_UNAVAILABLE', 409)
            targets[key] = {'entityUid': value['item']['entityUid'], 'entityRevision': value['item']['entityRevision'],
                            'installationContextId': value['context']['installationContextId'],
                            'hierarchyRevision': value['context']['hierarchyRevision']}
        return targets

    def simulation_stream(self, sid, payload):
        from .analysis_drafts import require
        row = self.current(sid, authenticated=True)
        require(payload.get('expectedSessionRevision') == row.revision, 'SESSION_CHANGED', 409)
        code = self._ref(payload.get('projectRef'))
        body = {key: value for key, value in payload.items() if key not in ('expectedSessionRevision', 'projectRef')}
        access = self._access(sid, row, code)

        def authorize():
            current = self._access(sid, row, code)
            require(current['accessRevision'] == access['accessRevision'], 'ACCESS_CHANGED', 409)

        return self.simulation_streams.subscribe(sid, code, body, row.revision,
                                                 lambda: self.guard(sid, row), authorize)

    def analysis_request(self, sid, path, payload):
        from .analysis_drafts import AnalysisDrafts, identifier, require, validate_snapshot
        row = self._session(sid, payload)
        code = self._ref(payload.get('projectRef'))
        action = path.removeprefix('/api/workbench/analysis-sessions').removeprefix('/')
        require(action in ('', 'create', 'detail', 'save', 'restore', 'revisions', 'trash', 'untrash', 'evidence/register',
                          'evidence/detail', 'evidence/content', 'evidence/batch', 'evidence/preview', 'evidence/relationships', 'evidence/preview-content', 'start', 'copy', 'recommendations', 'history-candidates', 'import-history', 'evidence/register-batch',
                          'link-work-order', 'simulation/catalogue', 'simulation/detail', 'simulation/qualify'))
        body = {key: value for key, value in payload.items() if key not in ('expectedSessionRevision', 'projectRef')}
        if action in ('simulation/catalogue', 'simulation/detail'):
            # These fixed, project-scoped reads have no analysis owner or storage.
            # /access checks the current active user and membership on every read.
            self._access(sid, row, code)
            from . import simulated_faults
            value = (simulated_faults.browser_catalogue(code, body) if action == 'simulation/catalogue'
                     else simulated_faults.detail(code, body))
            self.guard(sid, row)
            return {**value, 'projectRef': payload['projectRef'], 'sessionRevision': row.revision,
                    'capabilities': {'canWrite': False, 'canConfirmConclusion': False}}
        require(self.analysis_store_id is not None, 'ANALYSIS_NOT_ENABLED', 503)
        require(row.subject_id is not None, 'ANALYSIS_IDENTITY_REQUIRED', 401)
        actor = identifier(row.subject_id)
        writing = action in ('create', 'save', 'restore', 'trash', 'untrash', 'evidence/register', 'start', 'copy', 'import-history', 'evidence/register-batch', 'link-work-order')
        access = self._access(sid, row, code)
        if writing:
            require(access.get('role') == 'admin', 'ANALYSIS_WRITE_FORBIDDEN', 403)

        def authorize():
            self.guard(sid, row)
            try:
                me = row.authority.request('GET', '/api/v1/auth/me').get('user', {})
                require(me.get('id') == actor and me.get('is_active') is True
                        and me.get('username') == row.authority.username, 'SESSION_EXPIRED', 401)
                current = self._access(sid, row, code)
                require(current['accessRevision'] == access['accessRevision']
                        and (not writing or current.get('role') == 'admin'), 'ACCESS_CHANGED', 409)
                self.guard(sid, row)
            except PreviewError as error:
                if error.status == 401: self.invalidate(sid, row)
                raise

        if action in ('create','start'):
            if action == 'create':
                require(set(body) == {'requestId', 'snapshot'})
                identifier(body['requestId']); validate_snapshot(body['snapshot'], self.connection_id, code)
            authorize()
            workspace = self.registry.lookup(code)
            if workspace is None: workspace = self.registry.prepare(code)
            self._workspace(workspace)
        require(self.analysis_slots.acquire(timeout=5),'ANALYSIS_BUSY',503)
        store, held = None, True
        def release_store():
            nonlocal held
            if held:
                if store is not None:store.close()
                held=False;self.analysis_slots.release()
        try:
            store = AnalysisDrafts(self.analysis_database_url, self.connection_id, code)
            require(store.store_id == self.analysis_store_id, 'ANALYSIS_STORE_SCOPE_MISMATCH', 409)
            if action.startswith(('evidence/', 'simulation/')) or action in ('link-work-order','start','recommendations','history-candidates','import-history'):
                from .analysis_evidence import AnalysisEvidence
                from .analysis_source_reader import AnalysisSourceReader
                from . import simulated_faults
                workspace = self.registry.lookup(code)
                require(workspace is not None, 'NOT_FOUND_OR_FORBIDDEN', 404)
                service = self._workspace(workspace)
                if not hasattr(service, 'work_orders'):
                    with self.registry.lock:
                        if not hasattr(service, 'work_orders'):
                            service.work_orders = WorkOrders(service.library, code)
                sources = AnalysisEvidence(store)
                # The request is bracketed by live access checks. Each OntoBase
                # source also enforces membership; inner operations only need the
                # local session guard, not another remote grant per card/node.
                if writing:authorize()
                else:self.guard(sid,row)
                guard = lambda: self.guard(sid, row)
                reader = AnalysisSourceReader(SceneEngineeringReader(row.authority, self.connection_id, code, guard),
                    self.shared.project_models, service.work_orders, guard, actor, scene_library=service.library)
                if action == 'evidence/register':
                    value = sources.register(actor, body, authorize, reader.resolve)
                elif action == 'start':
                    from .analysis_queries import start_analysis
                    with self.registry.lock:
                        value = start_analysis(store, actor, reader, body, authorize)
                elif action == 'history-candidates':
                    from .analysis_queries import history_candidates
                    value = history_candidates(store,actor,reader,body,guard)
                elif action == 'import-history':
                    from .analysis_queries import import_history
                    value = import_history(store,actor,body,authorize)
                elif action == 'evidence/register-batch':
                    require(set(body)=={'analysisSessionId','expectedAnalysisRevision','items'} and type(body['items']) is list and 1<=len(body['items'])<=12)
                    results=[]
                    for item in body['items']:
                        require(type(item) is dict and set(item)=={'key','requestId','sourceKind','selector'})
                        try:
                            result=sources.register(actor,{k:v for k,v in body.items() if k!='items'}|{k:v for k,v in item.items() if k!='key'},authorize,reader.resolve)
                            results.append({'key':item['key'],'reference':result})
                        except PreviewError as error:
                            if error.status in (401,403) or error.code=='ANALYSIS_CHANGED':raise
                            results.append({'key':item['key'],'error':error.code})
                    value={'items':results}
                elif action == 'recommendations':
                    from .analysis_queries import recommendations
                    release_store()
                    value = recommendations(reader, body, service.library)
                elif action == 'evidence/batch':
                    require(set(body) == {'analysisSessionId','evidenceRefIds'} and type(body['evidenceRefIds']) is list
                            and 1 <= len(body['evidenceRefIds']) <= 12)
                    values = []
                    fixed = [sources.descriptor(actor, {'analysisSessionId':body['analysisSessionId'], 'evidenceRefId':evidence_id}, guard) for evidence_id in body['evidenceRefIds']]
                    release_store()
                    for evidence_id,(reference,descriptor) in zip(body['evidenceRefIds'],fixed):
                        try:
                            values.append({**reference,'availability':'available','source':reader.read(reference['sourceKind'],descriptor)})
                        except PreviewError as error:
                            if error.status == 401: raise
                            if error.status not in (403,404,409,410,502,503,504): raise
                            values.append({'evidenceRefId':evidence_id,'availability':'restricted' if error.status == 403 else 'unavailable','reason':error.code})
                    value = {'items':values}
                elif action == 'evidence/relationships':
                    require(set(body) == {'analysisSessionId', 'evidenceRefIds'} and type(body['evidenceRefIds']) is list and 1 <= len(body['evidenceRefIds']) <= 50)
                    require(all(isinstance(value, str) for value in body['evidenceRefIds']))
                    fixed = [sources.descriptor(actor, {'analysisSessionId': body['analysisSessionId'], 'evidenceRefId': evidence_id}, guard) for evidence_id in dict.fromkeys(body['evidenceRefIds'])]
                    release_store()
                    from .analysis_preview import relationships
                    value = relationships(reader, fixed, service.library)
                elif action in ('evidence/preview', 'evidence/preview-content'):
                    require({'analysisSessionId', 'evidenceRefId'} <= set(body) <= {'analysisSessionId', 'evidenceRefId', 'options'})
                    reference, descriptor = sources.descriptor(actor, {k: body[k] for k in ('analysisSessionId', 'evidenceRefId')}, guard)
                    release_store()
                    if action == 'evidence/preview':
                        from .analysis_preview import preview
                        value = preview(reader, reference['sourceKind'], descriptor, body.get('options', {}))
                    else:
                        if reference['sourceKind'] == 'document':
                            options = body.get('options', {})
                            require(type(options) is dict and set(options) == {'pageNumber'} and type(options['pageNumber']) is int)
                            value = reader.content('document', {**descriptor, 'pageNumber': options['pageNumber']})
                        else:
                            require(reference['sourceKind'] == 'photo' and 'options' not in body)
                            from .analysis_media import photo_preview
                            value = photo_preview(reader, descriptor)
                elif action in ('evidence/detail', 'evidence/content'):
                    reference, descriptor = sources.descriptor(actor, body, guard)
                    release_store()
                    if action == 'evidence/content':
                        value = reader.content(reference['sourceKind'], descriptor)
                    else:
                        try:
                            value = {**reference, 'availability': 'available', 'source': reader.read(reference['sourceKind'], descriptor)}
                        except PreviewError as error:
                            if error.status == 401: raise
                            if error.status not in (403, 404, 409, 410, 502, 503, 504): raise
                            value = {'availability': 'restricted' if error.status == 403 else 'changed' if error.status in (409, 410) else 'unavailable',
                                     'reason': error.code}
                elif action == 'simulation/qualify':
                    require(set(body) == {'faultCode'})
                    value = reader.qualify(body['faultCode'])
                else:
                    require(store.schema_version >= 2, 'ANALYSIS_SOURCES_NOT_ENABLED', 503)
                    require(set(body) == {'analysisSessionId', 'analysisRevision', 'orderId', 'expectedOrderRevision', 'requestId'})
                    # Serialize a new fixed link with deletion; previously saved links remain readable.
                    from .analysis_drafts import WRITE_LOCK
                    with store.connection.transaction() as cursor:
                        cursor.execute('select pg_advisory_xact_lock(%s)', (WRITE_LOCK,))
                        store._session(cursor, body['analysisSessionId'], actor, active=True)
                        _, fixed = store._revision(cursor, body['analysisSessionId'], body['analysisRevision'])
                        def analysis_guard():
                            authorize()
                            store._session(cursor, body['analysisSessionId'], actor, active=True)
                        value = service.work_orders.link_analysis({**body, 'analysisSha256': fixed[1]}, actor, authorize, analysis_guard)
                authorize()
            elif action == 'copy':
                from .analysis_queries import copy_analysis
                value = copy_analysis(store,actor,body,authorize)
            elif action in ('trash', 'untrash'):
                from .analysis_lifecycle import change
                value = change(store, actor, access['role'], action, body, authorize)
            elif writing:
                value = store.write(actor, access['role'], action, body, authorize)
            elif action == '':
                value = store.listing(actor, body, authorize, cursor_key=self.cursor_key, session_revision=row.revision)
            elif action == 'detail':
                require(set(body) in ({'analysisSessionId'}, {'analysisSessionId', 'analysisRevision'}))
                value = store.detail(actor, body['analysisSessionId'], authorize, revision=body.get('analysisRevision'))
            else:
                require('analysisSessionId' in body and set(body) <= {'analysisSessionId', 'before', 'limit'})
                value = store.history(actor, body['analysisSessionId'], authorize,
                                      before=body.get('before'), limit=body.get('limit', 25))
            return {**value, 'projectRef': payload['projectRef'], 'sessionRevision': row.revision,
                    'capabilities': {'canWrite': access.get('role') == 'admin', 'canConfirmConclusion': False,
                                     'sourceCardsEnabled': store.schema_version >= 2, 'sourceReferenceApiVersion': 2 if store.schema_version >= 2 else 0,
                                     'canManageLifecycle': store.schema_version >= 3 and access.get('role') == 'admin',
                                     'canLinkWorkOrder': store.schema_version >= 2 and access.get('role') == 'admin'}}
        finally:
            release_store()

    def work_order_request(self, sid, path, payload):
        row = self._session(sid, payload)
        code = self._ref(payload.get('projectRef'))
        access = self._access(sid, row, code)
        writing = path.endswith(('/seed-demo', '/action'))
        if writing and access.get('role') != 'admin':
            raise PreviewError(403, 'WORK_ORDER_WRITE_FORBIDDEN')
        def authorize():
            self.guard(sid, row)
            current = self._access(sid, row, code)
            order_require(current['accessRevision'] == access['accessRevision']
                          and (not writing or current.get('role') == 'admin'), 'ACCESS_CHANGED', 409)
        body = {key: value for key, value in payload.items() if key not in ('expectedSessionRevision', 'projectRef')}
        # Source reads enforce membership themselves. Bracket a read-only locate
        # with full access revisions, without repeating a remote grant per node.
        reader = SceneEngineeringReader(row.authority, self.connection_id, code,
            (lambda: self.guard(sid, row)) if path.endswith('/locate') else authorize)
        workspace = self.registry.lookup(code)
        targets = None
        if path.endswith('/seed-demo'):
            order_require(code == DEMO_PROJECT, 'DEMO_PROJECT_REQUIRED', 403)
            targets = self._demo_order_targets(reader)
            if workspace is None:
                authorize()
                workspace = self.registry.prepare(code)
        if workspace is None:
            if path != '/api/workbench/work-orders':
                raise PreviewError(404, 'NOT_FOUND_OR_FORBIDDEN')
            order_require(set(body) <= {'q', 'state', 'cursor', 'limit', 'expectedSnapshotRevision'})
            value = WorkOrders.empty(access.get('role') == 'admin' and code == DEMO_PROJECT)
        else:
            service = self._workspace(workspace)
            if not hasattr(service, 'work_orders'):
                with self.registry.lock:
                    if not hasattr(service, 'work_orders'):
                        service.work_orders = WorkOrders(service.library, code)
            orders = service.work_orders
            if path == '/api/workbench/work-orders':
                value = orders.listing(body, access.get('role') == 'admin')
            elif path.endswith('/detail'):
                value = orders.detail(body)
            elif path.endswith('/diagnosis-history'):
                value = orders.diagnosis_history(body)
            elif path.endswith('/snapshot'):
                value = orders.fixed_snapshot(body)
            elif path.endswith('/seed-demo'):
                value = orders.seed(body, targets, row.authority.username, authorize)
            elif path.endswith('/action'):
                value = orders.action(body, row.authority.username, authorize)
            elif path.endswith('/locate'):
                order_require(set(body) in ({'orderId', 'locateKey'}, {'orderId', 'locateKey', 'referenceRds'},
                                               {'orderId', 'locateKey', 'memberCursor'}))
                detail = orders.detail({'orderId': body['orderId']})
                key = body['locateKey']
                order_require(isinstance(key, str) and 0 < len(key) <= 100)
                key = 'CN2' if key == 'CN' else key
                cabinet = key if key in ('CN1', 'CN2') else None
                if 'referenceRds' in body:
                    rds = body['referenceRds']
                    prefix = '=WEC+' + key + '-'
                    order_require(cabinet and isinstance(rds, str) and rds == rds.strip()
                        and len(prefix) < len(rds) <= 200 and rds.startswith(prefix)
                        and all(ord(character) >= 32 for character in rds))
                elif cabinet:
                    rds = '=WEC+' + cabinet
                else:
                    order_require('memberCursor' not in body)
                    node = next((node for node in detail['diagnosis']['nodes'] if node.get('locateKey') == key), None)
                    order_require(node is not None and 'rds' in node)
                    rds = node['rds']
                if 'memberCursor' in body:
                    token = body['memberCursor']
                    order_require(isinstance(token, str) and 0 < len(token) <= 8192)
                from urllib.parse import urlencode
                catalog = reader._request('GET', reader.prefix + '/objects?' + urlencode({'primaryIdentifier': rds, 'limit': 50}))
                order_require(catalog.get('projectCode') == code, 'SOURCE_UNAVAILABLE', 502)
                order_require(type(catalog.get('items')) is list and len(catalog['items']) <= 50
                    and all(type(item) is dict and type(item.get('identifiers')) is list
                        and all(type(identifier) is dict for identifier in item['identifiers'])
                        for item in catalog['items']), 'SOURCE_UNAVAILABLE', 502)
                def matching(identifier, tag=rds):
                    return (identifier.get('value') == tag and identifier.get('role') == 'primary'
                        and identifier.get('status') in ('accepted', 'needs_review')
                        and identifier.get('scheme') in ('RDS', 'electrical_tag')
                        and identifier.get('scopeType') == 'project' and identifier.get('scopeKey') == code)
                matches = [item for item in catalog['items'] if any(matching(identifier) for identifier in item['identifiers'])]
                order_require(catalog.get('nextCursor') is None and len(matches) == 1, 'DIAGNOSTIC_OBJECT_UNRESOLVED', 409)
                value = reader.context_for_object(matches[0]['entityUid'], matches[0]['entityRevision'])
                identity = next(identifier for identifier in matches[0]['identifiers'] if matching(identifier))
                order_require(identity in value['item']['identifiers'], 'ENGINEERING_CHANGED', 409)
                value['referenceMatch'] = {field: identity[field] for field in ('scheme', 'status', 'value', 'scopeType', 'scopeKey')}
                if cabinet and 'referenceRds' not in body:
                    order_require(value['item']['objectScope'] == 'definition' and value['item']['objectKind'] == 'cabinet'
                        and value['item']['installationContextId'] is None, 'DIAGNOSTIC_OBJECT_UNRESOLVED', 409)
                    value['cabinetReference'] = {'code': cabinet, 'purpose': 'project_definition'}
                    value['cabinetMembers'] = reader.cabinet_members(value['item'], body.get('memberCursor'))
                elif cabinet:
                    parent_uid = value['item'].get('definitionParentEntityUid')
                    order_require(isinstance(parent_uid, str) and parent_uid, 'CABINET_MEMBERSHIP_UNRESOLVED', 409)
                    parent = reader.context_for_object(parent_uid)['item']
                    order_require(parent['objectScope'] == 'definition' and parent['objectKind'] == 'cabinet'
                        and parent['installationContextId'] is None
                        and any(matching(identifier, '=WEC+' + cabinet) for identifier in parent['identifiers']),
                        'CABINET_MEMBERSHIP_UNRESOLVED', 409)
                    value['definitionParent'] = parent
                value = {**value, 'locateKey': key, 'engineeringConfirmation': False}
            else:
                raise PreviewError(404, 'NOT_FOUND_OR_FORBIDDEN')
        authorize()
        return {**value, 'projectRef': {'ontobaseConnectionId': self.connection_id, 'projectCode': code},
                'sessionRevision': row.revision}


def _method(name):
    def request(self, sid, *args):
        if name.endswith('request') or name == 'read':
            path, payload, *rest = args
        else:
            payload, *rest = args
            path = {'resource_upload': '/api/workbench/resources/model/upload',
                    'terrain_upload': '/api/workbench/terrains/upload', 'imagery_upload': '/api/workbench/imagery/upload',
                    'imagery_chunk': '/api/workbench/imagery/uploads/chunk',
                    'upload': '/api/workbench/models/upload', 'save_binding': '/api/workbench/models/binding'}[name]
        return self._call(name, sid, path, payload, *rest)
    return request


for _name in METHODS:
    setattr(ProjectSessions, _name, _method(_name))
