from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
import json
from threading import Thread
from unittest import TestCase

from apps.api.authority import PreviewError
from apps.api.photo_media import ANALYSIS_BATCH, ANALYSIS_PHOTO, MEDIA_PATH, PHOTO_HEADER, PHOTO_ROUTES, PhotoTickets
from apps.api.project_sessions import ProjectSessions
from apps.api.session_http import handler_type
from apps.api.user_sessions import COOKIE


ORIGIN = 'https://vis.ontobase.ai'
MEDIA = 'https://vis-media.ontobase.ai'
SID = 'authorized-test-session'
FIXED = {'expectedSessionRevision': 'r1', 'projectRef': {'projectCode': 'test'}, 'analysisSessionId': 'a1', 'evidenceRefId': 'photo1'}


class Sessions:
    def __init__(self):
        self.active = True
        self.accessible = True
        self.reads = []

    def authorize_photo_ticket(self, sid, payload):
        if sid != SID or not self.active:
            raise PreviewError(401, 'SESSION_EXPIRED')
        if not self.accessible or payload['projectRef'] != FIXED['projectRef']:
            raise PreviewError(403, 'FORBIDDEN')
        if payload['expectedSessionRevision'] != FIXED['expectedSessionRevision']:
            raise PreviewError(409, 'SESSION_CHANGED')
        return 'r1'

    def fixed_photo_request(self, sid, path, payload):
        self.authorize_photo_ticket(sid, payload)
        self.reads.append((sid, path, payload))
        return {'content': b'fixed', 'mediaType': 'image/avif', 'sessionRevision': 'r1',
                'sha256': 'a'*64, 'fixedPhotoSha256': 'b'*64, 'photoEncodeMs': 98.3}

    def analysis_request(self, sid, path, payload):
        self.authorize_photo_ticket(sid, payload)
        assert path == ANALYSIS_BATCH
        return {'items': [
            {'evidenceRefId':'photo1', 'sourceKind':'photo', 'availability':'available'},
            {'evidenceRefId':'photo2', 'sourceKind':'photo', 'availability':'restricted'},
            {'evidenceRefId':'doc1', 'sourceKind':'document', 'availability':'available'},
        ]}


