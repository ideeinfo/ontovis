import {useCallback,useEffect,useId,useMemo,useRef,useState} from 'react';
import {ArrowLeft,Box,ChevronDown,ChevronRight,Focus,Layers,RotateCcw,Search} from 'lucide-react';
import {Btn} from './Primitives';
import {usePreferences} from './Preferences';
import {previewIdentity,type PreviewNode,type PreviewSelection,type PreviewStructure} from './modelPreviewTypes';
import type {ProjectModelVersion} from './resourceTypes';
import './modelPreview.css';

export function useModelPreview(version:ProjectModelVersion|null){
  const identity=previewIdentity(version),[loaded,setLoaded]=useState<PreviewStructure|null>(null);
  const [chosen,setChosen]=useState<PreviewSelection|null>(null),serial=useRef(0);
  const structure=loaded?.identity===identity?loaded:null;
  useEffect(()=>{setLoaded(null);setChosen(null);},[identity]);
  const selection=useMemo<PreviewSelection>(()=>chosen?.identity===identity?chosen:
    {identity,nodeId:null,display:'context',focusToken:0},[chosen,identity]);
  const ready=useCallback((value:PreviewStructure|null)=>{if(!value||value.identity===identity)setLoaded(value);},[identity]);
  const choose=useCallback((nodeId:string|null,focus=true)=>{
    if(!structure||nodeId&&!structure.nodes.some(node=>node.id===nodeId))return;
    setChosen(previous=>({identity,nodeId,display:nodeId&&previous?.identity===identity?previous.display:'context',
      focusToken:focus?++serial.current:previous?.identity===identity?previous.focusToken:0}));
  },[structure,identity]);
  const pick=useCallback((key:string,nodeId:string|null)=>{if(key===identity)choose(nodeId,nodeId!==null);},[identity,choose]);
  const restore=useCallback(()=>setChosen({identity,nodeId:null,display:'context',focusToken:++serial.current}),[identity]);
  const display=()=>setChosen({...selection,display:selection.display==='context'?'isolate':'context'});
  const node=structure?.nodes.find(row=>row.id===selection.nodeId)??null;
  return {structure,selection,node,ready,choose,pick,restore,display,focus:()=>choose(selection.nodeId)};
}
export type PreviewController=ReturnType<typeof useModelPreview>;

