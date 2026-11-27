"""Per-user in-memory sessions, shared by the workbench and local reference."""
from __future__ import annotations
from collections import deque
from dataclasses import dataclass, field
import secrets
from threading import RLock
import time
from urllib.parse import quote
from uuid import UUID
from .authority import Authority, PreviewError

COOKIE = '__Host-ontovis_session'
IDLE_SECONDS, MAX_SECONDS = 30 * 60, 8 * 60 * 60

@dataclass
class Session:
    revision: str = field(default_factory=lambda: secrets.token_urlsafe(24))
    created: float = 0
    touched: float = 0
    status: str = 'anonymous'
    authority: Authority | None = None
    subject_id: str | None = None
    rotated_to: str | None = None


class UserSessions:
    def __init__(self, base_url: str, project_code: str, *, clock=time.monotonic, factory=Authority):
        Authority(base_url)  # Validate the deployment-fixed loopback source.
        self.base_url, self.project_code = base_url, project_code
        self.clock, self.factory = clock, factory
        self.lock = RLock()
        self.rows: dict[str, Session] = {}
        self.attempts: dict[str, deque] = {}
        self.access_path = '/api/v1/projects/' + quote(project_code, safe='') + '/access'

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
        if (data.get('projectCode') != self.project_code
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
            subject = me.get('id')
            if subject is not None and (not isinstance(subject, str) or str(UUID(subject)) != subject
                    or result.get('user', {}).get('id', subject) != subject):
                raise PreviewError(502, 'SOURCE_UNAVAILABLE')
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
                active = Session(created=now, touched=now, status='active', authority=authority, subject_id=subject)
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
            if (me.get('username') != authority.username or me.get('is_active') is not True
                    or row.subject_id is not None and me.get('id') != row.subject_id):
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

