"""Run the fixed regional geometry checker in a bounded optional GIS process."""
from __future__ import annotations

import json
import os
from pathlib import Path
import selectors
import subprocess
import tempfile
from threading import BoundedSemaphore
import time

from .authority import PreviewError
from .scene_geometry import MAX_REQUEST_BYTES, MAX_OUTPUT_BYTES
from tools.model_probe import strict_json, ProbeError


class SceneGeometryProcess:
    def __init__(self, library, *, python_executable, terrain_root):
        self.library = library
        self.python = Path(python_executable)
        self.terrain_root = Path(terrain_root)
        if not self.python.is_absolute() or not self.python.is_file():
            raise ValueError('A trusted GIS interpreter is required')
        self.slots = BoundedSemaphore(1)

    def process(self, request, authorize):
        authorize()
        try:
            raw = json.dumps(request, ensure_ascii=False, allow_nan=False, separators=(',', ':')).encode()
        except (ValueError, TypeError, UnicodeError, RecursionError, OverflowError):
            raise PreviewError(422, 'INVALID_REQUEST') from None
        if len(raw) > MAX_REQUEST_BYTES:
            raise PreviewError(413, 'SCENE_LIMIT_EXCEEDED')
        if not self.slots.acquire(blocking=False):
            raise PreviewError(429, 'SCENE_GEOMETRY_BUSY')
        path = None
        process = None
        selector = None
        try:
            selector = selectors.DefaultSelector()
            with tempfile.NamedTemporaryFile(dir=self.library.root / 'temporary', prefix='scene-geometry-', suffix='.json', delete=False) as file:
                path = Path(file.name)
                file.write(raw)
                file.flush()
                os.fsync(file.fileno())
            environment = {key: os.environ[key] for key in ('PATH', 'LANG', 'LC_ALL', 'PYTHONPATH', 'PYTHONHOME',
                'SYSTEMROOT', 'LD_LIBRARY_PATH', 'GDAL_DATA', 'PROJ_DATA') if key in os.environ}
            environment.update({'OPENBLAS_NUM_THREADS': '1', 'OMP_NUM_THREADS': '1', 'PROJ_NETWORK': 'OFF'})
            process = subprocess.Popen([str(self.python), '-m', 'apps.api.scene_geometry', str(path),
                '--terrain-root', str(self.terrain_root)], cwd=Path(__file__).resolve().parents[2], env=environment,
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
            output = bytearray()
            deadline = time.monotonic() + 65
            os.set_blocking(process.stdout.fileno(), False)
            selector.register(process.stdout, selectors.EVENT_READ)
            while process.poll() is None or selector.get_map():
                if time.monotonic() >= deadline:
                    raise PreviewError(422, 'SCENE_LIMIT_EXCEEDED')
                for key, _ in selector.select(.05):
                    chunk = os.read(key.fd, 65536)
                    if not chunk:
                        selector.unregister(key.fileobj)
                    else:
                        output.extend(chunk)
                        if len(output) > MAX_OUTPUT_BYTES:
                            raise PreviewError(413, 'SCENE_LIMIT_EXCEEDED')
            if process.wait(timeout=1) not in (0, 2):
                raise PreviewError(422, 'SCENE_LIMIT_EXCEEDED')
            try:
                value = strict_json(bytes(output))
            except (ValueError, UnicodeError, ProbeError):
                raise PreviewError(502, 'PROCESSING_UNAVAILABLE') from None
            if not isinstance(value, dict):
                raise PreviewError(502, 'PROCESSING_UNAVAILABLE')
            if process.returncode:
                code = value.get('code')
                allowed = {'INVALID_REQUEST', 'INVALID_COORDINATE', 'UNSUPPORTED_CRS', 'VERTICAL_DATUM_CONFLICT',
                    'OUTSIDE_COVERAGE', 'OUTSIDE_PROJECTION_AREA', 'NO_DATA', 'RESOURCE_CHANGED', 'INVALID_TERRAIN',
                    'TRANSFORM_UNAVAILABLE', 'FRAME_CHANGED', 'TERRAIN_SAMPLE_CHANGED', 'SCENE_SCOPE_UNSUPPORTED',
                    'SCENE_LIMIT_EXCEEDED', 'PROCESSING_UNAVAILABLE', 'NOT_FOUND_OR_FORBIDDEN', 'INSTANCE_POSITION_LOCKED'}
                if not isinstance(code, str) or code not in allowed:
                    code = 'INVALID_REQUEST'
                status = 503 if code in ('PROCESSING_UNAVAILABLE', 'TRANSFORM_UNAVAILABLE') else 409 if code in (
                    'FRAME_CHANGED', 'RESOURCE_CHANGED', 'TERRAIN_SAMPLE_CHANGED', 'INSTANCE_POSITION_LOCKED') else 404 if code == 'NOT_FOUND_OR_FORBIDDEN' else 422
                raise PreviewError(status, code)
            if not {'snapshot', 'resourceRefs', 'geometrySummary', 'heightProvenance', 'displayPlacements'} <= set(value):
                raise PreviewError(502, 'PROCESSING_UNAVAILABLE')
            authorize()
            return value
        except OSError:
            raise PreviewError(503, 'PROCESSING_UNAVAILABLE') from None
        finally:
            cleanup_failed = False
            try:
                if selector is not None:
                    selector.close()
            except OSError:
                cleanup_failed = True
            try:
                if process is not None:
                    if process.poll() is None:
                        process.kill()
                    process.wait(timeout=3)
            except (OSError, subprocess.TimeoutExpired):
                cleanup_failed = True
            finally:
                try:
                    if process is not None and process.stdout:
                        process.stdout.close()
                except OSError:
                    cleanup_failed = True
            try:
                if path:
                    path.unlink(missing_ok=True)
            except OSError:
                cleanup_failed = True
            finally:
                self.slots.release()
            if cleanup_failed:
                raise PreviewError(503, 'PROCESSING_UNAVAILABLE')
