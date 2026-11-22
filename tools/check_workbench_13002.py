"""Run the 13002 browser regression before and after a workbench release."""
from contextlib import contextmanager
from datetime import datetime, timezone
from hashlib import sha256
from http.cookiejar import CookieJar
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from secrets import token_urlsafe
from threading import Thread
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import HTTPCookieProcessor, ProxyHandler, Request, build_opener
from uuid import uuid4
import argparse
import json
import os
import re
import subprocess

from apps.api.authority import NoRedirect
from apps.api.user_sessions import COOKIE

SCRIPTS = Path(__file__).resolve().parents[1]/'tests/browser'
USERNAME_ENV = 'ONTOVIS_RELEASE_USERNAME'
PASSWORD_ENV = 'ONTOVIS_RELEASE_PASSWORD'


def verify(condition, message):
    if not condition:
        raise RuntimeError(message)


class BrowserCheck:
    def __init__(self, cli, output, browser):
        self.cli, self.output, self.browser = cli, output, browser
        self.prefix = 'ontovis-13002-' + uuid4().hex[:12]
        self.sessions = set()
        self.env = {k:v for k,v in os.environ.items() if k not in (USERNAME_ENV, PASSWORD_ENV)}

    def call(self, role, *args, timeout=110):
        result = subprocess.run([self.cli, '-s='+self.prefix+'-'+role, *args], cwd=self.output,
                                env=self.env, capture_output=True, text=True, timeout=timeout)
        output = result.stdout
        if result.returncode or re.search(r'^### Error', output, re.M):
            detail = output.split('### Ran Playwright code')[0].strip()
            detail = re.sub(r'http://127\.0\.0\.1:\d+/[\w-]+', '[local handoff]', detail)
            raise RuntimeError(f'Browser check failed for {role}. {detail[-1500:]}')
        return output

    def open(self, role):
        self.call(role, 'open', 'about:blank', '--browser='+self.browser)
        self.sessions.add(role)

    def run(self, role, script, *args):
        arguments = ''.join(','+json.dumps(value,ensure_ascii=False) for value in args)
        result = self.call(role, 'run-code', f'async page=>({script})(page{arguments})', timeout=180)
        if '### Result\n' in result:
            return json.loads(result.split('### Result\n',1)[1].split('\n###',1)[0])
        return None

    def close(self):
        for role in self.sessions:
            self.call(role, 'close', timeout=20)


def isolated(browser, dist):
    from tests.work_order_13002_fixture import browser_site

    script = (SCRIPTS/'work_order_13002.js').read_text()
    roles = {'create':'manager','treat':'handler','revoke':'handler','archive':'manager','view':'viewer'}
    results = {}
    with browser_site(dist) as (facts, revoke):
        for phase, role in roles.items():
            if role not in browser.sessions:
                browser.open(role)
            if phase == 'revoke':
                revoke()
            row = browser.run(role, script, facts, phase)
            verify(isinstance(row,dict), f'Missing {phase} receipt')
            for key in ('orderId','initialSha256','recordId','replayBody'):
                if key in row:
                    facts[key] = row[key]
            results[phase] = {k:v for k,v in row.items() if k != 'replayBody'}
            print(f'13002 {phase} passed',flush=True)
    return results


@contextmanager
def signed_in(origin, release):
    jar = CookieJar()
    opener = build_opener(ProxyHandler({}), NoRedirect(), HTTPCookieProcessor(jar))

    def request(path, payload=None):
        data = json.dumps(payload).encode() if payload is not None else None
        headers = {'Origin':origin,'Content-Type':'application/json'} if data else {}
        try:
            with opener.open(Request(origin+path,data,headers), timeout=30) as reply:
                return json.load(reply)
        except HTTPError as error:
            raise RuntimeError(f'{path} returned HTTP {error.code}') from None

    health = request('/health')
    verify(health.get('status')=='ok' and health.get('frontendRelease')==health.get('backendRelease')==release,
           'The public site does not serve the expected release')
    session = request('/api/session')
    active = request('/api/session/login',dict(username=os.environ[USERNAME_ENV],password=os.environ[PASSWORD_ENV],
                                               expectedSessionRevision=session['sessionRevision']))
    verify(active.get('state')=='active','The release-check account could not sign in')
    try:
        cookies = [dict(name=cookie.name,value=cookie.value,url=origin,httpOnly=True,secure=True,sameSite='Strict')
                   for cookie in jar if cookie.name==COOKIE and cookie.secure]
        verify(len(cookies)==1,'The public site did not issue an authenticated session')
        yield cookies
    finally:
        request('/api/session/logout', dict(expectedSessionRevision=active['sessionRevision']))


