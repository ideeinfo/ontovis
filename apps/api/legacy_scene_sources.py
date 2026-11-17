"""Trusted, current-user verification of the deployment's exact legacy sources.

The registry calls this reader inside its own read/write transaction. Paths come
only from the configured private stores; browser JSON never supplies a path or
an engineering fact. No OntoBase writes or automatic source adoption occur here.
"""
from __future__ import annotations

import hashlib
import math
import os
from pathlib import Path
import stat
import struct

from .authority import PreviewError
from .legacy_scene_registry import LegacySceneRegistry, source_set_digest
from .model_validation import MAX_BYTES
from .project_model_library import ProjectModelLibrary
from .scene_bindings import validate_expectations
from .scene_library import _json
from tools.model_probe import strict_json, ProbeError


def _require(value, code='LEGACY_SOURCE_CHANGED', status=409):
    if not value:
        raise PreviewError(status, code)


def _digest(value):
    return hashlib.sha256(_json(value).encode()).hexdigest()


def _decoded(value, kind):
    try:
        result = strict_json(value.encode() if isinstance(value, str) else value)
        _require(type(result) is kind)
        _json(result)
        return result
    except (ValueError, UnicodeError, TypeError, ProbeError):
        raise PreviewError(409, 'LEGACY_SOURCE_CHANGED') from None


def _identity(value):
    return value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns


def _read(path, limit):
    """No links, special files or unbounded reads, including replacement races."""
    try:
        _require(not any(parent.is_symlink() for parent in path.parents))
        before = path.lstat()
        _require(stat.S_ISREG(before.st_mode) and 0 < before.st_size <= limit)
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(descriptor, 'rb') as file:
            opened = os.fstat(file.fileno())
            _require(stat.S_ISREG(opened.st_mode) and _identity(opened) == _identity(before))
            raw = file.read(limit + 1)
            _require(len(raw) == opened.st_size and _identity(os.fstat(file.fileno())) == _identity(opened))
        _require(_identity(path.lstat()) == _identity(opened) and not any(parent.is_symlink() for parent in path.parents))
        return raw, (_identity(opened), hashlib.sha256(raw).hexdigest())
    except OSError:
        raise PreviewError(409, 'LEGACY_SOURCE_CHANGED') from None


def _same_bounds(left, right, *, float32=False):
    try:
        if any(type(box) is not list or len(box) != 2 or any(type(p) is not list or len(p) != 3 for p in box)
               for box in (left, right)):
            return False
        if not all(type(n) in (int, float) and math.isfinite(n) for box in (left, right) for p in box for n in p):
            return False
        return all(struct.pack('<f', a) == struct.pack('<f', b) if float32 else a == b
                   for p, q in zip(left, right) for a, b in zip(p, q))
    except (OverflowError, struct.error):
        return False


