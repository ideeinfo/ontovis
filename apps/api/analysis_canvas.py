"""Q23 persisted layout and fixed sources, without client supplied engineering facts."""
from __future__ import annotations

import json
from . import analysis_drafts as d

CARD_KINDS = ('object', 'drawing', 'document', 'photo', 'model3d', 'trend', 'alarm', 'work_order', 'analysis')
SOURCE_KIND = {kind: ('model' if kind == 'model3d' else kind) for kind in CARD_KINDS[:-1]}


def validate_canvas(value, connection_id, project_code):
    d.require(set(value) <= {'schemaVersion', 'ontobaseConnectionId', 'projectCode', 'title', 'status',
        'context', 'cards', 'relations', 'viewport', 'frames', 'inheritedFrom'}
        and {'schemaVersion', 'ontobaseConnectionId', 'projectCode', 'title', 'status', 'context', 'cards', 'relations', 'viewport'} <= set(value))
    d.require(type(value['schemaVersion']) is int and value['schemaVersion'] == 2)
    d.require((value['ontobaseConnectionId'], value['projectCode']) == (connection_id, project_code), 'ANALYSIS_SCOPE_MISMATCH', 404)
    d.text(value['title'])
    d.require(value['status'] in ('analyzing', 'awaiting_field_check', 'awaiting_expert_review'), 'ANALYSIS_REVIEW_NOT_CONFIGURED', 409)
    context = value['context']
    d.require(type(context) is dict and {'objectIds', 'timeFrom', 'timeTo', 'timezone'} <= set(context)
        and set(context) <= {'objectIds', 'timeFrom', 'timeTo', 'timezone', 'eventId', 'workOrderId', 'faultCode',
                            'sourceConnectionId', 'branch', 'datasetId', 'datasetRevision'})
    d.require(type(context['objectIds']) is list and len(context['objectIds']) <= 20)
    for uid in context['objectIds']: d.text(uid, 512)
    d.require(len(set(context['objectIds'])) == len(context['objectIds']))
    for key in set(context) - {'objectIds', 'timeFrom', 'timeTo', 'timezone'}: d.text(context[key], 512)
    d.require(('faultCode' in context) == ('sourceConnectionId' in context))
    d.require(context['timezone'] in ('UTC', 'Asia/Shanghai') and d.utc(context['timeFrom']) < d.utc(context['timeTo']))
    view = value['viewport']
    d.require(type(view) is dict and set(view) == {'x', 'y', 'zoom'} and d.number(view['x'], -50000, 50000)
        and d.number(view['y'], -50000, 50000) and d.number(view['zoom'], .25, 1.5))
    cards, relations = value['cards'], value['relations']
    d.require(type(cards) is list and len(cards) <= 50 and type(relations) is list and len(relations) <= 100, 'ANALYSIS_SIZE_LIMIT', 413)
    ids = set()
    for card in cards:
        d.require(type(card) is dict and {'id','kind','title','x','y','width','height','pinned'} <= set(card)
            and set(card) <= {'id','kind','title','x','y','width','height','pinned','source','note','historical','checkState','frameId','view'})
        key = d.text(card['id'], 100); d.require(key not in ids); ids.add(key)
        d.text(card['title']); d.require(card['kind'] in CARD_KINDS)
        d.require(d.number(card['x'], -20000, 20000) and d.number(card['y'], -20000, 20000)
            and d.number(card['width'], 240, 1440) and d.number(card['height'], 176, 1200) and type(card['pinned']) is bool)
        if card['kind'] == 'analysis':
            d.require('source' not in card and type(card.get('note')) is str and len(card['note']) <= 4000 and '\x00' not in card['note'])
        else:
            d.require('note' not in card)
            source = card.get('source')
            d.require(type(source) is dict and set(source) == {'system','ontobaseConnectionId','projectCode','id','revision'})
            d.require(source['projectCode'] == project_code and source['ontobaseConnectionId'] == connection_id, 'ANALYSIS_SCOPE_MISMATCH', 404)
            d.require(source['system'] == ('ontobase' if card['kind'] in ('object','drawing','document','photo') else 'ontovis'))
            d.identifier(source['id'])
            from .analysis_evidence import sha
            sha(source['revision'])
        if 'historical' in card: d.require(type(card['historical']) is bool)
        if 'checkState' in card: d.require(card['kind'] == 'analysis' and card['checkState'] in ('not_started','checking','done','blocked'))
        if 'frameId' in card: d.text(card['frameId'], 100)
        if 'view' in card:
            view = card['view']; d.require(type(view) is dict)
            if card['kind'] in ('drawing','document','photo'):
                d.require(set(view) == {'zoom','centerX','centerY'} and d.number(view['zoom'],.1,16)
                    and d.number(view['centerX'],0,1) and d.number(view['centerY'],0,1))
            elif card['kind'] == 'model3d':
                d.require({'eye','target'} <= set(view) <= {'eye','target','componentId'})
                for field in ('eye','target'):
                    d.require(type(view[field]) is list and len(view[field]) == 3
                        and all(d.number(n,-2_000_000,2_000_000) for n in view[field]))
                if 'componentId' in view: d.text(view['componentId'],512)
            else: d.require(False)
    keys, edges = set(), set()
    for relation in relations:
        d.require(type(relation) is dict and set(relation) == {'id','from','to','kind','origin','reason'})
        key = d.text(relation['id'], 100)
        d.require(relation['origin'] == 'manual' and relation['kind'] in ('reference','hypothesis','supports','contradicts'), 'ANALYSIS_SOURCE_NOT_CONNECTED', 409)
        d.require(type(relation['from']) is str and type(relation['to']) is str and relation['from'] in ids and relation['to'] in ids and relation['from'] != relation['to'])
        edge = (relation['from'], relation['to'], relation['kind'])
        d.require(key not in keys and edge not in edges); keys.add(key); edges.add(edge); d.text(relation['reason'], 1000)
    frames = value.get('frames', [])
    d.require(type(frames) is list and len(frames) <= 10)
    frame_ids = set()
    for frame in frames:
        d.require(type(frame) is dict and set(frame) == {'id','title','x','y','width','height'})
        fid = d.text(frame['id'], 100); d.text(frame['title']); d.require(fid not in frame_ids); frame_ids.add(fid)
        d.require(d.number(frame['x'], -20000, 20000) and d.number(frame['y'], -20000, 20000)
            and d.number(frame['width'], 280, 20000) and d.number(frame['height'], 220, 20000))
    d.require(all(c.get('frameId') is None or c['frameId'] in frame_ids for c in cards))
    if 'inheritedFrom' in value:
        origin = value['inheritedFrom']
        d.require(type(origin) is dict and set(origin) == {'analysisSessionId','analysisRevision','contentSha256'})
        d.identifier(origin['analysisSessionId']); d.require(type(origin['analysisRevision']) is int and 1 <= origin['analysisRevision'] <= 1000)
        from .analysis_evidence import sha
        sha(origin['contentSha256'])
    raw = d.canonical(value); d.require(len(raw.encode()) <= d.MAX_BYTES, 'ANALYSIS_SIZE_LIMIT', 413)
    return raw


