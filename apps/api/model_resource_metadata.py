"""Append-only source specifications for fixed project model resources.

These records describe visual resources, not authoritative installed equipment.
Callers supply the same current-project authorization guard as model resources.
"""
from __future__ import annotations

from datetime import datetime
import hashlib
import hmac
import json
import math
import re
from urllib.parse import urlsplit
from uuid import uuid4

from .project_model_library import _canonical, _fields, _now, _require, _text, _uuid


MAX_METADATA_BYTES = 64 * 1024
MAX_METADATA_REQUEST_BYTES = 72 * 1024
FIELD_UNITS = {
    **dict.fromkeys(('manufacturer', 'designer', 'model', 'deploymentEnvironment',
                    'foundationType', 'driveTrainType', 'generatorType')),
    **dict.fromkeys(('ratedPowerKw', 'baseRatedPowerKw', 'siteOperatingPowerKw'), 'kW'),
    **dict.fromkeys(('hubHeightM', 'alternativeHubHeightM', 'towerHeightM', 'rotorDiameterM',
                    'bladeLengthM', 'nacelleLengthM', 'nacelleWidthM', 'nacelleHeightM', 'nacelleMaximumRadiusM'), 'm'),
    **dict.fromkeys(('cutInWindSpeedMps', 'ratedWindSpeedMps', 'cutOutWindSpeedMps',
                    'cutOutOptionMaximumMps', 'restartWindSpeedMps',
                    'survivalWindSpeed10minMps', 'survivalWindSpeed3secMps'), 'm/s'),
    **dict.fromkeys(('rotorSpeedMinimumRpm', 'rotorSpeedMaximumRpm', 'rotorRatedSpeedRpm'), 'rpm'),
    'gearboxRatio': '1', 'gearboxStages': 'count', 'designLifetimeYears': 'year', 'sweptAreaM2': 'm²',
}
KINDS = frozenset(('page_declared', 'program_geometry_parameter',
                   'simulation_operating_parameter', 'derived_calculation'))
CONFIDENCES = frozenset(('source_asserted_unverified', 'secondary_source_asserted', 'model_parameter',
                         'inferred', 'derived', 'teaching_design'))
SCOPES = frozenset(('type', 'site_configuration', 'program_default', 'teaching_reference',
                   'teaching_variant', 'platform_reference'))


def _string(value, maximum=500, *, empty=False, multiline=False):
    _require(type(value) is str and len(value) <= maximum and (empty or bool(value.strip())))
    _require(all(ord(c) >= 32 and ord(c) != 127 or multiline and c in '\n\r\t' for c in value))
    return value


def _sha(value):
    _require(type(value) is str and re.fullmatch('[a-f0-9]{64}', value) is not None)


def _timestamp(value):
    _string(value, 80)
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
        _require(parsed.tzinfo is not None)
    except ValueError:
        _require(False)


def _url(value):
    _string(value, 2048)
    try:
        parsed = urlsplit(value)
        _require(parsed.scheme == 'https' and parsed.hostname and not parsed.username and not parsed.password
                 and not any(c.isspace() for c in value))
        parsed.port
    except ValueError:
        _require(False)


def _source(value, *, page=False):
    _fields(value, ('url', 'sha256', 'fetchedAt') if page else
            ('url', 'locator', 'lineStart', 'lineEnd', 'pageSha256', 'fetchedAt'), ('localSnapshot',))
    _url(value['url']); _sha(value['sha256' if page else 'pageSha256'])
    _timestamp(value['fetchedAt'])
    if 'localSnapshot' in value:
        _string(value['localSnapshot'], 1000)
    if not page:
        _string(value['locator'], 1000)
        _require(type(value['lineStart']) is int and type(value['lineEnd']) is int
                 and 1 <= value['lineStart'] <= value['lineEnd'] <= 10_000_000)


