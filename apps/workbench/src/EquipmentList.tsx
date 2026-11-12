import {useEffect,useMemo,useState} from 'react';
import {Box,Search} from 'lucide-react';
import {cancelled,failureMessage,type WorkbenchApi} from './api';
import {EquipmentApi,type EquipmentCatalogItem} from './equipmentApi';
import {Btn} from './Primitives';
import {usePreferences} from './Preferences';

export function EquipmentList({api,selected,onSelect,query,draggable=false}:{api:WorkbenchApi;selected:string;onSelect:(uid:string)=>void;query?:string;draggable?:boolean}){
  const {locale}=usePreferences(),en=locale==='en',client=useMemo(()=>new EquipmentApi(api),[api]);
  const [search,setSearch]=useState(''),[settled,setSettled]=useState(query??''),[items,setItems]=useState<EquipmentCatalogItem[]>([]);
  const [cursor,setCursor]=useState<string|null>(null),[next,setNext]=useState<string|null>(null),[error,setError]=useState<unknown>(null),[busy,setBusy]=useState(false),[attempt,setAttempt]=useState(0);
  useEffect(()=>{const timer=setTimeout(()=>{setSettled((query??search).trim());setCursor(null);},250);return()=>clearTimeout(timer);},[query,search]);
  useEffect(()=>{
    const abort=new AbortController();setError(null);setBusy(true);
    if(!cursor)setItems([]);
    client.catalogue(settled,cursor,abort.signal).then(value=>{if(!abort.signal.aborted){setItems(rows=>cursor?[...rows,...value.items]:value.items);setNext(value.nextCursor);}})
      .catch(error=>{if(!abort.signal.aborted&&!cancelled(error))setError(error);}).finally(()=>{if(!abort.signal.aborted)setBusy(false);});
    return()=>abort.abort();
  },[client,api.epoch,api.revision,settled,cursor,attempt]);
  return <div className="eq-device-list se-equipment-list">{query===undefined&&<label className="se-search"><Search size={14}/><input value={search} placeholder={en?'Equipment name':'搜索设备'} onChange={event=>setSearch(event.target.value)}/></label>}
    {[...items].sort((a,b)=>a.displayName.localeCompare(b.displayName,en?'en':'zh',{numeric:true})).map(item=><button key={item.entityUid} aria-pressed={selected===item.entityUid} draggable={draggable} onDragStart={event=>{event.dataTransfer.setData('application/x-ontovis-equipment',JSON.stringify({entityUid:item.entityUid}));event.dataTransfer.effectAllowed='copy';}} onClick={()=>onSelect(item.entityUid)}><Box size={14}/><span>{item.displayName}<small>{item.sceneUseCount?(en?'Placed':'已布置'):(en?'Not placed':'未布置')}</small></span></button>)}
    {busy&&<p role="status">{en?'Loading equipment…':'正在读取设备…'}</p>}{!busy&&!error&&!items.length&&<p className="se-note">{en?'No matching equipment':'没有匹配设备'}</p>}
    {!!error&&<p role="alert">{failureMessage(error,locale)}<Btn onClick={()=>setAttempt(v=>v+1)}>{en?'Retry':'重试'}</Btn></p>}
    {!busy&&next&&<Btn onClick={()=>setCursor(next)}>{en?'Load more':'加载更多'}</Btn>}
  </div>;
}
