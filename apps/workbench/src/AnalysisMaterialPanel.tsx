import {displayText} from './displayText';
import {ArrowLeft,Box,FileImage,FileText,Image,Layers,Activity,Bell,ClipboardList,StickyNote,Plus,Search,X,RefreshCw} from 'lucide-react';
import {Btn,IconBtn} from './Primitives';
import {MATERIAL_CATEGORIES,groupMaterialRecommendations,materialCategories,recommendationRelevanceLabel} from './analysisMaterials';
import type {Recommendation,Recommendations} from './analysisSources';

const icons={object:Box,drawing:FileImage,document:FileText,photo:Image,model3d:Layers,trend:Activity,alarm:Bell,work_order:ClipboardList,analysis:StickyNote};
type Props={section:string;query:string;en:boolean;loading:boolean;value:Recommendations|null;chosen:string[];added:ReadonlySet<string>;canAdd:boolean;sourceTitles:ReadonlyMap<string,string>;
  contextLabel:string;onClose:()=>void;onSection:(section:string)=>void;onQuery:(query:string)=>void;onSearch:()=>void;
  onToggle:(key:string)=>void;onAdd:(item:Recommendation)=>void;onAddChosen:()=>void;onNote:()=>void;onMore:()=>void;onRefresh:()=>void};