def validate_metadata(value):
    """Validate the finite turbine-source schema while retaining all evidence."""
    try:
        length = len(_canonical(value).encode('utf-8'))
    except RecursionError:
        _require(False)
    _require(length <= MAX_METADATA_BYTES, 'METADATA_LIMIT_EXCEEDED', 413)
    _fields(value, ('schemaVersion', 'resourceKey', 'displayName', 'resourceClass', 'verificationStatus',
                    'sourcePage', 'fields', 'teachingVariants', 'cautions', 'excludedRuntimeValues', 'modelBasis'))
    _require(type(value['schemaVersion']) is int and value['schemaVersion'] == 1)
    _require(type(value['resourceKey']) is str and re.fullmatch('[a-z0-9][a-z0-9-]{0,199}', value['resourceKey']))
    _string(value['displayName'], 200)
    _require(value['resourceClass'] in ('teaching_reference', 'public_source_model')
             and value['verificationStatus'] == 'source_only_not_oem_verified')
    _source(value['sourcePage'], page=True)
    _fields(value['fields'], FIELD_UNITS)
    for name, evidence in value['fields'].items():
        if evidence is None:
            continue
        _require(type(evidence) is list and 1 <= len(evidence) <= 16)
        for item in evidence:
            _fields(item, ('value', 'rawValue', 'unit', 'source', 'kind', 'confidence', 'scope', 'note'))
            fact = item['value']
            if type(fact) is str:
                _string(fact, 1000, empty=True)
            else:
                _require(fact is None or type(fact) is bool or type(fact) in (int, float)
                         and abs(fact) <= 1e15 and math.isfinite(fact))
            _require(item['unit'] == FIELD_UNITS[name])
            _string(item['rawValue'], 4000, empty=True, multiline=True)
            _source(item['source'])
            _require(type(item['kind']) is str and item['kind'] in KINDS
                     and type(item['confidence']) is str and item['confidence'] in CONFIDENCES
                     and type(item['scope']) is str and item['scope'] in SCOPES)
            _string(item['note'], 2000, empty=True, multiline=True)
    variants = value['teachingVariants']
    _require(type(variants) is list and len(variants) <= 2
             and all(type(item) is str and item in ('geared', 'direct_drive') for item in variants)
             and len(variants) == len(set(variants)))
    _require(type(value['cautions']) is list and len(value['cautions']) <= 32)
    for caution in value['cautions']:
        _string(caution, 2000, multiline=True)
    _require(type(value['excludedRuntimeValues']) is list and len(value['excludedRuntimeValues']) <= 16)
    for item in value['excludedRuntimeValues']:
        _fields(item, ('name', 'reason', 'source', 'rawValue'))
        _string(item['name'], 100); _string(item['reason'], 1000, multiline=True)
        _string(item['rawValue'], 4000, empty=True, multiline=True); _source(item['source'])
    if value['modelBasis'] is not None:
        _fields(value['modelBasis'], ('source', 'note'), ('rawText', 'summary', 'sourceQuality'))
        _require('rawText' in value['modelBasis'] or 'summary' in value['modelBasis'])
        if 'rawText' in value['modelBasis']:
            _string(value['modelBasis']['rawText'], 16000, multiline=True)
        if 'summary' in value['modelBasis']:
            _string(value['modelBasis']['summary'], 4000, multiline=True)
        if 'sourceQuality' in value['modelBasis']:
            quality = value['modelBasis']['sourceQuality']
            _fields(quality, ('status', 'engineeringIdentityVerified', 'liveTelemetryIncluded'))
            _require(quality['status'] == 'source_only_not_oem_verified'
                     and quality['engineeringIdentityVerified'] is False and quality['liveTelemetryIncluded'] is False)
        _string(value['modelBasis']['note'], 2000, empty=True, multiline=True)
        _source(value['modelBasis']['source'])
    return value


