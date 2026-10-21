"""Bounded static GLB import probe, executed in a separate resource-limited process."""
from __future__ import annotations
import hashlib
import json
import math
from pathlib import Path
import struct
import sys

from tools.model_probe import Glb, ProbeError, require, strict_json, transform

MAX_BYTES = 20 * 1024 * 1024


def image_size(data: bytes, mime: str):
    if mime == 'image/png':
        require(len(data) >= 24 and data[:8] == b'\x89PNG\r\n\x1a\n' and data[12:16] == b'IHDR', 'INVALID_MODEL', 'Invalid PNG.')
        return struct.unpack_from('>II', data, 16)
    require(mime == 'image/jpeg' and data[:2] == b'\xff\xd8', 'UNSUPPORTED_MODEL', 'Only embedded PNG/JPEG textures are supported.')
    offset = 2
    while offset + 4 <= len(data):
        require(data[offset] == 255, 'INVALID_MODEL', 'Invalid JPEG marker.')
        while offset < len(data) and data[offset] == 255: offset += 1
        require(offset + 3 <= len(data), 'INVALID_MODEL', 'Truncated JPEG.')
        marker = data[offset]; offset += 1
        size = struct.unpack_from('>H', data, offset)[0]
        require(size >= 2 and offset + size <= len(data), 'INVALID_MODEL', 'Invalid JPEG segment.')
        if marker in (0xc0, 0xc1, 0xc2):
            require(size >= 8, 'INVALID_MODEL', 'Invalid JPEG frame.')
            height, width = struct.unpack_from('>HH', data, offset + 3)
            return width, height
        offset += size
    raise ProbeError('INVALID_MODEL', 'JPEG frame not found.')


