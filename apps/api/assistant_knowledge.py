"""Text-only provenance from the fixed, selected manual; no cross-document search."""
import json
from urllib.parse import quote, urlencode
from .assistant_store import require

PREDICATES = ('hasTrigger','hasClearCondition','hasSymptom','hasPossibleCause','hasCheckStep','referencesEquipment',
    'hasSubProcedure','hasRequirement','hasSubRequirement','hasPrerequisite','precedes','referencesConcept','partOf')
KINDS = ('FaultDefinition','TriggerCondition','ClearCondition','Symptom','PossibleCause','CheckStep','EquipmentReference',
    'Procedure','Requirement','ConceptDefinition')


def read_neighborhood(reader, descriptor):
    query = dict(root=descriptor['knowledgeNodeId'], version_id=descriptor['contentVersionId'], depth=2, node_limit=12, edge_limit=18)
    value = reader.reader._request('GET', reader.reader.prefix+'/knowledge-releases/'+quote(descriptor['knowledgeReleaseId'],safe='')
                                  +'/neighborhood?'+urlencode(query))
    require(type(value) is dict,'SOURCE_UNAVAILABLE',502)
    require(value.get('format')=='ontobase-document-neighborhood-v1' and value.get('scope')=='published_document_knowledge'
        and value.get('projectCode')==reader.reader.project_code and value.get('releaseId')==descriptor['knowledgeReleaseId']
        and value.get('documentId')==descriptor['documentId'] and value.get('contentVersionId')==descriptor['contentVersionId']
        and value.get('root')==descriptor['knowledgeNodeId'] and value.get('depth')==2 and value.get('engineeringConfirmation') is False,
        'SOURCE_CHANGED',409)
    require(value.get('availableForAnalysis') is True and value.get('state') in ('published','superseded'),
        'KNOWLEDGE_RELEASE_UNAVAILABLE',409)
    nodes, edges, evidence = value.get('nodes'), value.get('relations'), value.get('evidence')
    require(type(nodes) is list and 1<=len(nodes)<=12 and type(edges) is list and len(edges)<=18
            and type(evidence) is list and len(evidence)<=48,'SOURCE_UNAVAILABLE',502)
    def identity(row):
        require(type(row) is dict and type(row.get('id')) is str and 0<len(row['id'])<=160,'SOURCE_UNAVAILABLE',502)
        return row['id']
    ids=[identity(row) for row in nodes]; eids=[identity(row) for row in evidence]; edge_ids=[identity(row) for row in edges]
    require(len(ids)==len(set(ids)) and len(eids)==len(set(eids)) and len(edge_ids)==len(set(edge_ids))
            and ids[0]==descriptor['knowledgeNodeId'],'SOURCE_UNAVAILABLE',502)
    for row in evidence:
        require(type(row.get('page')) is int and 1<=row['page']<=100000 and type(row.get('text')) is str
                and len(row['text'])<=240,'SOURCE_UNAVAILABLE',502)
    for row in nodes+edges:
        refs=row.get('evidenceIds');require(type(refs) is list and len(refs)<=48
            and all(type(ref) is str and ref in eids for ref in refs) and len(refs)==len(set(refs))
            and type(row.get('evidenceComplete')) is bool and (not row['evidenceComplete'] or bool(refs)),'SOURCE_UNAVAILABLE',502)
    for row in nodes:
        require(row.get('kind') in KINDS and all(type(row.get(key)) is str and len(row[key])<=maximum
            for key,maximum in (('title',160),('statement',400),('faultCode',40))),'SOURCE_UNAVAILABLE',502)
    for row in edges:
        require(row.get('source') in ids and row.get('target') in ids and row.get('predicate') in PREDICATES,'SOURCE_UNAVAILABLE',502)
    reached={descriptor['knowledgeNodeId']}
    for _ in range(2):
        frontier=set(reached)
        for row in edges:
            if frontier.intersection((row['source'],row['target'])):reached.update((row['source'],row['target']))
    require(reached==set(ids),'SOURCE_UNAVAILABLE',502)
    require(type(value.get('truncated')) is bool and type(value.get('missingEvidenceCount')) is int
            and value['missingEvidenceCount']>=0,'SOURCE_UNAVAILABLE',502)
    return value


def summary(value, descriptor, redact):
    nodes={row['id']:row for row in value['nodes']}; proofs={row['id']:row for row in value['evidence']}; root=nodes[value['root']]
    result=dict(kind='document',page=descriptor['pageNumber'],knowledgeState=value['state'],
        selectedNode=dict(kind=root['kind'],title=redact(root['title'])[:80],statement=redact(root['statement'])[:160],faultCode=redact(root['faultCode'])[:40]),
        relatedKnowledge=[],gaps=[],scope='仅所选固定手册的有限两跳知识；文档关系不是现场因果确认')
    if value['truncated']:result['gaps'].append('邻域达到数量限制，未读取全部关联。')
    if value['missingEvidenceCount'] or any(not row['evidenceComplete'] for row in value['nodes']+value['relations']):
        result['gaps'].append('部分知识或关系缺少完整可定位证据。')
    if root['kind']=='FaultDefinition':
        for kind,label in (('PossibleCause','故障原因'),('CheckStep','检查步骤')):
            if not any(row['kind']==kind for row in value['nodes']):
                result['gaps'].append('所读知识中没有'+label+'条目。')
    order={local:i for i,local in enumerate(nodes)}; paths={value['root']:[]}; pending=[value['root']]
    while pending:
        current=pending.pop(0)
        for edge in value['relations']:
            if current not in (edge['source'],edge['target']):continue
            other=edge['target'] if edge['source']==current else edge['source']
            if other not in paths:paths[other]=paths[current]+[edge];pending.append(other)
    priorities={'PossibleCause':0,'CheckStep':1,'TriggerCondition':2,'ClearCondition':3,'Procedure':4,'Requirement':5}
    candidates=sorted((row for local,row in nodes.items() if local!=value['root'] and local in paths),
                      key=lambda row:(priorities.get(row['kind'],6),order[row['id']]))
    # Preserve a check step when several causes would otherwise consume the entire summary.
    first_kinds=set();first=[];remaining=[]
    for row in candidates:
        if row['kind'] in first_kinds:remaining.append(row)
        else:first_kinds.add(row['kind']);first.append(row)
    candidates=first+remaining
    omitted=False
    def encoded():return json.dumps(result,ensure_ascii=False,separators=(',',':'))
    for row in candidates:
        path=paths[row['id']]
        if not row['evidenceComplete'] or any(not edge['evidenceComplete'] for edge in path):continue
        references=[proofs[local] for local in row['evidenceIds']]
        if not references:continue
        steps=[];current=value['root']
        for edge in path:
            outgoing=edge['source']==current
            steps.append(('out:' if outgoing else 'in:')+edge['predicate'])
            current=edge['target'] if outgoing else edge['source']
            references.extend(proofs[local] for local in edge['evidenceIds'])
        item=dict(kind=row['kind'],text=redact(row['statement'] or row['title'])[:96],
                  path=steps,pages=sorted({proof['page'] for proof in references})[:3],
                  quote=redact(references[0]['text'])[:72])
        result['relatedKnowledge'].append(item)
        if len(result['relatedKnowledge'])>4 or len(encoded())>920:
            result['relatedKnowledge'].pop();omitted=True
    if omitted:result['gaps'].append('摘要只保留有限关联，其他内容可在手册图谱查看。')
    require(len(encoded())<=1000,'SOURCE_UNAVAILABLE',502)
    return encoded()
