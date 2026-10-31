"""Question-directed, read-only retrieval within the explicitly selected sources.

Plans are deterministic and saved with the receipt. Text never selects a URL,
project, release or write operation. One logical tool may use bounded metadata
reads internally; every source still enforces its current authorization.
"""
import json
import re
from urllib.parse import urlencode
from .assistant_store import digest, require
from .assistant_graph import material_summary
from .assistant_summaries import redact

TOOLS = {'object': 'engineering_neighborhood', 'document': 'selected_manual', 'alarm': 'selected_alarm',
         'trend': 'selected_trend', 'work_order': 'selected_order', 'drawing': 'selected_metadata',
         'photo': 'selected_metadata', 'model': 'selected_metadata'}


def plan(fixed, question, budget):
    require(1 <= len(fixed) <= budget <= 8, 'ASSISTANT_READ_LIMIT', 422)
    codes = list(dict.fromkeys(re.findall(r'(?<![A-Za-z0-9_])\d{5}(?![A-Za-z0-9_])', question)))[:3]
    remaining = budget - len(fixed)
    rows = []
    for ref, descriptor in fixed:
        tool = TOOLS[ref['sourceKind']]
        query = codes[0] if codes and tool == 'selected_manual' and descriptor.get('knowledgeReleaseId') and remaining else None
        if query: remaining -= 1
        rows.append(dict(tool=tool, faultCode=query, operations=2 if query else 1))
    return rows


def retrieve(reader, kind, descriptor, selected, private=()):
    require(type(selected) is dict and set(selected) == {'tool', 'faultCode', 'operations'}
            and selected['tool'] == TOOLS.get(kind) and selected['operations'] == (2 if selected['faultCode'] else 1), 'ASSISTANT_TOOL_NOT_ALLOWED', 422)
    code = selected['faultCode']
    require(code is None or kind == 'document' and type(code) is str and re.fullmatch(r'\d{5}', code)
            and selected['operations'] == 2, 'ASSISTANT_TOOL_NOT_ALLOWED', 422)
    trace = dict(version=1, plan=selected, tools=[], anchor=None)
    if code:
        from .analysis_preview import literal
        from .assistant_knowledge import read_neighborhood, summary
        require(descriptor.get('knowledgeReleaseId'), 'SOURCE_CHANGED', 409)
        # Identity and version come only from the owned fixed reference.
        query = urlencode(dict(view='application', kind='FaultDefinition', q=code, limit=12, cursor=0))
        value = reader.reader._request('GET', reader.reader.prefix + '/knowledge-releases/' + descriptor['knowledgeReleaseId'] + '/graph?' + query)
        require(value.get('document_id') == descriptor['documentId'] and value.get('content_version_id') == descriptor['contentVersionId']
                and value.get('available_for_analysis') is True and value.get('state') in ('published', 'superseded'), 'SOURCE_CHANGED', 409)
        nodes = value.get('nodes')
        require(type(nodes) is list and len(nodes) <= 12, 'SOURCE_UNAVAILABLE', 502)
        matched = [row for row in nodes if row.get('kind') == 'FaultDefinition' and literal(row, 'fault_code') == code]
        trace['tools'].append(dict(tool='fixed_manual_fault_lookup', state='matched' if len(matched) == 1 else 'ambiguous' if matched else 'not_found',
                                   matches=len(matched), truncated=value.get('next_cursor') is not None))
        if len(matched) != 1 or value.get('next_cursor') is not None:
            text = json.dumps(dict(kind='document', requestedFaultCode=code,
                gaps=['所选固定手册未返回唯一且完整的故障码匹配，未用其他发布版或演示规则补充。'],
                scope='仅所选固定文档发布版；没有可引用的匹配摘录'), ensure_ascii=False, separators=(',', ':'))
            result = dict(summary=text, summaryHash=digest(text), retrievalRevision=digest(value))
        else:
            fixed = {**descriptor, 'knowledgeNodeId': matched[0]['local_id']}
            neighborhood = read_neighborhood(reader, fixed)
            proofs = set(neighborhood['nodes'][0]['evidenceIds'])
            pages = sorted({row['page'] for row in neighborhood['evidence'] if row['id'] in proofs})
            require(bool(pages), 'SOURCE_UNAVAILABLE', 502)
            fixed['pageNumber'] = pages[0]
            text = summary(neighborhood, fixed, lambda s: redact(s, private))
            trace['tools'].append(dict(tool='fixed_manual_neighborhood', state='complete', nodes=len(neighborhood['nodes']),
                                       relations=len(neighborhood['relations']), truncated=neighborhood['truncated']))
            trace['anchor'] = dict(nodeId=fixed['knowledgeNodeId'], pageNumber=pages[0])
            result = dict(summary=text, summaryHash=digest(text), retrievalRevision=digest(neighborhood))
    else:
        result = material_summary(reader, kind, descriptor, private)
        trace['tools'].append(dict(tool=selected['tool'], state='complete'))
    return {**result, 'retrieval': trace}
