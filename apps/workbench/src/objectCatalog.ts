import { translate, type Locale, type MessageKey } from './messages.ts';
import type { CatalogGroup, EngineeringObject, ObjectView } from './types';

const kinds:Record<string,MessageKey> = {turbine:'turbine',cabinet:'cabinet',device:'device',component:'component',terminal:'terminal',cable:'cable',loop_label:'loopLabel',unknown:'unclassified',
  blade_assembly:'bladeAssembly',rotor:'rotorAssembly',yaw_mechanism:'yawMechanism',transformer:'transformer',generator:'generator',gearbox:'gearbox',main_shaft:'mainShaft',hub:'hub',tower:'tower',nacelle:'nacelle'};
export function categoryLabel(value:Pick<CatalogGroup,'code'|'nameZh'|'nameEn'|'objectKind'>, locale:Locale) {
  if (value.code) {
    const name = locale==='en' ? value.nameEn || value.nameZh : value.nameZh || value.nameEn;
    return name ? `${value.code} · ${name}` : value.code;
  }
  const key = kinds[value.objectKind];
  return key ? translate(locale,key) : value.objectKind || translate(locale,'unclassified');
}
export function objectCategory(item:Pick<EngineeringObject,'objectKind'|'classification'>, locale:Locale) {
  return categoryLabel({code:null,nameZh:null,nameEn:null,...item.classification,objectKind:item.objectKind},locale);
}
export function objectLocationLabel(item:{objectKind?:string;classification?:EngineeringObject['classification'];identifiers?:{value:string;role:string}[]}|null|undefined,locale:Locale){
  if(!item)return '';
  const standard=item.classification;
  const type=(locale==='en'?standard?.nameEn||standard?.nameZh:standard?.nameZh||standard?.nameEn)?.trim()
    ||standard?.code?.trim()||(item.objectKind&&item.objectKind!=='unknown'?objectCategory({objectKind:item.objectKind},locale):'');
  const code=[...new Set(item.identifiers?.filter(value=>value.role==='primary').map(value=>value.value.trim()).filter(Boolean))].join(' / ');
  return [type,code].filter(Boolean).join('-');
}
export function recordedObjectPath(detail:ObjectView) {
  if (!detail.item.installationContextId) return [];
  return [...detail.ancestors.path].reverse().map(row=>row.object).concat(detail.item);
}
