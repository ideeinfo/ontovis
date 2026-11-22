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
    BrowserCheck, PASSWORD_ENV, SCRIPTS, USERNAME_ENV, isolated, public_13002, public_browser, verify,
)

RECEIPT = 'workbench-release-check.json'
SUITES = {'13002','assistantModelUsage','analysisSaveRecovery','fixedEvidenceAccess'}
SOURCE_SERVICES = {'ontobase-api','ontobase-web','ontobase-worker','ontobase-region-ocr'}
SOURCE_RELEASE_ENV = 'ONTOVIS_EXPECTED_SOURCE_RELEASE'


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
    with browser_site(dist) as (facts,advance,revoked,model_calls,verify_saved):
        browser.open('models')
        details = browser.run('models',script,facts,'browse')
        verify(details and details['laterScene'], 'Missing model catalogue pagination receipt')
        facts['newRevision'] = advance()
        changed = browser.run('models',script,facts,'changed')
        verify(changed and changed['refreshAfterChange'], 'Missing fixed scene and refresh receipt')
        revoked.set()
        denied = browser.run('models',script,facts,'revoke')
        verify(denied and denied['revokedStatus']==403,
               'Model catalogue permission or no-generation check failed')
        revoked.clear()
        edited = browser.run('models',script,facts,'edit')
        verify(edited and edited['enteredEditor'] and model_calls==['plan','answer'],
               'Scene edit handoff or no-generation check failed')
        verify_saved(edited['savedRevision'])
        return {**details,**changed,**denied,**edited,'modelCallsDuringBrowsing':0}


def analysis_save_recovery(browser, dist):
    from tests.analysis_save_recovery_fixture import browser_site

    script = (SCRIPTS/'analysis_save_recovery.js').read_text()
    with browser_site(dist) as (facts,hold_slots,detail,advance,revisions):
        browser.open('analysis-save')

        def run(phase):
            result = browser.run('analysis-save',script,facts,phase)
            verify(type(result) is dict, f'Missing analysis save receipt for {phase}')
            return result

        run('open')
        with hold_slots():
            busy = run('busy')
        unchanged = detail()
        verify(unchanged['analysisRevision']==1 and unchanged['contentSha256']==facts['initialSha'],
               'The busy request changed the canvas')
        facts['originalRequest'] = busy.pop('originalRequest')
        saved = run('retry-busy')
        dropped = run('disconnect')
        facts.update(originalRequest=dropped.pop('originalRequest'),committedSha=dropped['sha256'])
        verify(detail()['contentSha256']==dropped['sha256'], 'The disconnected response did not persist revision 3')
        replayed = run('retry-disconnect')
        verify(revisions()==[3,2,1], 'Retried save created a duplicate or missing revision')
        new_head = advance()
        conflict = run('conflict')
        final_revisions = revisions()
        verify(final_revisions==[4,3,2,1] and detail()['contentSha256']==new_head['contentSha256'],
               'A stale write changed the saved canvas')
        verify(detail(1)['contentSha256']==facts['initialSha'] and detail(2)['contentSha256']==saved['sha256']
               and detail(3)['contentSha256']==dropped['sha256'], 'An earlier revision changed')
        return dict(busy=busy,saved=saved,disconnected=dropped,replayed=replayed,conflict=conflict,revisions=final_revisions)


def fixed_evidence_access(browser, dist):
    from tests.analysis_fixed_access_fixture import browser_site

    script = (SCRIPTS/'analysis_fixed_access.js').read_text()
    results = {}
    with browser_site(dist) as (facts,restore,verify_snapshot):
        for mode in ('withdraw-document','switch-project','expire-session','withdraw-project'):
            browser.open(mode)
            try:
                result = browser.run(mode,script,facts,mode)
                verify(type(result) is dict, f'Missing fixed evidence access receipt for {mode}')
                results[mode] = result
            finally:
                restore()
        verify_snapshot()
        return results


def candidate(browser, release, dist, output):
    receipt = dict(mode='candidate',release=release,recordedAt=timestamp(),passed=False)
    record(output,receipt)
    identity = build_identity(dist)
    try:
        results = {'assistantModelUsage':assistant_model_usage(browser,dist),
                   'analysisSaveRecovery':analysis_save_recovery(browser,dist),
                   'fixedEvidenceAccess':fixed_evidence_access(browser,dist),'13002':isolated(browser,dist)}
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


def source_probe(command, action, *args):
    result = subprocess.run([str(command),action,*args],capture_output=True,text=True,timeout=90)
    verify(result.returncode==0,f'Source {action} check failed')
    return json.loads(result.stdout)


def source_runtime(command, observations):
    inventory = source_probe(command,'runtime')
    verify(type(inventory) is dict and set(inventory)==SOURCE_SERVICES, 'The source inventory is incomplete')
    observed = {}
    for service, row in inventory.items():
        verify(type(row) is dict and type(row.get('release')) is str and re.fullmatch('[a-f0-9]{40}',row['release']),
               f'The source service {service} has no verified release')
        observed[service] = dict(release=row['release'],health='healthy' if row.get('health')=='healthy' else 'not-ready')
    observations.append(observed)
    verify(all(row['health']=='healthy' for row in observed.values()), 'A source service is not ready')
    releases = {row['release'] for row in observed.values()}
    verify(len(releases)==1,'The source rollout is still in progress')
    return releases.pop()


