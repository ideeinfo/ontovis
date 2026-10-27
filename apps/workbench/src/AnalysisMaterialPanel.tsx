import {ArrowLeft,Box,FileImage,FileText,Image,Layers,Activity,Bell,ClipboardList,StickyNote,Plus,Search,X,RefreshCw} from 'lucide-react';
import {Btn,IconBtn} from './Primitives';
import {MATERIAL_CATEGORIES,materialCategories} from './analysisMaterials';
import type {Recommendation,Recommendations,RecommendationMatch} from './analysisSources';

const icons={object:Box,drawing:FileImage,document:FileText,photo:Image,model3d:Layers,trend:Activity,alarm:Bell,work_order:ClipboardList,analysis:StickyNote};
const matches:Record<RecommendationMatch,[string,string]>={binding:['已绑定','Recorded binding'],historical_binding:['历史绑定','Historical binding'],name_candidate:['名称候选','Name candidate'],catalogue_search:['目录检索','Catalogue search'],simulation_mapping:['模拟映射','Simulation mapping'],simulation_rule:['演练规则','Rehearsal rule']};
type Props={section:string;query:string;en:boolean;loading:boolean;value:Recommendations|null;chosen:string[];editable:boolean;canAdd:boolean;
  contextLabel:string;onClose:()=>void;onSection:(section:string)=>void;onQuery:(query:string)=>void;onSearch:()=>void;
  onToggle:(key:string)=>void;onAdd:(item:Recommendation)=>void;onAddChosen:()=>void;onNote:()=>void;onMore:()=>void;onRefresh:()=>void};
export function AnalysisMaterialPanel({section,query,en,loading,value,chosen,editable,canAdd,contextLabel,onClose,onSection,onQuery,onSearch,onToggle,onAdd,onAddChosen,onNote,onMore,onRefresh}:Props){
  const t=(zh:string,eng:string)=>en?eng:zh,home=section==='types';
  const category=MATERIAL_CATEGORIES.find(row=>row.id===section),label=category?t(category.zh,category.en):t('图纸与照片','Drawings & photos');
  const localSearch=['materials','drawings','photos'].includes(section),needle=query.trim().toLocaleLowerCase();
  const items=(value?.items||[]).filter(row=>!localSearch||[row.title,row.identifier,row.reason].join(' ').toLocaleLowerCase().includes(needle));
  return <aside className="ac-material-panel" data-canvas-inner aria-label={t('加入资料','Add materials')}>
    <header><strong>{t('加入资料','Add materials')}</strong><IconBtn label={t('关闭资料库','Close materials')} onClick={onClose}><X size={17}/></IconBtn></header>
    {!home&&<button type="button" className="ac-material-back" onClick={()=>onSection('types')}><ArrowLeft size={14}/>{t('全部资料类型','All material types')}<span>{label}</span></button>}
    <form className="ac-material-search" onSubmit={event=>{event.preventDefault();onSearch();}}><Search size={16}/><input aria-label={home?t('搜索资料类型','Search material types'):t('搜索所选类型的资料','Search selected material type')} placeholder={home?t('搜索资料类型','Search material types'):t('名称、故障码或位号','Name, fault code or tag')} value={query} maxLength={200} onChange={event=>onQuery(event.target.value)}/>{!home&&!localSearch&&<button type="submit">{t('搜索','Search')}</button>}</form>
    <p className="ac-material-scope">{home?t('选择资料类型 · 仅本项目','Choose a material type · This project only'):t('选择或拖入画布 · 仅本项目','Select or drag onto the canvas · This project only')}<small>{contextLabel||t('加入首个报警后，自动推荐相关资料','The first alarm provides related recommendations')}</small></p>
    <div className="ac-material-scroll">
      {home?materialCategories(query).map(row=>{const Icon=icons[row.kind];return <button type="button" className="ac-material-category" key={row.id} data-material-kind={row.kind} onClick={()=>row.id==='analysis'?onNote():onSection(row.id)} disabled={row.id==='analysis'&&!canAdd}>
        <span className="ac-material-icon"><Icon size={22}/></span><span><strong>{t(row.zh,row.en)}</strong><small>{t(row.hint,row.hintEn)}</small></span><Plus size={16}/></button>;
      }):loading?<p role="status">{t('正在读取相关推荐…','Loading recommendations…')}</p>:items.map(item=>{const kind=item.kind==='model'?'model3d':item.kind,Icon=icons[kind];return <div className="ac-material-result" key={item.key} data-material-kind={kind} draggable={editable&&canAdd} onDragStart={event=>{event.dataTransfer.effectAllowed='copy';event.dataTransfer.setData('application/x-ontovis-recommendation',item.key);}}>
        <label><input type="checkbox" aria-label={t('选择资料 ','Select material ')+item.title} checked={chosen.includes(item.key)} disabled={!canAdd} onChange={()=>onToggle(item.key)}/><Icon size={18}/></label>
        <div><strong>{item.title}</strong>{item.matchType&&matches[item.matchType]&&<small className="ac-match-type" data-match={item.matchType}>{t(...matches[item.matchType])}</small>}{item.identifier&&<small>{item.identifier}</small>}<small>{item.reason}</small>{item.preview?.dataset&&<small>{new Date(item.preview.dataset.timeFrom).toLocaleString(en?'en-GB':'zh-CN',{timeZone:'Asia/Shanghai'})} · UTC+8 · {t('模拟数据','Simulated data')}</small>}</div>
        <IconBtn label={t('加入画布：','Add to canvas: ')+item.title} disabled={!editable||!canAdd} onClick={()=>onAdd(item)}><Plus size={17}/></IconBtn>
      </div>;})}
      {home&&!materialCategories(query).length&&<p>{t('没有匹配的资料类型','No matching material types')}</p>}
      {!home&&!loading&&!items.length&&<p>{t('暂无匹配资料，可切换类型或调整搜索。','No matching materials. Choose another type or adjust the search.')}</p>}
      {!home&&!!value?.gaps.length&&<details><summary>{t('来源信息','Source details')}</summary>{value.gaps.map((gap,i)=><p key={i}>{gap}</p>)}</details>}
    </div>
    {!home&&<footer>{!!chosen.length&&<Btn primary disabled={!editable||!canAdd} onClick={onAddChosen}>{t('加入所选资料','Add selected')} ({chosen.length})</Btn>}{(value?.nextCursor||value?.nextOffset!=null)&&<Btn disabled={loading} onClick={onMore}>{t('更多资料','More materials')}</Btn>}<IconBtn label={t('刷新推荐','Refresh recommendations')} onClick={onRefresh} disabled={loading}><RefreshCw size={15}/></IconBtn></footer>}
  </aside>;
}
