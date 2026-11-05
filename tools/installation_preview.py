#!/usr/bin/env python3
"""Read an approved demonstration installation through a local user session.

This local preview serves the existing spatial demo and two fixed read routes.
It never writes OntoBase, publishes bindings, or stores login credentials.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import getpass
import hashlib
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import re
import socket
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request


from apps.api.authority import Authority, PreviewError


def load_manifest(path: Path, demo_root: Path) -> dict:
    value = json.loads(path.read_text())
    required = ('projectCode','installationContextId','rootEntityUid','childEntityUid','unitLabel',
                'sourceModelSha256','derivedModelSha256','bindings')
    if type(value.get('schemaVersion')) is not int or value['schemaVersion'] != 1 or any(key not in value for key in required):
        raise ValueError('Invalid preview manifest')
    for key in required[:-1]:
        if not isinstance(value[key], str) or not value[key] or len(value[key]) > 512:
            raise ValueError('Invalid preview identity')
    if value['unitLabel'] != '7':
        raise ValueError('This first slice is restricted to unit 7')
    if not isinstance(value['bindings'], list) or len(value['bindings']) != 3:
        raise ValueError('The first slice requires the three cabinet bindings')
    if {row.get('componentKey') for row in value['bindings']} != {'CT','CN1','CN'}:
        raise ValueError('Missing or ambiguous cabinet geometry')
    uids = [row.get('entityUid') for row in value['bindings']]
    if any(not isinstance(uid,str) or not uid or len(uid)>512 for uid in uids) or len(set(uids)) != 3:
        raise ValueError('Ambiguous cabinet identities')
    if value['childEntityUid'] in uids or value['rootEntityUid'] in uids or value['rootEntityUid'] == value['childEntityUid']:
        raise ValueError('Object roles must have independent identities')
    for row in value['bindings']:
        expected = 'source_candidate' if row['componentKey'] == 'CN' else 'proxy_schematic'
        if row.get('geometryQuality') != expected:
            raise ValueError('Unverified geometry cannot be promoted')
    files = {'sourceModelSha256':'tu3000-geared-original.glb', 'derivedModelSha256':'tu3000-geared-merged.glb'}
    for key, filename in files.items():
        if not re.fullmatch('[0-9a-f]{64}',value[key]):
            raise ValueError('Invalid model fingerprint')
        if hashlib.sha256((demo_root/'assets/models'/filename).read_bytes()).hexdigest() != value[key]:
            raise ValueError('Model artifact changed')
    return value


class InstallationPreview:
    def __init__(self, authority: Authority, manifest: dict):
        self.authority, self.manifest = authority, manifest
        self.prefix = '/api/v1/projects/' + urllib.parse.quote(manifest['projectCode'], safe='')
        self.context_path = self.prefix + '/installations/' + urllib.parse.quote(manifest['installationContextId'],safe='')
        self.bindings = {row['entityUid']: row for row in manifest['bindings']}
        self.allowed_uids = set(self.bindings) | {manifest['rootEntityUid'],manifest['childEntityUid']}

    def context(self) -> dict:
        value = self.authority.request('GET', self.context_path)['item']
        if (value.get('installationContextId') != self.manifest['installationContextId']
                or value.get('projectCode') != self.manifest['projectCode']
                or value.get('purpose') != 'demonstration' or value.get('engineeringUseAllowed') is not False
                or value.get('rootEntityUid') != self.manifest['rootEntityUid']):
            raise PreviewError(409, 'DEMO_SCOPE_REQUIRED')
        return value

    def object_ref(self, uid: str) -> dict:
        return {'ontobaseConnectionId':'ontobase-test-user-session', 'projectCode':self.manifest['projectCode'], 'entityUid':uid}

    def catalog(self) -> dict:
        context = self.context()
        query = urllib.parse.urlencode({'installationContextId':self.manifest['installationContextId'],'limit':100})
        data = self.authority.request('GET', self.prefix+'/objects?'+query)
        # Only the five explicitly reviewed preview roles are exposed by this bridge.
        items = [row for row in data['items'] if row['entityUid'] in self.allowed_uids]
        if data.get('nextCursor') or {row['entityUid'] for row in items} != self.allowed_uids:
            raise PreviewError(409,'PREVIEW_INPUT_CHANGED')
        return {'context':context,'items':items,'unitLabel':self.manifest['unitLabel'],
                'childEntityUid':self.manifest['childEntityUid'], 'operator':self.authority.username,
                'previewOnly':True,'bindingStatus':'demonstration_draft','engineeringUseAllowed':False}

    def locate(self, uid: str, unit: str, epoch: str) -> dict:
        if uid not in self.allowed_uids:
            raise PreviewError(404,'NOT_FOUND_OR_FORBIDDEN')
        if unit != self.manifest['unitLabel']:
            raise PreviewError(409,'INSTANCE_MISMATCH')
        for attempt in range(2):
            context = self.context()
            resolved = self.authority.request('POST', self.prefix+'/objects/resolve',
                                              {'entityUids':[uid],'installationContextId':self.manifest['installationContextId']})['items'][0]
            selected = resolved.get('object')
            if selected is None:
                raise PreviewError(404,'NOT_FOUND_OR_FORBIDDEN')
            if selected.get('installationContextId') != self.manifest['installationContextId']:
                raise PreviewError(409,'INSTANCE_MISMATCH')
            result = {'selectedObjectRef':self.object_ref(uid), 'selectedObject':selected,
                      'locatedObjectRef':None,'componentKey':None,'geometryQuality':None,'path':[],
                      'locationMode':'unlocated','reasonCode':None,'contextEpoch':epoch,
                      'installationContextId':self.manifest['installationContextId'],
                      'hierarchyRevision':context['hierarchyRevision'],'previewOnly':True,
                      'bindingStatus':'demonstration_draft','engineeringUseAllowed':False,
                      'modelVersionId':'sha256:'+self.manifest['derivedModelSha256']}
            if resolved.get('resolution') != 'exact' or resolved.get('canonicalEntityUid') != uid or selected.get('lifecycle') != 'active':
                result['reasonCode'] = 'IDENTITY_CHANGED'
                return result
            query = urllib.parse.urlencode({'entityUid':uid,'maxDepth':32})
            tree = self.authority.request('GET', self.context_path+'/ancestors?'+query)
            if tree.get('hierarchyRevision') != context['hierarchyRevision']:
                if attempt == 0:
                    continue
                raise PreviewError(409,'REVISION_CONFLICT')
            if (tree.get('installationContextId') != self.manifest['installationContextId']
                    or tree.get('purpose') != 'demonstration' or tree.get('engineeringUseAllowed') is not False):
                raise PreviewError(409,'DEMO_SCOPE_REQUIRED')
            if tree.get('completeness') != 'complete':
                result['reasonCode'] = tree.get('reasonCode') or 'PATH_UNAVAILABLE'
                return result
            path = tree.get('path',[])
            child = uid
            for step in path:
                parent, relation = step['object'], step['relation']
                if (parent.get('entityUid') not in self.allowed_uids
                        or parent.get('installationContextId') != self.manifest['installationContextId']
                        or parent.get('lifecycle') != 'active' or relation.get('status') != 'assumed'
                        or relation.get('childEntityUid') != child or relation.get('parentEntityUid') != parent.get('entityUid')):
                    raise PreviewError(409,'INVALID_HIERARCHY')
                child = parent['entityUid']
            if child != self.manifest['rootEntityUid']:
                raise PreviewError(409,'INVALID_HIERARCHY')
            located = uid if uid in self.bindings else next((step['object']['entityUid'] for step in path if step['object']['entityUid'] in self.bindings), None)
            result.update(resolvedAsOf=tree['resolvedAsOf'])
            if located is None:
                result['reasonCode'] = 'NO_GEOMETRY'
                return result
            binding = self.bindings[located]
            result.update(locatedObjectRef=self.object_ref(located),componentKey=binding['componentKey'],
                          geometryQuality=binding['geometryQuality'],path=path,
                          locationMode='demo_direct_geometry' if located == uid else 'demo_ancestor_proxy',
                          reasonCode='DEMONSTRATION_ASSUMPTION')
            return result
        raise PreviewError(409,'REVISION_CONFLICT')


def handler_type(preview: InstallationPreview, directory: Path, port: int):
    class Handler(SimpleHTTPRequestHandler):
        def __init__(self,*args,**kwargs):
            super().__init__(*args,directory=str(directory),**kwargs)

        def reply(self, status: int, value: dict):
            body = json.dumps(value,ensure_ascii=False).encode()
            self.send_response(status)
            self.send_header('Content-Type','application/json; charset=utf-8')
            self.send_header('Content-Length',str(len(body)))
            self.send_header('Cache-Control','no-store')
            self.send_header('X-Content-Type-Options','nosniff')
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            parts = urllib.parse.urlsplit(self.path)
            if not parts.path.startswith('/api/'):
                return super().do_GET()
            try:
                expected = f'127.0.0.1:{port}'
                if (self.headers.get('Host') != expected
                        or self.headers.get('Origin') not in (None,'http://'+expected)
                        or self.headers.get('Sec-Fetch-Site') not in (None,'none','same-origin')):
                    raise PreviewError(403,'FORBIDDEN')
                query = urllib.parse.parse_qs(parts.query,keep_blank_values=True)
                if parts.path == '/api/demo/context' and not query:
                    value = preview.catalog()
                elif parts.path == '/api/demo/locate' and set(query) == {'entityUid','unitLabel','contextEpoch'} and all(len(values)==1 and len(values[0])<=512 for values in query.values()):
                    value = preview.locate(query['entityUid'][0],query['unitLabel'][0],query['contextEpoch'][0])
                else:
                    raise PreviewError(404,'NOT_FOUND_OR_FORBIDDEN')
                self.reply(200,value)
            except PreviewError as error:
                self.reply(error.status,{'code':error.code,'previewOnly':True})
            except (KeyError,TypeError,ValueError):
                self.reply(502,{'code':'SOURCE_UNAVAILABLE','previewOnly':True})

        def do_POST(self):
            self.reply(405,{'code':'READ_ONLY_PREVIEW','previewOnly':True})

        def log_message(self,format,*args):
            # Request URLs can contain engineering UIDs; do not persist them.
            return
    return Handler


@contextmanager
def ssh_source(target: str, backend_port: int):
    if not re.fullmatch(r'[A-Za-z0-9_.-]+@[0-9.]+',target) or not 1<=backend_port<=65535:
        raise ValueError('Invalid authorized SSH endpoint')
    with socket.socket() as reserve:
        reserve.bind(('127.0.0.1',0))
        port = reserve.getsockname()[1]
    tunnel = subprocess.Popen(['ssh','-N','-o','BatchMode=yes','-o','ExitOnForwardFailure=yes','-L',
                               f'127.0.0.1:{port}:127.0.0.1:{backend_port}',target],
                              stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    try:
        for _ in range(100):
            if tunnel.poll() is not None:
                raise PreviewError(502,'SOURCE_UNAVAILABLE')
            try:
                with socket.create_connection(('127.0.0.1',port),timeout=.1):
                    break
            except OSError:
                time.sleep(.1)
        else:
            raise PreviewError(502,'SOURCE_UNAVAILABLE')
        yield f'http://127.0.0.1:{port}'
    finally:
        tunnel.terminate()
        try:
            tunnel.wait(timeout=5)
        except subprocess.TimeoutExpired:
            tunnel.kill()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest',type=Path,required=True)
    parser.add_argument('--demo-root',type=Path,required=True)
    parser.add_argument('--ssh-target',required=True)
    parser.add_argument('--backend-port',type=int,default=18001)
    parser.add_argument('--port',type=int,default=8766)
    parser.add_argument('--username',default='admin')
    args = parser.parse_args()
    manifest = load_manifest(args.manifest,args.demo_root)
    with ssh_source(args.ssh_target,args.backend_port) as url:
        authority = Authority(url)
        password = getpass.getpass('OntoBase password: ')
        try:
            authority.login(args.username,password)
            password = None
            preview = InstallationPreview(authority,manifest)
            preview.catalog()
            server = ThreadingHTTPServer(('127.0.0.1',args.port),handler_type(preview,args.demo_root,args.port))
            print(f'ONTOVis local authenticated preview: http://127.0.0.1:{args.port}/',flush=True)
            try:
                server.serve_forever()
            finally:
                server.server_close()
        finally:
            password = None
            authority.token = None


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        pass
    except (PreviewError,ValueError) as error:
        raise SystemExit(str(error)) from None
