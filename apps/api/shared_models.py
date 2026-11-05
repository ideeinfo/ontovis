"""Connection-wide model access; engineering projects and scene grants remain separate."""
from __future__ import annotations

import hashlib
import hmac
import json

from .authority import PreviewError


class SharedModelAccess:
    def __init__(self, sessions):
        self.sessions = sessions

    def identity(self, sid, row):
        self.sessions.guard(sid, row)
        me = row.authority.request('GET', '/api/v1/auth/me').get('user', {})
        if me.get('username') != row.authority.username or me.get('is_active') is not True:
            raise PreviewError(401, 'SESSION_EXPIRED')
        self.sessions.guard(sid, row)

    def grants(self, sid, row):
        source = row.authority.request('GET', '/api/v1/projects')
        items = source.get('items')
        if not isinstance(items, list) or len(items) > 1000:
            raise PreviewError(502, 'SOURCE_UNAVAILABLE')
        values, seen = [], set()
        for item in items:
            if not isinstance(item, dict) or item.get('status') != 'active':
                raise PreviewError(502, 'SOURCE_UNAVAILABLE')
            code = item.get('project_code')
            if not isinstance(code, str) or not code or code in seen:
                raise PreviewError(502, 'SOURCE_UNAVAILABLE')
            seen.add(code)
            try:
                access = self.sessions._access(sid, row, code)
            except PreviewError as error:
                if error.status == 403:
                    continue
                raise
            values.append((code, access))
        return sorted(values, key=lambda item: item[0])

    def authorize(self, sid, payload, *, writing, write_code='MODEL_WRITE_FORBIDDEN', read_capabilities=True):
        row = self.sessions._session(sid, payload)
        try:
            self.identity(sid, row)
            grants = self.grants(sid, row) if writing or read_capabilities else []
            maintainers = [(code, item['accessRevision']) for code, item in grants if item.get('role') == 'admin']
            revision = hashlib.sha256(json.dumps([row.authority.username, maintainers], sort_keys=True).encode()).hexdigest()
            access = {'role': 'admin' if maintainers else 'reader', 'accessRevision': 'shared:' + revision}

            def check():
                try:
                    self.identity(sid, row)
                    if writing:
                        current = [(code, item['accessRevision']) for code, item in self.grants(sid, row)
                                   if item.get('role') == 'admin']
                        if not current:
                            raise PreviewError(403, write_code)
                        if current != maintainers:
                            raise PreviewError(409, 'ACCESS_CHANGED')
                except PreviewError as error:
                    if error.status == 401:
                        self.sessions.invalidate(sid, row)
                    raise

            if writing and not maintainers:
                raise PreviewError(403, write_code)
            check()
            return row, check, access, row.authority.username
        except PreviewError as error:
            if error.status == 401:
                self.sessions.invalidate(sid, row)
            raise

    def uses(self, sid, payload):
        row, authorize, access, actor = self.authorize(sid, payload, writing=False)
        body = {key: value for key, value in payload.items() if key != 'expectedSessionRevision'}
        if not {'resourceKind', 'versionId'} <= set(body) <= {'resourceKind', 'versionId', 'scope', 'cursor', 'limit'}:
            raise PreviewError(422, 'INVALID_REQUEST')
        if body['resourceKind'] != 'model':
            raise PreviewError(422, 'SCENE_SCOPE_UNSUPPORTED')
        limit, scope = body.get('limit', 50), body.get('scope', 'current_or_retained')
        if type(limit) is not int or not 1 <= limit <= 100 or scope not in ('current', 'retained', 'current_or_retained'):
            raise PreviewError(422, 'INVALID_REQUEST')
        self.sessions.shared.project_models.content_identity(body['versionId'])
        items, states = [], []
        grants = self.grants(sid, row)
        for code, project_access in grants:
            workspace = self.sessions.registry.lookup(code)
            if workspace is None or workspace['state'] != 'ready':
                continue
            service = self.sessions._workspace(workspace)
            cursor = None
            while True:
                value = service.scenes.uses(body['versionId'], actor, authorize,
                    access_revision=project_access['accessRevision'], scope=scope, limit=100, cursor=cursor)
                states.append((code, project_access['accessRevision'], value['snapshotRevision']))
                for item in value['items']:
                    items.append({**item, 'projectRef': {'ontobaseConnectionId': self.sessions.connection_id, 'projectCode': code},
                                  'projectName': project_access.get('projectName', code)})
                    if len(items) > 10_000:
                        raise PreviewError(413, 'SCENE_LIMIT_EXCEEDED')
                cursor = value['nextCursor']
                if cursor is None:
                    break
        items.sort(key=lambda item: (item['projectRef']['projectCode'], item['sceneId']))
        revision = hashlib.sha256(json.dumps([row.revision, actor, body['versionId'], scope, limit, states, items],
            sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        start = 0
        if body.get('cursor') is not None:
            try:
                offset, previous, signature = body['cursor'].split('.')
                unsigned = offset + '.' + previous
                if not hmac.compare_digest(signature, hmac.new(self.sessions.cursor_key, unsigned.encode(), 'sha256').hexdigest()):
                    raise ValueError()
                start = int(offset)
                if start < 0:
                    raise ValueError()
                if previous != revision:
                    raise PreviewError(409, 'SNAPSHOT_EXPIRED')
            except (AttributeError, ValueError, TypeError):
                raise PreviewError(422, 'INVALID_REQUEST') from None
        following = None
        if start + limit < len(items):
            unsigned = str(start + limit) + '.' + revision
            following = unsigned + '.' + hmac.new(self.sessions.cursor_key, unsigned.encode(), 'sha256').hexdigest()
        # A project revoked during aggregation must not leak its scenes or counts.
        current = [(code, item['accessRevision']) for code, item in self.grants(sid, row)]
        if current != [(code, item['accessRevision']) for code, item in grants]:
            raise PreviewError(409, 'ACCESS_CHANGED')
        authorize()
        counts = {key: sum(item[key] for item in items)
                  for key in ('currentInstanceCount', 'retainedInstanceCount', 'retainedReferenceCount')}
        return self.sessions.shared.resource_response({'versionId': body['versionId'], 'items': items[start:start+limit],
            'nextCursor': following, 'snapshotRevision': revision, **counts}, row, access)
