"""A selected engineering UID's bounded, source-labelled associations."""
import json
import re
from .assistant_store import require

TYPES=('DEFINITION_MEMBER','INSTANCE_OF','DRAWING_LOCATION','CANDIDATE_CONNECTION','KNOWLEDGE_MAPPING')
LABELS=dict(DEFINITION_MEMBER='柜内工程定义关系',INSTANCE_OF='安装对象采用定义',DRAWING_LOCATION='图纸定位记录',
            CANDIDATE_CONNECTION='候选连接（待复核）',KNOWLEDGE_MAPPING='已确认文档知识映射')


def read_graph(reader, descriptor):
    value=reader.reader._request('POST',reader.reader.prefix+'/objects/neighborhood',
        {**descriptor,'depth':2,'nodeLimit':24,'edgeLimit':48,'relationTypes':list(TYPES)})
    require(type(value) is dict and value.get('format')=='ontobase-engineering-neighborhood-v1'
        and value.get('projectCode')==reader.reader.project_code and value.get('engineeringConfirmation') is False
        and value.get('depth')==2 and value.get('relationTypes')==list(TYPES),'SOURCE_UNAVAILABLE',502)
    require(type(value.get('revision')) is str and re.fullmatch('[0-9a-f]{64}',value['revision']) is not None,'SOURCE_UNAVAILABLE',502)
    nodes,edges=value.get('nodes'),value.get('relations')
    require(type(nodes) is list and 1<=len(nodes)<=24 and type(edges) is list and len(edges)<=48,'SOURCE_UNAVAILABLE',502)
    ids=[]
    for row in nodes:
        require(type(row) is dict and type(row.get('id')) is str and 0<len(row['id'])<=700
            and row.get('kind') in ('object','drawing','knowledge') and type(row.get('title')) is str and len(row['title'])<=160,'SOURCE_UNAVAILABLE',502)
        ids.append(row['id'])
    require(len(ids)==len(set(ids)) and value.get('root')==ids[0] and nodes[0].get('entityUid')==descriptor['entityUid']
        and nodes[0].get('entityRevision')==descriptor['expectedEntityRevision']
        and nodes[0].get('installationContextId')==descriptor['installationContextId'],'SOURCE_CHANGED',409)
    edge_ids=set()
    for row in edges:
        require(type(row) is dict and type(row.get('id')) is str and row['id'] not in edge_ids
            and row.get('source') in ids and row.get('target') in ids and row.get('type') in TYPES
            and row.get('status')==('needs_review' if row['type']=='CANDIDATE_CONNECTION' else 'recorded')
            and type(row.get('provenance')) is dict and type(row['provenance'].get('recordId')) is str
            and type(row['provenance'].get('recordRevision')) is str
            and re.fullmatch('[0-9a-f]{64}',row['provenance']['recordRevision']) is not None,'SOURCE_UNAVAILABLE',502)
        edge_ids.add(row['id'])
    reached={value['root']}
    for _ in range(2):
        before=set(reached)
        for row in edges:
            if before.intersection((row['source'],row['target'])):reached.update((row['source'],row['target']))
    require(reached==set(ids) and type(value.get('truncated')) is bool and type(value.get('gaps')) is list
        and len(value['gaps'])<=16 and all(type(v) is str and len(v)<=300 for v in value['gaps']),'SOURCE_UNAVAILABLE',502)
    return value


def graph_summary(value, redact):
    nodes={n['id']:n for n in value['nodes']};root=nodes[value['root']]
    data=dict(kind='object',classification=root.get('classification'),objectScope=root.get('objectScope'),
              associations=[],gaps=[redact(g) for g in value['gaps']],
              scope='按精确工程UID读取的有限两跳关联；定义归属、资料定位和候选接线不代表现场事实确认')
    priorities={'CANDIDATE_CONNECTION':0,'DRAWING_LOCATION':1,'DEFINITION_MEMBER':2,'INSTANCE_OF':3,'KNOWLEDGE_MAPPING':4}
    # Spread the summary across relation types before including more of the same type.
    counts={};chosen=[]
    for edge in sorted(value['relations'],key=lambda r:(priorities[r['type']],r['id'])):
        index=counts.get(edge['type'],0);counts[edge['type']]=index+1;chosen.append((index,edge))
    omitted=False
    def encoded():return json.dumps(data,ensure_ascii=False,separators=(',',':'))
    for _,edge in sorted(chosen,key=lambda pair:(pair[0],priorities[pair[1]['type']],pair[1]['id'])):
        item=dict(relation=LABELS[edge['type']],source=redact(nodes[edge['source']]['title'])[:56],
                  target=redact(nodes[edge['target']]['title'])[:56],status=edge['status'])
        if edge['provenance'].get('pageNumber'):item['page']=edge['provenance']['pageNumber']
        if edge['type']=='CANDIDATE_CONNECTION':item['source']='待复核端口导入：'+item['source']
        data['associations'].append(item)
        if len(data['associations'])>5 or len(encoded())>900:data['associations'].pop();omitted=True
    if omitted:data['gaps'].append('摘要仅保留有限关联，完整返回邻域可在工程图谱查看。')
    require(len(encoded())<=1000,'SOURCE_UNAVAILABLE',502)
    return encoded()


def material_summary(reader, kind, descriptor, private=()):
    from .assistant_summaries import redact, summarize
    from .assistant_store import digest
    if kind=='object' and hasattr(reader,'reader'):
        value=read_graph(reader,descriptor)
        text=graph_summary(value,lambda s:redact(s,private))
        return dict(summary=text,summaryHash=digest(text),retrievalRevision=value['revision'])
    text=summarize(reader,kind,descriptor,private)
    return dict(summary=text,summaryHash=digest(text))
