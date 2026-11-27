"""A stopped and restarted loopback-only workbench with pinned synthetic GIS data."""
from contextlib import closing, contextmanager
from copy import deepcopy
from hashlib import sha256
from multiprocessing import get_context
from os import getpid
from pathlib import Path
import sys

from apps.api.imagery_uploads import CHUNK_BYTES
from apps.api.project_sessions import ProjectSessions
from tests.test_imagery_http import ImageryHttpTests
from tests.test_imagery_library import metadata
from tests.test_project_workspaces import ProjectsAuthority
from tests.test_scene_http import CONTEXT
from tests.work_order_13002_fixture import serve_workbench

PROJECT = 'fixture-project'
TITLE = 'Q-08 影像续传隔离项目'
HISTORICAL = 'Q-08 历史影像'
UPLOAD = 'Q-08 本次合成影像'


class ImageryAuthority(ProjectsAuthority):
    projects = {PROJECT: TITLE}
    permissions = {'writer': {PROJECT: 'admin'}, 'reader': {PROJECT: 'viewer'}}

    def request(self, method, path, body=None):
        if method == 'GET' and path.endswith(('/installations', '/objects')):
            return {'items': [], 'total': 0, 'nextCursor': None}
        return super().request(method, path, body)


def create_transfer(path):
    import numpy as np
    import rasterio
    from rasterio.transform import from_origin

    size = 400
    pixels = np.random.default_rng(8).integers(0, 256, (3, size, size), dtype='uint8')
    with rasterio.open(path, 'w', driver='GTiff', width=size, height=size, count=3, dtype='uint8',
                       crs='EPSG:32649', transform=from_origin(500000, 3700000, 0.8, 0.8)) as image:
        image.write(pixels)
    data = path.read_bytes()
    assert CHUNK_BYTES * 3 < len(data) < CHUNK_BYTES * 4
    return dict(file=str(path), bytes=len(data), sourceSha256=sha256(data).hexdigest(), chunkBytes=CHUNK_BYTES)


@contextmanager
def imagery_workspace():
    fixture = ImageryHttpTests()
    try:
        fixture.setUp()
        scene = fixture.anchored()
        status, historical, _ = fixture.upload_image(payload=metadata(displayName=HISTORICAL))
        assert status == 200, historical
        keys = ('imageryVersionId', 'contentRevision', 'expectedReportSha256', 'sha256')
        reference = dict(imageryVersionId=historical['imageryVersionId'], expectedContentRevision=historical['contentRevision'],
                         expectedReportSha256=historical['expectedReportSha256'], visible=True)
        proposed = {**deepcopy(scene['snapshot']), 'imagery': reference}
        status, checked, _ = fixture.check(fixture.validate_body(scene, proposed))
        assert status == 200, checked
        status, saved, _ = fixture.save(fixture.save_body(scene, checked['proposedSnapshot']))
        assert status == 200, saved
        pinned = fixture.opened(scene, saved['sceneRevision'])
        status, head, _ = fixture.save(fixture.save_body(pinned, {**pinned['snapshot'], 'imagery': None}))
        assert status == 200, head
        facts = dict(projectCode=PROJECT, projectTitle=TITLE, sceneId=scene['sceneId'],
                     sceneCenter=scene['snapshot']['coordinateFrame']['anchor']['geographicAnchor'],
                     terrainVersionId=scene['snapshot']['terrain']['terrainVersionId'],
                     pinnedRevision=pinned['sceneRevision'], headRevision=head['sceneRevision'],
                     historical={k: historical[k] for k in keys}, textureSha256=historical['texture']['sha256'],
                     reference=reference, uploadTitle=UPLOAD,
                     **create_transfer((fixture.root/'synthetic-resume.tif').resolve()))
        wrong = fixture.root/'synthetic-different.tif'
        data = Path(facts['file']).read_bytes()
        wrong.write_bytes(data[:-1]+bytes([data[-1]^1]))
        facts['wrongFile'] = str(wrong)
        fixture.server.shutdown()
        fixture.thread.join()
        yield fixture.root.resolve(), facts
    finally:
        fixture.doCleanups()


def site_process(public, root, port, ready, stop):
    with closing(ProjectSessions('http://127.0.0.1:1', PROJECT, CONTEXT, library_root=root/'private',
                                 workspace_root=root/'project-spaces', terrain_python=Path(sys.executable),
                                 factory=ImageryAuthority)) as app:
        with serve_workbench(public, app, port=port) as origin:
            ready.send((origin, getpid()))
            stop.wait()


@contextmanager
def imagery_browser_site(public, root, port=0):
    context = get_context('spawn')
    receive, ready = context.Pipe(duplex=False)
    stop = context.Event()
    child = context.Process(target=site_process, args=(public.resolve(strict=True), root, port, ready, stop))
    child.start()
    ready.close()
    try:
        if not receive.poll(25):
            raise RuntimeError('The isolated imagery workbench did not start')
        try:
            identity = receive.recv()
        except EOFError as error:
            raise RuntimeError('The isolated imagery workbench exited during startup') from error
        yield identity
    finally:
        receive.close()
        stop.set()
        child.join(12)
        if child.is_alive():
            child.terminate()
            child.join()