def validate(path: Path) -> dict:
    data = path.read_bytes()
    require(24 <= len(data) <= MAX_BYTES, 'MODEL_LIMIT_EXCEEDED', 'File budget exceeded.')
    require(data[:4] == b'glTF', 'INVALID_MODEL', 'Expected GLB.')
    size = struct.unpack_from('<I', data, 12)[0]
    require(size <= min(len(data)-20, 2*1024*1024), 'MODEL_LIMIT_EXCEEDED', 'JSON budget exceeded.')
    doc = strict_json(data[20:20+size])
    require(isinstance(doc, dict), 'INVALID_MODEL', 'Expected object.')
    count = 0
    def bounded(value, depth=0):
        nonlocal count
        count += 1
        require(depth <= 48 and count <= 100000, 'MODEL_LIMIT_EXCEEDED', 'Metadata budget exceeded.')
        if isinstance(value, dict):
            require(not value.get('extensions'), 'UNSUPPORTED_MODEL', 'Extensions are not enabled.')
            for key, item in value.items():
                require(len(key) <= 512, 'MODEL_LIMIT_EXCEEDED', 'Property length exceeded.')
                require(key not in ('__proto__','constructor','prototype'), 'UNSUPPORTED_MODEL', 'Unsafe metadata key.')
                bounded(item, depth+1)
        elif isinstance(value, list):
            for item in value: bounded(item, depth+1)
        elif isinstance(value, str): require(len(value) <= 8192, 'MODEL_LIMIT_EXCEEDED', 'Text budget exceeded.')
    bounded(doc)
    require(not doc.get('extensionsUsed') and not doc.get('extensionsRequired') and not doc.get('animations') and not doc.get('skins'), 'UNSUPPORTED_MODEL', 'Only static models without extensions are enabled.')
    for key, limit in (('nodes', 2000), ('meshes', 500), ('accessors', 4000), ('materials', 100), ('images', 16)):
        require(isinstance(doc.get(key, []), list) and len(doc.get(key, [])) <= limit, 'MODEL_LIMIT_EXCEEDED', 'Geometry budget exceeded.')
    require(all(isinstance(a, dict) and type(a.get('count')) is int and 0 <= a['count'] <= 500000 for a in doc.get('accessors', [])), 'MODEL_LIMIT_EXCEEDED', 'Accessor budget exceeded.')
    require(sum(a['count'] for a in doc.get('accessors', [])) <= 2000000, 'MODEL_LIMIT_EXCEEDED', 'Decoded geometry budget exceeded.')
    require(all(isinstance(a, dict) and 'uri' not in a for key in ('buffers', 'images') for a in doc.get(key, [])), 'UNSUPPORTED_MODEL', 'Only embedded resources are enabled.')
    model = Glb(path)
    texels = 0
    for item in model.array('images'):
        view = model.ref('bufferViews', item.get('bufferView'))
        start, length = view.get('byteOffset', 0), view['byteLength']
        width, height = image_size(model.bin[start:start+length], item.get('mimeType'))
        require(0 < width <= 4096 and 0 < height <= 4096, 'MODEL_LIMIT_EXCEEDED', 'Texture dimension budget exceeded.')
        texels += width*height
    require(texels <= 16*1024*1024, 'MODEL_LIMIT_EXCEEDED', 'Texture budget exceeded.')
    for item in model.array('textures'):
        model.ref('images', item.get('source'))
        if 'sampler' in item: model.ref('samplers', item['sampler'])
    summary = model.summary()
    require(summary['triangles'] <= 500000 and summary['activeMeshInstances'] <= 500, 'MODEL_LIMIT_EXCEEDED', 'Draw/triangle budget exceeded.')
    groups = {}
    for index in model.geometry:
        node = model.doc['nodes'][index]
        extras = node.get('extras') if isinstance(node.get('extras'), dict) else {}
        label = extras.get('component')
        if not isinstance(label, str) or not label.strip(): label = None
        group = ('label', label) if label else ('node', index)
        groups.setdefault(group, []).append(index)
    components = []
    for ordinal, ((kind, label), nodes) in enumerate(groups.items()):
        low, high = [math.inf]*3, [-math.inf]*3
        for index in nodes:
            for positions, _ in model.geometry[index]:
                for point in positions:
                    world = transform(model.worlds[index], point)
                    low = [min(a,b) for a,b in zip(low,world)]
                    high = [max(a,b) for a,b in zip(high,world)]
        name = label if kind == 'label' else model.doc['nodes'][nodes[0]].get('name') or f'#{nodes[0]}'
        require(all(math.isfinite(n) and abs(n)<=1000000 for point in (low,high) for n in point), 'MODEL_LIMIT_EXCEEDED', 'Coordinate budget exceeded.')
        components.append({'componentKey':f'component:{ordinal}', 'displayName':name[:200], 'nodeIndices':nodes,
                           'keyStability':'version_local', 'geometryQuality':'source_candidate', 'bounds':[low,high]})
    return {'sha256':hashlib.sha256(data).hexdigest(), 'components':components,
            'report':{key:summary[key] for key in ('bytes','nodes','activeMeshInstances','triangles','bounds','coordinateConvention','animations')}
                      | {'images':len(model.array('images')), 'texturePixels':texels, 'externalResourcesFetched':0,
                         'coordinateVerification':'unverified', 'sourceIdentityVerified':False}}


def main():
    import resource
    resource.setrlimit(resource.RLIMIT_CPU, (6,6))
    # macOS does not implement RLIMIT_AS; the deployed Linux worker enforces it.
    if sys.platform.startswith('linux'):
        resource.setrlimit(resource.RLIMIT_AS, (192*1024*1024,192*1024*1024))
    resource.setrlimit(resource.RLIMIT_FSIZE, (1024*1024,1024*1024))
    try: print(json.dumps(validate(Path(sys.argv[1])), ensure_ascii=False))
    except (ProbeError, ValueError, KeyError, TypeError, IndexError, OverflowError, MemoryError, RecursionError, struct.error) as error:
        code = error.code if isinstance(error, ProbeError) and error.code in ('UNSUPPORTED_MODEL','MODEL_LIMIT_EXCEEDED') else 'INVALID_MODEL'
        print(json.dumps({'code':code})); return 2
    return 0


if __name__ == '__main__': sys.exit(main())