class ModelResourceMetadata:
    def __init__(self, models):
        self.models, self.library, self.project_code = models, models.library, models.project_code
        with self.library.connect() as db:
            db.executescript('''
                create table if not exists model_resource_metadata_revisions (
                    revision text primary key, project_code text not null,
                    asset_id text not null references project_model_assets(id),
                    version_id text not null references project_model_versions(version_id),
                    sequence integer not null, model_sha256 text not null, metadata text not null,
                    created_at text not null, created_by text not null,
                    unique(project_code,asset_id,version_id,sequence));
                create table if not exists model_resource_metadata_requests (
                    project_code text not null, actor text not null, request_id text not null,
                    payload_sha256 text not null,
                    metadata_revision text not null references model_resource_metadata_revisions(revision),
                    primary key(project_code,actor,request_id));
                create table if not exists model_resource_metadata_audit (
                    id integer primary key, project_code text not null, actor text not null,
                    request_id text not null, action text not null,
                    metadata_revision text not null references model_resource_metadata_revisions(revision),
                    payload_sha256 text not null, created_at text not null);
            ''')
            for table in ('model_resource_metadata_revisions', 'model_resource_metadata_requests', 'model_resource_metadata_audit'):
                for action in ('update', 'delete'):
                    db.execute(f'''create trigger if not exists {table}_no_{action} before {action} on {table}
                        begin select raise(abort, 'immutable model resource metadata'); end''')

    def _identity(self, db, asset_id, version_id):
        self.models._asset(db, asset_id)
        version = self.models._version(db, version_id)
        _require(version['modelAssetId'] == asset_id, 'NOT_FOUND_OR_FORBIDDEN', 404)
        return version

    @staticmethod
    def _public(row):
        return {'metadataRevision': row['revision'], 'modelAssetId': row['asset_id'],
                'modelVersionId': row['version_id'], 'modelSha256': row['model_sha256'],
                'metadata': json.loads(row['metadata']), 'createdAt': row['created_at'], 'createdBy': row['created_by']}

    def read(self, body, authorize):
        _require(callable(authorize)); authorize()
        _fields(body, ('modelAssetId', 'modelVersionId'), ('metadataRevision',))
        if 'metadataRevision' in body:
            _text(body['metadataRevision'], 100)
        with self.library.connect() as db:
            db.execute('begin')
            self._identity(db, body['modelAssetId'], body['modelVersionId'])
            conditions = 'project_code=? and asset_id=? and version_id=?'
            args = (self.project_code, body['modelAssetId'], body['modelVersionId'])
            if 'metadataRevision' in body:
                conditions += ' and revision=?'
                args += (body['metadataRevision'],)
            row = db.execute('select * from model_resource_metadata_revisions where ' + conditions
                             + ' order by sequence desc limit 1', args).fetchone()
            if 'metadataRevision' in body:
                _require(row is not None, 'NOT_FOUND_OR_FORBIDDEN', 404)
            result = {'item': self._public(row) if row else None}
            authorize()
        return result

    def save(self, body, actor, authorize):
        _require(callable(authorize)); actor = _text(actor); authorize()
        _fields(body, ('modelAssetId', 'modelVersionId', 'expectedMetadataRevision', 'clientRequestId', 'metadata'))
        _uuid(body['modelAssetId']); _uuid(body['modelVersionId']); _uuid(body['clientRequestId'])
        if body['expectedMetadataRevision'] is not None:
            _text(body['expectedMetadataRevision'], 100)
        metadata = _canonical(validate_metadata(body['metadata']))
        digest = hashlib.sha256(_canonical(body).encode()).hexdigest()
        with self.library.connect() as db:
            db.execute('begin immediate')
            version = self._identity(db, body['modelAssetId'], body['modelVersionId'])
            prior = db.execute('''select payload_sha256,metadata_revision from model_resource_metadata_requests
                where project_code=? and actor=? and request_id=?''',
                (self.project_code, actor, body['clientRequestId'])).fetchone()
            if prior:
                _require(hmac.compare_digest(prior['payload_sha256'], digest), 'REQUEST_CONFLICT', 409)
                row = db.execute('select * from model_resource_metadata_revisions where revision=?',
                                 (prior['metadata_revision'],)).fetchone()
            else:
                self.models._asset(db, body['modelAssetId'])
                latest = db.execute('''select revision,sequence from model_resource_metadata_revisions
                    where project_code=? and asset_id=? and version_id=? order by sequence desc limit 1''',
                    (self.project_code, body['modelAssetId'], body['modelVersionId'])).fetchone()
                _require(body['expectedMetadataRevision'] == (latest['revision'] if latest else None), 'METADATA_CHANGED', 409)
                authorize()
                revision, now = 'metadata:' + str(uuid4()), _now()
                db.execute('insert into model_resource_metadata_revisions values (?,?,?,?,?,?,?,?,?)',
                    (revision, self.project_code, body['modelAssetId'], body['modelVersionId'],
                     latest['sequence'] + 1 if latest else 1, version['sha256'], metadata, now, actor))
                db.execute('insert into model_resource_metadata_requests values (?,?,?,?,?)',
                    (self.project_code, actor, body['clientRequestId'], digest, revision))
                db.execute('''insert into model_resource_metadata_audit
                    (project_code,actor,request_id,action,metadata_revision,payload_sha256,created_at)
                    values (?,?,?,?,?,?,?)''',
                    (self.project_code, actor, body['clientRequestId'], 'metadata_saved', revision, digest, now))
                row = db.execute('select * from model_resource_metadata_revisions where revision=?', (revision,)).fetchone()
            authorize()
            result = {'item': self._public(row)}
        return result
