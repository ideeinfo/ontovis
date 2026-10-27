import type {PreviewRow} from './analysisSources';

const typeNames:Record<string,[string,string]>={
  equipment:['设备','Equipment'],heater:['加热器','Heater'],pump:['泵','Pump'],tank:['罐/容器','Tank / vessel'],fan:['风机','Fan'],
  valve:['阀门','Valve'],control_valve:['调节阀','Control valve'],check_valve:['止回阀','Check valve'],safety_valve:['安全阀','Safety valve'],
  pipe:['管道/管系','Pipe / connection'],instrument:['仪表/测点','Instrument / measurement'],actuator:['执行机构','Actuator'],
  flow:['流量测量','Flow'],pressure:['压力测量','Pressure'],temperature:['温度测量','Temperature'],level:['液位/料位','Level'],
  signal:['信号/联锁','Signal / interlock'],interlock:['联锁','Interlock'],device:['设备/机柜','Device / cabinet'],
  terminal:['端子/端口','Terminal / port'],cable:['线缆/连接','Cable / connection'],control_cabinet:['控制箱/控制柜','Control box / cabinet'],
  pid_logic_function:['逻辑功能块','Logic function block'],pid_reference:['图纸引用标记','Drawing reference'],
};
const aliases:Record<string,string>={equipment:'pid_equipment',heater:'pid_heater',pump:'pid_pump',tank:'pid_tank',vessel:'pid_tank',fan:'pid_fan',valve:'pid_valve',control_valve:'pid_control_valve',check_valve:'pid_check_valve',safety_valve:'pid_safety_valve',pipe:'pid_pipe',line:'pid_pipe',instrument:'pid_instrument',actuator:'pid_actuator',flow:'pid_flow',pressure:'pid_pressure',temperature:'pid_temperature',level:'pid_level',signal:'pid_signal',interlock:'pid_interlock'};
export type DrawingOwnerGroup={key:string;label:string;rows:PreviewRow[]};
export type DrawingTypeGroup=DrawingOwnerGroup&{owners:DrawingOwnerGroup[]};

function rowType(row:PreviewRow,en:boolean){
  const standard=row.classification;
  if(standard?.code){const name=en?standard.nameEn||standard.nameZh:standard.nameZh||standard.nameEn;
    return {key:JSON.stringify(['standard',standard.revisionId||'',standard.code]),label:standard.code+(name?' · '+name:'')};}
  let raw=(row.objectType||'unknown').trim().toLowerCase().replace(/[\s-]+/g,'_')||'unknown';
  raw=aliases[raw]||raw;
  const nameKey=raw.startsWith('pid_')&&aliases[raw.slice(4)]===raw?raw.slice(4):raw;
  return {key:JSON.stringify(['type',raw]),label:raw==='unknown'||raw==='unclassified'?(en?'Unclassified':'未分类'):typeNames[nameKey]?.[en?1:0]||row.objectType||raw};
}

export function drawingGroups(rows:PreviewRow[],ports:boolean,en:boolean,query=''):DrawingTypeGroup[]{
  const groups=new Map<string,DrawingTypeGroup>(),collator=new Intl.Collator(en?'en':'zh-CN',{numeric:true,sensitivity:'base'});
  const needle=query.trim().toLocaleLowerCase();
  for(const row of rows){const type=rowType(row,en);
    if(needle&&![row.title,row.identifier,row.owner,row.targetTitle,type.label,row.objectType,row.classification?.nameZh,row.classification?.nameEn].join(' ').toLocaleLowerCase().includes(needle))continue;
    let group=groups.get(type.key);if(!group){group={...type,rows:[],owners:[]};groups.set(type.key,group);}group.rows.push(row);
    if(ports){const key=row.ownerId?JSON.stringify(['owner',type.key,row.ownerId]):JSON.stringify(['unassigned',type.key]);
      let owner=group.owners.find(item=>item.key===key);
      if(!owner){owner={key,label:row.owner||row.ownerId||(en?'Unassigned object':'未关联对象'),rows:[]};group.owners.push(owner);}owner.rows.push(row);}
  }
  const compareRows=(a:PreviewRow,b:PreviewRow)=>collator.compare(a.title,b.title)||collator.compare(a.id,b.id);
  for(const group of groups.values()){group.rows.sort(compareRows);group.owners.sort((a,b)=>collator.compare(a.label,b.label)||collator.compare(a.key,b.key));for(const owner of group.owners)owner.rows.sort(compareRows);}
  return [...groups.values()].sort((a,b)=>Number(a.label===(en?'Unclassified':'未分类'))-Number(b.label===(en?'Unclassified':'未分类'))||collator.compare(a.label,b.label)||collator.compare(a.key,b.key));
}