@contextmanager
def cookie_handoff(cookies):
    path = '/'+token_urlsafe(32)
    body = json.dumps(cookies).encode()

    class Bridge(BaseHTTPRequestHandler):
        def log_message(self,*_args):
            pass

        def do_GET(self):
            nonlocal body
            if self.path != path or not body:
                return self.send_error(404)
            payload,body = body,b''
            self.send_response(200)
            self.send_header('Content-Type','application/json')
            self.send_header('Cache-Control','no-store')
            self.send_header('Content-Length',str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

    with HTTPServer(('127.0.0.1',0),Bridge) as server:
        thread = Thread(target=server.serve_forever,daemon=True)
        thread.start()
        try:
            yield f'http://127.0.0.1:{server.server_port}'+path
        finally:
            server.shutdown()
            thread.join()


def public(browser, origin, release):
    with signed_in(origin,release) as cookies:
        browser.open('public')
        with cookie_handoff(cookies) as url:
            browser.run('public', """async (page,url)=>{
              const response=await page.request.get(url);
              if(!response.ok())throw Error('Could not transfer browser session');
              await page.context().addCookies(await response.json());
            }""", url)
        return browser.run('public',(SCRIPTS/'work_order_13002_public.js').read_text(),
                           dict(origin=origin,release=release))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode',choices=('candidate','public'))
    parser.add_argument('--release',required=True,help='Full git SHA of the workbench release')
    parser.add_argument('--output',required=True,type=Path)
    parser.add_argument('--playwright-cli',default='playwright-cli')
    parser.add_argument('--browser',default='chrome')
    parser.add_argument('--dist',type=Path)
    parser.add_argument('--origin',default='https://vis.ontobase.ai')
    args = parser.parse_args()
    if not re.fullmatch('[a-f0-9]{40}',args.release):
        parser.error('--release requires a full git SHA')
    if args.mode=='candidate' and (args.dist is None or not os.environ.get('ONTOVIS_ANALYSIS_TEST_DATABASE_URL')):
        parser.error('Candidate check requires --dist and a disposable ONTOVIS_ANALYSIS_TEST_DATABASE_URL')
    origin = args.origin.rstrip('/')
    parsed = urlsplit(origin)
    if args.mode=='public' and (parsed.scheme!='https' or not parsed.hostname or parsed.username
            or parsed.path or parsed.query or parsed.fragment or not os.environ.get(USERNAME_ENV)
            or not os.environ.get(PASSWORD_ENV)):
        parser.error('Public check requires an HTTPS origin and the release-check account in the environment')
    output = args.output.resolve()
    output.mkdir(parents=True,exist_ok=True)
    cli = str(Path(args.playwright_cli).resolve()) if '/' in args.playwright_cli else args.playwright_cli
    browser = BrowserCheck(cli,output,args.browser)
    receipt = dict(mode=args.mode,release=args.release,recordedAt=datetime.now(timezone.utc).isoformat(),passed=False)
    try:
        try:
            if args.mode=='candidate':
                results = isolated(browser,args.dist)
                receipt['indexSha256'] = sha256((args.dist/'index.html').read_bytes()).hexdigest()
            else:
                results = public(browser,origin,args.release)
        finally:
            browser.close()
        verify(bool(results),'Missing browser check results')
        receipt.update(passed=True,results=results)
    finally:
        (output/'13002-release-check.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+'\n')
    print('13002 browser check passed',flush=True)


if __name__ == '__main__':
    main()