export function AnalysisMaterialPanel({section,query,en,loading,value,chosen,added,canAdd,sourceTitles,contextLabel,onClose,onSection,onQuery,onSearch,onToggle,onAdd,onAddChosen,onNote,onMore,onRefresh}:Props){
  const t=(zh:string,eng:string)=>en?eng:zh,home=section==='types';
  const category=MATERIAL_CATEGORIES.find(row=>row.id===section),label=category?t(category.zh,category.en):t('图纸与照片','Drawings & photos');
  const items=value?.items||[],continuing=!!value?.nextCursor||value?.nextOffset!=null;
  const {groups,ungrouped}=groupMaterialRecommendations(items,sourceTitles);
  function renderItem(item:Recommendation,groupRef?:string){
    const kind=item.kind==='model'?'model3d':item.kind,Icon=icons[kind],alreadyAdded=added.has(item.key);
    const selectable=canAdd&&!alreadyAdded&&(!item.availability||item.availability==='available');
    const basis=recommendationRelevanceLabel(item,en);
    const otherCards=item.relatedSourceRefs?.filter(ref=>ref!==groupRef).map(ref=>sourceTitles.get(ref)).filter(Boolean).join(' · ');
    const reason=displayText(en?item.reasonEn||item.reason:item.reason);
    const date=item.preview?.dataset?.timeFrom;
    const metadata=[item.identifier!==item.title?item.identifier:undefined,
      date?new Date(date).toLocaleString(en?'en-GB':'zh-CN',{timeZone:'Asia/Shanghai',dateStyle:'short',timeStyle:'short'}):undefined,
      kind!=='alarm'&&reason!==basis?reason:undefined,
      otherCards?displayText(t('也关联','Also related to')+' '+otherCards):undefined,
      item.availability&&item.availability!=='available'?(item.availability==='field_record'
        ?t('单台现场资料','Device field record'):t('来源暂不可用','Source unavailable')):undefined].filter(Boolean).join(' · ');
    return <div className="ac-material-result" key={item.key} data-material-kind={kind} draggable={selectable}
      onDragStart={selectable?event=>{event.dataTransfer.effectAllowed='copy';event.dataTransfer.setData('application/x-ontovis-recommendation',item.key);}:undefined}>
      <label><input type="checkbox" aria-label={displayText(t('选择资料 ','Select material ')+item.title)} checked={chosen.includes(item.key)} disabled={!selectable} onChange={()=>onToggle(item.key)}/><Icon size={18}/></label>
      <div className="ac-material-copy">
        <div className="ac-material-title"><strong>{displayText(item.title)}</strong>
          {alreadyAdded&&<span>{t('已加入','Already added')}</span>}</div>
        {(basis||metadata)&&<small className="ac-material-meta">
          {basis&&<span className="ac-match-type" data-match={item.matchType||item.relevance}>{basis}</span>}
          {metadata&&<span title={metadata}>{metadata}</span>}
        </small>}
      </div>
      <IconBtn label={displayText(t('加入画布：','Add to canvas: ')+item.title)} disabled={!selectable} onClick={()=>onAdd(item)}><Plus size={17}/></IconBtn>
    </div>;
  }
  return <aside className="ac-material-panel" data-canvas-inner aria-label={t('加入资料','Add materials')}>
    <header><strong>{t('加入资料','Add materials')}</strong><IconBtn label={t('关闭资料库','Close materials')} onClick={onClose}><X size={17}/></IconBtn></header>
    {!home&&<button type="button" className="ac-material-back" onClick={()=>onSection('types')}><ArrowLeft size={14}/>{t('全部资料类型','All material types')}<span>{displayText(label)}</span></button>}
    <form className="ac-material-search" onSubmit={event=>{event.preventDefault();onSearch();}}><Search size={16}/><input aria-label={home?t('搜索资料类型','Search material types'):t('搜索所选类型的资料','Search selected material type')} placeholder={home?t('搜索资料类型','Search material types'):t('名称、故障码或位号','Name, fault code or tag')} value={query} maxLength={200} onChange={event=>onQuery(event.target.value)}/>{!home&&<button type="submit">{t('搜索','Search')}</button>}</form>
    <p className="ac-material-scope">{home?t('选择资料类型 · 仅本项目','Choose a material type · This project only'):t('选择或拖入画布 · 仅本项目','Select or drag onto the canvas · This project only')}<small>{contextLabel||t('加入首个报警后，自动推荐相关资料','The first alarm provides related recommendations')}</small></p>
    <div className="ac-material-scroll">
      {home?materialCategories(query).map(row=>{const Icon=icons[row.kind];return <button type="button" className="ac-material-category" key={row.id} data-material-kind={row.kind} onClick={()=>row.id==='analysis'?onNote():onSection(row.id)} disabled={row.id==='analysis'&&!canAdd}>
        <span className="ac-material-icon"><Icon size={22}/></span><span><strong>{t(row.zh,row.en)}</strong><small>{t(row.hint,row.hintEn)}</small></span><Plus size={16}/></button>;
      }):loading?<p role="status">{t('正在读取相关推荐…','Loading recommendations…')}</p>:<>
        {groups.map(([ref,rows])=><section className="ac-material-group" key={ref}>
          <h3>{displayText(sourceTitles.get(ref))}</h3>{rows.map(item=>renderItem(item,ref))}
        </section>)}
        {ungrouped.map(item=>renderItem(item))}
      </>}
      {home&&!materialCategories(query).length&&<p>{t('没有匹配的资料类型','No matching material types')}</p>}
      {!home&&!loading&&!items.length&&<p>{continuing?t('本批暂无匹配项，可继续读取。','No matches in this batch. Continue loading.'):t('当前范围暂无匹配资料。','No matching materials in this scope.')}</p>}
      {!home&&!!value?.gaps.length&&<details><summary>{t('来源信息','Source details')}</summary>{value.gaps.map((gap,i)=><p key={i}>{gap}</p>)}</details>}
    </div>
    {!home&&<footer>{!!chosen.length&&<Btn primary disabled={loading||!canAdd} onClick={onAddChosen}>{t('加入所选资料','Add selected')} ({chosen.length})</Btn>}{(value?.nextCursor||value?.nextOffset!=null)&&<Btn disabled={loading} onClick={onMore}>{t('更多资料','More materials')}</Btn>}<IconBtn label={t('刷新推荐','Refresh recommendations')} onClick={onRefresh} disabled={loading}><RefreshCw size={15}/></IconBtn></footer>}
  </aside>;
}
