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


METHODS = ('scene_request', 'scene_object_request', 'resource_request', 'resource_upload',
           'terrain_request', 'terrain_upload', 'imagery_request', 'imagery_upload', 'imagery_chunk',
           'public_geodata_request', 'legacy_migration_request', 'read', 'upload', 'save_binding')


class ProjectSessions(UserSessions):
    def __init__(self, base_url, project_code=None, installation_context_id=None, *, library_root,
                 workspace_root=None, model_root=None, ontobase_connection_id='ontobase-primary',
                 registry_backend='sqlite', registry_database_url=None, **kwargs):
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
        try:
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
        access = self._access(sid, row, code)
        clean = {k: v for k, v in payload.items() if k != 'projectRef'}
        writing = method.endswith('upload') or method == 'imagery_chunk' or path == '/api/workbench/imagery/uploads/complete' or path.endswith(('/create', '/save', '/calibrate', '/import-existing',
            '/preserve-legacy-display', '/ensure', '/binding', '/cancel', '/start', '/activate'))
        if writing and access.get('role') != 'admin':
            raise PreviewError(403, 'SCENE_WRITE_FORBIDDEN' if '/scenes' in path or '/terrains' in path or '/public-geodata/' in path
                               else 'IMAGERY_WRITE_FORBIDDEN' if '/imagery' in path else 'MODEL_WRITE_FORBIDDEN')
        workspace = self.registry.lookup(code)
        if workspace is None and writing and path not in ('/api/workbench/imagery/uploads/chunk',
                '/api/workbench/imagery/uploads/complete', '/api/workbench/imagery/uploads/cancel'):
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
        reader = SceneEngineeringReader(row.authority, self.connection_id, code, authorize)
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
