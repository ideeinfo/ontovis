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


METHODS = ('scene_request', 'scene_object_request', 'resource_request', 'resource_upload',
           'terrain_request', 'terrain_upload', 'imagery_request', 'imagery_upload',
           'public_geodata_request', 'legacy_migration_request', 'read', 'upload', 'save_binding')


class ProjectSessions(UserSessions):
    def __init__(self, base_url, project_code=None, installation_context_id=None, *, library_root,
                 workspace_root=None, model_root=None, ontobase_connection_id='ontobase-primary', **kwargs):
        identity_options = {key: kwargs.pop(key) for key in ('clock', 'factory') if key in kwargs}
        super().__init__(base_url, project_code or '', **identity_options)
        self.connection_id = text(ontobase_connection_id)
        self.options = kwargs
        self.model_root = model_root
        self.registry = ProjectWorkspaces(workspace_root or Path(library_root).parent / 'workbench-projects',
            self.connection_id, legacy_root=library_root, legacy_project=project_code,
            legacy_context=installation_context_id)
        self.services = {}
        self.readers = {}
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
        with self.registry.connect() as db:
            db.execute('''create table if not exists shared_model_store (
                id integer primary key check(id=1), connection_id text not null, scope_version integer not null)''')
            db.execute('insert or ignore into shared_model_store values(1,?,1)', (self.connection_id,))
            if tuple(db.execute('select connection_id,scope_version from shared_model_store where id=1').fetchone()) != (self.connection_id, 1):
                raise ValueError('Shared model registry belongs to a different source connection')
        self.shared.model_authorization = self.shared_access.authorize
        self.shared.model_scope = 'shared_static_glb_resources'
        self.shared.scenes.use_shared_models(lambda identifier, db=None: self.shared.project_models.content_identity(identifier), self.connection_id)
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
                        lambda identifier, db=None: self.shared.project_models.content_identity(identifier), self.connection_id)
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
        allowed = {'/api/workbench/scenes': {'q', 'cursor', 'limit'},
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
            return {'items': [], 'nextCursor': None, 'snapshotRevision': 'scenes:empty',
                'capabilities': {**SceneLibrary.capabilities(geographic=bool(self.options.get('terrain_python')), engineering=True),
                    'scope': 'project_scenes', 'canRead': True, 'canWrite': can_write, 'sceneInfoWriteVersion': 1},
                'limits': {'maxInstances': MAX_INSTANCES, 'maxComponentBindings': MAX_COMPONENT_BINDINGS,
                    'maxSaveJsonBytes': MAX_SCENE_BYTES, 'maxCheckJsonBytes': MAX_SCENE_BYTES,
                    'maxReadJsonBytes': 16384, 'maxNameCharacters': 200, 'maxLocalCoordinateM': MAX_COORDINATE_M}}
        if path in ('/api/workbench/resources/models', '/api/workbench/resources/models/legacy'):
            limits = ProjectModelLibrary.capabilities()
            return {'items': [], 'libraryRevision': 'library:0', 'nextCursor': None,
                    'capabilities': {'canRead': True, 'canUpload': can_write, 'canCalibrate': can_write},
                    'limits': limits}
        if path in ('/api/workbench/terrains', '/api/workbench/imagery'):
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
        access = self._access(sid, row, code)
        clean = {k: v for k, v in payload.items() if k != 'projectRef'}
        writing = method.endswith('upload') or path.endswith(('/create', '/save', '/calibrate', '/import-existing',
            '/preserve-legacy-display', '/ensure', '/binding', '/cancel', '/start', '/activate'))
        if writing and access.get('role') != 'admin':
            raise PreviewError(403, 'SCENE_WRITE_FORBIDDEN' if '/scenes' in path or '/terrains' in path or '/public-geodata/' in path
                               else 'IMAGERY_WRITE_FORBIDDEN' if '/imagery' in path else 'MODEL_WRITE_FORBIDDEN')
        workspace = self.registry.lookup(code)
        if workspace is None and writing:
            workspace = self.registry.prepare(code)
        if method == 'scene_object_request' or path == '/api/workbench/catalog':
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
        for service in {self.shared, *self.services.values()}:
            self._close(service)


def _method(name):
    def request(self, sid, *args):
        if name.endswith('request') or name == 'read':
            path, payload, *rest = args
        else:
            payload, *rest = args
            path = {'resource_upload': '/api/workbench/resources/model/upload',
                    'terrain_upload': '/api/workbench/terrains/upload', 'imagery_upload': '/api/workbench/imagery/upload',
                    'upload': '/api/workbench/models/upload', 'save_binding': '/api/workbench/models/binding'}[name]
        return self._call(name, sid, path, payload, *rest)
    return request


for _name in METHODS:
    setattr(ProjectSessions, _name, _method(_name))
