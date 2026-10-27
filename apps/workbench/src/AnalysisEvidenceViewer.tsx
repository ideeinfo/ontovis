import {useEffect,useLayoutEffect,useMemo,useRef,useState} from 'react';
import * as Tabs from '@radix-ui/react-tabs';
import {ArrowLeft,BookOpen,GitBranch,Search,ExternalLink,RefreshCw} from 'lucide-react';
import {Btn} from './Primitives';
import {WorkOrderPhotoViewport} from './WorkOrderPhotoViewport';
import {AnalysisSources,type EvidenceSource,type KnowledgeNode,type PreviewRow,type SourceAnchor,type SourcePreview,type Recommendation} from './analysisSources';
import type {CanvasCard} from './analysisCanvas';
import type {PhotoSelector} from './workOrderTypes';

function region(box:PreviewRow['bbox'],revision:string):PhotoSelector|null{
  return box?{kind:'image_bbox',renditionId:'source-region',displayRevision:revision,regionKind:'device_region',coordinateSpace:'oriented_display_normalized',bbox:box}:null;
}
const nodeNames:Record<string,string>={FaultDefinition:'故障定义',TriggerCondition:'触发条件',ClearCondition:'复位条件',Symptom:'现象',PossibleCause:'可能原因',CheckStep:'排查步骤',EquipmentReference:'工程对象',Procedure:'操作程序',Requirement:'要求',ConceptDefinition:'概念'};
const propertyNames:Record<string,string>={unknown:'未分类',needs_review:'待复核',accepted:'已采用',approved:'已审核',document_reference:'文档引用',wire_connectivity:'导线连接'};
const relationNames:Record<string,string>={hasTrigger:'触发条件',hasTriggerCondition:'触发条件',hasPossibleCause:'可能原因',hasCheckStep:'排查步骤',refersToEquipment:'涉及对象',hasSymptom:'故障现象',hasClearCondition:'复位条件'};

function KnowledgeGraph({nodes,relations,selected,onSelect}:{nodes:KnowledgeNode[];relations:NonNullable<SourcePreview['relations']>;selected:string;onSelect:(id:string)=>void}){
  const viewport=useRef<HTMLDivElement>(null);
  const positioned=useMemo(()=>{
    const incoming=new Set(relations.map(edge=>edge.to)),levels=new Map<string,number>();
    nodes.filter(node=>!incoming.has(node.id)).forEach(node=>levels.set(node.id,0));
    for(let round=0;round<4;round++)for(const edge of relations)if(levels.has(edge.from)&&!levels.has(edge.to))levels.set(edge.to,Math.min(4,levels.get(edge.from)!+1));
    const columns=new Map<number,number>();return nodes.map(node=>{const col=levels.get(node.id)??0,row=columns.get(col)||0;columns.set(col,row+1);return {...node,x:32+col*300,y:36+row*160};});
  },[nodes,relations]);
  useLayoutEffect(()=>{const view=viewport.current,item=positioned.find(n=>n.id===selected);if(view&&item)view.scrollTo({left:Math.max(0,item.x-(view.clientWidth-244)/2),top:Math.max(0,item.y-(view.clientHeight-150)/2)});},[positioned,selected]);
  return <div ref={viewport} className="ac-knowledge-graph" aria-label="文档知识图谱"><div style={{width:Math.max(600,...positioned.map(n=>n.x+285)),height:Math.max(360,...positioned.map(n=>n.y+150))}}>
    <svg aria-hidden="true">{relations.map(edge=>{const a=positioned.find(n=>n.id===edge.from),b=positioned.find(n=>n.id===edge.to);if(!a||!b)return null;const x=a.x+244,y=a.y+52,x2=b.x,y2=b.y+52;return <g key={edge.id}><path d={`M${x},${y} C${x+40},${y} ${x2-40},${y2} ${x2},${y2}`}/><text x={(x+x2)/2} y={(y+y2)/2-8} textAnchor="middle">{relationNames[edge.label]||edge.label.split(':').at(-1)}</text></g>;})}</svg>
    {positioned.map(node=><button key={node.id} type="button" className={`ac-knowledge-node${selected===node.id?' selected':''}`} style={{left:node.x,top:node.y}} onClick={()=>onSelect(node.id)}><small>{nodeNames[node.kind]||node.kind}</small><strong>{node.title}</strong><span>{node.statement}</span></button>)}
  </div></div>;
}

