"""Read bounded project topics and their fixed, independently cited publications."""
import json
from urllib.parse import urlencode

from .assistant_store import require,digest
from .assistant_summaries import redact
from .authority import PreviewError


def query(tools,query):
    from .analysis_preview import literal,node_evidence
    from .assistant_knowledge import read_neighborhood,summary
    from .fixed_documents import FixedDocuments
    reader=tools.reader;fault=query['faultCode']
    params=dict(q=query['query'] or fault,limit=12)
    if fault and (not query['query'] or query['query']==fault):params['kind']='FaultDefinition'
    pages=[];roots=[];seen=set()
    def page(options):
        value=tools.read(lambda:reader.reader._request('GET',reader.reader.prefix+'/document-knowledge/graph?'+urlencode(options)))
        require(value.get('project_code')==reader.reader.project_code and type(value.get('nodes')) is list
                and len(value['nodes'])<=13 and type(value.get('relations')) is list,'SOURCE_UNAVAILABLE',502)
        if pages:require(value.get('scope_token')==pages[0].get('scope_token'),'SOURCE_CHANGED',409)
        pages.append(value);tools.graphs.append(dict(kind='knowledge',graph=value))
        for node in value['nodes']:
            source=node.get('source')
            if not source or node['kind']=='KnowledgeAssociation' or (fault and literal(node,'fault_code')!=fault):continue
            # One bounded neighborhood per publication; a document's several matching
            # nodes must not crowd out an independent publication.
            identity=(source['document']['id'],source['version']['id'],source['release_id'])
            if identity not in seen:seen.add(identity);roots.append(node)
        return value
    value=page(params)
    # Keep enough budget to read two fixed publications after the second directory page.
    if len(roots)<2 and value.get('next_cursor') is not None and value.get('scope_token') and tools.limit-tools.reads>=7:
        value=page({**params,'cursor':value['next_cursor'],'scope_token':value['scope_token']})
    next_cursor=value.get('next_cursor')
    directory=dict(scope='项目已发布知识目录；未读原文的匹配不能支持现场结论',nodes=[],truncated=next_cursor is not None)
    for node in [n for p in pages for n in p['nodes']][:6]:
        directory['nodes'].append(dict(title=redact(literal(node,'title'),tools.private)[:80],kind=node['kind']))
        if len(json.dumps(directory,ensure_ascii=False,separators=(',',':')))>900:
            directory['nodes'].pop();directory['truncated']=True;break
    if sum(len(p['nodes']) for p in pages)>len(directory['nodes']):directory['truncated']=True
    tools.source('document',json.dumps(directory,ensure_ascii=False,separators=(',',':')),retrievalRevision=digest(pages))
    tools.trace.append(dict(tool='knowledge',state='complete',count=sum(len(p['nodes']) for p in pages),
        nextCursor=next_cursor,scopeToken=value.get('scope_token'),filters=query,pagesRead=len(pages)))
    read=0
    for node in roots[:2]:
        if tools.limit-tools.reads<3:break
        source=node['source'];fixed=dict(documentId=source['document']['id'],contentVersionId=source['version']['id'])
        try:
            metadata=tools.read(lambda:FixedDocuments(reader.reader).metadata(fixed))
            fixed.update(sourceSha256=metadata['sourceSha256'],knowledgeReleaseId=source['release_id'],knowledgeNodeId=source['local_id'],pageNumber=1)
            proof=tools.read(lambda:node_evidence(reader,fixed))
            original_pages=sorted({p['selector'].get('page') for p in proof['items'] if type(p['selector'].get('page')) is int})
            require(original_pages,'SOURCE_UNAVAILABLE',502);fixed['pageNumber']=original_pages[0]
            graph=tools.read(lambda:read_neighborhood(reader,fixed))
            row=tools.source('document',summary(graph,fixed,lambda text:redact(text,tools.private)),descriptor=fixed,
                retrievalRevision=digest(graph),title=metadata.get('title',source['document'].get('name','')),
                pageNumbers=sorted({p['page'] for p in graph['evidence']}),
                retrieval=dict(version=1,plan=dict(tool='manual_fault_lookup',faultCode=fault or None,operations=3),
                    anchor=dict(nodeId=source['local_id'],pageNumber=fixed['pageNumber']),tools=[]))
            references={p['id']:p for p in graph['evidence']};edges=[]
            for edge in graph['relations']:
                edge_pages=sorted({references[e]['page'] for e in edge['evidenceIds'] if e in references})
                edges.append(dict(id=edge['id'],source=edge['source'],target=edge['target'],type=edge['predicate'],
                    status='document_rule',evidenceComplete=edge['evidenceComplete'],evidenceIds=edge['evidenceIds'],
                    provenance=dict(recordId=source['release_id']+'/'+edge['id'],recordRevision=digest(graph),pageNumbers=edge_pages,
                        **(dict(pageNumber=edge_pages[0]) if edge_pages else {}))))
            tools.graphs.append(dict(kind='knowledge',sourceKey=row['key'] if row else None,graph={**graph,'relations':edges}))
            tools.trace.append(dict(tool='fixed_manual_neighborhood',state='complete',count=len(edges),truncated=graph['truncated'],
                releaseId=source['release_id'],scope='固定发布版及原页证据；项目其他分页未读取' if next_cursor is not None else '固定发布版及原页证据'))
        except PreviewError as error:
            if error.status in (401,403) or error.code in ('ASSISTANT_CANCELLED','ACCESS_CHANGED','SESSION_CHANGED','ASSISTANT_TIMEOUT'):raise
            tools.trace.append(dict(tool='fixed_manual_neighborhood',state='unavailable',releaseId=source['release_id'],reason=error.code))
        read+=1
    if len(roots)>read:
        tools.trace.append(dict(tool='fixed_manual_neighborhood',state='budget_limited',count=len(roots)-read,
            reason='ASSISTANT_READ_LIMIT',scope='其余发布版未读原文；不能把未读取当成没有证据'))
