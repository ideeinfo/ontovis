#!/usr/bin/env python3
"""ONTOVis first workbench slice: one configured installation, current evidence.

No spatial-demo assets, role UID manifest, business writes or arbitrary proxy.
"""
from __future__ import annotations
import argparse
from http.server import ThreadingHTTPServer
from pathlib import Path
import sys
from urllib.parse import quote, urlencode
from uuid import UUID

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from apps.api.authority import Authority, PreviewError
from apps.api.user_sessions import UserSessions
from apps.api.session_http import handler_type
from apps.api.model_assets import ModelAsset


class WorkbenchSessions(UserSessions):
    def __init__(self, base_url, project_code, installation_context_id, *, model_root=None, **kwargs):
        super().__init__(base_url, project_code, **kwargs)
        self.context_id = str(UUID(installation_context_id))
        self.prefix = '/api/v1/projects/' + quote(project_code, safe='')
        self.context_path = self.prefix + '/installations/' + self.context_id
        self.model = ModelAsset(Path(model_root), project_code, self.context_id) if model_root else None

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
            elif path == '/api/workbench/catalog' and set(body).issubset({'q','cursor','scope'}):
                q, cursor = body.get('q',''), body.get('cursor')
                if (not isinstance(q, str) or len(q) > 200 or cursor is not None
                        and (not isinstance(cursor, str) or not 0 < len(cursor) <= 8192)):
                    raise PreviewError(422, 'INVALID_REQUEST')
                params = {'q':q, 'limit':50}
                if body.get('scope','project') not in ('equipment','project'):
                    raise PreviewError(422, 'INVALID_REQUEST')
                if body.get('scope') == 'equipment': params['installationContextId'] = self.context_id
                if cursor: params['cursor'] = cursor
                value = authority.request('GET', self.prefix + '/objects?' + urlencode(params))
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
    args = parser.parse_args()
    sessions = WorkbenchSessions(args.source, args.project_code, args.installation_context_id, model_root=args.model_root)
    server = ThreadingHTTPServer(('127.0.0.1', args.port), handler_type(sessions, args.origin, development=args.development))
    print('ONTOVis evidence workbench ready', flush=True)
    server.serve_forever()


if __name__ == '__main__': main()