export function AnalysisEvidenceViewer({card,source,sources,en,anchor,onAdd}:{card:CanvasCard;source:EvidenceSource;sources:AnalysisSources;en:boolean;anchor?:SourceAnchor|null;onAdd?:(item:Recommendation)=>void}){
  const t=(zh:string,eng:string)=>en?eng:zh;
  const document=card.kind==='document';
  const [section,setSection]=useState('objects'),[mode,setMode]=useState(document&&source.knowledgeNodeId?'graph':'page');
  const [preview,setPreview]=useState<SourcePreview|null>(null),[loading,setLoading]=useState(false),[error,setError]=useState(false),[reload,setReload]=useState(0);
  const [image,setImage]=useState(''),[imageError,setImageError]=useState(false),[page,setPage]=useState(anchor?.pageNumber||source.pageNumber||1);
  const [selected,setSelected]=useState(''),[node,setNode]=useState(anchor?.nodeId||source.knowledgeNodeId||''),[query,setQuery]=useState(''),[filter,setFilter]=useState(''),[cursor,setCursor]=useState(0);
  const [citation,setCitation]=useState<PhotoSelector|null>(null);
  const [graphScope,setGraphScope]=useState('related');
  useEffect(()=>{const abort=new AbortController();setLoading(true);setError(false);
    void sources.preview(card.source!,document?{cursor,graphScope,...(filter?{q:filter}:{}),...(node?{nodeId:node}:{})}:{section,cursor},abort.signal)
      .then(value=>{if(!abort.signal.aborted){setPreview(value);if(!selected&&value.focusId)setSelected(value.focusId);if(!node&&value.focusId)setNode(value.focusId);}})
      .catch(()=>{if(!abort.signal.aborted){setPreview(null);setError(true);}}).finally(()=>{if(!abort.signal.aborted)setLoading(false);});return()=>abort.abort();
  },[sources,card.source!.id,document,section,cursor,filter,reload,node,graphScope]);
  useEffect(()=>{if(document&&mode==='graph')return;const abort=new AbortController();setImage('');setImageError(false);
    void sources.file(card.source!,source,abort.signal,'original',document?page:undefined).then(value=>{if(!abort.signal.aborted)setImage(value);}).catch(()=>{if(!abort.signal.aborted)setImageError(true);});return()=>abort.abort();
  },[sources,card.source!.id,page,reload,mode]);
  const rows=preview?.[section as 'objects'|'ports'|'references'|'connections']||[];
  const chosen=rows.find(row=>row.id===selected),chosenNode=preview?.nodes?.find(row=>row.id===(node||preview.focusId));
  const selector=chosen?region(chosen.bbox,preview?.sourceRevision||''):document?citation||(page===source.pageNumber?preview?.selector:null)||null:preview?.selector||anchor?.selector||null;
  const chooseRow=(row:PreviewRow)=>{setSelected(row.id);};
  const chooseNode=(id:string)=>{setNode(id);setSelected(id);setCitation(null);};
  const showPage=(value:number)=>{setPage(value);setCitation(null);};
  const showEvidence=(evidence:NonNullable<SourcePreview['evidence']>[number])=>{setPage(evidence.page);setCitation(region(evidence.bbox,source.sourceSha256||''));setMode('page');};
  const showOriginal=()=>{const first=preview?.evidence?.[0];if(first)showEvidence(first);else setMode('page');};
  const showSection=(value:string)=>{setSection(value);setSelected('');setCursor(0);setFilter('');setQuery('');};
  return <div className="ac-evidence-viewer">
    <aside className="ac-preview-list">
      <header><strong>{t(document?'文档导航':'图纸内容',document?'Document navigation':'Drawing content')}</strong></header>
      {document?<><Tabs.Root value={mode} onValueChange={setMode}><Tabs.List className="ac-preview-tabs"><Tabs.Trigger value="page"><BookOpen size={14}/>{t('正文','Pages')}</Tabs.Trigger><Tabs.Trigger value="graph"><GitBranch size={14}/>{t('知识图谱','Knowledge graph')}</Tabs.Trigger></Tabs.List></Tabs.Root>
        {mode==='page'?<><label className="ac-page">{t('页码','Page')}<input type="number" min={1} max={source.pageCount||1} aria-label={t('文档页码','Document page')} value={page} onChange={event=>{const value=Number(event.target.value);if(value>=1&&value<=(source.pageCount||1))showPage(value);}}/><span>/ {source.pageCount}</span></label>
          <nav className="ac-preview-rows" aria-label={t('文档目录','Document outline')}>{source.outline?.map((row,i)=><button key={i} type="button" aria-current={page===row.page?'page':undefined} onClick={()=>showPage(row.page)}><span>{row.title}</span><small>{row.page}</small></button>)}</nav></>:<>
          {source.knowledgeNodeId&&<div className="ac-preview-tabs">{[['related','关联知识','Related'],['all','全部节点','All nodes']].map(([id,zh,eng])=><button key={id} type="button" data-state={graphScope===id?'active':'inactive'} onClick={()=>{setGraphScope(id);setCursor(0);setFilter('');setQuery('');}}>{t(zh,eng)}</button>)}</div>}
          <form className="ad-search" onSubmit={event=>{event.preventDefault();setCursor(0);setFilter(query);}}><Search size={14}/><input aria-label={t('搜索知识节点','Search knowledge nodes')} placeholder={t('故障码、对象或条件','Code, object or condition')} value={query} onChange={event=>setQuery(event.target.value)}/><button>{t('搜索','Search')}</button></form>
          <nav className="ac-preview-rows" aria-label={t('知识节点','Knowledge nodes')}>{preview?.nodes?.map(row=><button key={row.id} type="button" aria-current={node===row.id?'true':undefined} onClick={()=>chooseNode(row.id)}><small>{nodeNames[row.kind]||row.kind}</small><strong>{row.title}</strong></button>)}</nav></>}
      </>:<><Tabs.Root value={section} onValueChange={showSection}><Tabs.List className="ac-preview-tabs">{[['objects','对象','Objects'],['ports','端口','Ports'],['connections','连接','Connections'],['references','引用','References']].map(([id,zh,eng])=><Tabs.Trigger key={id} value={id}>{t(zh,eng)}</Tabs.Trigger>)}</Tabs.List></Tabs.Root>
        <label className="ad-search"><Search size={14}/><input aria-label={t('筛选图纸内容','Filter drawing content')} placeholder={t('名称、位号或端口','Name, tag or port')} value={query} onChange={event=>setQuery(event.target.value)}/></label>
        <nav className="ac-preview-rows" aria-label={t('图纸内容列表','Drawing contents')}>{rows.filter(row=>[row.title,row.identifier,row.owner,row.targetTitle].join(' ').toLowerCase().includes(query.toLowerCase())).map(row=><button key={row.id} type="button" aria-current={selected===row.id?'true':undefined} onClick={()=>chooseRow(row)}><strong>{row.title}</strong><small>{row.identifier||row.owner||row.targetTitle||''}</small>{!row.bbox&&<small>{t('未提供可定位区域','No locatable region')}</small>}</button>)}</nav></>}
      {loading&&<small role="status">{t('正在读取内容…','Loading content…')}</small>}{error&&<div role="alert">{t('来源读取失败','Source unavailable')}<Btn onClick={()=>setReload(v=>v+1)}><RefreshCw size={13}/>{t('重试','Retry')}</Btn></div>}
      {preview?.nextCursor!=null&&<Btn onClick={()=>setCursor(preview.nextCursor!)}>{t('下一页','Next page')}</Btn>}{cursor>0&&<Btn onClick={()=>setCursor(0)}><ArrowLeft size={13}/>{t('返回首批','First page')}</Btn>}
    </aside>
    <main className="ac-preview-main"><div className="ac-preview-heading"><strong>{document?(mode==='graph'?t('文档知识图谱','Document knowledge graph'):t(`第 ${page} 页`,`Page ${page}`)):preview?.title||card.title}</strong><small>{document?source.knowledgeReleaseId?t('已发布知识','Published knowledge'):t('固定文档版本','Fixed document version'):preview?.drawingNumber}</small></div>
      {document&&mode==='graph'?<KnowledgeGraph nodes={preview?.nodes||[]} relations={preview?.relations||[]} selected={node||preview?.focusId||''} onSelect={chooseNode}/>:image?<div className="ac-photo-view"><WorkOrderPhotoViewport key={`${card.source!.id}:${page}:${selected}:${node}:${JSON.stringify(selector)}`} embedded focusFraction={.35} image={image} decodedImage={sources.decodedImage(image)} selector={selector} label={card.title} en={en} onError={()=>setImageError(true)}
        regions={rows.filter((row):row is PreviewRow&{bbox:NonNullable<PreviewRow['bbox']>}=>!!row.bbox).map(row=>({id:row.id,title:row.title,bbox:row.bbox}))} onRegion={id=>setSelected(id)}/></div>:<div className="ac-source-state" role="status">{imageError?t('图像读取失败，可重试','Image unavailable; retry'):t('正在载入页面…','Loading page…')}<Btn onClick={()=>setReload(v=>v+1)}>{t('重试','Retry')}</Btn></div>}
      {!!preview?.gaps.length&&<div className="ac-preview-notice">{preview.gaps.join(' · ')}</div>}
    </main>
    <aside className="ac-preview-properties"><header><strong>{t(document?'知识与来源':'所选内容',document?'Knowledge & sources':'Selection')}</strong></header>
      {document?<>{chosenNode?<><span className="ad-badge">{nodeNames[chosenNode.kind]||chosenNode.kind}</span><h3>{chosenNode.title}</h3><p>{chosenNode.statement}</p><Btn onClick={()=>mode==='graph'?showOriginal():setMode('graph')}><ExternalLink size={13}/>{t(mode==='graph'?'查看原文':'查看知识图谱',mode==='graph'?'Read source':'View knowledge graph')}</Btn>
        <h4>{t('原文证据','Source evidence')}</h4>{preview?.evidence?.map(row=><button className="ac-evidence-citation" key={row.id} type="button" onClick={()=>showEvidence(row)}><small>{t(`第 ${row.page} 页`,`Page ${row.page}`)}</small><span>{row.text}</span></button>)}</>:<p>{t('此页尚未选择知识节点。','Select a knowledge node.')}</p>}
        {preview?.scope&&<details><summary>{t('适用范围','Applicability')}</summary><p>{preview.scope.coverage==='partial'?t('当前图谱覆盖部分文档内容。','The graph covers part of this document.'):t('以当前文档版本为准。','Applies to this document version.')}</p>{preview.limitations?.unknown_applicability===true&&<p>{t('来源尚未明确适用机型或安装范围，使用时需结合当前设备核对。','The source has not specified applicable equipment or installation scope.')}</p>}</details>}

      </>:chosen?<><span className="ad-badge">{t(chosen.bbox?'可定位':'未定位',chosen.bbox?'Locatable':'No region')}</span><h3>{chosen.title}</h3><dl>{Object.entries(chosen.properties||{}).filter(([key,value])=>key!=='来源批次'&&value!=null&&value!=='').map(([key,value])=><div key={key}><dt>{key}</dt><dd>{typeof value==='object'?JSON.stringify(value):propertyNames[String(value)]||String(value)}</dd></div>)}</dl>
        {chosen.selector&&<Btn primary disabled={!onAdd} onClick={()=>onAdd?.({key:chosen.id,kind:'drawing',title:chosen.targetTitle||chosen.title,reason:chosen.reason||t('图纸中的已登记引用','Recorded drawing reference'),selector:chosen.selector!})}><ExternalLink size={14}/>{t('打开引用图纸并放入画布','Open referenced drawing')}</Btn>}
      </>:<p>{t('选择图面中的对象，或从左侧列表交叉定位。','Select an object on the drawing or in the list.')}</p>}
    </aside>
  </div>;
}
