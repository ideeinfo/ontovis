"""Summarize the existing OntoBase processing-task list without creating tasks."""
import json
from urllib.parse import urlencode

from .assistant_store import require
from .assistant_summaries import redact
from .equipment_reader import EquipmentReader

KINDS = {'drawing_batch','drawing_recognition','drawing_import','document_batch','document_source',
         'document_generation','photo','knowledge_import','knowledge_release'}
STATES = {'queued','running','awaiting_input','completed','failed','cancelled','unknown'}
RESULTS = {'not_formed','applied','pending_review','available','source_ready','published','superseded','withdrawn'}


def query(tools, needle):
    photo_allowed = 'photo' in tools.allowed
    require('document' in tools.allowed,'ASSISTANT_TOOL_NOT_ALLOWED',403)
    reader = tools.reader.reader
    path = reader.prefix+'/processing-tasks?'+urlencode(dict(q=needle,cursor=0,limit=6))
    value = tools.read(lambda:reader._request('GET',path))
    require(type(value) is dict and type(value.get('items')) is list and len(value['items'])<=6,
            'SOURCE_UNAVAILABLE',502)
    records = []
    for item in value['items']:
        require(type(item) is dict and item.get('kind') in KINDS and item.get('state') in STATES
                and item.get('result_state') in RESULTS and type(item.get('source_available')) is bool,
                'SOURCE_UNAVAILABLE',502)
        if item['kind']=='photo' and not photo_allowed:
            continue
        identifier = EquipmentReader.identifier(item.get('id'))
        title = item.get('title') if item['source_available'] else None
        title = title[:200] if isinstance(title,str) and title.strip() else '资料处理任务'
        row = dict(key='R'+str(len(tools.results)+1),kind='processing_task',title=title,
            identifier=identifier,version='',reason='OntoBase 处理进度',simulated=False,
            state=item['state'],resultState=item['result_state'],processingKind=item['kind'])
        done,total = item.get('completed_units'),item.get('total_units')
        if type(done) is int and type(total) is int and 0<=done<=total<=1000000:
            row.update(completedUnits=done,totalUnits=total)
        if item['source_available'] and item.get('document_id') and item.get('version_id'):
            row['documentPreview'] = dict(documentId=EquipmentReader.identifier(item['document_id']),
                contentVersionId=EquipmentReader.identifier(item['version_id']),title=title)
        tools.results.append(row)
        records.append([redact(title,tools.private)[:30],item['kind'],item['state'],item['result_state'],
                        row.get('completedUnits'),row.get('totalUnits')])
    scope = 'OntoBase 任务读取快照，分别列出处理状态和结果状态。'
    more = value.get('next_cursor') is not None
    tools.trace.append(dict(tool='processing_tasks',state='complete',count=len(records),scope=scope,truncated=more))
    summary = json.dumps(dict(scope=scope,columns=['标题','任务类型','处理状态','结果状态','已完成','总数'],
                              more=more,items=records),ensure_ascii=False,separators=(',',':'))
    tools.source('document',summary)
