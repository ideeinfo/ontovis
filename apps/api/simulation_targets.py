"""Resolve the private deployment's explicit replay registrations for the current member."""
import json
import re
from uuid import UUID

from .authority import PreviewError
from .equipment_reader import EquipmentReader

FILENAME = 'simulation-alarm-targets.json'
FIELDS = {'datasetRevision','rootUid','entityUid','definitionUid','installationContextId','sceneId','instanceId'}


def load_registrations(path, connection, project):
    try:
        with path.open('rb') as source:
            raw = source.read(32769)
        if len(raw) > 32768:
            raise ValueError('oversize registration file')
        value = json.loads(raw)
        if (type(value) is not dict or set(value) != {'schemaVersion','projectRef','targets'}
                or type(value['schemaVersion']) is not int or value['schemaVersion'] != 1
                or value['projectRef'] != {'ontobaseConnectionId': connection, 'projectCode': project}
                or type(value['targets']) is not dict or len(value['targets']) > 32):
            raise ValueError('invalid registration scope')
        for key, target in value['targets'].items():
            if (not key.startswith('SIM-') or len(key) > 100 or type(target) is not dict or set(target) != FIELDS
                    or any(type(entry) is not str or not entry.strip() or len(entry) > 512 for entry in target.values())
                    or not re.fullmatch('[0-9a-f]{64}',target['datasetRevision']) or target['rootUid'] == target['entityUid']
                    or any(str(UUID(target[field])) != target[field] for field in ('installationContextId','sceneId','instanceId'))):
                raise ValueError('invalid registration target')
        return value['targets']
    except FileNotFoundError:
        return {}
    except (OSError, ValueError, RecursionError):
        raise PreviewError(503, 'SIMULATION_TARGETS_UNAVAILABLE') from None


def resolve_targets(path, reader, datasets):
    registered = load_registrations(path, reader.connection_id, reader.project_code)
    pairs = {row['datasetId']: registered[row['datasetId']] for row in datasets
             if registered.get(row['datasetId'], {}).get('datasetRevision') == row['datasetRevision']}
    if not pairs:
        return {}
    equipment = EquipmentReader(reader)
    identifiers = list(dict.fromkeys(row[key] for row in pairs.values() for key in ('rootUid','entityUid')))
    records = {}
    for start in range(0,len(identifiers),50):
        records.update(equipment.resolve(identifiers[start:start+50]))
    targets = {}
    for dataset_id, entry in pairs.items():
        root, device = records[entry['rootUid']], records[entry['entityUid']]
        uid, context = entry['rootUid'], entry['installationContextId']
        item = device['item']
        if (root['context']['rootEntityUid'] != uid or device['context']['rootEntityUid'] != uid
                or root['context']['installationContextId'] != context or device['context']['installationContextId'] != context
                or root['context']['hierarchyRevision'] != device['context']['hierarchyRevision']
                or root['item']['equipmentState'] != 'active' or item['equipmentState'] != 'active'
                or item['sourceTemplateEntityUid'] != entry['definitionUid']
                or not any(child['entityUid'] == item['entityUid'] and child['entityRevision'] == item['entityRevision']
                           for child in root['children'])):
            continue
        targets[dataset_id] = {key: entry[key] for key in ('sceneId','instanceId','rootUid','entityUid','datasetRevision')}
        targets[dataset_id].update(rootName=root['item']['displayName'], displayName=item['displayName'],
                                   entityRevision=item['entityRevision'], installationContextId=context,
                                   hierarchyRevision=device['context']['hierarchyRevision'])
    return targets
