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


class WorkbenchSessions(UserSessions):
    def __init__(self, base_url, project_code, installation_context_id, *, model_root=None, library_root=None, **kwargs):
        super().__init__(base_url, project_code, **kwargs)
        self.context_id = str(UUID(installation_context_id))
        self.prefix = '/api/v1/projects/' + quote(project_code, safe='')
        self.context_path = self.prefix + '/installations/' + self.context_id
        self.model = ModelAsset(Path(model_root), project_code, self.context_id) if model_root else None
        self.library = ModelLibrary(Path(library_root),project_code,self.context_id) if library_root else None

    def writer(self, sid, payload):
        row = self.current(sid, authenticated=True, touch=True)
        if payload.get('expectedSessionRevision') != row.revision: raise PreviewError(409,'SESSION_CHANGED')
        if self.library is None or self.model is None: raise PreviewError(503,'MODEL_UNAVAILABLE')
        authority = row.authority
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
        return row,context,authorize

    def upload(self, sid, payload, stream, length):
        ModelLibrary.upload_metadata(payload)
        if not 24 <= length <= MAX_BYTES: raise PreviewError(413,'MODEL_LIMIT_EXCEEDED')
        with self.lock: row,context,authorize = self.writer(sid,payload)
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
            with self.lock:
                self.guard(sid,row)
                value = self.library.save_upload(path,payload,row.authority.username,result,authorize)
                return {'item':value, 'libraryRevision':self.library.listing()['libraryRevision'], 'sessionRevision':row.revision}
        finally:
            if path: path.unlink(missing_ok=True)
            self.library.slots.release()

    def save_binding(self, sid, payload):
        with self.lock: row,context,authorize = self.writer(sid,payload)
        body = {key:value for key,value in payload.items() if key!='expectedSessionRevision'}
        uid = body.get('entityUid')
        if not isinstance(uid,str) or uid not in {item['entityUid'] for item in self.model.value['bindings']}: raise PreviewError(422,'INVALID_CABINET')
        def verify():
            authorize()
            item = self.object(row.authority,uid)
            ancestors = row.authority.request('GET',self.context_path+'/ancestors?'+urlencode({'entityUid':uid}))
            if (body.get('expectedHierarchyRevision')!=context['hierarchyRevision']
                    or item['entityRevision']!=body.get('expectedEntityRevision') or item.get('objectKind')!='cabinet'
                    or ancestors.get('hierarchyRevision')!=context['hierarchyRevision'] or ancestors.get('completeness')!='complete'
                    or not any(p.get('object',{}).get('entityUid')==context['rootEntityUid'] for p in ancestors.get('path',[]))):
                raise PreviewError(409,'MODEL_BINDING_CHANGED')
        with self.lock:
            self.guard(sid,row)
            self.library.bind(body,row.authority.username,verify)
            self.guard(sid,row)
            return {'modelRevision':self.library.version(body['modelVersionId'])['modelRevision'], 'sessionRevision':row.revision}

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
    args = parser.parse_args()
    sessions = WorkbenchSessions(args.source, args.project_code, args.installation_context_id, model_root=args.model_root, library_root=args.library_root)
    server = ThreadingHTTPServer(('127.0.0.1', args.port), handler_type(sessions, args.origin, development=args.development))
    print('ONTOVis evidence workbench ready', flush=True)
    server.serve_forever()


if __name__ == '__main__': main()
