"""Read-only source-node reports for an already retained, authorized fixed GLB."""
from __future__ import annotations

from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import select
import selectors
import struct
import subprocess
import sys
import threading
import time

from tools.model_probe import ProbeError, strict_json
from .authority import PreviewError
from .model_validation import limit_process, validate

PROFILE = 'source-nodes-v1'
MAX_OUTPUT_BYTES = 4 * 1024 * 1024
TIMEOUT_SECONDS = 12
REFERENCE_FIELDS = {'modelVersionId', 'expectedContentRevision', 'expectedSha256'}


def processor_fingerprint():
    root = Path(__file__).resolve().parents[2]
    files = ('apps/api/model_inspection.py', 'apps/api/model_validation.py', 'tools/model_probe.py')
    values = {name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in files}
    return hashlib.sha256(json.dumps(values, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def catalog_digest(nodes):
    # Match the existing offline components.json bytes, without rewriting that artifact.
    data = (json.dumps({'source': nodes}, ensure_ascii=False, indent=2, allow_nan=False) + '\n').encode()
    return hashlib.sha256(data).hexdigest()


def inspect(path):
    result = validate(path, include_source_nodes=True)
    nodes = result['sourceNodes']
    return {'schemaVersion': 1, 'profileVersion': PROFILE, 'processorSha256': processor_fingerprint(),
            'scope': 'fixed_glb_source_local_only', 'sha256': result['sha256'],
            'sourceValidation': result['report'], 'sourceNodes': nodes,
            'sourceIdentityStates': dict(Counter(row['sourceIdentityState'] for row in nodes)),
            'catalogSha256': catalog_digest(nodes), 'sourceIdentityVerified': False,
            'geometryCorrespondenceVerified': False, 'bindingMigrationApproved': False,
            'releaseReadiness': {'eligible': False, 'G2Passed': False}}


class ModelInspection:
    def __init__(self, models):
        self.models = models
        self.library = models.library

    def _process(self, path):
        process = None
        selector = selectors.DefaultSelector()
        try:
            environment = {key: os.environ[key] for key in ('PATH', 'LANG', 'LC_ALL', 'PYTHONPATH',
                           'PYTHONHOME', 'SYSTEMROOT', 'LD_LIBRARY_PATH') if key in os.environ}
            process = subprocess.Popen([sys.executable, '-m', 'apps.api.model_inspection', str(path)],
                cwd=Path(__file__).resolve().parents[2], env=environment, stdin=subprocess.PIPE,
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
            os.set_blocking(process.stdout.fileno(), False)
            selector.register(process.stdout, selectors.EVENT_READ)
            output = bytearray()
            deadline = time.monotonic() + TIMEOUT_SECONDS
            while process.poll() is None or selector.get_map():
                if time.monotonic() >= deadline:
                    raise PreviewError(422, 'MODEL_LIMIT_EXCEEDED')
                for key, _ in selector.select(.05):
                    chunk = os.read(key.fd, 65536)
                    if not chunk:
                        selector.unregister(key.fileobj)
                    else:
                        output.extend(chunk)
                        if len(output) > MAX_OUTPUT_BYTES:
                            raise PreviewError(422, 'MODEL_LIMIT_EXCEEDED')
            if process.wait(timeout=1) not in (0, 2):
                raise PreviewError(422, 'MODEL_LIMIT_EXCEEDED')
            try:
                value = strict_json(bytes(output))
            except ProbeError:
                raise PreviewError(502, 'MODEL_INSPECTION_UNAVAILABLE') from None
            if not isinstance(value, dict):
                raise PreviewError(502, 'MODEL_INSPECTION_UNAVAILABLE')
            if process.returncode:
                code = value.get('code')
                if code not in ('INVALID_MODEL', 'UNSUPPORTED_MODEL', 'MODEL_LIMIT_EXCEEDED'):
                    raise PreviewError(502, 'MODEL_INSPECTION_UNAVAILABLE')
                raise PreviewError(422, code)
            return value
        except OSError:
            raise PreviewError(503, 'MODEL_INSPECTION_UNAVAILABLE') from None
        finally:
            selector.close()
            if process is not None:
                if process.poll() is None:
                    process.kill()
                process.wait(timeout=3)
                process.stdin.close()
                process.stdout.close()

    def read(self, body, authorize):
        if not callable(authorize):
            raise PreviewError(422, 'INVALID_REQUEST')
        authorize()
        if not isinstance(body, dict) or set(body) != REFERENCE_FIELDS:
            raise PreviewError(422, 'INVALID_REQUEST')
        if not self.library.slots.acquire(blocking=False):
            raise PreviewError(429, 'MODEL_BUSY')
        try:
            content = self.models.content(body['modelVersionId'], body['expectedContentRevision'],
                                          body['expectedSha256'], authorize)
            source_bytes = len(content)
            del content
            identity = self.models.content_identity(body['modelVersionId'])
            path = self.library.root / 'files' / (identity['modelVersionId'] + '.glb')
            if path.stat().st_nlink != 1:
                raise PreviewError(409, 'RESOURCE_CHANGED')
            expected_processor = processor_fingerprint()
            authorize()
            value = self._process(path)
            if not isinstance(value, dict):
                raise PreviewError(502, 'MODEL_INSPECTION_UNAVAILABLE')
            nodes, report = value.get('sourceNodes'), value.get('sourceValidation')
            if (value.get('schemaVersion') != 1 or value.get('profileVersion') != PROFILE
                    or value.get('processorSha256') != expected_processor
                    or value.get('scope') != 'fixed_glb_source_local_only'
                    or value.get('sha256') != body['expectedSha256']
                    or value.get('sourceIdentityVerified') is not False
                    or value.get('geometryCorrespondenceVerified') is not False
                    or value.get('bindingMigrationApproved') is not False
                    or value.get('releaseReadiness') != {'eligible': False, 'G2Passed': False}
                    or not isinstance(nodes, list) or not isinstance(report, dict)
                    or type(report.get('nodes')) is not int or len(nodes) != report['nodes']
                    or not 0 < len(nodes) <= 2000 or report.get('bytes') != source_bytes):
                raise PreviewError(502, 'MODEL_INSPECTION_UNAVAILABLE')
            if value.get('catalogSha256') != catalog_digest(nodes):
                raise PreviewError(502, 'MODEL_INSPECTION_UNAVAILABLE')
            if any(not isinstance(row, dict) or row.get('nodeIndex') != index
                   or row.get('componentKey') != f"{body['expectedSha256']}:node:{index}"
                   or row.get('keyStability') != 'version_local' or row.get('sourceIdentityVerified') is not False
                   for index, row in enumerate(nodes)):
                raise PreviewError(502, 'MODEL_INSPECTION_UNAVAILABLE')
            if value.get('sourceIdentityStates') != dict(Counter(row.get('sourceIdentityState') for row in nodes)):
                raise PreviewError(502, 'MODEL_INSPECTION_UNAVAILABLE')
            # Verify the retained file and current permission again after isolated processing.
            self.models.content(body['modelVersionId'], body['expectedContentRevision'],
                                body['expectedSha256'], authorize)
            if processor_fingerprint() != expected_processor:
                raise PreviewError(409, 'RESOURCE_CHANGED')
            authorize()
            return {'modelVersionId': identity['modelVersionId'], 'contentRevision': identity['contentRevision'], **value}
        except OSError:
            raise PreviewError(503, 'MODEL_STORAGE_UNAVAILABLE') from None
        finally:
            self.library.slots.release()


def main():
    def watchdog():
        ready, _, _ = select.select([sys.stdin.buffer], [], [], TIMEOUT_SECONDS)
        os._exit(125 if ready else 124)
    threading.Thread(target=watchdog, daemon=True).start()
    limit_process(MAX_OUTPUT_BYTES)
    try:
        value = inspect(Path(sys.argv[1]))
        encoded = json.dumps(value, ensure_ascii=False, allow_nan=False).encode()
        if len(encoded) > MAX_OUTPUT_BYTES:
            raise ProbeError('MODEL_LIMIT_EXCEEDED', 'Inspection output budget exceeded.')
        sys.stdout.buffer.write(encoded)
    except (ProbeError, ValueError, KeyError, TypeError, IndexError, OverflowError, MemoryError,
            RecursionError, OSError, struct.error) as error:
        code = error.code if isinstance(error, ProbeError) and error.code in (
            'UNSUPPORTED_MODEL', 'MODEL_LIMIT_EXCEEDED') else 'INVALID_MODEL'
        print(json.dumps({'code': code}))
        return 2
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
