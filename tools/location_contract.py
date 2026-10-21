#!/usr/bin/env python3
"""Offline OV-C05 contract examples; synthetic authority replies, no product API."""
from __future__ import annotations

import argparse
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import sys


class FixtureError(ValueError):
    """Malformed synthetic input, distinct from a simulated business refusal."""


@dataclass(frozen=True)
class ObjectRef:
    ontobaseConnectionId: str
    projectCode: str
    entityUid: str

    @classmethod
    def read(cls, value: dict) -> ObjectRef:
        keys = ('ontobaseConnectionId', 'projectCode', 'entityUid')
        if not isinstance(value, dict) or set(value) != set(keys):
            raise FixtureError('ObjectRef must have exactly three identity fields.')
        if not all(isinstance(value[k], str) and value[k].startswith('fixture-') for k in keys):
            raise FixtureError('Only synthetic fixture-* ObjectRefs are accepted.')
        return cls(*(value[k] for k in keys))


def instant(value: str) -> datetime:
    try:
        result = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if result.utcoffset() is None or result.utcoffset().total_seconds() != 0:
            raise ValueError('UTC required')
        return result
    except (AttributeError, TypeError, ValueError) as error:
        raise FixtureError('An explicit UTC timestamp is required.') from error


def flag(value: bool) -> bool:
    if type(value) is not bool:
        raise FixtureError('Authority boolean fields must be JSON booleans.')
    return value


MESSAGES = {
    'FORBIDDEN': '当前无权访问项目或场景',
    'NOT_FOUND_OR_FORBIDDEN': '对象不可用或无权访问',
    'SOURCE_UNAVAILABLE': '工程对象来源暂不可用',
    'INSTANCE_MISMATCH': '对象与安装实例不一致',
    'IDENTITY_CHANGED': '工程身份已变化，绑定需要复核',
    'OBJECT_RETIRED': '工程对象已退役，当前位置不可用',
    'HISTORY_UNAVAILABLE': '指定历史组合不可用，请另行选择查询时点',
    'MULTIPLE_REPRESENTATIONS': '存在多个几何表示，请明确选择',
    'REVISION_CONFLICT': '读取修订不一致，请重新获取',
    'NO_GEOMETRY': '没有可用的已发布几何',
    'NO_CONFIRMED_PATH': '没有完整的已确认物理父链',
    'PATH_UNAVAILABLE': '物理父链不可用',
    'DEPTH_LIMIT': '物理父链超过本次验证深度',
    'MULTIPLE_PARENTS': '物理父链存在多个父级',
    'CYCLE_DETECTED': '物理父链存在环',
    'DIRECT_GEOMETRY': '定位到所选对象的已发布几何',
    'ANCESTOR_GEOMETRY': '定位到所属祖先几何；所选设备未独立建模，内部坐标未知',
}
CHOICE_FIELDS = ('sceneRevision', 'sceneModelInstanceId', 'modelVersionId', 'componentKeys')
REQUEST_FIELDS = {'selectedObjectRef', 'sceneId', 'sceneModelInstanceId', 'representationChoice',
                  'resolutionMode', 'asOf', 'sceneRevision', 'hierarchyRevision', 'contextEpoch'}


