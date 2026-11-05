import copy
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
import json
from threading import Event, Thread
import unittest

from apps.api.session_server import COOKIE, IDLE_SECONDS, MAX_SECONDS, Sessions, handler_type
from tests.test_installation_preview import FixtureAuthority, manifest, CHILD, CT, CN1, CN
from tools.installation_preview import PreviewError


class Account(FixtureAuthority):
    def __init__(self, base):
        super().__init__()
        self.token = None
        self.username = None
        self.allowed = True
        self.expired = False
        self.version = 'grant-1'
        self.wait = None
        self.started = None

    def request(self, method, path, body=None):
        if path == '/api/v1/auth/login':
            if self.started: self.started.set()
            if self.wait: self.wait.wait(3)
            if body['password'] != 'synthetic-password': raise PreviewError(401, 'OTHER_SOURCE_MESSAGE')
            self.username = body['username']
            return {'token':'synthetic-token-' + self.username, 'user':{'username':self.username}}
        if self.expired: raise PreviewError(401, 'SESSION_EXPIRED')
        if path == '/api/v1/auth/me':
            return {'user':{'username':self.username,'is_active':True}}
        if not self.allowed: raise PreviewError(403, 'FORBIDDEN')
        if path.endswith('/access'):
            return {'projectCode':'fixture-project','accessRevision':self.version,
                    'capabilities':['objects.read','objects.resolve','installations.read','hierarchy.read']}
        if self.started: self.started.set()
        if self.wait: self.wait.wait(3)
        return super().request(method,path,body)


