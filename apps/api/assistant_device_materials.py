"""Read applicable material versions through the existing installation and source grants."""
import json

from .assistant_store import require
from .assistant_summaries import redact
from .equipment_reader import EquipmentReader


def query(tools, needle):
    allowed = tools.allowed & {'document','photo'}
    require('object' in tools.allowed and allowed,'ASSISTANT_TOOL_NOT_ALLOWED',403)
    equipment = EquipmentReader(tools.reader.reader)
    directory = tools.read(lambda:equipment.catalogue(dict(q=needle,rootsOnly=False,limit=6)))
    items = directory['items']
    exact = [item for item in items if item['displayName'].casefold()==needle.strip().casefold()]
    unique = (exact or items) if needle.strip() and directory['nextCursor'] is None else []
    for item in items:
        tools.results.append(dict(key='R'+str(len(tools.results)+1),kind='equipment_material_scope',
            title=item['displayName'],identifier=item['entityUid'],version=item['entityRevision'],
            reason='项目中的登记安装设备',simulated=False))
    tools.trace.append(dict(tool='equipment_materials',state='complete',count=len(items),
        scope='在当前项目查询已登记的安装设备',truncated=directory['nextCursor'] is not None))
    tools.source('object',json.dumps(dict(scope='项目安装设备目录，无法唯一匹配时由用户选择',
        matches=[redact(item['displayName'],tools.private)[:42] for item in items]),
        ensure_ascii=False,separators=(',',':')))
    if len(unique)!=1:
        return

    item = unique[0]
    uid = item['entityUid']
    fixed = tools.read(lambda:equipment.resolve([uid])[uid])
    require(fixed['item']['entityRevision']==item['entityRevision']
            and fixed['item']['equipmentState']=='active','ENGINEERING_CHANGED',409)
    context = fixed['context']
    selection = dict(entityUid=uid,expectedEntityRevision=item['entityRevision'],
        installationContextId=context['installationContextId'],expectedHierarchyRevision=context['hierarchyRevision'])
    materials = tools.read(lambda:equipment.material_devices({**selection,'limit':6}))
    available = []
    for entry in materials['items']:
        kind = 'document' if entry['kind']=='pdf' else 'photo'
        if kind not in allowed:
            continue
        fixed_doc = {key:entry[key] for key in ('documentId','contentVersionId','title')}
        row = dict(key='R'+str(len(tools.results)+1),kind='material_unavailable',title=entry['title'],
            identifier=entry['documentId'],version=entry['versionNumber'],state=entry['availability'],
            reason='设备适用资料',simulated=False)
        if entry['availability']=='available':
            selector = {key:fixed_doc[key] for key in ('documentId','contentVersionId')}
            if kind=='document':
                selector['pageNumber']=1
            else:
                selector['sourceType']='project_document'
            row.update(kind=kind,selector=selector,documentPreview=fixed_doc)
        tools.results.append(row)
        available.append([redact(entry['title'],tools.private)[:42],entry['versionNumber'],kind,entry['availability']])
    scope = '设备适用资料的固定目录，模型只读取名称、版本、类型和可用状态'
    truncated = materials['nextCursor'] is not None
    tools.trace.append(dict(tool='equipment_applicable_materials',state='complete',count=len(available),
        scope=scope,truncated=truncated))
    summary = json.dumps(dict(scope=scope,materialRevision=materials['revision'],more=truncated,items=available),
                         ensure_ascii=False,separators=(',',':'))
    tools.source('document' if 'document' in allowed else 'photo',summary)