def evaluate(request: dict, facts: dict) -> dict:
    """Evaluate recorded, trusted fixture facts. Client input never supplies access facts."""
    if set(request) - REQUEST_FIELDS:
        raise FixtureError('Unknown request field; client capabilities/parent paths are not accepted.')
    selected = ObjectRef.read(request['selectedObjectRef'])
    mode = request['resolutionMode']
    if mode not in ('live', 'history') or not isinstance(request['contextEpoch'], str) or not request['contextEpoch']:
        raise FixtureError('resolutionMode and a nonempty contextEpoch are required.')
    if mode == 'live' and any(k in request for k in ('asOf', 'sceneRevision', 'hierarchyRevision')):
        raise FixtureError('A live request cannot nominate authority time or revisions.')
    if mode == 'history' and (not request.get('asOf') or not request.get('sceneRevision')):
        raise FixtureError('History requires asOf and sceneRevision.')
    as_of = request['asOf'] if mode == 'history' else facts['resolvedAsOf']
    at = instant(as_of)
    instant(facts['resolvedAt'])

    def error(code: str, retryable: bool = False) -> dict:
        return {'code': code, 'message': MESSAGES[code], 'retryable': retryable,
                'requestId': facts['requestId']}

    access = facts['access']
    if not flag(access['project']) or not flag(access['scene']):
        return error('FORBIDDEN')
    if facts['sourceState'] != 'connected':
        return error('SOURCE_UNAVAILABLE', True)
    readable = {ObjectRef.read(ref) for ref in access['objectRefs']}
    scope = (facts['ontobaseConnectionId'], facts['projectCode'])

    def in_scope(ref: ObjectRef) -> bool:
        return (ref.ontobaseConnectionId, ref.projectCode) == scope

    objects = {}
    for obj in facts['objects']:
        key = ObjectRef.read(obj['objectRef'])
        if key in objects:
            raise FixtureError('Duplicate object authority reply.')
        objects[key] = obj
    if selected not in readable or not in_scope(selected) or selected not in objects:
        return error('NOT_FOUND_OR_FORBIDDEN')
    if instant(facts['resolvedAsOf']) != at:
        return error('REVISION_CONFLICT', True)

    scene = facts['scene']
    response = {
        'requestedObjectRef': deepcopy(request['selectedObjectRef']),
        'selectedObjectRef': deepcopy(request['selectedObjectRef']),
        'identityState': 'exact', 'canonicalObjectRef': None, 'locatedObjectRef': None,
        'locationMode': 'unlocated', 'geometryQuality': None, 'resolutionMode': mode,
        'resolvedAsOf': as_of, 'resolvedAt': facts['resolvedAt'],
        'sceneRevision': None, 'bindingRevision': None, 'hierarchyRevision': None,
        'modelVersionId': None, 'sceneModelInstanceId': None, 'componentKey': None,
        'componentKeys': [], 'path': [], 'representationChoices': [],
        'reasonCode': None, 'reason': None, 'contextEpoch': request['contextEpoch'],
    }

    def unlocated(code: str) -> dict:
        response.update(reasonCode=code, reason=MESSAGES[code])
        return response

    # Never reinterpret an available current scene as the requested historical scene.
    if (scene is None or scene['sceneId'] != request['sceneId']
            or (mode == 'history' and scene['sceneRevision'] != request['sceneRevision'])):
        return unlocated('HISTORY_UNAVAILABLE') if mode == 'history' else error('SOURCE_UNAVAILABLE', True)
    response['sceneRevision'] = scene['sceneRevision']
    response['bindingRevision'] = scene['bindingRevision']
    if scene['unavailableParts']:
        if 'binding' in scene['unavailableParts']:
            response['bindingRevision'] = None
        return unlocated('HISTORY_UNAVAILABLE') if mode == 'history' else error('SOURCE_UNAVAILABLE', True)
    if not flag(scene['published']):
        return error('REVISION_CONFLICT')
    if request.get('sceneModelInstanceId'):
        instances = [item for item in scene['instances']
                     if item['sceneModelInstanceId'] == request['sceneModelInstanceId']]
        if len(instances) != 1 or instances[0]['installationContextId'] != facts['installationContextId']:
            return unlocated('INSTANCE_MISMATCH')

    def identity_issue(ref: ObjectRef) -> str | None:
        obj = objects[ref]
        if obj['installationContextId'] != facts['installationContextId']:
            return 'INSTANCE_MISMATCH'
        if obj['resolution'] != 'exact' or obj['lifecycle'] == 'deleted':
            return 'IDENTITY_CHANGED'
        if obj['lifecycle'] != 'active':
            return 'OBJECT_RETIRED'
        return None

    issue = identity_issue(selected)
    if issue:
        if issue == 'IDENTITY_CHANGED':
            response['identityState'] = 'needs_review'
            canonical = objects[selected].get('canonicalRef')
            if canonical is not None:
                ref = ObjectRef.read(canonical)
                if ref in readable and in_scope(ref):
                    response['canonicalObjectRef'] = deepcopy(canonical)
        return unlocated(issue)

    if mode == 'history' and request.get('hierarchyRevision'):
        fixed = facts['hierarchy']
        if fixed is None or fixed['hierarchyRevision'] != request['hierarchyRevision']:
            return unlocated('HISTORY_UNAVAILABLE')
        if (instant(fixed['resolvedAsOf']) != at or not flag(fixed['consistent'])
                or fixed['installationContextId'] != facts['installationContextId']):
            return error('REVISION_CONFLICT', True)
        response['hierarchyRevision'] = fixed['hierarchyRevision']

    def representation(ref: ObjectRef) -> tuple[dict | None, str | None, list]:
        candidates = [r for r in facts['representations'] if ObjectRef.read(r['objectRef']) == ref
                      and r['status'] != 'draft'
                      and (not request.get('sceneModelInstanceId')
                           or r['sceneModelInstanceId'] == request['sceneModelInstanceId'])]
        if not candidates:
            return None, None, []
        for r in candidates:
            instances = [i for i in scene['instances'] if i['sceneModelInstanceId'] == r['sceneModelInstanceId']]
            if len(instances) != 1 or instances[0]['installationContextId'] != facts['installationContextId']:
                return None, 'INSTANCE_MISMATCH', []
            instance = instances[0]
            if (r['status'] != 'published' or r['sceneRevision'] != scene['sceneRevision']
                    or r['bindingRevision'] != scene['bindingRevision']
                    or r['modelVersionId'] != instance['modelVersionId']
                    or not r['componentKeys'] or len(set(r['componentKeys'])) != len(r['componentKeys'])
                    or not set(r['componentKeys']) <= set(instance['componentKeys'])):
                return None, 'REVISION_CONFLICT', []
            if r['entityRevision'] != objects[ref]['entityRevision']:
                return None, 'IDENTITY_CHANGED', []
            if r['geometryQuality'] not in ('source_verified', 'source_candidate', 'proxy_schematic'):
                raise FixtureError('Unknown geometry quality.')
        choices = [{k: deepcopy(r[k]) for k in CHOICE_FIELDS} for r in candidates]
        chosen = request.get('representationChoice')
        if chosen is not None:
            matches = [r for r, choice in zip(candidates, choices) if chosen == choice]
            return (matches[0], None, []) if len(matches) == 1 else (None, 'REVISION_CONFLICT', [])
        primary = [r for r in candidates if flag(r['reviewedPrimary'])]
        if len(candidates) == 1:
            return candidates[0], None, []
        if len(primary) == 1:
            return primary[0], None, []
        return None, 'MULTIPLE_REPRESENTATIONS', choices

    def locate(ref: ObjectRef, path: list) -> dict | None:
        candidate, issue, choices = representation(ref)
        if issue:
            response['representationChoices'] = choices
            return unlocated(issue)
        if candidate is None:
            return None
        code = 'DIRECT_GEOMETRY' if ref == selected else 'ANCESTOR_GEOMETRY'
        response.update(locatedObjectRef=deepcopy(candidate['objectRef']),
                        locationMode='direct_geometry' if ref == selected else 'ancestor_proxy',
                        geometryQuality=candidate['geometryQuality'],
                        modelVersionId=candidate['modelVersionId'],
                        sceneModelInstanceId=candidate['sceneModelInstanceId'],
                        componentKey=candidate['componentKeys'][0],
                        componentKeys=deepcopy(candidate['componentKeys']), path=deepcopy(path),
                        reasonCode=code, reason=MESSAGES[code])
        return response

    direct = locate(selected, [])
    if direct is not None:
        return direct
    hierarchy = facts['hierarchy']
    if hierarchy is None:
        return unlocated('HISTORY_UNAVAILABLE' if mode == 'history' else 'NO_CONFIRMED_PATH')
    if instant(hierarchy['resolvedAsOf']) != at or hierarchy['installationContextId'] != facts['installationContextId']:
        return error('REVISION_CONFLICT', True)
    if mode == 'history' and request.get('hierarchyRevision') not in (None, hierarchy['hierarchyRevision']):
        return unlocated('HISTORY_UNAVAILABLE')
    if not flag(hierarchy['consistent']):
        return error('REVISION_CONFLICT', True)
    completeness = hierarchy['completeness']
    if completeness != 'complete':
        codes = {'unavailable': 'PATH_UNAVAILABLE', 'truncated': 'DEPTH_LIMIT',
                 'multiple_parents': 'MULTIPLE_PARENTS', 'cycle': 'CYCLE_DETECTED'}
        return unlocated(codes.get(completeness, 'NO_CONFIRMED_PATH'))
    path = hierarchy['path']
    if len(path) > 32:
        return unlocated('DEPTH_LIMIT')
    seen, previous = {selected}, selected
    # Validate the entire authorized chain before using even its nearest geometry.
    for step in path:
        child, parent = ObjectRef.read(step['childRef']), ObjectRef.read(step['parentRef'])
        if child != previous or not in_scope(parent) or parent not in readable or parent not in objects:
            return unlocated('PATH_UNAVAILABLE')
        if parent in seen:
            return unlocated('CYCLE_DETECTED')
        if step['status'] != 'confirmed' or not step['evidenceRefs']:
            return unlocated('NO_CONFIRMED_PATH')
        start, end = instant(step['validFrom']), instant(step['validTo']) if step['validTo'] else None
        if (end is not None and end <= start) or at < start or (end is not None and at >= end):
            return unlocated('NO_CONFIRMED_PATH')
        issue = identity_issue(parent)
        if issue:
            return unlocated(issue)
        seen.add(parent)
        previous = parent
    response['hierarchyRevision'] = hierarchy['hierarchyRevision']
    for depth, step in enumerate(path, 1):
        result = locate(ObjectRef.read(step['parentRef']), path[:depth])
        if result is not None:
            return result
    return unlocated('NO_GEOMETRY')