def source_preflight(command, release, output):
    receipt = dict(mode='sourcePreflight',release=release,recordedAt=timestamp(),passed=False)
    area = output/'preflight'
    record(area,receipt)
    observations = []
    try:
        source = source_runtime(command,observations)
        for _ in range(2):
            try:
                checked = source_probe(command,'compatibility',source)
                verify(type(checked) is dict and checked.get('compatible') is True and checked.get('sourceRelease')==source,
                       'Source compatibility was not verified for the observed release')
            except (RuntimeError,ValueError,subprocess.TimeoutExpired):
                current = source_runtime(command,observations)
                if source==current:
                    raise
            else:
                current = source_runtime(command,observations)
                if source==current:
                    receipt.update(passed=True,sourceRelease=source)
                    return source
            source = current
        raise RuntimeError('The source release changed again during compatibility checks')
    finally:
        record(area,dict(receipt,runtimeChecks=observations))


def promote(dist, release, output, command, source_command):
    receipt = require_candidate(dist,release,output)
    source = source_preflight(source_command,release,output)
    env = dict(os.environ)
    for name in (USERNAME_ENV,PASSWORD_ENV):
        env.pop(name,None)
    env[SOURCE_RELEASE_ENV] = source
    subprocess.run(command,env=env,check=True)
    return {**receipt,'sourceRelease':source}


def load_evidence_case(path):
    case = json.loads(path.read_text())
    def matches(value, pattern):
        return type(value) is str and re.fullmatch(pattern,value) is not None

    identifier = r'[A-Za-z0-9_.:-]{1,200}'
    digest = r'[a-f0-9]{64}'
    uuid = r'[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}'
    verify(type(case) is dict and set(case)=={'analysisSessionId','analysisRevision','contentSha256','datasetRevision','cards'}
           and matches(case['analysisSessionId'],uuid) and type(case['analysisRevision']) is int
           and 1<=case['analysisRevision']<=1000 and all(matches(case[key],digest) for key in ('contentSha256','datasetRevision'))
           and type(case['cards']) is list and len(case['cards'])==6, 'Invalid 13001 acceptance case')

    extra = {
        'document':{'documentId':uuid,'contentVersionId':uuid,'knowledgeReleaseId':uuid,'sourceSha256':digest},
        'drawing':{'drawingUid':identifier,'contentSha256':digest},
        'work_order':{'orderId':identifier},
    }
    checked = {'document':[],'drawing':[],'work_order':[]}
    for card in case['cards']:
        verify(type(card) is dict and type(card.get('kind')) is str and card['kind'] in extra, 'Invalid fixed source kind')
        kind = card['kind']
        number = 'orderRevision' if kind=='work_order' else 'pageNumber'
        fields = dict(extra[kind],cardId=identifier,evidenceRefId=uuid,sourceRevision=digest)
        verify(set(card)==set(fields)|{'kind',number} and all(matches(card[name],pattern) for name,pattern in fields.items())
               and type(card[number]) is int and card[number]>0, 'Invalid fixed source in the 13001 acceptance case')
        checked[kind].append(card[number])
    verify(len({card['cardId'] for card in case['cards']})==len({card['evidenceRefId'] for card in case['cards']})==6
           and sorted(checked['document'])==[9,53] and sorted(checked['drawing'])==[89,189,228]
           and checked['work_order']==[6], '13001 needs both manual pages, three drawings and the historical order')
    return case


def public_evidence(browser, role, origin, case):
    script = (SCRIPTS/'analysis_13001_public.js').read_text()
    results = {}
    for mode in ('workbench','cockpit'):
        row = browser.run(role,script,origin,case,mode)
        verify(type(row) is dict and row.get('analysisRevision')==case['analysisRevision']
               and row.get('analysisSha256')==case['contentSha256'] and row.get('readOnly') is True
               and len(row.get('sources',[]))==len(case['cards']), f'Missing fixed evidence receipt for {mode}')
        results[mode] = row
    verify(results['workbench']['sources']==results['cockpit']['sources'],
           'Workbench and cockpit opened different fixed sources')
    return results


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
    parser.add_argument('--evidence-case',type=Path,help='Private JSON manifest of the fixed 13001 acceptance canvas')
    parser.add_argument('--source-preflight',type=Path,help='Source runtime and compatibility probe executable before activation')
    parser.add_argument('--activation-command',nargs=argparse.REMAINDER,
                        help='Existing deployment command, supplied last for the activate phase')
    args = parser.parse_args()
    if not re.fullmatch('[a-f0-9]{40}',args.release):
        parser.error('--release requires the full git commit')
    if (args.phase=='activate') != bool(args.activation_command) or (args.phase=='activate') != bool(args.source_preflight):
        parser.error('Activate requires --source-preflight and --activation-command')
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
    if not args.evidence_case:
        parser.error('Public checks require --evidence-case')
    try:
        case = load_evidence_case(args.evidence_case)
    except (OSError,ValueError,RuntimeError) as error:
        parser.error(str(error))
    verified = (promote(args.dist,args.release,output,args.activation_command,args.source_preflight.resolve()) if args.phase=='activate'
                else require_candidate(args.dist,args.release,output))
    browser = BrowserCheck(cli,area,args.browser)
    try:
        with public_browser(browser,origin,args.release) as role:
            orders = public_13002(browser,role,origin,args.release,verified['indexSha256'])
            verify(bool(orders),'The public 13002 browser check returned no receipt')
            if args.phase=='activate':
                verify(orders.get('sourceRelease')==verified['sourceRelease'],
                       'The public release reports a different source than preflight')
            results = {'13002':orders,'evidence13001':public_evidence(browser,role,origin,case)}
    finally:
        browser.close()
    receipt.update(passed=True,indexSha256=verified['indexSha256'],distSha256=verified['distSha256'],results=results)
    record(area,receipt)
    print('Public browser check passed',flush=True)


if __name__=='__main__':
    main()
