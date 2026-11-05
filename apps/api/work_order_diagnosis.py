"""Per-order human investigation drafts; source graph facts remain read-only."""
from __future__ import annotations

from copy import deepcopy
import json

from .authority import PreviewError

HYPOTHESIS_STATES = ('candidate', 'supported', 'rejected')
STEP_STATES = ('pending', 'observed', 'gap', 'not_applicable')
CAUSES = {
    '13001': '实际温度偏高或温度测量链异常',
    '13002': '实际温度偏低或温度测量链异常',
    '13003': '浪涌保护器状态或状态反馈链异常',
    '13004': '断路器动作原因或位置反馈异常',
    '13033': '24V供电支路状态或相关反馈异常',
    '13035': '24V电源输出或供电链异常',
    '13058': '供电开关状态异常，柜体术语与适用性待核实',
}


def require(value):
    if not value:
        raise PreviewError(422, 'WORK_ORDER_DIAGNOSIS_INVALID')


def _text(value, limit, empty=False):
    require(type(value) is str and len(value) <= limit and (empty or value.strip())
            and all(ord(c) >= 32 or c in '\n\r\t' for c in value))
    try:
        value.encode('utf-8')
    except UnicodeError:
        raise PreviewError(422, 'WORK_ORDER_DIAGNOSIS_INVALID') from None
    return value.strip()


def initial_plan(code, graph):
    parts = [node for node in graph['nodes'] if node['kind'] == 'component']
    return {'hypotheses': [{'id': 'cause-1', 'description': CAUSES[code], 'status': 'candidate', 'basis': ''}],
            'steps': [{'id': 'step-' + str(index + 1), 'title': '核对' + node['label'] + '的资料或观测并记录缺口',
                       'targetKey': node['locateKey'], 'outcome': 'pending', 'result': ''}
                      for index, node in enumerate(parts)], 'conclusion': '', 'reviewBasis': ''}


def validate_plan(value, graph):
    require(type(value) is dict and set(value) == {'hypotheses', 'steps', 'conclusion', 'reviewBasis'})
    result = {'conclusion': _text(value['conclusion'], 2000, True), 'reviewBasis': _text(value['reviewBasis'], 2000, True)}
    targets = {node['locateKey'] for node in graph['nodes'] if node.get('locateKey')}
    for group, fields, maximum in (
        ('hypotheses', {'id', 'description', 'status', 'basis'}, 6),
        ('steps', {'id', 'title', 'targetKey', 'outcome', 'result'}, 12),
    ):
        rows = value[group]
        require(type(rows) is list and 1 <= len(rows) <= maximum)
        output, identifiers = [], set()
        for row in rows:
            require(type(row) is dict and set(row) == fields)
            identifier = _text(row['id'], 80)
            require(identifier not in identifiers and all(c.isascii() and (c.isalnum() or c == '-') for c in identifier))
            identifiers.add(identifier)
            if group == 'hypotheses':
                require(row['status'] in HYPOTHESIS_STATES)
                output.append({'id': identifier, 'description': _text(row['description'], 500),
                               'status': row['status'], 'basis': _text(row['basis'], 2000, True)})
            else:
                require(type(row['targetKey']) is str and row['targetKey'] in targets | {''}
                        and row['outcome'] in STEP_STATES)
                output.append({'id': identifier, 'title': _text(row['title'], 500), 'targetKey': row['targetKey'],
                               'outcome': row['outcome'], 'result': _text(row['result'], 2000, True)})
        result[group] = output
    require(len(json.dumps(result, ensure_ascii=False).encode()) <= 24 * 1024)
    return result


def complete(value):
    return bool(value['conclusion'].strip() and value['reviewBasis'].strip()
                and all(step['outcome'] != 'pending' and step['result'].strip() for step in value['steps'])
                and all(item['status'] == 'candidate' or item['basis'].strip() for item in value['hypotheses']))


def reset_results(value):
    result = deepcopy(value)
    for row in result['hypotheses']:
        row.update(status='candidate', basis='')
    for row in result['steps']:
        row.update(outcome='pending', result='')
    result.update(conclusion='', reviewBasis='')
    return result