def run_suite(path: Path) -> dict:
    def unique_fields(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise FixtureError('Duplicate JSON field in fixture input.')
            result[key] = value
        return result

    suite = json.loads(path.read_text(encoding='utf-8'), object_pairs_hook=unique_fields)
    if suite['fixtureKind'] != 'synthetic_location_contract' or suite['contractVersion'] != '0.1':
        raise FixtureError('Expected the explicitly marked V0.1 synthetic fixture suite.')
    cases, seen = [], set()
    for case in suite['cases']:
        if set(case) - {'caseId', 'covers', 'request', 'facts', 'expected', 'expectedError'}:
            raise FixtureError('Unknown case property.')
        if case['caseId'] in seen or not case['covers']:
            raise FixtureError('Case IDs must be unique and linked to acceptance criteria.')
        if 'expected' in case and 'expectedError' in case:
            raise FixtureError('A case cannot expect both a location response and an error.')
        if any(k not in suite['baseRequest'] and k not in REQUEST_FIELDS for k in case.get('request', {})):
            raise FixtureError('Unknown request override.')
        if set(case.get('facts', {})) - set(suite['baseFacts']):
            raise FixtureError('Unknown authority fact override.')
        seen.add(case['caseId'])
        request = deepcopy(suite['baseRequest']) | deepcopy(case.get('request', {}))
        facts = deepcopy(suite['baseFacts']) | deepcopy(case.get('facts', {}))
        expected = (deepcopy(case['expectedError']) if 'expectedError' in case
                    else deepcopy(suite['baseExpected']) | deepcopy(case.get('expected', {})))
        actual = evaluate(request, facts)
        cases.append({'caseId': case['caseId'], 'covers': case['covers'],
                      'request': request, 'recordedAuthority': facts,
                      'expected': expected, 'actual': actual, 'passed': actual == expected})
    if not cases:
        raise FixtureError('An empty suite cannot pass.')
    return {'fixtureKind': suite['fixtureKind'], 'contractVersion': suite['contractVersion'],
            'verificationScope': 'offline_contract_only', 'realIntegrationPassed': False,
            'G1Passed': False, 'G2Passed': False, 'G3Passed': False,
            'caseCount': len(cases), 'passedCount': sum(c['passed'] for c in cases),
            'status': 'passed' if all(c['passed'] for c in cases) else 'failed', 'cases': cases}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--fixtures', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True, help='A new local output directory')
    args = parser.parse_args()
    try:
        args.output.mkdir(parents=True, exist_ok=False)
    except OSError as error:
        print(f'Output directory must be new: {error}', file=sys.stderr)
        return 1
    try:
        report = run_suite(args.fixtures)
    except (FixtureError, OSError, ValueError, KeyError, TypeError) as error:
        report = {'status': 'failed', 'verificationScope': 'offline_contract_only',
                  'realIntegrationPassed': False, 'error': f'{type(error).__name__}: {error}'}
    report['generatedAt'] = datetime.now(timezone.utc).isoformat()
    (args.output / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({k: report[k] for k in ('status', 'caseCount', 'passedCount') if k in report}, ensure_ascii=False))
    return 0 if report['status'] == 'passed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
