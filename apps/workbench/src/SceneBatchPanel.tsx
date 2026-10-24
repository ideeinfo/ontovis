import {useState} from 'react';
import {usePreferences} from './Preferences';
import {Btn} from './Primitives';
import {groupSceneInstances,sceneOrganization,ungroupSceneInstances} from './sceneOrganization';
import {organizationText} from './sceneOrganizationMessages';
import type {EditableSceneSnapshot} from './sceneTypes';
import './sceneOrganization.css';

export interface SceneSnap {grid:number;angle:number}
export function SceneBatchPanel({snapshot,editable,selectedIds,onSelect,onCommit,onMove,onError,continuous,onContinuous,snap,onSnap}: {
  snapshot:EditableSceneSnapshot;editable:boolean;selectedIds:string[];onSelect:(ids:string[])=>void;
  onCommit:(next:EditableSceneSnapshot)=>Promise<boolean>;onMove:(delta:[number,number],heading:number)=>Promise<boolean>;
  onError:(error:unknown)=>void;continuous:boolean;onContinuous:(value:boolean)=>void;snap:SceneSnap;onSnap:(value:SceneSnap)=>void;
}) {
  const {locale}=usePreferences(),t=(key:Parameters<typeof organizationText>[1])=>organizationText(locale,key);
  const [groupName,setGroupName]=useState(''),[x,setX]=useState('10'),[z,setZ]=useState('0'),[heading,setHeading]=useState('0'),[message,setMessage]=useState('');
  const data=sceneOrganization(snapshot),selected=snapshot.instances.filter(item=>selectedIds.includes(item.sceneModelInstanceId));
  const grouped=selected.some(item=>data.groups.some(group=>group.instanceIds.includes(item.sceneModelInstanceId)));
  const apply=async()=>{setMessage(t('unchanged'));if([x,z,heading].some(value=>!value.trim())){onError(new Error(t('invalid')));return;}
    if(await onMove([Number(x),Number(z)],Number(heading)))setMessage(t('moveDone'));};
  return <div className="so-tools" data-testid="scene-batch-panel">
    <section><h3>{t('selection')} <span className="ov-badge">{selected.length}</span></h3><div className="so-actions"><Btn onClick={()=>onSelect(snapshot.instances.map(item=>item.sceneModelInstanceId))}>{t('selectAll')}</Btn><Btn onClick={()=>onSelect([])}>{t('clear')}</Btn></div>
      <p className="so-note">{t('selectionHint')}</p><label>{t('groupName')}<input value={groupName} maxLength={80} disabled={!editable} onChange={event=>setGroupName(event.target.value)}/></label>
      <Btn disabled={!editable||selected.length<2||grouped||!groupName.trim()||data.groups.length>=16} onClick={()=>{try{void onCommit(groupSceneInstances(snapshot,selectedIds,groupName,crypto.randomUUID())).then(ok=>{if(ok)setGroupName('');});}catch(error){onError(error);}}}>{t('group')}</Btn>
      {grouped&&<p className="so-note">{t('groupHint')}</p>}
      {data.groups.map(group=><div className="so-row" key={group.groupId}><button type="button" className="so-text" onClick={()=>onSelect(group.instanceIds)}>{group.displayName} · {group.instanceIds.length}</button><Btn disabled={!editable} onClick={()=>void onCommit(ungroupSceneInstances(snapshot,group.groupId))}>{t('ungroup')}</Btn></div>)}
    </section>
    <section><h3>{t('move')}</h3><div className="sw-field-pair"><label>{t('dx')}<input type="number" value={x} disabled={!editable} onChange={event=>setX(event.target.value)}/></label><label>{t('dz')}<input type="number" value={z} disabled={!editable} onChange={event=>setZ(event.target.value)}/></label></div>
      <label>{t('heading')}<input type="number" value={heading} disabled={!editable} onChange={event=>setHeading(event.target.value)}/></label><Btn disabled={!editable||!selected.length} onClick={()=>void apply()}>{t('apply')}</Btn><p className="so-note">{t('moveHint')}</p>
      {message&&<p className="so-note" role="status">{message}</p>}
    </section>
    <section><h3>{t('placement')}</h3><label className="so-check"><input type="checkbox" checked={continuous} disabled={!editable} onChange={event=>onContinuous(event.target.checked)}/>{t('continuous')}</label>
      <div className="sw-field-pair"><label>{t('grid')}<select aria-label={t('grid')} value={snap.grid} disabled={!editable} onChange={event=>onSnap({...snap,grid:Number(event.target.value)})}>{[0,1,5,10].map(value=><option key={value} value={value}>{value?`${value} m`:t('off')}</option>)}</select></label>
      <label>{t('angle')}<select aria-label={t('angle')} value={snap.angle} disabled={!editable} onChange={event=>onSnap({...snap,angle:Number(event.target.value)})}>{[0,5,15,30,45,90].map(value=><option key={value} value={value}>{value?`${value}°`:t('off')}</option>)}</select></label></div><p className="so-note">{t('placementHint')}</p>
    </section>
  </div>;
}
