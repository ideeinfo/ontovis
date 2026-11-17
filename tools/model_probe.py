#!/usr/bin/env python3
"""Read-only GLB model/mapping probe for PREP-02, not an upload service or full validator."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import struct
import sys

MAX_BYTES = 200 * 1024 * 1024  # Local probe budget, not a production upload limit.
IDENTITY = (1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1)
WIDTHS = {5120: ('b', 1), 5121: ('B', 1), 5122: ('h', 2),
          5123: ('H', 2), 5125: ('I', 4), 5126: ('f', 4)}
DIMENSIONS = {'SCALAR': 1, 'VEC2': 2, 'VEC3': 3, 'VEC4': 4}
IDENTITY_FIELDS = ('sourceModelKey', 'sourceElementId', 'placementId')


class ProbeError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def require(condition: bool, code: str, message: str) -> None:
    if not condition:
        raise ProbeError(code, message)


def integer(value: object, minimum: int = 0) -> bool:
    return type(value) is int and value >= minimum


def finite_vector(value: object, size: int) -> bool:
    return (isinstance(value, (list, tuple)) and len(value) == size
            and all(type(v) in (int, float) and math.isfinite(v) for v in value))


def strict_json(data: bytes) -> object:
    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, 'INVALID_JSON', 'Duplicate JSON property.')
            result[key] = value
        return result

    def invalid_constant(_):
        raise ProbeError('INVALID_JSON', 'Non-finite JSON constant.')

    def finite_float(value):
        result = float(value)
        require(math.isfinite(result), 'INVALID_JSON', 'Non-finite JSON number.')
        return result

    try:
        return json.loads(data, object_pairs_hook=pairs, parse_constant=invalid_constant, parse_float=finite_float)
    except (UnicodeError, ValueError, RecursionError) as error:
        raise ProbeError('INVALID_JSON', 'Invalid or excessively nested JSON.') from error


def source_identity(extras):
    if not isinstance(extras, dict) or 'ontoVis' not in extras:
        return None, 'missing', [], []
    claim = extras['ontoVis']
    if not isinstance(claim, dict):
        return None, 'invalid', [], ['ontoVis']
    missing = [key for key in IDENTITY_FIELDS if key not in claim]
    invalid = [key for key in IDENTITY_FIELDS if key in claim
               and not (isinstance(claim[key], str) and claim[key].strip())]
    state = 'invalid' if invalid else 'incomplete' if missing else 'unverified_claim'
    return ({key: claim[key] for key in IDENTITY_FIELDS} if not missing and not invalid else None,
            state, missing, invalid)


def multiply(a, b):
    return tuple(sum(a[k * 4 + row] * b[col * 4 + k] for k in range(4))
                 for col in range(4) for row in range(4))


def transform(matrix, point):
    result = tuple(sum(matrix[k * 4 + row] * point[k] for k in range(3)) + matrix[12 + row]
                   for row in range(3))
    require(finite_vector(result, 3), 'INVALID_MODEL', 'Non-finite transformed vertex.')
    return result


def determinant(matrix):
    a, b, c, d, e, f, g, h, i = (matrix[k] for k in (0, 4, 8, 1, 5, 9, 2, 6, 10))
    return a * (e * i - f * h) - b * (d * i - f * g) + c * (d * h - e * g)


def local_matrix(node):
    if 'matrix' in node:
        require(not any(k in node for k in ('translation', 'rotation', 'scale')),
                'INVALID_MODEL', 'Node combines matrix and TRS.')
        m = node['matrix']
        require(finite_vector(m, 16) and all(abs(m[k]) < 1e-8 for k in (3, 7, 11))
                and abs(m[15] - 1) < 1e-8, 'INVALID_MODEL', 'Invalid affine matrix.')
        return tuple(m)
    t, q, s = node.get('translation', [0, 0, 0]), node.get('rotation', [0, 0, 0, 1]), node.get('scale', [1, 1, 1])
    require(finite_vector(t, 3) and finite_vector(q, 4) and finite_vector(s, 3),
            'INVALID_MODEL', 'Invalid node TRS.')
    require(abs(sum(v * v for v in q) - 1) < 1e-4, 'INVALID_MODEL', 'Non-unit quaternion.')
    x, y, z, w = q
    return ((1 - 2*y*y - 2*z*z)*s[0], (2*x*y + 2*z*w)*s[0], (2*x*z - 2*y*w)*s[0], 0,
            (2*x*y - 2*z*w)*s[1], (1 - 2*x*x - 2*z*z)*s[1], (2*y*z + 2*x*w)*s[1], 0,
            (2*x*z + 2*y*w)*s[2], (2*y*z - 2*x*w)*s[2], (1 - 2*x*x - 2*y*y)*s[2], 0, *t, 1)


class Glb:
    def __init__(self, path: Path, expected_sha256: str | None = None):
        require(path.stat().st_size <= MAX_BYTES, 'LIMIT_EXCEEDED', 'Local file budget exceeded.')
        data = path.read_bytes()
        self.sha256 = hashlib.sha256(data).hexdigest()
        require(not expected_sha256 or self.sha256 == expected_sha256,
                'DIGEST_MISMATCH', 'Model fingerprint differs from the supplied reference.')
        require(len(data) >= 20, 'INVALID_MODEL', 'Truncated GLB header.')
        magic, version, length = struct.unpack_from('<4sII', data)
        require(magic == b'glTF' and version == 2 and length == len(data),
                'INVALID_MODEL', 'Invalid GLB magic, version or declared length.')
        chunks, offset = [], 12
        while offset < len(data):
            require(offset + 8 <= len(data), 'INVALID_MODEL', 'Truncated chunk header.')
            size, kind = struct.unpack_from('<II', data, offset)
            offset += 8
            require(size % 4 == 0 and offset + size <= len(data), 'INVALID_MODEL', 'Invalid chunk length.')
            chunks.append((kind, data[offset:offset + size]))
            offset += size
        require(chunks and chunks[0][0] == 0x4E4F534A and len(chunks) <= 2
                and (len(chunks) == 1 or chunks[1][0] == 0x004E4942),
                'UNSUPPORTED_MODEL', 'Probe accepts one JSON chunk and an optional BIN chunk.')
        self.doc = strict_json(chunks[0][1])
        require(isinstance(self.doc, dict) and isinstance(self.doc.get('asset'), dict)
                and self.doc['asset'].get('version') == '2.0', 'INVALID_MODEL', 'Expected glTF 2.0 asset.')
        require(self.doc['asset'].get('minVersion', '2.0') == '2.0',
                'UNSUPPORTED_MODEL', 'Minimum asset version is outside this probe.')
        self.bin = chunks[1][1] if len(chunks) == 2 else b''
        self.bytes, self.filename = len(data), path.name
        self.accessor_cache = {}
        self.geometry = {}
        self.worlds = {}
        self._validate_resources()
        self._read_scene()

    def array(self, key):
        result = self.doc.get(key, [])
        require(isinstance(result, list), 'INVALID_MODEL', 'Expected glTF array.')
        return result

    def ref(self, key, index):
        items = self.array(key)
        require(integer(index) and index < len(items) and isinstance(items[index], dict),
                'INVALID_MODEL', 'Invalid glTF index.')
        return items[index]

    def _validate_resources(self):
        require(not self.doc.get('extensionsRequired'), 'UNSUPPORTED_EXTENSION',
                'Required extensions need a separately validated decoder.')
        for key in ('buffers', 'images'):
            for item in self.array(key):
                require(isinstance(item, dict), 'INVALID_MODEL', 'Invalid resource entry.')
                if 'uri' in item:
                    code = 'UNSUPPORTED_RESOURCE' if str(item['uri']).startswith('data:') else 'EXTERNAL_RESOURCE'
                    raise ProbeError(code, 'Probe accepts embedded BIN/bufferView resources only; no URI is fetched.')
        buffers = self.array('buffers')
        require(len(buffers) == 1 and integer(buffers[0].get('byteLength'), 1)
                and 0 <= len(self.bin) - buffers[0]['byteLength'] <= 3,
                'INVALID_MODEL', 'Expected one embedded buffer with matching length.')
        for view in self.array('bufferViews'):
            require(isinstance(view, dict) and not view.get('extensions'), 'UNSUPPORTED_EXTENSION',
                    'bufferView extensions need a separately validated decoder.')
            require(isinstance(view, dict) and type(view.get('buffer')) is int and view['buffer'] == 0
                    and integer(view.get('byteOffset', 0)) and integer(view.get('byteLength'), 1)
                    and view.get('byteOffset', 0) + view['byteLength'] <= buffers[0]['byteLength'],
                    'INVALID_MODEL', 'bufferView exceeds embedded buffer.')
            if 'byteStride' in view:
                require(integer(view['byteStride'], 4) and view['byteStride'] <= 252 and view['byteStride'] % 4 == 0,
                        'INVALID_MODEL', 'Invalid byteStride.')
        for image in self.array('images'):
            self.ref('bufferViews', image.get('bufferView'))
        for index in range(len(self.array('accessors'))):
            self._accessor_layout(index)

    def _accessor_layout(self, index):
        a = self.ref('accessors', index)
        require(not a.get('sparse') and a.get('type') in DIMENSIONS,
                'UNSUPPORTED_MODEL', 'Sparse and matrix accessors are outside this probe.')
        require(a.get('componentType') in WIDTHS and integer(a.get('count'), 1)
                and integer(a.get('byteOffset', 0)), 'INVALID_MODEL', 'Invalid accessor declaration.')
        view = self.ref('bufferViews', a.get('bufferView'))
        fmt, width = WIDTHS[a['componentType']]
        size, start = DIMENSIONS[a['type']] * width, a.get('byteOffset', 0)
        stride = view.get('byteStride', size)
        require(stride >= size and stride % width == 0 and start % width == 0
                and (view.get('byteOffset', 0) + start) % width == 0
                and start + (a['count'] - 1) * stride + size <= view['byteLength'],
                'INVALID_MODEL', 'Accessor exceeds bufferView or has invalid alignment.')
        return a, fmt, view.get('byteOffset', 0) + start, stride

    def accessor(self, index):
        if index not in self.accessor_cache:
            a, fmt, start, stride = self._accessor_layout(index)
            unpacker = struct.Struct('<' + fmt * DIMENSIONS[a['type']])
            values = [unpacker.unpack_from(self.bin, start + i * stride) for i in range(a['count'])]
            require(all(math.isfinite(v) for row in values for v in row),
                    'INVALID_MODEL', 'Accessor contains non-finite values.')
            self.accessor_cache[index] = values
        return self.accessor_cache[index]

    def _read_scene(self):
        nodes = self.array('nodes')
        locals_, parents = {}, {}
        for i in range(len(nodes)):
            node = self.ref('nodes', i)
            require('name' not in node or isinstance(node['name'], str), 'INVALID_MODEL', 'Invalid node name.')
            require(not node.get('extensions') and 'skin' not in node, 'UNSUPPORTED_MODEL',
                    'Node extensions and skinned geometry are outside this static probe.')
            locals_[i] = local_matrix(node)
            children = node.get('children', [])
            require(isinstance(children, list), 'INVALID_MODEL', 'Invalid node children.')
            for child in children:
                self.ref('nodes', child)
                require(child not in parents, 'INVALID_MODEL', 'Node has multiple parents or duplicate edges.')
                parents[child] = i
        colors = {}
        for start in range(len(nodes)):
            stack = [(start, False)]
            while stack:
                index, leaving = stack.pop()
                if leaving:
                    colors[index] = 2
                elif colors.get(index) != 2:
                    require(colors.get(index) != 1, 'INVALID_MODEL', 'Cyclic node graph.')
                    colors[index] = 1
                    stack.append((index, True))
                    stack.extend((child, False) for child in nodes[index].get('children', []))
        scene = self.ref('scenes', self.doc.get('scene', 0))
        roots = scene.get('nodes', [])
        require(isinstance(roots, list) and all(integer(root) for root in roots)
                and len(set(roots)) == len(roots), 'INVALID_MODEL', 'Invalid scene roots.')
        require(all(root not in parents for root in roots), 'INVALID_MODEL', 'Scene root also has a parent.')
        stack = [(root, IDENTITY) for root in roots]
        while stack:
            index, parent = stack.pop()
            node = self.ref('nodes', index)
            world = multiply(parent, locals_[index])
            self.worlds[index] = world
            if 'mesh' in node:
                mesh = self.ref('meshes', node['mesh'])
                primitives = mesh.get('primitives')
                require(isinstance(primitives, list) and primitives, 'INVALID_MODEL', 'Mesh has no primitives.')
                self.geometry[index] = [self._primitive(p) for p in primitives]
            stack.extend((child, world) for child in node.get('children', []))
        require(self.geometry, 'INVALID_MODEL', 'Selected scene has no supported geometry.')

    def _primitive(self, primitive):
        require(isinstance(primitive, dict) and primitive.get('mode', 4) == 4
                and not primitive.get('targets') and not primitive.get('extensions'),
                'UNSUPPORTED_MODEL', 'Only static, uncompressed triangle primitives are supported.')
        attrs = primitive.get('attributes', {})
        require(isinstance(attrs, dict), 'INVALID_MODEL', 'Invalid mesh attributes.')
        for index in attrs.values():
            self.ref('accessors', index)
        index = attrs.get('POSITION')
        declaration = self.ref('accessors', index)
        require(declaration.get('componentType') == 5126 and declaration.get('type') == 'VEC3'
                and not declaration.get('normalized'), 'UNSUPPORTED_MODEL', 'Expected float VEC3 POSITION.')
        positions = self.accessor(index)
        if 'indices' in primitive:
            a = self.ref('accessors', primitive['indices'])
            require(a.get('type') == 'SCALAR' and a.get('componentType') in (5121, 5123, 5125)
                    and not a.get('normalized'), 'INVALID_MODEL', 'Invalid triangle index accessor.')
            indices = [row[0] for row in self.accessor(primitive['indices'])]
        else:
            indices = list(range(len(positions)))
        require(indices and len(indices) % 3 == 0 and all(i < len(positions) for i in indices),
                'INVALID_MODEL', 'Invalid triangle indices.')
        return positions, indices

    def point(self, node, primitive, vertex):
        require(integer(node) and node in self.geometry and integer(primitive) and primitive < len(self.geometry[node]),
                'INVALID_REFERENCE', 'Control point references unavailable geometry.')
        positions, _ = self.geometry[node][primitive]
        require(integer(vertex) and vertex < len(positions), 'INVALID_REFERENCE', 'Control point vertex is unavailable.')
        return transform(self.worlds[node], positions[vertex])

    def catalog(self):
        result = []
        for i, node in enumerate(self.array('nodes')):
            extras = node.get('extras') if isinstance(node.get('extras'), dict) else {}
            claim, state, missing, invalid = source_identity(extras)
            result.append({'componentKey': f'{self.sha256}:node:{i}', 'nodeIndex': i,
                           'keyStability': 'version_local', 'name': node.get('name'),
                           'componentLabel': extras.get('component'),
                           'legacySourceObjectId': extras.get('sourceObjectId'),
                           'sourceExtrasPresent': 'extras' in node, 'sourceExtras': node.get('extras'),
                           'sourceIdentityClaim': claim, 'sourceIdentityState': state,
                           'sourceIdentityMissingFields': missing, 'sourceIdentityInvalidFields': invalid,
                           'sourceIdentityVerified': False, 'activeScene': i in self.worlds,
                           'meshPrimitiveCount': len(self.geometry.get(i, []))})
        counts = Counter(tuple(row['sourceIdentityClaim'].values()) for row in result if row['sourceIdentityClaim'])
        for row in result:
            claim = row['sourceIdentityClaim']
            if claim and counts[tuple(claim.values())] > 1:
                row['sourceIdentityState'] = 'collision'
        return result

    def summary(self):
        points = (transform(self.worlds[node], point) for node, primitives in self.geometry.items()
                  for positions, _ in primitives for point in positions)
        low, high = [math.inf] * 3, [-math.inf] * 3
        for point in points:
            low = [min(a, b) for a, b in zip(low, point)]
            high = [max(a, b) for a, b in zip(high, point)]
        catalog = self.catalog()
        legacy = Counter(str(row['legacySourceObjectId']) for row in catalog if row['legacySourceObjectId'] is not None)
        return {'filename': self.filename, 'sha256': self.sha256, 'bytes': self.bytes,
                'generator': self.doc['asset'].get('generator'), 'nodes': len(catalog),
                'activeMeshInstances': len(self.geometry),
                'triangles': sum(len(indices) // 3 for primitives in self.geometry.values() for _, indices in primitives),
                'componentLabels': sorted({row['componentLabel'] for row in catalog if isinstance(row['componentLabel'], str)}),
                'bounds': {'min': low, 'max': high, 'basis': 'decoded vertices, selected scene, static base pose'},
                'coordinateConvention': 'glTF 2.0: metres, right-handed, Y-up; exporter/site correctness unverified',
                'legacyIdDistinctCount': len(legacy), 'legacyIdDuplicateValues': sum(n > 1 for n in legacy.values()),
                'sourceIdentityStates': dict(Counter(row['sourceIdentityState'] for row in catalog)),
                'animations': len(self.array('animations')), 'externalResourcesFetched': 0}


def compare_identity_claims(previous: Glb, current: Glb) -> dict:
    groups, unavailable = {}, []
    for side, model in (('previous', previous), ('current', current)):
        for row in model.catalog():
            claim = row['sourceIdentityClaim']
            if claim is None:
                unavailable.append({'side': side, 'componentKey': row['componentKey'],
                                    'state': row['sourceIdentityState'], 'activeScene': row['activeScene']})
            else:
                pair = groups.setdefault(tuple(claim[key] for key in IDENTITY_FIELDS),
                                         {'previous': [], 'current': []})
                pair[side].append(row)
    entries = []
    for identity, pair in sorted(groups.items()):
        old, new = pair['previous'], pair['current']
        state = ('collision' if len(old) > 1 or len(new) > 1 else
                 'inactive' if any(not row['activeScene'] for row in old + new) else
                 'current_only' if not old else 'previous_only' if not new else 'candidate')
        entry = {'state': state, 'sourceIdentityClaim': dict(zip(IDENTITY_FIELDS, identity))}
        for side, rows in pair.items():
            entry[side] = [{key: row[key] for key in ('componentKey', 'nodeIndex', 'name', 'activeScene')}
                           for row in rows]
        if state == 'candidate':
            # JSON comparison preserves boolean/number types, unlike Python's True == 1.
            properties = [json.dumps([row['sourceExtrasPresent'], row['sourceExtras']],
                                     ensure_ascii=False, sort_keys=True, allow_nan=False) for row in (old[0], new[0])]
            entry['propertiesChanged'] = properties[0] != properties[1]
            entry['nameChanged'] = old[0]['name'] != new[0]['name']
        entries.append(entry)
    counts = Counter(row['state'] for row in entries)
    return {'schemaVersion': 1, 'status': 'review_required',
            'previousSha256': previous.sha256, 'currentSha256': current.sha256,
            'rule': 'Exact sourceModelKey/sourceElementId/placementId strings; no normalization or fallback.',
            'sourceIdentityVerified': False, 'geometryCorrespondenceVerified': False,
            'bindingMigrationApproved': False,
            'counts': {state: counts[state] for state in ('candidate', 'collision', 'previous_only', 'current_only', 'inactive')},
            'unavailableCounts': {side: dict(Counter(row['state'] for row in unavailable if row['side'] == side))
                                  for side in ('previous', 'current')},
            'entries': entries, 'unavailable': unavailable}


def compare_mapping(source: Glb, derived: Glb, sidecar: dict, tolerance: float = 0.0001) -> dict:
    require(isinstance(sidecar, dict), 'INVALID_MAPPING', 'Mapping must be a JSON object.')
    require(sidecar.get('sourceSha256') == source.sha256, 'DIGEST_MISMATCH', 'Mapping source fingerprint differs.')
    require(not sidecar.get('derivedSha256') or sidecar['derivedSha256'] == derived.sha256,
            'DIGEST_MISMATCH', 'Mapping derivative fingerprint differs.')
    rows = sidecar.get('sourceMapping')
    require(isinstance(rows, list) and rows, 'INVALID_MAPPING', 'Missing source mapping rows.')
    destinations = defaultdict(list)
    for i in derived.geometry:
        destinations[derived.doc['nodes'][i].get('name')].append(i)
    consumed, ranges = Counter(), defaultdict(list)
    max_error, triangles = 0.0, 0
    for row in rows:
        require(isinstance(row, dict), 'INVALID_MAPPING', 'Invalid mapping row.')
        node, group = row.get('sourceNodeIndex'), row.get('destinationGroup')
        require(integer(node) and node in source.geometry and isinstance(group, str),
                'INVALID_MAPPING', 'Mapping source geometry is unavailable.')
        # The existing local sidecar lists primitives in source order, without a primitive index.
        primitive = consumed[node]
        require(primitive < len(source.geometry[node]), 'INVALID_MAPPING', 'Repeated source primitive mapping.')
        consumed[node] += 1
        source_positions, source_indices = source.geometry[node][primitive]
        extras = source.doc['nodes'][node].get('extras', {})
        require(isinstance(extras, dict), 'INVALID_MAPPING', 'Mapping needs object-valued source extras.')
        require(row.get('sourceObjectId') == extras.get('sourceObjectId')
                and row.get('component') == extras.get('component'),
                'INVALID_MAPPING', 'Mapping source attributes differ from the artifact.')
        require(len(destinations[group]) == 1, 'INVALID_MAPPING', 'Destination group is absent or ambiguous.')
        target = destinations[group][0]
        require(len(derived.geometry[target]) == 1, 'UNSUPPORTED_MAPPING', 'Expected one primitive per destination group.')
        target_positions, target_indices = derived.geometry[target][0]
        start, count = row.get('firstTriangle'), row.get('triangleCount')
        require(integer(start) and integer(count, 1) and count * 3 == len(source_indices)
                and (start + count) * 3 <= len(target_indices), 'INVALID_MAPPING', 'Mapping triangle range is invalid.')
        ranges[target].append((start, start + count))
        mirror = (determinant(source.worlds[node]) < 0) != (determinant(derived.worlds[target]) < 0)
        for triangle in range(count):
            for corner in range(3):
                source_corner = (0, 2, 1)[corner] if mirror else corner
                a = transform(source.worlds[node], source_positions[source_indices[triangle * 3 + source_corner]])
                b = transform(derived.worlds[target], target_positions[target_indices[(start + triangle) * 3 + corner]])
                max_error = max(max_error, *(abs(x - y) for x, y in zip(a, b)))
        triangles += count
    require(set(consumed) == set(source.geometry) and all(consumed[n] == len(p) for n, p in source.geometry.items()),
            'INCOMPLETE_MAPPING', 'Full-detail mapping omits source geometry.')
    require(set(ranges) == set(derived.geometry), 'INCOMPLETE_MAPPING', 'Mapping omits destination geometry.')
    for target, intervals in ranges.items():
        end = 0
        for start, stop in sorted(intervals):
            require(start == end, 'INVALID_MAPPING', 'Destination ranges overlap or contain gaps.')
            end = stop
        require(end * 3 == len(derived.geometry[target][0][1]), 'INCOMPLETE_MAPPING', 'Destination range is incomplete.')
    require(max_error <= tolerance, 'GEOMETRY_MISMATCH', 'Mapped vertex positions exceed the local conversion tolerance.')
    return {'status': 'passed', 'rows': len(rows), 'trianglesCompared': triangles,
            'sourceSha256': source.sha256, 'derivedSha256': derived.sha256,
            'inputSidecarBindsDerivative': bool(sidecar.get('derivedSha256')),
            'maximumVertexAxisError': max_error, 'localConversionTolerance': tolerance,
            'scope': 'Full selected-scene triangle positions and component/legacy-ID correspondence; not normals, UV, materials or engineering identity.'}


def check_control_points(model: Glb, control: dict | None) -> dict:
    if control is None:
        return {'status': 'not_provided', 'engineeringCoordinatesVerified': False}
    require(isinstance(control, dict), 'INVALID_CONTROL_POINTS', 'Control points must be a JSON object.')
    require(control.get('modelSha256') == model.sha256, 'DIGEST_MISMATCH', 'Control point artifact fingerprint differs.')
    points, tolerance = control.get('points'), control.get('toleranceMetres')
    require(control.get('units') == 'm' and isinstance(control.get('basis'), str) and bool(control['basis'].strip())
            and type(tolerance) in (int, float) and math.isfinite(tolerance) and tolerance > 0,
            'INVALID_CONTROL_POINTS', 'Control point units, basis or tolerance are invalid.')
    require(isinstance(points, list) and len(points) >= 3, 'INVALID_CONTROL_POINTS', 'At least three reference points are required.')
    seen, results, expected = set(), [], []
    for point in points:
        require(isinstance(point, dict) and isinstance(point.get('id'), str) and point['id']
                and point['id'] not in seen and finite_vector(point.get('expected'), 3),
                'INVALID_CONTROL_POINTS', 'Invalid or duplicate control point.')
        seen.add(point['id'])
        observed = model.point(point.get('nodeIndex'), point.get('primitiveIndex', 0), point.get('vertexIndex'))
        error = math.dist(observed, point['expected'])
        expected.append(point['expected'])
        results.append({'id': point['id'], 'observed': observed, 'expected': point['expected'],
                        'errorMetres': error, 'passed': error <= tolerance})
    a, b, c = expected[:3]
    u, v = [b[i] - a[i] for i in range(3)], [c[i] - a[i] for i in range(3)]
    area = math.sqrt(sum(x*x for x in (u[1]*v[2]-u[2]*v[1], u[2]*v[0]-u[0]*v[2], u[0]*v[1]-u[1]*v[0])))
    require(area > 1e-12, 'INVALID_CONTROL_POINTS', 'First three reference points must be distinct and non-collinear.')
    return {'status': 'passed' if all(p['passed'] for p in results) else 'failed',
            'basis': control['basis'], 'toleranceMetres': tolerance, 'points': results,
            'engineeringCoordinatesVerified': False,
            'limitation': 'Checks supplied local references only; reference authority, survey/site transform and purpose tolerance require review.'}


def run_probe(source_path: Path, output: Path, *, derived_path: Path | None = None,
              mapping_path: Path | None = None, source_sha256: str | None = None,
              derived_sha256: str | None = None, control_points: Path | None = None,
              previous_path: Path | None = None, previous_sha256: str | None = None) -> dict:
    output.mkdir(parents=True, exist_ok=False)
    report = {'schemaVersion': 2, 'purpose': 'PREP-02/Q-09 read-only model inspection',
              'createdAt': datetime.now(timezone.utc).isoformat(), 'status': 'failed',
              'releaseReadiness': {'eligible': False, 'G2Passed': False,
                                   'reasons': ['ENGINEERING_IDENTITY_UNVERIFIED', 'SITE_COORDINATES_UNVERIFIED',
                                               'LICENCE_UNVERIFIED', 'REVIEW_REQUIRED']}}
    try:
        require(bool(derived_path) == bool(mapping_path), 'INVALID_ARGUMENT', 'Derivative and mapping must be supplied together.')
        require(previous_path is not None or previous_sha256 is None, 'INVALID_ARGUMENT',
                'Previous fingerprint requires a previous source artifact.')
        source = Glb(source_path, source_sha256)
        report['source'] = source.summary()
        catalogs = {'source': source.catalog()}
        identity_comparison = None
        if previous_path is not None:
            previous = Glb(previous_path, previous_sha256)
            report['previous'] = previous.summary()
            catalogs['previous'] = previous.catalog()
            identity_comparison = compare_identity_claims(previous, source)
        checked_mapping = None
        if derived_path:
            derived = Glb(derived_path, derived_sha256)
            report['derived'] = derived.summary()
            mapping_bytes = mapping_path.read_bytes()
            sidecar = strict_json(mapping_bytes)
            report['mapping'] = compare_mapping(source, derived, sidecar)
            report['mapping']['inputSidecarSha256'] = hashlib.sha256(mapping_bytes).hexdigest()
            checked_mapping = {'schemaVersion': 1, 'keyStability': 'version_local',
                               'sourceSha256': source.sha256, 'derivedSha256': derived.sha256,
                               'scope': report['mapping']['scope'], 'sourceMapping': sidecar['sourceMapping']}
            catalogs['derived'] = derived.catalog()
        control_bytes = control_points.read_bytes() if control_points else None
        report['controlPoints'] = check_control_points(source, strict_json(control_bytes) if control_bytes is not None else None)
        if control_bytes is not None:
            report['controlPoints']['inputSha256'] = hashlib.sha256(control_bytes).hexdigest()
        report['status'] = 'failed' if report['controlPoints']['status'] == 'failed' else 'passed'
        report['limitations'] = ['Static uncompressed TRIANGLES in the selected scene only; no decoders or resource downloads.',
                                 'Version-local keys only. Source-ID claims, hierarchy, equipment UIDs and permissions are not verified.',
                                 'This probe does not replace Khronos glTF Validator or runtime picking/rendering checks.']
        catalog_bytes = (json.dumps(catalogs, ensure_ascii=False, indent=2, allow_nan=False) + '\n').encode('utf-8')
        (output / 'components.json').write_bytes(catalog_bytes)
        report['catalog'] = {'file': 'components.json', 'sha256': hashlib.sha256(catalog_bytes).hexdigest(),
                             'scope': 'All declared nodes, original extras and version-local keys; no engineering verification.'}
        if identity_comparison is not None and report['status'] == 'passed':
            candidate_bytes = (json.dumps(identity_comparison, ensure_ascii=False, indent=2, allow_nan=False) + '\n').encode('utf-8')
            (output / 'identity-candidates.json').write_bytes(candidate_bytes)
            report['identityComparison'] = {key: identity_comparison[key] for key in
                                            ('status', 'previousSha256', 'currentSha256', 'counts', 'unavailableCounts',
                                             'sourceIdentityVerified', 'geometryCorrespondenceVerified', 'bindingMigrationApproved')}
            report['identityComparison'].update(file='identity-candidates.json', sha256=hashlib.sha256(candidate_bytes).hexdigest())
        if checked_mapping is not None and report['status'] == 'passed':
            (output / 'mapping-checked.json').write_text(json.dumps(checked_mapping, ensure_ascii=False, indent=2, allow_nan=False) + '\n')
            report['mapping']['checkedSidecar'] = 'mapping-checked.json'
    except (ProbeError, OSError, TypeError, KeyError, struct.error) as error:
        report['error'] = {'code': error.code if isinstance(error, ProbeError) else 'INVALID_INPUT',
                           'message': str(error) if isinstance(error, ProbeError) else 'Cannot read or interpret local input.'}
    (output / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + '\n')
    return report


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--derived', type=Path)
    parser.add_argument('--mapping', type=Path)
    parser.add_argument('--source-sha256')
    parser.add_argument('--derived-sha256')
    parser.add_argument('--previous-source', type=Path, help='Previous source artifact; compares identity claims only, not a geometry derivative.')
    parser.add_argument('--previous-source-sha256')
    parser.add_argument('--control-points', type=Path, help='Source-model local reference JSON; never treated as survey approval.')
    parser.add_argument('--output', type=Path, required=True, help='New local output directory; existing directories are never replaced.')
    args = parser.parse_args(argv)
    try:
        report = run_probe(args.source, args.output, derived_path=args.derived, mapping_path=args.mapping,
                           source_sha256=args.source_sha256, derived_sha256=args.derived_sha256,
                           control_points=args.control_points, previous_path=args.previous_source,
                           previous_sha256=args.previous_source_sha256)
    except OSError:
        print('Cannot create a new output directory; existing output is never replaced.', file=sys.stderr)
        return 1
    print(json.dumps({'status': report['status'], 'report': str(args.output / 'report.json'),
                      'releaseEligible': False, 'errorCode': report.get('error', {}).get('code')}, ensure_ascii=False))
    return 0 if report['status'] == 'passed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
