import { translate, type Locale, type MessageKey } from './messages.ts';
import type { CatalogGroup, EngineeringObject, ObjectView } from './types';

const kinds:Record<string,MessageKey> = {turbine:'turbine',cabinet:'cabinet',device:'device',component:'component',terminal:'terminal',cable:'cable',loop_label:'loopLabel',unknown:'unclassified'};
export function categoryLabel(value:Pick<CatalogGroup,'code'|'nameZh'|'nameEn'|'objectKind'>, locale:Locale) {
  if (value.code) {
    const name = locale==='en' ? value.nameEn || value.nameZh : value.nameZh || value.nameEn;
    return name ? `${value.code} · ${name}` : value.code;
  }
  const key = kinds[value.objectKind];
  return key ? translate(locale,key) : value.objectKind || translate(locale,'unclassified');
}
export function objectCategory(item:EngineeringObject, locale:Locale) {
  return categoryLabel({code:null,nameZh:null,nameEn:null,...item.classification,objectKind:item.objectKind},locale);
}
export function recordedObjectPath(detail:ObjectView) {
  if (!detail.item.installationContextId) return [];
  return [...detail.ancestors.path].reverse().map(row=>row.object).concat(detail.item);
}
