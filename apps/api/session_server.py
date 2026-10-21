#!/usr/bin/env python3
"""Same-origin user sessions for the single approved demonstration installation.

Run behind the site's loopback reverse proxy. No business writes or arbitrary
upstream routes are exposed; passwords are used once and never retained.
"""
from __future__ import annotations

import argparse
from collections import deque
from dataclasses import dataclass, field
from http.cookies import SimpleCookie, CookieError
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import secrets
import sys
from threading import RLock
import time
from urllib.parse import parse_qs, quote, urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tools.installation_preview import Authority, InstallationPreview, PreviewError, load_manifest

COOKIE = '__Host-ontovis_session'
IDLE_SECONDS, MAX_SECONDS = 30 * 60, 8 * 60 * 60


@dataclass
class Session:
    revision: str = field(default_factory=lambda: secrets.token_urlsafe(24))
    created: float = 0
    touched: float = 0
    status: str = 'anonymous'
    authority: Authority | None = None
    rotated_to: str | None = None


class Sessions:
    def __init__(self, base_url: str, manifest: dict, *, clock=time.monotonic, factory=Authority):
        Authority(base_url)  # Validate the deployment-fixed loopback source.
        self.base_url, self.manifest = base_url, manifest
        self.clock, self.factory = clock, factory
        self.lock = RLock()
        self.rows: dict[str, Session] = {}
        self.attempts: dict[str, deque] = {}
        self.access_path = '/api/v1/projects/' + quote(manifest['projectCode'], safe='') + '/access'

    def _expired(self, row):
        now = self.clock()
        return now - row.created >= MAX_SECONDS or now - row.touched >= (IDLE_SECONDS if row.status == 'active' else 600)

    def _prune(self):
        self.rows = {key:row for key,row in self.rows.items() if not self._expired(row)}
        cutoff = self.clock() - 60
        self.attempts = {key:values for key,values in self.attempts.items() if values and values[-1] > cutoff}

    def anonymous(self):
        with self.lock:
            self._prune()
            if len(self.rows) >= 1000:
                raise PreviewError(503, 'SERVICE_BUSY')
            sid = secrets.token_urlsafe(32)
            now = self.clock()
            self.rows[sid] = Session(created=now, touched=now)
            return sid, self.rows[sid]

    def current(self, sid, *, authenticated=False, touch=False):
        with self.lock:
            row = self.rows.get(sid)
            if row is None or self._expired(row) or row.status == 'retired':
                if row and self._expired(row): self.rows.pop(sid, None)
                raise PreviewError(401, 'SESSION_EXPIRED')
            if authenticated and row.status != 'active':
                raise PreviewError(401, 'LOGIN_REQUIRED')
            if touch: row.touched = self.clock()
            return row

    def guard(self, sid, row):
        if self.current(sid, authenticated=True) is not row:
            raise PreviewError(401, 'SESSION_EXPIRED')

    def access(self, authority):
        # /access rechecks active user and explicit current project membership.
        data = authority.request('GET', self.access_path)
        if (data.get('projectCode') != self.manifest['projectCode']
                or not {'objects.read','objects.resolve','installations.read','hierarchy.read'}.issubset(data.get('capabilities', []))
                or not isinstance(data.get('accessRevision'), str)):
            raise PreviewError(403, 'FORBIDDEN')
        return data['accessRevision']

    def limit_login(self, client):
        with self.lock:
            self._prune()
            if len(self.attempts) >= 10000 and client not in self.attempts:
                raise PreviewError(429, 'LOGIN_RATE_LIMITED')
            values = self.attempts.setdefault(client, deque())
            while values and values[0] <= self.clock() - 60: values.popleft()
            if len(values) >= 10: raise PreviewError(429, 'LOGIN_RATE_LIMITED')
            values.append(self.clock())

    def login(self, sid, payload, client):
        self.limit_login(client)
        if (set(payload) != {'username','password','expectedSessionRevision'}
                or not isinstance(payload['username'], str) or not 1 <= len(payload['username'].strip()) <= 200
                or not isinstance(payload['password'], str) or not 1 <= len(payload['password']) <= 1024):
            raise PreviewError(422, 'INVALID_REQUEST')
        with self.lock:
            row = self.current(sid)
            if row.revision != payload['expectedSessionRevision'] or row.status != 'anonymous':
                raise PreviewError(409, 'SESSION_CHANGED')
            row.status = 'pending'
        try:
            authority = self.factory(self.base_url)
            result = authority.request('POST', '/api/v1/auth/login',
                                       {'username':payload['username'].strip(), 'password':payload['password']})
            token, username = result.get('token'), result.get('user', {}).get('username')
            if not isinstance(token, str) or not token or not isinstance(username, str) or not username:
                raise PreviewError(502, 'SOURCE_UNAVAILABLE')
            authority.token, authority.username = token, username
            me = authority.request('GET', '/api/v1/auth/me').get('user', {})
            if me.get('username') != username or me.get('is_active') is not True:
                raise PreviewError(401, 'CREDENTIALS_REJECTED')
            readable = True
            try: self.access(authority)
            except PreviewError as error:
                if error.status != 403: raise
                readable = False
            with self.lock:
                if self.rows.get(sid) is not row or self._expired(row) or row.status != 'pending':
                    raise PreviewError(409, 'SESSION_CHANGED')
                new_sid = secrets.token_urlsafe(32)
                now = self.clock()
                active = Session(created=now, touched=now, status='active', authority=authority)
                self.rows[new_sid] = active
                # A cancelled in-flight login can still invalidate its rotated
                # cookie before a delayed response reaches the browser.
                row.status, row.rotated_to, row.authority = 'retired', new_sid, None
                return new_sid, self.view(active, readable)
        except PreviewError as error:
            with self.lock:
                if self.rows.get(sid) is row and row.status == 'pending': row.status = 'anonymous'
            if error.status == 401: raise PreviewError(401, 'CREDENTIALS_REJECTED') from None
            raise
        except (KeyError, TypeError, ValueError, AttributeError):
            with self.lock:
                if self.rows.get(sid) is row and row.status == 'pending': row.status = 'anonymous'
            raise PreviewError(502, 'SOURCE_UNAVAILABLE') from None

    @staticmethod
    def view(row, readable):
        return {'state':'active' if readable else 'denied', 'username':row.authority.username,
                'sessionRevision':row.revision}

    def inspect(self, sid, activity=False):
        with self.lock:
            row = self.current(sid, touch=activity)
            authority = row.authority
        if row.status != 'active':
            return {'state':'signedOut', 'sessionRevision':row.revision}
        try:
            me = authority.request('GET', '/api/v1/auth/me').get('user', {})
            if me.get('username') != authority.username or me.get('is_active') is not True:
                raise PreviewError(401, 'SESSION_EXPIRED')
            readable = True
            try: self.access(authority)
            except PreviewError as error:
                if error.status != 403: raise
                readable = False
            value = {'state':'active' if readable else 'denied', 'username':authority.username,
                     'sessionRevision':row.revision}
            self.guard(sid, row)
            return value
        except PreviewError as error:
            if error.status == 401: self.invalidate(sid, row)
            raise

    def invalidate(self, sid, row):
        with self.lock:
            if self.rows.get(sid) is row: self.rows.pop(sid, None)

    def logout(self, sid, expected):
        with self.lock:
            row = self.rows.get(sid)
            if row is None: return
            if not isinstance(expected, str) or expected != row.revision:
                raise PreviewError(409, 'SESSION_CHANGED')
            self.rows.pop(sid, None)
            if row.rotated_to: self.rows.pop(row.rotated_to, None)
            row.status, row.authority = 'retired', None

    def read(self, sid, path, query):
        with self.lock:
            row = self.current(sid, authenticated=True, touch=True)
            authority = row.authority
        try:
            revision = self.access(authority)
            preview = InstallationPreview(authority, self.manifest)
            if path == '/api/demo/context' and not query:
                value = preview.catalog()
            elif path == '/api/demo/locate' and set(query) == {'entityUid','unitLabel','contextEpoch'} and all(len(items)==1 and 0 < len(items[0]) <= 512 for items in query.values()):
                value = preview.locate(query['entityUid'][0], query['unitLabel'][0], query['contextEpoch'][0])
            else:
                raise PreviewError(422, 'INVALID_REQUEST')
            self.guard(sid, row)
            if self.access(authority) != revision:
                raise PreviewError(409, 'ACCESS_CHANGED')
            self.guard(sid, row)
            value['sessionRevision'] = row.revision
            return value
        except PreviewError as error:
            if error.status == 401: self.invalidate(sid, row)
            raise