def validate_handles(cursor, session_id, snapshot, schema_version):
    d.require(schema_version == 2, 'ANALYSIS_SOURCES_NOT_ENABLED', 503)
    origin = snapshot.get('inheritedFrom')
    historical = [c for c in snapshot['cards'] if c.get('historical')]
    d.require(not historical or origin is not None, 'ANALYSIS_HISTORY_REFERENCE_REQUIRED', 409)
    if origin:
        cursor.execute(f'''select r.snapshot_json,r.content_sha256 from {d.SCHEMA}.analysis_sessions current
            join {d.SCHEMA}.analysis_sessions original on original.owner_id=current.owner_id
              and original.connection_id=current.connection_id and original.project_code=current.project_code
            join {d.SCHEMA}.analysis_revisions r on r.session_id=original.session_id
            where current.session_id=%s and original.session_id=%s and r.revision=%s''',
            (session_id,origin['analysisSessionId'],origin['analysisRevision']))
        row=cursor.fetchone()
        d.require(row and row[1] == origin['contentSha256'], 'NOT_FOUND_OR_FORBIDDEN', 404)
        original=json.loads(row[0])
    else: original=None
    cursor.execute(f'''select evidence_ref_id::text,source_kind,descriptor_sha256,descriptor_json
        from {d.SCHEMA}.analysis_evidence_refs where session_id=%s''', (session_id,))
    rows={r[0]:r for r in cursor.fetchall()}
    validate_registered(snapshot,rows,original)


def validate_registered(snapshot, rows, original=None):
    historical=[c for c in snapshot['cards'] if c.get('historical')]
    d.require(not historical or original is not None,'ANALYSIS_HISTORY_REFERENCE_REQUIRED',409)
    for card in historical:
        if card['kind']=='analysis':
            d.require(any(old['kind']=='analysis' and all(card.get(k)==old.get(k) for k in ('title','note','checkState'))
                for old in original['cards']),'ANALYSIS_HISTORY_READ_ONLY',409)
        else:
            d.require(any(old['kind']==card['kind'] and old['source']['revision']==card['source']['revision']
                for old in original['cards']),'ANALYSIS_HISTORY_READ_ONLY',409)
    for card in snapshot['cards']:
        if card['kind']=='analysis':continue
        source=card['source'];row=rows.get(source['id'])
        d.require(row and row[1]==SOURCE_KIND[card['kind']] and row[2]==source['revision'],'ANALYSIS_SOURCE_NOT_REGISTERED',409)
    objects, events, orders = set(), [], set()
    for row in rows.values():
        descriptor = json.loads(row[3])
        if 'entityUid' in descriptor: objects.add(descriptor['entityUid'])
        if row[1] == 'alarm': events.append(descriptor)
        if row[1] == 'work_order': orders.add(descriptor['orderId'])
    context = snapshot['context']
    d.require(set(context['objectIds']) <= objects, 'ANALYSIS_SOURCE_NOT_REGISTERED', 409)
    if context.get('eventId'):
        from . import simulated_faults
        event = next((e for e in events if e['eventId'] == context['eventId']), None)
        d.require(event is not None, 'ANALYSIS_SOURCE_NOT_REGISTERED', 409)
        dataset = simulated_faults.dataset(event['datasetId'], event['datasetRevision'])
        d.require(all(context.get(key) == dataset[key] for key in ('faultCode','sourceConnectionId','datasetId','datasetRevision','branch')), 'ANALYSIS_CONTEXT_CHANGED', 409)
    elif context.get('faultCode'):
        d.require(False, 'ANALYSIS_CONTEXT_CHANGED', 409)
    if context.get('workOrderId'): d.require(context['workOrderId'] in orders, 'ANALYSIS_SOURCE_NOT_REGISTERED', 409)
