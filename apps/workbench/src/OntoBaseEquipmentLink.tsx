import {ExternalLink} from 'lucide-react';

export function OntoBaseEquipmentLink({en}:{en:boolean}){
  return <a className="ov-btn" href="https://demo.ontobase.ai/#/equipment" target="_blank" rel="noreferrer" title={en?'Open the equipment library; select the project in OntoBase.':'打开设备库后，在 OntoBase 中选择项目。'}><ExternalLink size={14}/>{en?'Manage in OntoBase':'在 OntoBase 中管理'}</a>;
}