def handler_type(sessions: Sessions, origin: str, *, development=False):
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
            if self.command != 'POST' or parts.path not in ('/api/session/login','/api/session/logout') or query:
                raise PreviewError(404, 'NOT_FOUND')
            if self.headers.get('Transfer-Encoding') or self.headers.get('Content-Type','').split(';')[0].strip() != 'application/json':
                raise PreviewError(415, 'INVALID_REQUEST')
            try: length = int(self.headers.get('Content-Length','0'))
            except ValueError: raise PreviewError(422, 'INVALID_REQUEST') from None
            if not 0 < length <= 4096: raise PreviewError(413, 'INVALID_REQUEST')
            try: payload = json.loads(self.rfile.read(length))
            except (ValueError, UnicodeError): raise PreviewError(422, 'INVALID_REQUEST') from None
            if not isinstance(payload, dict): raise PreviewError(422, 'INVALID_REQUEST')
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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', required=True, type=Path)
    parser.add_argument('--model-root', required=True, type=Path)
    parser.add_argument('--source', default='http://127.0.0.1:18001')
    parser.add_argument('--origin', default='https://vis.ontobase.ai')
    parser.add_argument('--port', type=int, default=18083)
    args = parser.parse_args()
    manifest = load_manifest(args.manifest, args.model_root)
    sessions = Sessions(args.source, manifest)
    server = ThreadingHTTPServer(('127.0.0.1',args.port), handler_type(sessions,args.origin))
    print('ONTOVis read-only session service ready', flush=True)
    server.serve_forever()


if __name__ == '__main__': main()