export function ModelComponentTree({version,inspection,onClose,onSelect}:{version:ProjectModelVersion;inspection:PreviewController;onClose:()=>void;onSelect?:()=>void}){
  const {locale}=usePreferences(),text=(zh:string,en:string)=>locale==='zh'?zh:en;
  const [query,setQuery]=useState(''),[collapsed,setCollapsed]=useState<Set<string>>(new Set());
  const selected=useRef<HTMLButtonElement|null>(null),prefix=useId();
  const {structure,selection}=inspection;
  useEffect(()=>{setQuery('');setCollapsed(new Set());},[selection.identity]);
  useEffect(()=>{
    if(!selection.nodeId||!structure)return;
    setQuery('');setCollapsed(previous=>{
      const next=new Set(previous);let node=structure.nodes.find(row=>row.id===selection.nodeId);
      while(node?.parentId){next.delete(node.parentId);node=structure.nodes.find(row=>row.id===node!.parentId);}return next;
    });
    const frame=requestAnimationFrame(()=>selected.current?.scrollIntoView({block:'nearest'}));return()=>cancelAnimationFrame(frame);
  },[selection.nodeId,structure]);
  const byId=new Map(structure?.nodes.map(node=>[node.id,node])??[]),matches=new Set<string>(),rows:{node:PreviewNode;level:number}[]=[];
  for(const node of structure?.nodes??[])if(node.name.toLocaleLowerCase().includes(query.trim().toLocaleLowerCase())){
    let current:PreviewNode|undefined=node;while(current){matches.add(current.id);current=current.parentId?byId.get(current.parentId):undefined;}
  }
  const visit=(id:string,level:number)=>{const node=byId.get(id);if(!node||!matches.has(id))return;
    rows.push({node,level});if(query||!collapsed.has(id))for(const child of node.children)visit(child,level+1);};
  for(const id of structure?.roots??[])visit(id,1);
  const toggle=(id:string)=>setCollapsed(previous=>{const next=new Set(previous);if(next.has(id))next.delete(id);else next.add(id);return next;});
  return <section className="mp-tree" aria-label={text('模型构件树','Model component tree')}>
    <header><strong>{text('构件树','Component tree')}</strong><Btn onClick={onClose}><ArrowLeft size={14}/>{text('模型资源','Resources')}</Btn></header>
    <label className="mp-search"><Search size={14}/><input aria-label={text('搜索构件','Search components')} placeholder={text('搜索构件','Search components')} value={query} onChange={e=>setQuery(e.target.value)}/></label>
    <p className="mp-caption">{text('源模型层级；不代表现场物理层级。','Source model hierarchy; does not confirm installed hierarchy.')}</p>
    <button className="mp-model-root" onClick={inspection.restore} disabled={!structure}><Box size={15}/><span>{version.displayName}</span></button>
    {!structure?<p role="status" className="mp-caption">{text('正在读取构件…','Loading components…')}</p>:<>
      <div role="tree" aria-label={text('源模型构件','Source model components')} className="mp-tree-items" onKeyDown={event=>{
        const target=event.target as HTMLElement,item=target.closest<HTMLButtonElement>('[role="treeitem"]');if(!item)return;
        const items=[...event.currentTarget.querySelectorAll<HTMLButtonElement>('[role="treeitem"]')],index=items.indexOf(item);
        const row=rows[index];if(!row)return;
        if(['ArrowDown','ArrowUp','Home','End'].includes(event.key)){event.preventDefault();
          items[event.key==='Home'?0:event.key==='End'?items.length-1:Math.max(0,Math.min(items.length-1,index+(event.key==='ArrowDown'?1:-1)))]?.focus();}
        if(event.key==='ArrowRight'&&row.node.children.length){event.preventDefault();if(collapsed.has(row.node.id))toggle(row.node.id);else items[index+1]?.focus();}
        if(event.key==='ArrowLeft'){event.preventDefault();if(row.node.children.length&&!collapsed.has(row.node.id))toggle(row.node.id);
          else if(row.node.parentId)items[rows.findIndex(other=>other.node.id===row.node.parentId)]?.focus();}
      }}>
        {rows.map(({node,level},index)=><div className="mp-tree-row" key={node.id} style={{paddingInlineStart:(level-1)*14}}>
          <button type="button" className="mp-expand" aria-label={text(collapsed.has(node.id)?'展开构件':'收起构件',collapsed.has(node.id)?'Expand component':'Collapse component')}
            disabled={!node.children.length} onClick={()=>toggle(node.id)}>{node.children.length?(collapsed.has(node.id)?<ChevronRight size={13}/>:<ChevronDown size={13}/>):null}</button>
          <button type="button" role="treeitem" id={`${prefix}-${index}`} aria-level={level} aria-selected={selection.nodeId===node.id}
            aria-expanded={node.children.length?!collapsed.has(node.id):undefined} className="mp-tree-item" ref={selection.nodeId===node.id?selected:undefined} onClick={()=>{inspection.choose(node.id);onSelect?.();}}>
            <Box size={14}/><span>{node.name}</span>{node.kind!=='source'&&<small>{text(node.kind==='proxy'?'示意':'无几何',node.kind==='proxy'?'Schematic':'No geometry')}</small>}
          </button></div>)}
      </div>{rows.length===0&&<p className="mp-caption">{text(structure.nodes.length?'没有匹配构件':'源模型未提供可识别的构件节点',structure.nodes.length?'No matching components':'No identifiable source nodes')}</p>}
    </>}
  </section>;
}

export function ModelPreviewTools({inspection}:{inspection:PreviewController}){
  const {locale}=usePreferences(),text=(zh:string,en:string)=>locale==='zh'?zh:en;
  return <div className="mp-tools" role="group" aria-label={text('构件显示','Component display')}>
    <Btn disabled={!inspection.node?.bounds} onClick={inspection.focus}><Focus size={14}/>{text('定位所选','Locate selected')}</Btn>
    <Btn disabled={!inspection.node?.bounds} aria-pressed={inspection.selection.display==='isolate'} onClick={inspection.display}><Layers size={14}/>{text(inspection.selection.display==='isolate'?'其他构件半透明':'仅显示所选',inspection.selection.display==='isolate'?'Ghost other parts':'Show selected only')}</Btn>
    <Btn disabled={!inspection.structure} onClick={inspection.restore}><RotateCcw size={14}/>{text('恢复全部','Restore all')}</Btn>
  </div>;
}