class SessionTests(unittest.TestCase):
    def setUp(self):
        self.now = 1000
        self.accounts = []
        def factory(base):
            account = Account(base)
            self.accounts.append(account)
            return account
        self.sessions = Sessions('http://127.0.0.1:1234',manifest(),clock=lambda:self.now,factory=factory)
        self.sid, self.row = self.sessions.anonymous()

    def login(self, user='fixture-user', sid=None, row=None):
        return self.sessions.login(sid or self.sid, {'username':user,'password':'synthetic-password',
                                   'expectedSessionRevision':(row or self.row).revision},'fixture-client')

    def assert_error(self, status, code, fn):
        with self.assertRaises(PreviewError) as error: fn()
        self.assertEqual((error.exception.status,error.exception.code),(status,code))

    def test_cookie_rotates_and_untrusted_id_cannot_be_fixed(self):
        self.assert_error(401,'SESSION_EXPIRED',lambda:self.login(sid='attacker-chosen'))
        sid, view = self.login()
        self.assertNotEqual(sid,self.sid)
        self.assertEqual(view['state'],'active')
        self.assertNotEqual(view['sessionRevision'], self.row.revision)
        self.assert_error(401,'SESSION_EXPIRED',lambda:self.sessions.read(self.sid,'/api/demo/context',{}))
        self.assertNotIn('token',json.dumps(view))

    def test_two_users_have_independent_tokens_and_logout(self):
        sid1, _ = self.login('user-one')
        anon2, row2 = self.sessions.anonymous()
        sid2, _ = self.login('user-two',anon2,row2)
        self.assertNotEqual(self.sessions.rows[sid1].authority.token,self.sessions.rows[sid2].authority.token)
        self.sessions.logout(sid1,self.sessions.rows[sid1].revision)
        self.assert_error(401,'SESSION_EXPIRED',lambda:self.sessions.inspect(sid1))
        self.assertEqual(self.sessions.read(sid2,'/api/demo/context',{})['operator'],'user-two')

    def test_project_denial_keeps_only_identity_and_rechecks_reinstatement(self):
        sid, _ = self.login()
        self.accounts[0].allowed = False
        self.assertEqual(self.sessions.inspect(sid)['state'],'denied')
        self.assert_error(403,'FORBIDDEN',lambda:self.sessions.read(sid,'/api/demo/context',{}))
        self.accounts[0].allowed = True
        self.assertEqual(len(self.sessions.read(sid,'/api/demo/context',{})['items']),5)

    def test_project_denial_at_login_does_not_return_catalogue(self):
        factory = self.sessions.factory
        def denied(base):
            item=factory(base); item.allowed=False; return item
        self.sessions.factory=denied
        sid, view=self.login()
        self.assertEqual(view['state'],'denied')
        self.assertNotIn('items',view)
        self.assert_error(403,'FORBIDDEN',lambda:self.sessions.read(sid,'/api/demo/context',{}))

    def test_upper_401_invalidates_local_session(self):
        sid, _ = self.login(); self.accounts[0].expired = True
        self.assert_error(401,'SESSION_EXPIRED',lambda:self.sessions.read(sid,'/api/demo/context',{}))
        self.assertNotIn(sid,self.sessions.rows)

    def test_idle_expiry_and_poll_does_not_extend_activity(self):
        sid, _ = self.login()
        self.now += IDLE_SECONDS - 1
        self.sessions.inspect(sid)
        self.now += 1
        self.assert_error(401,'SESSION_EXPIRED',lambda:self.sessions.inspect(sid))

    def test_real_activity_extends_idle_but_never_absolute_deadline(self):
        sid, _ = self.login()
        for _ in range(MAX_SECONDS // 1000 - 1):
            self.now += 1000; self.sessions.inspect(sid,activity=True)
        self.now=1000+MAX_SECONDS
        self.assert_error(401,'SESSION_EXPIRED',lambda:self.sessions.inspect(sid,activity=True))

    def test_login_limit_is_per_client_and_does_not_lock_accounts(self):
        for _ in range(10):
            self.assert_error(401,'CREDENTIALS_REJECTED',lambda:self.sessions.login(self.sid,
                {'username':'user','password':'bad','expectedSessionRevision':self.row.revision},'client-one'))
        self.assert_error(429,'LOGIN_RATE_LIMITED',lambda:self.sessions.login(self.sid,{},'client-one'))
        self.sessions.limit_login('client-two')
        self.now += 60
        self.sessions.limit_login('client-one')

    def test_cancel_during_login_cannot_create_a_late_authenticated_session(self):
        started, release=Event(),Event()
        factory=self.sessions.factory
        def slow(base):
            item=factory(base); item.started=started; item.wait=release; return item
        self.sessions.factory=slow
        result=[]
        def login():
            try: self.login()
            except PreviewError as error: result.append(error.code)
        thread=Thread(target=login); thread.start(); self.assertTrue(started.wait(2))
        self.sessions.logout(self.sid,self.row.revision)
        release.set(); thread.join(3)
        self.assertEqual(result,['SESSION_CHANGED'])
        self.assertFalse(any(row.status=='active' for row in self.sessions.rows.values()))

    def test_cancel_after_rotation_revokes_delayed_login_cookie(self):
        sid,_=self.login()
        self.sessions.logout(self.sid,self.row.revision)
        self.assert_error(401,'SESSION_EXPIRED',lambda:self.sessions.inspect(sid))

    def test_logout_version_conflict_does_not_destroy_new_session(self):
        sid,_=self.login()
        self.assert_error(409,'SESSION_CHANGED',lambda:self.sessions.logout(sid,'old-revision'))
        self.assertEqual(self.sessions.inspect(sid)['state'],'active')

    def test_logout_drops_inflight_engineering_response(self):
        sid,_=self.login(); account=self.accounts[0]
        account.started,account.wait=Event(),Event(); result=[]
        def read():
            try: result.append(self.sessions.read(sid,'/api/demo/context',{}))
            except PreviewError as error: result.append(error.code)
        thread=Thread(target=read);thread.start();self.assertTrue(account.started.wait(2))
        self.sessions.logout(sid,self.sessions.rows[sid].revision)
        account.wait.set();thread.join(3)
        self.assertEqual(result,['SESSION_EXPIRED'])

    def test_fixed_five_roles_and_three_cabinets_and_child_host(self):
        sid,view=self.login()
        self.assertEqual(len(self.sessions.read(sid,'/api/demo/context',{})['items']),5)
        for uid,key in [(CT,'CT'),(CN1,'CN1'),(CN,'CN'),(CHILD,'CN')]:
            data=self.sessions.read(sid,'/api/demo/locate',{'entityUid':[uid],'unitLabel':['7'],'contextEpoch':['17']})
            self.assertEqual(data['componentKey'],key)
            self.assertEqual(data['selectedObjectRef']['entityUid'],uid)
            self.assertEqual(data['sessionRevision'],view['sessionRevision'])
            self.assertFalse(data['engineeringUseAllowed'])
        self.assert_error(404,'NOT_FOUND_OR_FORBIDDEN',lambda:self.sessions.read(sid,'/api/demo/locate',
                    {'entityUid':['other'],'unitLabel':['7'],'contextEpoch':['18']}))

    def test_input_cannot_select_connection_project_or_other_unit(self):
        sid,_=self.login()
        self.assert_error(422,'INVALID_REQUEST',lambda:self.sessions.read(sid,'/api/demo/context',{'project':['other']}))
        self.assert_error(409,'INSTANCE_MISMATCH',lambda:self.sessions.read(sid,'/api/demo/locate',
                    {'entityUid':[CHILD],'unitLabel':['8'],'contextEpoch':['1']}))

    def test_authorization_changed_mid_read_cannot_return_old_details(self):
        sid,_=self.login();account=self.accounts[0]; original=account.request
        def changing(method,path,body=None):
            data=original(method,path,body)
            if '/objects?' in path: account.version='grant-2'
            return data
        account.request=changing
        self.assert_error(409,'ACCESS_CHANGED',lambda:self.sessions.read(sid,'/api/demo/context',{}))

    def test_upstream_failure_is_never_an_empty_success(self):
        sid,_=self.login()
        def unavailable(*_): raise PreviewError(502,'SOURCE_UNAVAILABLE')
        self.accounts[0].request=unavailable
        self.assert_error(502,'SOURCE_UNAVAILABLE',lambda:self.sessions.read(sid,'/api/demo/context',{}))

    def test_malformed_login_response_can_be_retried_without_stuck_pending_state(self):
        factory=self.sessions.factory
        def malformed(base):
            account=factory(base)
            account.request=lambda *_args: {'token':None,'user':None}
            return account
        self.sessions.factory=malformed
        self.assert_error(502,'SOURCE_UNAVAILABLE',self.login)
        self.assertEqual(self.row.status,'anonymous')
        self.sessions.factory=factory
        self.assertEqual(self.login()[1]['state'],'active')


class HttpTests(unittest.TestCase):
    def setUp(self):
        self.sessions=Sessions('http://127.0.0.1:1234',manifest(),factory=Account)
        self.server=ThreadingHTTPServer(('127.0.0.1',0),handler_type(self.sessions,'https://test.example'))
        self.thread=Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
        self.addCleanup(self.server.server_close);self.addCleanup(self.server.shutdown)
        self.cookie=None

    def request(self, method, path, body=None, headers=None):
        conn=HTTPConnection('127.0.0.1',self.server.server_port,timeout=3)
        self.addCleanup(conn.close)
        actual={'Host':'test.example','Origin':'https://test.example'}
        if self.cookie:actual['Cookie']=self.cookie
        if body is not None: actual['Content-Type']='application/json'
        actual.update(headers or {})
        conn.request(method,path,json.dumps(body) if body is not None else None,actual)
        response=conn.getresponse(); payload=json.loads(response.read())
        return response.status,dict(response.getheaders()),payload

    def bootstrap(self):
        status,headers,data=self.request('GET','/api/session')
        self.cookie=headers['Set-Cookie'].split(';')[0]
        return data

    def test_anonymous_can_only_bootstrap_not_read_engineering(self):
        status,headers,data=self.request('GET','/api/demo/context')
        self.assertEqual(status,401);self.assertNotIn('items',data)
        data=self.bootstrap();self.assertEqual(data['state'],'signedOut')
        self.assertEqual(self.request('GET','/api/demo/context')[0],401)

    def test_cookie_and_no_store_are_enforced_without_token_or_secret_fields(self):
        status,headers,data=self.request('GET','/api/session')
        self.assertIn(COOKIE,headers['Set-Cookie'])
        for flag in ['Secure','HttpOnly','SameSite=Strict','Path=/']:self.assertIn(flag,headers['Set-Cookie'])
        self.assertNotIn('Domain=',headers['Set-Cookie']);self.assertEqual(headers['Cache-Control'],'no-store')
        self.assertEqual(set(data),{'state','sessionRevision'})

    def test_cross_origin_and_bad_host_cannot_set_login_cookie(self):
        for headers in [{'Origin':'https://other.example'},{'Host':'other.example'},{'Sec-Fetch-Site':'cross-site'}]:
            status,actual,data=self.request('POST','/api/session/login',{},headers)
            self.assertEqual(status,403);self.assertNotIn('Set-Cookie',actual)

    def test_malformed_body_and_unsupported_route_never_proxy(self):
        for method,path,body,headers,status in [('POST','/api/session/login',{}, {'Content-Type':'text/plain'},415),
                ('POST','/api/demo/context',{}, {},404),('GET','/api/v1/auth/me',None,{},404),
                ('POST','/api/session/login',[],{},422),('GET','/api/session?source=other',None,{},404)]:
            self.assertEqual(self.request(method,path,body,headers)[0],status)

    def test_login_and_logout_use_http_session_version(self):
        data=self.bootstrap()
        status,headers,view=self.request('POST','/api/session/login',{'username':'fixture','password':'synthetic-password',
            'expectedSessionRevision':data['sessionRevision']})
        self.assertEqual(status,200);self.assertEqual(view['state'],'active')
        old=self.cookie;self.cookie=headers['Set-Cookie'].split(';')[0];self.assertNotEqual(old,self.cookie)
        self.assertEqual(self.request('GET','/api/demo/context')[0],200)
        self.assertEqual(self.request('POST','/api/session/logout',{'expectedSessionRevision':'old'})[0],409)
        status,headers,_=self.request('POST','/api/session/logout',{'expectedSessionRevision':view['sessionRevision']})
        self.assertEqual(status,200);self.assertIn('Max-Age=0',headers['Set-Cookie'])
        self.assertEqual(self.request('GET','/api/demo/context')[0],401)

    def test_invalid_credentials_are_generic_and_rate_limit_has_retry(self):
        data=self.bootstrap()
        for _ in range(10):
            status,_,body=self.request('POST','/api/session/login',{'username':'fixture','password':'bad',
                'expectedSessionRevision':data['sessionRevision']})
            self.assertEqual((status,body),(401,{'code':'CREDENTIALS_REJECTED'}))
        status,headers,_=self.request('POST','/api/session/login',{})
        self.assertEqual(status,429);self.assertEqual(headers['Retry-After'],'60')

    def test_production_origin_cannot_downgrade_to_http(self):
        with self.assertRaises(ValueError):handler_type(self.sessions,'http://test.example')
        with self.assertRaises(ValueError):handler_type(self.sessions,'https://test.example/path')


if __name__=='__main__':unittest.main()
