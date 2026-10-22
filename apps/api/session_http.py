"""Same-origin HTTP boundary for ONTOVis in-memory user sessions."""
from __future__ import annotations
from http.cookies import SimpleCookie, CookieError
import base64
from http.server import BaseHTTPRequestHandler
import json
from urllib.parse import parse_qs, urlsplit
from .authority import PreviewError
from .user_sessions import COOKIE, UserSessions
from .scene_library import decode_scene_request, MAX_SCENE_BYTES
from .terrain_validation import MAX_BYTES as MAX_TERRAIN_BYTES
from tools.model_probe import strict_json, ProbeError

def handler_type(sessions: UserSessions, origin: str, *, development=False):
    parsed = urlsplit(origin)
    if (parsed.scheme != ('http' if development else 'https') or not parsed.netloc
            or parsed.path or parsed.query or parsed.fragment or parsed.username
            or development and parsed.hostname != '127.0.0.1'):
        raise ValueError('A fixed HTTPS origin is required')
    cookie_name = 'ontovis_development_session' if development else COOKIE

    class Handler(BaseHTTPRequestHandler):
        server_version = 'ONTOVis'
        sys_version = ''

        def setup(self):
            super().setup()
            self.connection.settimeout(15)

        def log_message(self, *_args):
            pass  # No request bodies, paths, identities or tokens in access logs.

        def sid(self):
            cookie = SimpleCookie()
            try: cookie.load(self.headers.get('Cookie', ''))
            except CookieError: return None
            value = cookie.get(cookie_name)
            return value.value if value and len(value.value) <= 128 else None

        def reply(self, status, body, *, cookie=None):
            data = json.dumps(body, ensure_ascii=False).encode()
            self.send_response(status)
            self.send_header('Content-Type','application/json; charset=utf-8')
            self.send_header('Content-Length',str(len(data)))
            self.send_header('Cache-Control','no-store')
            self.send_header('X-Content-Type-Options','nosniff')
            if cookie is not None:
                value = f'{cookie_name}={cookie}; Path=/; HttpOnly; SameSite=Strict'
                if not development: value += '; Secure'
                if not cookie: value += '; Max-Age=0'
                self.send_header('Set-Cookie', value)
            if status == 429: self.send_header('Retry-After', '60')
            self.end_headers()
            try: self.wfile.write(data)
            except (BrokenPipeError, ConnectionResetError): pass

        def image(self, data, revision, media_type='image/png', sha256=None):
            self.send_response(200)
            for key, value in (('Content-Type',media_type), ('Content-Length',str(len(data))),
                               ('Cache-Control','no-store'), ('X-Content-Type-Options','nosniff'),
                               ('X-Session-Revision',revision)):
                self.send_header(key, value)
            if sha256 is not None:
                self.send_header('X-Content-SHA256', sha256)
            self.end_headers()
            try: self.wfile.write(data)
            except (BrokenPipeError, ConnectionResetError): pass

        def dispatch(self):
            hosts, origins = self.headers.get_all('Host', []), self.headers.get_all('Origin', [])
            if (len(hosts) != 1 or len(origins) > 1
                    or self.command == 'POST' and len(origins) != 1
                    or self.headers.get('Host') != parsed.netloc
                    or self.headers.get('Origin') not in ((origin,) if self.command == 'POST' else (None,origin))
                    or self.headers.get('Sec-Fetch-Site') not in (None,'none','same-origin')):
                raise PreviewError(403, 'FORBIDDEN')
            parts = urlsplit(self.path)
            query = parse_qs(parts.query, keep_blank_values=True)
            if parts.fragment: raise PreviewError(422, 'INVALID_REQUEST')
            sid = self.sid()
            if self.command == 'GET' and parts.path == '/api/session' and query in ({}, {'activity':['1']}):
                if not sid:
                    sid, row = sessions.anonymous()
                    return self.reply(200, {'state':'signedOut','sessionRevision':row.revision}, cookie=sid)
                try: value = sessions.inspect(sid, activity=bool(query))
                except PreviewError as error:
                    if error.status != 401: raise
                    # Re-bootstrap after expiry/restart. This cookie never grants
                    # engineering access until a version-checked login succeeds.
                    sid, row = sessions.anonymous()
                    return self.reply(200, {'state':'expired','sessionRevision':row.revision}, cookie=sid)
                return self.reply(200, value)
            if self.command == 'GET' and parts.path in ('/api/demo/context','/api/demo/locate'):
                return self.reply(200, sessions.read(sid, parts.path, query))
            if self.command == 'POST' and parts.path == '/api/workbench/terrains/upload' and not query:
                if (self.headers.get('Transfer-Encoding') or self.headers.get_all('Transfer-Encoding')
                        or self.headers.get_all('Content-Type') != ['image/tiff']
                        or len(self.headers.get_all('Content-Length', [])) != 1
                        or len(self.headers.get_all('X-Terrain-Metadata', [])) != 1):
                    raise PreviewError(415, 'INVALID_REQUEST')
                try:
                    header = self.headers['X-Terrain-Metadata']
                    if len(header) > 8192: raise ValueError()
                    data = base64.b64decode(header, validate=True)
                    if len(data) > 6144: raise ValueError()
                    payload = strict_json(data)
                    text_length = self.headers['Content-Length']
                    if not text_length.isascii() or not text_length.isdecimal(): raise ValueError()
                    length = int(text_length)
                    if not isinstance(payload, dict): raise ValueError()
                except (ValueError, UnicodeError, ProbeError):
                    raise PreviewError(422, 'INVALID_REQUEST') from None
                if not 8 <= length <= MAX_TERRAIN_BYTES:
                    raise PreviewError(413, 'TERRAIN_LIMIT_EXCEEDED')
                return self.reply(202, sessions.terrain_upload(sid, payload, self.rfile, length))
            if self.command == 'POST' and parts.path in ('/api/workbench/models/upload', '/api/workbench/resources/model/upload') and not query:
                if (self.headers.get_all('Transfer-Encoding') or self.headers.get_all('Content-Type')!=['model/gltf-binary']
                        or len(self.headers.get_all('Content-Length',[]))!=1
                        or len(self.headers.get_all('X-Model-Metadata',[]))!=1): raise PreviewError(415,'INVALID_REQUEST')
                try:
                    header = self.headers['X-Model-Metadata']
                    if len(header)>8192: raise ValueError()
                    data = base64.b64decode(header,validate=True)
                    if len(data)>6144: raise ValueError()
                    payload = strict_json(data)
                    text_length = self.headers['Content-Length']
                    if not text_length.isascii() or not text_length.isdecimal(): raise ValueError()
                    length = int(text_length)
                    if not isinstance(payload,dict): raise ValueError()
                except (ValueError,UnicodeError,ProbeError): raise PreviewError(422,'INVALID_REQUEST') from None
                method = sessions.resource_upload if parts.path.endswith('/resources/model/upload') else sessions.upload
                return self.reply(200,method(sid,payload,self.rfile,length))
            workbench_paths = ('/api/workbench/context','/api/workbench/children','/api/workbench/object','/api/workbench/catalog',
                               '/api/workbench/model','/api/workbench/model/content','/api/workbench/models','/api/workbench/models/binding',
                               '/api/workbench/evidence/resolve','/api/workbench/evidence/content')
            scene_paths = ('/api/workbench/scenes','/api/workbench/scenes/create','/api/workbench/scenes/open',
                           '/api/workbench/scenes/head','/api/workbench/scenes/save','/api/workbench/scenes/check',
                           '/api/workbench/scenes/replacement-check','/api/workbench/scenes/locate')
            scene_object_paths = ('/api/workbench/objects/context', '/api/workbench/objects/detail',
                                  '/api/workbench/objects/children', '/api/workbench/objects/evidence/resolve',
                                  '/api/workbench/objects/evidence/content')
            terrain_paths = ('/api/workbench/terrains', '/api/workbench/terrains/job', '/api/workbench/terrains/job/cancel',
                             '/api/workbench/terrains/version', '/api/workbench/terrains/content')
            resource_paths = ('/api/workbench/resources/models', '/api/workbench/resources/model',
                              '/api/workbench/resources/model/content', '/api/workbench/resources/model/calibrate',
                              '/api/workbench/resources/uses', '/api/workbench/resources/models/legacy',
                              '/api/workbench/resources/model/import-existing')
            if self.command != 'POST' or parts.path not in ('/api/session/login','/api/session/logout', *workbench_paths, *scene_paths, *scene_object_paths, *terrain_paths, *resource_paths) or query:
                raise PreviewError(404, 'NOT_FOUND')
            if (self.headers.get_all('Transfer-Encoding') or len(self.headers.get_all('Content-Type', [])) != 1
                    or self.headers.get('Content-Type','').split(';')[0].strip() != 'application/json'):
                raise PreviewError(415, 'INVALID_REQUEST')
            if len(self.headers.get_all('Content-Length', [])) != 1:
                raise PreviewError(422, 'INVALID_REQUEST')
            try: length = int(self.headers.get('Content-Length','0'))
            except ValueError: raise PreviewError(422, 'INVALID_REQUEST') from None
            large_scene = parts.path in ('/api/workbench/scenes/save', '/api/workbench/scenes/check',
                                         '/api/workbench/scenes/replacement-check')
            limit = MAX_SCENE_BYTES if large_scene else 16384 if parts.path in (*workbench_paths, *scene_paths, *scene_object_paths, *terrain_paths, *resource_paths) else 4096
            if not 0 < length <= limit:
                raise PreviewError(413, 'SCENE_LIMIT_EXCEEDED' if large_scene else 'INVALID_REQUEST')
            try:
                raw = self.rfile.read(length)
                if len(raw) != length:
                    raise PreviewError(422, 'INVALID_REQUEST')
                payload = decode_scene_request(raw) if parts.path in scene_paths else strict_json(raw)
            except (ValueError, UnicodeError, ProbeError): raise PreviewError(422, 'INVALID_REQUEST') from None
            if not isinstance(payload, dict): raise PreviewError(422, 'INVALID_REQUEST')
            if parts.path in scene_paths: return self.reply(200,sessions.scene_request(sid,parts.path,payload))
            if parts.path in scene_object_paths:
                value = sessions.scene_object_request(sid, parts.path, payload)
                if parts.path.endswith('/evidence/content'):
                    return self.image(value['content'], value['sessionRevision'], 'image/png', value['imageSha256'])
                return self.reply(200, value)
            if parts.path in resource_paths:
                value = sessions.resource_request(sid, parts.path, payload)
                if parts.path.endswith('/content'):
                    return self.image(value['content'], value['sessionRevision'], 'model/gltf-binary', value['sha256'])
                return self.reply(200, value)
            if parts.path in terrain_paths:
                value = sessions.terrain_request(sid, parts.path, payload)
                if parts.path.endswith('/content'):
                    return self.image(value['content'], value['sessionRevision'], 'application/octet-stream', value['sha256'])
                return self.reply(200, value)
            if parts.path=='/api/workbench/models/binding': return self.reply(200,sessions.save_binding(sid,payload))
            if parts.path in workbench_paths:
                value = sessions.read(sid, parts.path, payload)
                if parts.path in ('/api/workbench/evidence/content','/api/workbench/model/content'):
                    return self.image(value['content'], value['sessionRevision'],
                                      'model/gltf-binary' if parts.path.endswith('/model/content') else 'image/png')
                return self.reply(200, value)
            if parts.path.endswith('/login'):
                client = self.client_address[0] if development else self.headers.get('X-Vis-Client-IP','loopback')[:128]
                new_sid, value = sessions.login(sid, payload, client)
                return self.reply(200, value, cookie=new_sid)
            if set(payload) != {'expectedSessionRevision'}: raise PreviewError(422, 'INVALID_REQUEST')
            sessions.logout(sid, payload['expectedSessionRevision'])
            return self.reply(200, {'state':'signedOut'}, cookie='')

        def do_GET(self):
            self.handle_request()

        def do_POST(self):
            self.handle_request()

        def handle_request(self):
            try: self.dispatch()
            except PreviewError as error: self.reply(error.status, {'code':error.code})
            except (TimeoutError, ConnectionError, OSError): self.reply(504, {'code':'SOURCE_UNAVAILABLE'})
            except Exception: self.reply(502, {'code':'SOURCE_UNAVAILABLE'})

    return Handler

