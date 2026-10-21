"""Same-origin HTTP boundary for ONTOVis in-memory user sessions."""
from __future__ import annotations
from http.cookies import SimpleCookie, CookieError
from http.server import BaseHTTPRequestHandler
import json
from urllib.parse import parse_qs, urlsplit
from .authority import PreviewError
from .user_sessions import COOKIE, UserSessions

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

        def image(self, data, revision, media_type='image/png'):
            self.send_response(200)
            for key, value in (('Content-Type',media_type), ('Content-Length',str(len(data))),
                               ('Cache-Control','no-store'), ('X-Content-Type-Options','nosniff'),
                               ('X-Session-Revision',revision)):
                self.send_header(key, value)
            self.end_headers()
            try: self.wfile.write(data)
            except (BrokenPipeError, ConnectionResetError): pass

        def dispatch(self):
            if (self.headers.get('Host') != parsed.netloc
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
            workbench_paths = ('/api/workbench/context','/api/workbench/children','/api/workbench/object','/api/workbench/catalog',
                               '/api/workbench/model','/api/workbench/model/content',
                               '/api/workbench/evidence/resolve','/api/workbench/evidence/content')
            if self.command != 'POST' or parts.path not in ('/api/session/login','/api/session/logout', *workbench_paths) or query:
                raise PreviewError(404, 'NOT_FOUND')
            if self.headers.get('Transfer-Encoding') or self.headers.get('Content-Type','').split(';')[0].strip() != 'application/json':
                raise PreviewError(415, 'INVALID_REQUEST')
            try: length = int(self.headers.get('Content-Length','0'))
            except ValueError: raise PreviewError(422, 'INVALID_REQUEST') from None
            if not 0 < length <= (16384 if parts.path in workbench_paths else 4096): raise PreviewError(413, 'INVALID_REQUEST')
            try: payload = json.loads(self.rfile.read(length))
            except (ValueError, UnicodeError): raise PreviewError(422, 'INVALID_REQUEST') from None
            if not isinstance(payload, dict): raise PreviewError(422, 'INVALID_REQUEST')
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

