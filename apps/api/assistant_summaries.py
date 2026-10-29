"""Deterministic, text-only material summaries and reference validation."""
import json
import math
import re
from .assistant_store import require

def redact(value, private=()):
    value=str(value)
    for item in sorted({v for v in private if isinstance(v,str) and len(v)>2},key=len,reverse=True):
        value=value.replace(item,'[项目身份]')
    value=re.sub(r'(?i)(?:bearer\s+\S+|(?:api[_ -]?key|token|password|secret|密码|密钥)\s*[:=：]\s*[^\s,;，；]+)', '[凭据已隐去]',value)
    value=re.sub(r'https?://\S+|[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}', '[地址已隐去]',value)
    value=re.sub(r'(?i)(?:entity:)?\b[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}\b','[身份已隐去]',value)
    value=re.sub(r'(?<!\w)(?:/Users/|/home/|[A-Za-z]:\\)[^\s,;，；]+|(?<!\d)(?:\+?86[- ]?)?1[3-9]\d{9}(?!\d)','[个人信息已隐去]',value)
    return value

def summarize(reader, kind, descriptor, private=()):
    if kind=='document' and descriptor.get('knowledgeNodeId'):
        from .analysis_preview import document_preview
        value=document_preview(reader,descriptor,{})
        node=next((n for n in value.get('nodes',[]) if n['id']==descriptor['knowledgeNodeId']),None)
        result={'kind':'document','page':descriptor['pageNumber'],'knowledgeState':value.get('state'),
            'selectedNode':None if not node else {k:node.get(k) for k in ('kind','title','statement','faultCode')},
            'properties':{} if not node else dict(list(node.get('properties',{}).items())[:5]),
            'gaps':value.get('gaps',[])[:3],'scope':'仅所选知识节点，不含文档原图或整批原文'}
    else:
        value=reader.read(kind,descriptor)
        if kind=='object':
            item=value.get('item',{});category=item.get('classification') or {}
            result={'kind':kind,'objectKind':item.get('objectKind'),'scope':item.get('objectScope'),
                'reviewStatus':item.get('reviewStatus'),'classification':{k:category.get(k) for k in ('code','nameZh')},
                'physicalPath':value.get('ancestors',{}).get('completeness'),'precision':'工程定义、安装目标与几何表示不同；未据模型确认现场位置'}
        elif kind=='alarm':
            result={'kind':kind,'simulated':True,'faultCode':(value.get('dataset') or {}).get('faultCode'),
                'scenario':(value.get('dataset') or {}).get('title'),
                'events':[{k:row.get(k) for k in ('state','severity','sourceTime')} for row in value.get('items',[])[:4]],
                'confirmation':'预设模拟事件，不代表设备确诊故障'}
        elif kind=='trend':
            samples=value.get('samples',[]);valid=[p['value'] for p in samples if p.get('quality')=='good' and type(p.get('value')) in (int,float) and math.isfinite(p['value'])]
            result={'kind':kind,'simulated':True,'metricId':value.get('metricId'),'unit':value.get('unit'),
                'timeFrom':value.get('timeFrom'),'timeTo':value.get('timeTo'),'sampleCount':len(samples),
                'badQualityCount':sum(p.get('quality')!='good' for p in samples),'min':min(valid) if valid else None,'max':max(valid) if valid else None,
                'lastGood':valid[-1] if valid else None,'coverage':'固定历史演练窗口；坏质量不填补'}
        elif kind=='document':
            result={'kind':kind,'page':value.get('pageNumber'),'version':value.get('versionNumber'),
                'gaps':['所选卡片没有固定知识节点；本次仅文档元数据，没有读取原文。']}
        elif kind=='drawing':
            result={'kind':kind,'page':value.get('pageNumber'),'availability':value.get('availability','available'),
                'gaps':['仅图纸元数据和固定版本；未向模型发送图面、接线或全部对象端口。']}
        elif kind=='photo':
            result={'kind':kind,'purpose':descriptor.get('photoPurpose','object_location'),
                'regionPresent':value.get('selector') is not None,'availability':value.get('displayAvailability'),
                'gaps':['仅定位区域元数据，不含照片像素，不能判断器件外观或现场状况。']}
        elif kind=='model':
            report=value.get('report') or {}
            result={'kind':kind,'report':{k:report.get(k) for k in ('nodes','triangles','coordinateVerification')},
                'precision':'既有模型/绑定摘要；柜体可能为示意代理，不代表内部器件精确几何。','geometrySent':False}
        elif kind=='work_order':
            result={'kind':kind,'faultCode':value.get('faultCode'),'state':value.get('state'),'revision':value.get('orderRevision'),
                'history':'固定历史参考；同码不能直接复用根因结论。'}
        else:require(False,'ASSISTANT_TOOL_NOT_ALLOWED',422)
    text=redact(json.dumps(result,ensure_ascii=False,separators=(',',':')),private)
    return text if len(text)<=1000 else text[:970]+'…[摘要已截断]'

def validate_answer(value, keys):
    require(type(value) is dict and set(value)=={'observations','hypotheses','gaps','nextSteps'},'ASSISTANT_OUTPUT_INVALID',502)
    for name,rows in value.items():
        require(type(rows) is list and len(rows)<=5,'ASSISTANT_OUTPUT_INVALID',502)
        for row in rows:
            require(type(row) is dict and set(row)=={'text','refs'} and type(row['text']) is str and 0<len(row['text'])<=300
                and type(row['refs']) is list and len(row['refs'])<=8 and all(type(k) is str and k in keys for k in row['refs'])
                and len(row['refs'])==len(set(row['refs'])) and (name not in ('observations','hypotheses') or bool(row['refs'])),
                'ASSISTANT_REFERENCE_INVALID',502)
            row['text']=redact(row['text'])
    return value