class LegacySceneSources:
    def __init__(self, library, fixed_model, reader):
        _require(library is not None and fixed_model is not None, 'LEGACY_REGISTRY_UNAVAILABLE', 503)
        self.library, self.fixed_model, self.reader = library, fixed_model, reader
        self._validated_files = {}

    @staticmethod
    def _file(path, limit, files):
        raw, identity = _read(path, limit)
        if path in files:
            _require(files[path] == (limit, identity))
        files[path] = (limit, identity)
        return raw

    @staticmethod
    def _finish(files):
        for path, (limit, identity) in files.items():
            _require(_read(path, limit)[1] == identity)

    def assert_unchanged(self):
        """Final local check after the caller's last network authorization.

        This request-local fingerprint set is not a cached engineering proof.
        The caller must perform no further network reads before commit/return.
        """
        self._finish(self._validated_files)

    def _inventory(self, db, files):
        scope = dict(db.execute('select * from library where id=1').fetchone())
        _require(scope['project_code'] == self.reader.project_code)
        raw = self._file(self.fixed_model.root / 'model.json', 1024 * 1024, files)
        fixed = _decoded(raw, dict)
        fields = {'schemaVersion', 'projectCode', 'installationContextId', 'rootEntityUid', 'sha256', 'bindings'}
        _require(fields <= set(fixed) <= fields | {'licenceBasis', 'sourceModelSha256'}
                 and type(fixed['schemaVersion']) is int and fixed['schemaVersion'] == 1
                 and fixed['projectCode'] == scope['project_code'] and fixed['installationContextId'] == scope['context_id']
                 and type(fixed['rootEntityUid']) is str and 0 < len(fixed['rootEntityUid']) <= 512)
        _require(fixed == self.fixed_model.value)  # A changed deployment needs an explicit service restart/check.
        if 'licenceBasis' in fixed:
            _require(type(fixed['licenceBasis']) is str and 0 < len(fixed['licenceBasis']) <= 2000)
        if 'sourceModelSha256' in fixed:
            _require(type(fixed['sourceModelSha256']) is str and len(fixed['sourceModelSha256']) == 64
                     and all(c in '0123456789abcdef' for c in fixed['sourceModelSha256']))
        bindings = fixed['bindings']
        _require(type(bindings) is list and len(bindings) == 3
                 and {item.get('componentKey') for item in bindings if type(item) is dict} == {'CT', 'CN1', 'CN'}
                 and len({item.get('entityUid') for item in bindings}) == 3)
        for binding in bindings:
            _require(set(binding) == {'entityUid', 'entityRevision', 'componentKey', 'geometryQuality', 'bounds'}
                     and all(type(binding[k]) is str and 0 < len(binding[k]) <= 512 for k in ('entityUid', 'entityRevision'))
                     and binding['entityUid'] != fixed['rootEntityUid']
                     and binding['geometryQuality'] == ('source_candidate' if binding['componentKey'] == 'CN' else 'proxy_schematic')
                     and _same_bounds(binding['bounds'], binding['bounds']))
        artifact = self._file(self.fixed_model.root / 'model.glb', MAX_BYTES, files)
        _require(hashlib.sha256(artifact).hexdigest() == fixed['sha256'])
        fixed_key = hashlib.sha256(raw).hexdigest()
        legacy = LegacySceneRegistry._legacy_rows(db)
        internal, public = {}, []
        for identifier, source in legacy.items():
            components = _decoded(source['components'], list)
            report = _decoded(source['report'], dict)
            _require(0 < len(components) <= 2002 and len({c.get('componentKey') for c in components if type(c) is dict}) == len(components))
            content = self._file(self.library.root / 'files' / (identifier + '.glb'), MAX_BYTES, files)
            _require(len(content) == source['bytes'] and hashlib.sha256(content).hexdigest() == source['sha256'])
            digest = _digest({'scope': scope, 'version': source})
            internal[identifier] = {'source': source, 'components': components, 'report': report}
            public.append({'sourceKind': 'uploaded_version', 'sourceKey': identifier, 'sourceDigest': digest})
        candidates = [identifier for identifier, item in internal.items() if self._matches_fixed(fixed, len(artifact), item)]
        public.append({'sourceKind': 'fixed_model', 'sourceKey': fixed_key, 'sourceDigest': _digest({
            'configurationSha256': fixed_key, 'contentSha256': fixed['sha256'], 'bytes': len(artifact),
            'configuration': fixed, 'catalogCandidates': sorted(candidates)})})
        public.sort(key=lambda item: (item['sourceKind'], item['sourceKey']))
        return {'libraryRevision': self.library.revision(db), 'items': public, 'defaultSourceKey': fixed_key,
                'sourceSetDigest': source_set_digest(public)}, fixed, internal

    @staticmethod
    def _matches_fixed(fixed, size, item):
        source, components = item['source'], {c.get('componentKey'): c for c in item['components']}
        if source['sha256'] != fixed['sha256'] or source['bytes'] != size or len(source['bindings']) != 3:
            return False
        old = {b['entity_uid']: b for b in source['bindings']}
        if set(old) != {b['entityUid'] for b in fixed['bindings']}:
            return False
        for binding in fixed['bindings']:
            record = old[binding['entityUid']]; part = components.get(record['component_key'], {})
            role = binding['componentKey']
            if (record['entity_revision'] != binding['entityRevision']
                    or part.get('geometryQuality') != binding['geometryQuality']
                    or role != 'CN' and record['component_key'] != 'proxy:' + role
                    or not _same_bounds(part.get('bounds'), binding['bounds'], float32=role == 'CN')):
                return False
        return True

    def inventory(self):
        files = {}
        with self.library.connect() as db:
            db.execute('pragma query_only=on'); db.execute('begin')
            value, _, _ = self._inventory(db, files)
            self._finish(files)
            self._validated_files = dict(files)
            return value

    def __call__(self, db, requested_sources, default_source_key):
        if not self.library.slots.acquire(blocking=False):
            raise PreviewError(429, 'MODEL_BUSY')
        try:
            return self._verify(db, requested_sources, default_source_key)
        finally:
            self.library.slots.release()

    def _verify(self, db, requested_sources, default_source_key):
        files = {}
        inventory, fixed, originals = self._inventory(db, files)
        _require(default_source_key == inventory['defaultSourceKey'])
        expected = [{'sourceKind': item['sourceKind'], 'sourceKey': item['sourceKey'],
                     'sourceDigest': item['expectedSourceDigest']} for item in requested_sources]
        _require(source_set_digest(expected) == inventory['sourceSetDigest'])
        legacy = {key: item['source'] for key, item in originals.items()}
        # Re-probe actual original geometry in the existing bounded subprocess.
        # Only the two explicitly configured proxies may augment that directory.
        for identifier, item in originals.items():
            source = item['source']
            _require(ProjectModelLibrary._source_rights(db, source), 'MODEL_SOURCE_RIGHTS_REQUIRED', 422)
            probe = self.library.process(self.library.root / 'files' / (identifier + '.glb'))
            parts = item['components']
            _require([part for part in parts if part.get('geometryQuality') != 'proxy_schematic'] == probe['components']
                     and item['report'] == probe['report'])
            proxies = [part for part in parts if part.get('geometryQuality') == 'proxy_schematic']
            _require(len(proxies) == 2 and {part['componentKey'] for part in proxies} == {'proxy:CT', 'proxy:CN1'}
                     and all(part.get('nodeIndices') == [] and part.get('keyStability') == 'version_local'
                             and _same_bounds(part.get('bounds'), part.get('bounds')) for part in proxies))
            by_key = {part['componentKey']: part for part in parts}
            old = {record['entity_uid']: record for record in source['bindings']}
            _require(len(old) == 3 and set(old) == {binding['entityUid'] for binding in fixed['bindings']},
                     'LEGACY_SOURCE_NOT_MIGRATABLE', 409)
            for binding in fixed['bindings']:
                record = old[binding['entityUid']]; part = by_key.get(record['component_key'], {})
                role = binding['componentKey']
                _require(part.get('geometryQuality') == binding['geometryQuality']
                         and (role == 'CN' or record['component_key'] == 'proxy:' + role),
                         'LEGACY_SOURCE_NOT_MIGRATABLE', 409)
            for record in source['bindings']:
                payloads = [_decoded(audit['payload'], dict) for audit in source['audit'] if audit['action'] == 'binding_saved']
                _require(any(all(body.get(key) == value for key, value in (
                    ('modelVersionId', identifier), ('entityUid', record['entity_uid']), ('componentKey', record['component_key']),
                    ('expectedEntityRevision', record['entity_revision']), ('expectedHierarchyRevision', record['hierarchy_revision'])))
                    for body in payloads))
        fresh = {}
        for requested in requested_sources:
            target = LegacySceneRegistry._target(db, requested, legacy, self.reader.project_code)
            model = target['model']; calibration = _decoded(model['calibration'], dict)
            cursor, seen = model['id'], set()
            while cursor not in legacy:
                _require(cursor not in seen and len(seen) < 20); seen.add(cursor)
                parent = db.execute('select source_version_id from project_model_versions where version_id=?', (cursor,)).fetchone()
                _require(parent is not None); cursor = parent[0]
            if requested['sourceKind'] == 'fixed_model':
                candidates = [key for key, item in originals.items() if self._matches_fixed(fixed, len(self._file(
                    self.fixed_model.root / 'model.glb', MAX_BYTES, files)), item)]
                explicit = calibration.get('sourceModelVersionId')
                if explicit is not None: candidates = [key for key in candidates if key == explicit]
                _require(len(candidates) == 1 and cursor == candidates[0], 'LEGACY_SOURCE_NOT_MIGRATABLE', 409)
            else:
                _require(cursor == requested['sourceKey'])
            raw = self._file(self.library.root / 'files' / (model['id'] + '.glb'), MAX_BYTES, files)
            _require(len(raw) == model['bytes'] and hashlib.sha256(raw).hexdigest() == model['sha256'])
            instance = target['snapshot']['instances'][0]
            root = instance['rootBinding']['objectRef']
            _require(root == self.reader._ref(fixed['rootEntityUid']))
            refs = [root, *[binding['objectRef'] for binding in instance['componentBindings']]]
            expectations = validate_expectations(target['validation']['engineeringExpectations'],
                connection_id=self.reader.connection_id, project_code=self.reader.project_code, required_refs=refs)
            by_uid = {fact['ref']['entityUid']: fact for fact in expectations}
            old = {record['entity_uid']: record for record in legacy[cursor]['bindings']}
            _require(set(by_uid) == {fixed['rootEntityUid'], *old})
            hierarchy = {record['hierarchy_revision'] for record in old.values()}
            _require(len(hierarchy) == 1 and by_uid[fixed['rootEntityUid']]['expectedHierarchyRevision'] in hierarchy)
            for uid, fact in by_uid.items():
                _require(fact['installationContextId'] == fixed['installationContextId'])
                if uid in old:
                    _require(fact['expectedEntityRevision'] == old[uid]['entity_revision']
                             and fact['expectedHierarchyRevision'] == old[uid]['hierarchy_revision'])
                key = (uid, fact['installationContextId'], fact['expectedEntityRevision'], fact['expectedHierarchyRevision'])
                if key not in fresh:
                    actual = self.reader.detail(fact['installationContextId'], uid, fact['expectedHierarchyRevision'],
                        expected_entity_revision=fact['expectedEntityRevision'])
                    _require(actual['bindingEligible'] and actual['expectation'] == fact
                             and actual['context']['rootEntityUid'] == fixed['rootEntityUid']
                             and actual['context']['purpose'] == 'demonstration'
                             and actual['context']['engineeringUseAllowed'] is False, 'ENGINEERING_CHANGED', 409)
                    # Exclude retrieval timestamps; retain every current ancestor
                    # incarnation and relation revision used by the Reader.
                    fresh[key] = {'expectation': fact, 'context': actual['context'], 'item': actual['item'],
                        'ancestors': actual['ancestors']['path']}
        self._finish(files)
        self._validated_files = dict(files)
        return {'sourceSetDigest': inventory['sourceSetDigest'],
                'engineeringDigest': _digest([fresh[key] for key in sorted(fresh)])}