export function ModelComponentProperties({version,inspection}:{version:ProjectModelVersion;inspection:PreviewController}){
  const {locale}=usePreferences(),text=(zh:string,en:string)=>locale==='zh'?zh:en,node=inspection.node;
  const number=(value:number)=>Number(value.toPrecision(6)).toLocaleString(locale==='zh'?'zh-CN':'en-GB',{maximumFractionDigits:6});
  const vector=(value:number[]|null)=>value?.map(number).join(' × ')??'—';
  const attributes=Object.entries(node?.attributes??{}).filter(([key])=>!key.startsWith('ontoVis')).slice(0,100);
  return <section className="mp-properties" aria-label={text('预览属性','Preview properties')}>
    <h3>{text(node?'构件属性':'模型属性',node?'Component properties':'Model properties')}</h3>
    {node?<><strong className="mp-name">{node.name}</strong><p className="mp-caption mp-path">{node.path.join(' / ')}</p>
      <dl><dt>{text('所属模型','Model')}</dt><dd>{version.displayName}</dd><dt>{text('固定几何版本','Fixed geometry version')}</dt><dd title={version.modelVersionId}>{version.modelVersionId.slice(0,8)}</dd>
        <dt>{text('几何来源','Geometry source')}</dt><dd>{text(node.kind==='proxy'?'示意代理几何':node.kind==='metadata'?'仅元数据，无几何':'源模型节点',node.kind==='proxy'?'Schematic proxy':node.kind==='metadata'?'Metadata only, no geometry':'Source model node')}</dd>
        <dt>{text('源节点编号','Source node index')}</dt><dd>{node.nodeIndex??'—'}</dd>
        <dt>{text('子节点','Child nodes')}</dt><dd>{node.children.length}</dd><dt>{text('网格','Meshes')}</dt><dd>{node.meshes}</dd>
        <dt>{text('顶点 / 三角面','Vertices / triangles')}</dt><dd>{number(node.vertices)} / {number(node.triangles)}</dd>
        <dt>{text('源模型尺寸（m）','Source dimensions (m)')}</dt><dd>{vector(node.bounds?node.bounds[1].map((v,i)=>v-node.bounds![0][i]):null)}</dd>
      </dl>
      {!node.bounds&&<p className="mp-caption">{text('此节点没有可定位的几何，保留自身属性。','This node has no locatable geometry; its own properties remain available.')}</p>}
      <details><summary>{text('源坐标与标识','Source coordinates and identity')}</summary><dl>
        <dt>{text('局部平移','Local translation')}</dt><dd>{vector(node.translation)}</dd><dt>{text('局部旋转（°）','Local rotation (°)')}</dt><dd>{vector(node.rotation)}</dd><dt>{text('局部缩放','Local scale')}</dt><dd>{vector(node.scale)}</dd>
        <dt>{text('构件键','Component keys')}</dt><dd>{node.componentKeys.join(', ')||'—'}</dd></dl><p className="mp-caption">{text('节点编号与构件键仅对本固定版本有效。','Node indices and component keys are local to this fixed version.')}</p></details>
      <details><summary>{text('材质','Materials')} · {node.materials.length}</summary>{node.materials.map((material,index)=><dl key={index}><dt>{text('名称','Name')}</dt><dd>{material.name||`#${index}`}</dd><dt>{text('类型','Type')}</dt><dd>{material.type}</dd><dt>{text('颜色 / 不透明度','Color / opacity')}</dt><dd>{material.color??'—'} / {material.opacity}</dd><dt>{text('贴图','Texture')}</dt><dd>{text(material.textured?'有':'无',material.textured?'Yes':'No')}</dd></dl>)}</details>
      {attributes.length>0&&<details><summary>{text('源自定义属性','Source custom attributes')} · {attributes.length}</summary><dl>{attributes.map(([key,value])=><div className="mp-attribute" key={key}><dt>{key}</dt><dd>{(typeof value==='string'?value:JSON.stringify(value))?.slice(0,1200)}</dd></div>)}</dl></details>}
    </>:<><strong className="mp-name">{version.displayName}</strong><p>{text('从左侧构件树或三维模型中选择构件，查看其属性。','Select a component in the tree or the 3D model to inspect its properties.')}</p></>}
    <p className="mp-caption">{text('属性来自源模型，不确认现场设备身份、物理关系或工程精度。','Properties come from the source model and do not confirm installed identity, physical relationships or engineering accuracy.')}</p>
  </section>;
}