class PhotoMediaTests(TestCase):
    def setUp(self):
        self.sessions = Sessions()
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), handler_type(self.sessions, ORIGIN, photo_media_origin=MEDIA))
        self.thread = Thread(target=self.server.serve_forever, kwargs={'poll_interval': .03})
        self.thread.start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.thread.join)
        self.addCleanup(self.server.shutdown)

    def request(self, path, body=None, *, host='vis.ontobase.ai', origin=ORIGIN, cookie=SID, method='POST', extras=None):
        with closing(HTTPConnection(*self.server.server_address, timeout=4)) as connection:
            headers = {'Host': host, 'Origin': origin}
            if cookie is not None:
                headers['Cookie'] = COOKIE+'='+cookie
            if body is not None:
                headers['Content-Type'] = 'application/json' if isinstance(body, dict) else 'text/plain'
            headers.update(extras or {})
            connection.request(method, path, json.dumps(body) if isinstance(body, dict) else body, headers)
            reply = connection.getresponse()
            return reply.status, reply.headers, reply.read()

    def issue(self, path=ANALYSIS_PHOTO, payload=FIXED):
        status, headers, body = self.request(path, {**payload, 'representation':'full_resolution_avif'},
            extras={PHOTO_HEADER:'full_resolution_avif'})
        self.assertEqual(status, 200)
        self.assertEqual(headers['Cache-Control'], 'no-store')
        return json.loads(body)['photoTicket']

    def media(self, ticket=None, *, path=MEDIA_PATH, **kwargs):
        return self.request(path, ticket, **({'host':'vis-media.ontobase.ai', 'cookie':None} | kwargs))

    def test_prefetched_grant_carries_only_the_authorized_fixed_photo(self):
        payload = {k:v for k,v in FIXED.items() if k != 'evidenceRefId'} | {'evidenceRefIds':['photo1','photo2','doc1']}
        status, _, result = self.request(ANALYSIS_BATCH, payload, extras={PHOTO_HEADER:'full_resolution_avif'})
        self.assertEqual(status, 200)
        allowed, restricted, document = json.loads(result)['items']
        self.assertNotIn('photoTicket', restricted)
        self.assertNotIn('photoTicket', document)
        status, headers, body = self.media(allowed['photoTicket'])
        self.assertEqual((status, body), (200, b'fixed'))
        self.assertEqual(headers['Cache-Control'], 'no-store')
        self.assertEqual(headers['X-Fixed-Photo-SHA256'], 'b'*64)
        self.assertEqual(headers['X-Session-Revision'], 'r1')
        self.assertEqual(headers['Access-Control-Allow-Origin'], ORIGIN)
        self.assertEqual(headers['Server-Timing'], 'photo-encode;dur=98.3')
        self.assertIsNone(headers.get('Set-Cookie'))
        self.assertEqual(self.sessions.reads, [(SID, ANALYSIS_PHOTO, FIXED | {'representation':'full_resolution_avif'})])
        self.assertEqual(self.media(allowed['photoTicket'])[0], 410)

    def test_delivery_revalidates_current_session_and_project_access(self):
        ticket = self.issue()
        self.sessions.accessible = False
        self.assertEqual(self.media(ticket)[0], 403)
        self.assertEqual(self.media(ticket)[0], 410)
        self.sessions.accessible = True
        ticket = self.issue()
        self.sessions.active = False
        self.assertEqual(self.media(ticket)[0], 401)
        self.assertFalse(self.sessions.reads)

    def test_media_origin_only_accepts_its_exact_post_and_safelisted_preflight(self):
        ticket = self.issue()
        self.assertEqual(self.media(ticket, path='/api/session')[0], 404)
        self.assertEqual(self.media(ticket, path=MEDIA_PATH+'?ticket=x')[0], 404)
        self.assertEqual(self.media(ticket, method='GET')[0], 404)
        status, headers, _ = self.media(ticket, origin='https://unrelated.test')
        self.assertEqual(status, 403)
        self.assertIsNone(headers.get('Access-Control-Allow-Origin'))
        self.assertEqual(self.media(ticket, cookie=SID)[0], 401)
        self.assertEqual(self.media()[0], 401)
        self.assertEqual(self.media('X'*43)[0], 410)
        self.assertEqual(self.media(method='OPTIONS', extras={'Access-Control-Request-Method':'POST',
            'Access-Control-Request-Headers':'content-type'})[0], 204)
        self.assertFalse(self.sessions.reads)
        self.assertEqual(self.media(ticket)[0], 200)

    def test_issue_uses_session_revision_and_project_scope_for_each_fixed_route(self):
        for path in PHOTO_ROUTES:
            with self.subTest(path=path):
                self.assertEqual(self.media(self.issue(path))[0], 200)
                self.assertEqual(self.sessions.reads[-1][1], path)
        for body, status in ((FIXED|{'expectedSessionRevision':'old'},409), (FIXED|{'projectRef':{}},403)):
            reply = self.request(ANALYSIS_PHOTO, body|{'representation':'full_resolution'}, extras={PHOTO_HEADER:'full_resolution'})
            self.assertEqual(reply[0], status)
            self.assertNotIn('photoTicket', json.loads(reply[2]))

    def test_ticket_expiry_and_concurrent_redemption(self):
        now = [40]
        store = PhotoTickets(lambda:now[0])
        expired = store.issue(SID, ANALYSIS_PHOTO, FIXED).encode()
        now[0] += 91
        with self.assertRaises(PreviewError) as failure:
            store.consume(expired)
        self.assertEqual(failure.exception.status, 410)
        ticket = self.issue()
        with ThreadPoolExecutor(max_workers=2) as pool:
            self.assertEqual(sorted(pool.map(lambda _:self.media(ticket)[0], range(2))), [200,410])

    def test_non_photo_results_do_not_escape_the_fixed_photo_method(self):
        self.sessions.analysis_request = lambda *args, **kwargs: {'mediaType':'image/png'}
        with self.assertRaises(PreviewError) as failure:
            ProjectSessions.fixed_photo_request(self.sessions, SID, ANALYSIS_PHOTO, FIXED)
        self.assertEqual(failure.exception.status, 404)
