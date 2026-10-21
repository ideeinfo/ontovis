"""One deployment-configured, private GLB and reviewed demonstration mappings.

No browser paths, uploads, external glTF resources or public static model URLs.
"""
from __future__ import annotations
import hashlib
import json
import math
from pathlib import Path
import re
import struct
from .authority import PreviewError

MAX_MODEL = 20 * 1024 * 1024


class ModelAsset:
    def __init__(self, root: Path, project: str, context: str):
        self.root = root.resolve()
        value = json.loads((self.root / 'model.json').read_text())
        if (value.get('schemaVersion') != 1 or value.get('projectCode') != project
                or value.get('installationContextId') != context
                or not re.fullmatch('[0-9a-f]{64}', value.get('sha256',''))
                or not isinstance(value.get('bindings'), list) or len(value['bindings']) != 3):
            raise ValueError('Invalid private model configuration')
        bindings = value['bindings']
        if ({row.get('componentKey') for row in bindings} != {'CT','CN','CN1'}
                or len({row.get('entityUid') for row in bindings}) != 3):
            raise ValueError('Ambiguous cabinet mapping')
        for row in bindings:
            quality = 'source_candidate' if row['componentKey'] == 'CN' else 'proxy_schematic'
            if (row.get('geometryQuality') != quality or not isinstance(row.get('entityRevision'), str)
                    or not row['entityRevision'] or not isinstance(row.get('entityUid'), str)
                    or not 0 < len(row['entityUid']) <= 512):
                raise ValueError('Invalid demonstration mapping')
            bounds = row.get('bounds')
            if (not isinstance(bounds,list) or len(bounds) != 2
                    or any(not isinstance(point,list) or len(point) != 3 for point in bounds)
                    or any(type(n) not in (float,int) or not math.isfinite(n) for point in bounds for n in point)
                    or any(bounds[0][i] >= bounds[1][i] for i in range(3))):
                raise ValueError('Invalid cabinet bounds')
        self.value = value
        self.content()  # Validate the immutable artifact before the service starts.

    def content(self) -> bytes:
        path = self.root / 'model.glb'
        if path.is_symlink() or path.stat().st_size > MAX_MODEL:
            raise PreviewError(503, 'MODEL_UNAVAILABLE')
        data = path.read_bytes()
        if (len(data) > MAX_MODEL or len(data) < 24
                or hashlib.sha256(data).hexdigest() != self.value['sha256']):
            raise PreviewError(409, 'MODEL_CHANGED')
        magic, version, length, size, kind = struct.unpack_from('<4sIIII', data)
        if magic != b'glTF' or version != 2 or length != len(data) or kind != 0x4e4f534a or size > len(data) - 20:
            raise ValueError('Invalid GLB')
        document = json.loads(data[20:20+size])
        # GLTFLoader must never fetch a URI supplied by model data.
        if (document.get('asset',{}).get('version') != '2.0' or document.get('extensionsUsed')
                or any('uri' in item for key in ('buffers','images') for item in document.get(key,[]))):
            raise ValueError('Only embedded GLB resources are supported')
        return data

    def metadata(self, items: list[dict], context: dict) -> dict:
        if (context.get('purpose') != 'demonstration' or context.get('engineeringUseAllowed') is not False
                or context.get('rootEntityUid') != self.value.get('rootEntityUid')):
            raise PreviewError(409, 'MODEL_SCOPE_CHANGED')
        objects = {row.get('object',{}).get('entityUid'):row for row in items}
        for binding in self.value['bindings']:
            row = objects.get(binding['entityUid'], {})
            item = row.get('object') or {}
            if (row.get('resolution') != 'exact' or item.get('lifecycle') != 'active'
                    or item.get('installationContextId') != context['installationContextId']
                    or item.get('objectKind') != 'cabinet'
                    or item.get('entityRevision') != binding['entityRevision']):
                raise PreviewError(409, 'MODEL_BINDING_CHANGED')
        return {'sha256':self.value['sha256'], 'mediaType':'model/gltf-binary',
                'rootEntityUid':context['rootEntityUid'],
                'bindingStatus':'demonstration_draft', 'engineeringUseAllowed':False,
                'bindings':[{key:row[key] for key in ('entityUid','entityRevision','componentKey','geometryQuality','bounds')}
                            for row in self.value['bindings']]}
