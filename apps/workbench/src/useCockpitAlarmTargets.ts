import {useMemo,useState} from 'react';
import {cockpitAlarmTarget} from './cockpitAlarmTarget';
import type {CockpitAlarmRow} from './cockpitAlarms';
import type {CockpitCatalog} from './cockpitState';
import type {ProjectRef} from './projectTypes';

export function useCockpitAlarmTargets(catalog:CockpitCatalog|null,project:ProjectRef,replay:CockpitAlarmRow[]|null){
 const [choice,choose]=useState('');
 const rows=useMemo(()=>replay?.map(row=>({...row,target:cockpitAlarmTarget(catalog,project,row.registration)}))||[],[replay,catalog,project]);
 const units=useMemo(()=>[...new Map(rows.flatMap(row=>row.registration?
  [[row.registration.rootUid,row.registration.rootName] as const]:[]))], [rows]);
 const selected=units.some(([id])=>id===choice)?choice:'';
 const visibleRows=selected?rows.filter(row=>row.registration?.rootUid===selected):rows;
 const loading=!!replay&&(!catalog||!!catalog.loading)&&rows.some(row=>row.registration&&!row.target);
 return {rows,visibleRows,units,selected,choose,loading};
}
