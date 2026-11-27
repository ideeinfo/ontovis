"""Drive real analysis saves against a disposable database from the browser."""
from contextlib import contextmanager
from uuid import uuid4

from tests.test_analysis_drafts import snapshot
from tests.test_work_order_workflow_integration import ANALYSIS
from tests.work_order_13002_fixture import EndToEnd, PROJECT, serve_workbench


@contextmanager
def browser_site(public):
    public = public.resolve(strict=True)
    if not (public/'index.html').is_file():
        raise ValueError('A built workbench directory is required')
    fixture = EndToEnd()
    fixture.setUpClass()
    try:
        fixture.setUp()
        fixture.source.projects = {PROJECT:'Q-13 合成项目'}
        fixture.source.permissions = {'writer':{PROJECT:'admin'}}
        fixture.admin = fixture.login('writer')
        board = snapshot()
        title = 'Q-13 隔离验收 · 保存恢复'
        board.update(schemaVersion=2,projectCode=PROJECT,ontobaseConnectionId='ontobase-primary',title=title)
        initial = fixture.ok(ANALYSIS+'/create',dict(snapshot=board,requestId=str(uuid4())))
        analysis_id = initial['analysisSessionId']

        @contextmanager
        def busy():
            held = 0
            try:
                for _ in range(4):
                    assert fixture.sessions.analysis_slots.acquire(timeout=5)
                    held += 1
                yield
            finally:
                for _ in range(held):
                    fixture.sessions.analysis_slots.release()

        def detail(revision=None):
            request = dict(analysisSessionId=analysis_id)
            if revision is not None:
                request['analysisRevision'] = revision
            return fixture.ok(ANALYSIS+'/detail',request)

        def advance():
            current = detail()
            updated = dict(current['snapshot'],title=title+' · 并行会话')
            return fixture.ok(ANALYSIS+'/save',dict(analysisSessionId=analysis_id,snapshot=updated,
                expectedAnalysisRevision=current['analysisRevision'],requestId=str(uuid4())))

        def revisions():
            return [row['revision'] for row in fixture.ok(ANALYSIS+'/revisions',dict(analysisSessionId=analysis_id,limit=10))['items']]

        with serve_workbench(public,fixture.sessions) as origin:
            yield dict(origin=origin,title=title,analysisId=analysis_id,initialSha=initial['contentSha256']),busy,detail,advance,revisions
    finally:
        fixture.doCleanups()
        fixture.tearDownClass()
