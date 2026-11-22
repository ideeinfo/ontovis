"""Gate a workbench release on the candidate and public browser checks."""
import argparse
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import subprocess
from tempfile import NamedTemporaryFile
from urllib.parse import urlsplit

from tools.check_workbench_13002 import (
    BrowserCheck, PASSWORD_ENV, SCRIPTS, USERNAME_ENV, isolated, public, verify,
)

RECEIPT = 'workbench-release-check.json'
SUITES = {'13002','assistantModelUsage'}


def build_identity(dist):
    dist = dist.resolve(strict=True)
    verify((dist/'index.html').is_file(), 'A built workbench index is required')
    entries = []
    for path in sorted(dist.rglob('*')):
        verify(not path.is_symlink(), 'The candidate contains a symbolic link')
        if path.is_file():
            entries.append([path.relative_to(dist).as_posix(),sha256(path.read_bytes()).hexdigest()])
    verify(any(name.startswith('assets/') and name.endswith('.js') for name,_ in entries),
           'A built workbench asset directory is required')
    return dict(indexSha256=dict(entries)['index.html'],
                distSha256=sha256(json.dumps(entries,separators=(',',':')).encode()).hexdigest())


def record(output, receipt):
    output.mkdir(parents=True,exist_ok=True)
    run_file = output/RECEIPT
    with NamedTemporaryFile('w',encoding='utf-8',dir=output,delete=False) as stream:
        scratch = Path(stream.name)
        try:
            json.dump(receipt,stream,ensure_ascii=False,indent=2)
            stream.write('\n')
            stream.flush()
            scratch.replace(run_file)
        finally:
            scratch.unlink(missing_ok=True)


def assistant_model_usage(browser, dist):
    from tests.assistant_model_usage_fixture import browser_site

    script = (SCRIPTS/'assistant_model_usage.js').read_text()
    with browser_site(dist) as (facts,advance,revoke,model_calls):
        browser.open('models')
        details = browser.run('models',script,facts,'browse')
        verify(details and details['laterScene'], 'Missing model catalogue pagination receipt')
        facts['newRevision'] = advance()
        changed = browser.run('models',script,facts,'changed')
        verify(changed and changed['refreshAfterChange'], 'Missing fixed scene and refresh receipt')
        revoke()
        denied = browser.run('models',script,facts,'revoke')
        verify(denied and denied['revokedStatus']==403 and model_calls==['plan','answer'],
               'Model catalogue permission or no-generation check failed')
        return {**details,**changed,**denied,'modelCallsDuringBrowsing':0}


def candidate(browser, release, dist, output):
    receipt = dict(mode='candidate',release=release,recordedAt=timestamp(),passed=False)
    record(output,receipt)
    identity = build_identity(dist)
    try:
        results = {'assistantModelUsage':assistant_model_usage(browser,dist),'13002':isolated(browser,dist)}
        verify(build_identity(dist)==identity, 'The build changed during browser checks')
    finally:
        browser.close()
    receipt.update(passed=True,**identity,results=results)
    record(output,receipt)


def require_candidate(dist, release, output):
    path = output/'candidate'/RECEIPT
    verify(path.is_file(), 'No browser candidate receipt exists')
    receipt = json.loads(path.read_text())
    verify(receipt.get('mode')=='candidate' and receipt.get('passed') is True and receipt.get('release')==release,
           'Successful checks for this release are required')
    suites = receipt.get('results')
    verify(type(suites) is dict and set(suites)==SUITES and all(suites.values()), 'A candidate browser suite is missing')
    verify(all(receipt.get(key)==value for key,value in build_identity(dist).items()),
           'The release build differs from the checked candidate')
    return receipt


def promote(dist, release, output, command):
    receipt = require_candidate(dist,release,output)
    env = dict(os.environ)
    for name in (USERNAME_ENV,PASSWORD_ENV):
        env.pop(name,None)
    subprocess.run(command,env=env,check=True)
    return receipt


def timestamp():
    return datetime.now(timezone.utc).isoformat()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('phase',choices=('candidate','activate','public'))
    parser.add_argument('--release',required=True)
    parser.add_argument('--dist',required=True,type=Path)
    parser.add_argument('--output',required=True,type=Path)
    parser.add_argument('--playwright-cli',default='playwright-cli')
    parser.add_argument('--browser',default='chrome')
    parser.add_argument('--origin',default='https://vis.ontobase.ai')
    parser.add_argument('--activation-command',nargs=argparse.REMAINDER,
                        help='Existing deployment command, supplied last for the activate phase')
    args = parser.parse_args()
    if not re.fullmatch('[a-f0-9]{40}',args.release):
        parser.error('--release requires the full git commit')
    if (args.phase=='activate') != bool(args.activation_command):
        parser.error('Only activate requires an --activation-command')
    if args.phase=='candidate' and not os.environ.get('ONTOVIS_ANALYSIS_TEST_DATABASE_URL'):
        parser.error('The candidate requires a disposable PostgreSQL test database')
    origin = args.origin.rstrip('/')
    parsed = urlsplit(origin)
    if args.phase!='candidate' and (parsed.scheme!='https' or not parsed.hostname or parsed.username or parsed.password
            or parsed.path or parsed.query or parsed.fragment or not all(os.environ.get(name) for name in (USERNAME_ENV,PASSWORD_ENV))):
        parser.error('Public checks require an HTTPS origin and the release-check account in the environment')
    output = args.output.resolve()
    cli = str(Path(args.playwright_cli).resolve()) if '/' in args.playwright_cli else args.playwright_cli
    if args.phase=='candidate':
        area = output/'candidate'
        candidate(BrowserCheck(cli,area,args.browser),args.release,args.dist,area)
        print('Candidate browser checks passed',flush=True)
        return

    area = output/'public'
    receipt = dict(mode='public',release=args.release,recordedAt=timestamp(),passed=False)
    record(area,receipt)
    verified = (promote(args.dist,args.release,output,args.activation_command) if args.phase=='activate'
                else require_candidate(args.dist,args.release,output))
    browser = BrowserCheck(cli,area,args.browser)
    try:
        results = public(browser,origin,args.release,verified['indexSha256'])
        verify(bool(results),'The public browser check returned no receipt')
    finally:
        browser.close()
    receipt.update(passed=True,indexSha256=verified['indexSha256'],distSha256=verified['distSha256'],results=results)
    record(area,receipt)
    print('Public browser check passed',flush=True)


if __name__=='__main__':
    main()
