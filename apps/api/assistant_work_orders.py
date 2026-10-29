"""Human-selected assistant suggestions; never copy observations into verified results."""
from copy import deepcopy
from uuid import UUID, uuid5

from .assistant_store import digest, require
from .work_order_diagnosis import validate_plan

KINDS = {'hypotheses': 'hypothesis', 'nextSteps': 'step', 'gaps': 'gap'}


def proposal(run):
    require(run['state'] in ('complete', 'partial') and run.get('result') is not None,
            'ASSISTANT_TRANSFER_UNAVAILABLE', 409)
    sources = {s['key']: s for s in run['sources'] if s.get('availability') == 'available'}
    require(all(type(source.get('summaryHash')) is str and len(source['summaryHash']) == 64
                and all(c in '0123456789abcdef' for c in source['summaryHash']) for source in sources.values()),
            'ASSISTANT_TRANSFER_UNAVAILABLE', 409)
    items = []
    for group, kind in KINDS.items():
        for index, row in enumerate(run['result']['answer'][group]):
            require(all(key in sources for key in row['refs']), 'ASSISTANT_REFERENCE_INVALID', 409)
            items.append({'id': f'{group}-{index}', 'kind': kind, 'text': row['text'], 'refs': row['refs']})
    value = {'runId': run['runId'], 'runVersion': run['version'], 'conversationId': run.get('conversationId'),
             'conversationVersion': run.get('conversationVersion', 0), 'analysisSessionId': run['analysisSessionId'],
             'analysisRevision': run['analysisRevision'], 'items': items,
             'sources': [{key: source[key] for key in ('key', 'kind', 'evidenceRefId', 'sourceRevision',
                         'summaryHash', 'retrievalRevision', 'retrieval') if key in source} for source in sources.values()],
             'observations': run['result']['answer']['observations'], 'engineeringConfirmation': False}
    return {**value, 'proposalSha256': digest(value)}


def selected_items(value, proposed, graph):
    require(type(value) is list and 1 <= len(value) <= 15, 'ASSISTANT_TRANSFER_INVALID', 422)
    candidates = {row['id']: row for row in proposed['items']}
    targets = {node['locateKey'] for node in graph['nodes'] if node.get('locateKey')} | {''}
    seen, rows = set(), []
    for row in value:
        require(type(row) is dict and set(row) == {'id', 'text', 'targetKey'}, 'ASSISTANT_TRANSFER_INVALID', 422)
        key = row['id']
        require(type(key) is str and key in candidates and key not in seen, 'ASSISTANT_TRANSFER_INVALID', 422)
        text = row['text']
        require(type(text) is str and 0 < len(text.strip()) <= 500
                and all(ord(c) >= 32 or c in '\n\r\t' for c in text), 'ASSISTANT_TRANSFER_INVALID', 422)
        require(type(row['targetKey']) is str and row['targetKey'] in targets
                and (candidates[key]['kind'] != 'hypothesis' or row['targetKey'] == ''),
                'ASSISTANT_TRANSFER_INVALID', 422)
        seen.add(key)
        rows.append({'sourceItemId': key, 'kind': candidates[key]['kind'], 'originalText': candidates[key]['text'],
                     'text': text.strip(), 'refs': candidates[key]['refs'], 'targetKey': row['targetKey']})
    return rows


def merge_plan(detail, proposed, rows):
    plan = deepcopy(detail['investigation'])
    adopted = {item['sourceItemId'] for transfer in detail.get('assistantTransfers', [])
               if transfer['runId'] == proposed['runId'] for item in transfer['items']}
    require(not adopted.intersection(row['sourceItemId'] for row in rows), 'ASSISTANT_ITEM_ALREADY_APPLIED', 409)
    for row in rows:
        key = str(uuid5(UUID(proposed['runId']), detail['orderId'] + ':' + row['sourceItemId']))
        row['planItemId'] = key
        if row['kind'] == 'hypothesis':
            require(not any(item['description'] == row['text'] for item in plan['hypotheses']),
                    'WORK_ORDER_ITEM_DUPLICATE', 409)
            plan['hypotheses'].append({'id': key, 'description': row['text'], 'status': 'candidate', 'basis': ''})
        else:
            title = ('补充证据：' if row['kind'] == 'gap' else '') + row['text']
            require(len(title) <= 500, 'ASSISTANT_TRANSFER_INVALID', 422)
            require(not any(item['title'] == title for item in plan['steps']), 'WORK_ORDER_ITEM_DUPLICATE', 409)
            plan['steps'].append({'id': key, 'title': title, 'targetKey': row['targetKey'], 'outcome': 'pending', 'result': ''})
    require(len(plan['hypotheses']) <= 6 and len(plan['steps']) <= 12, 'WORK_ORDER_PLAN_LIMIT', 409)
    return validate_plan(plan, detail['diagnosis'])
