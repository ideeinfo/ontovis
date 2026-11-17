export const noteSections=[['观察','Observation'],['原因假设','Hypothesis'],['检查步骤','Checks'],['检查结果','Result'],['反证与缺口','Counterevidence & gaps'],['下一步','Next steps']] as const;
type Section=typeof noteSections[number][0];
export type NoteFields=Record<Section,string>;
export function readNote(text:string):NoteFields{
  const result=Object.fromEntries(noteSections.map(([key])=>[key,''])) as NoteFields;let current:Section='观察';
  for(const line of text.split('\n')){const match=noteSections.find(([key])=>line.startsWith(key+'：'));
    if(match){current=match[0];result[current]+=(result[current]?'\n':'')+line.slice(current.length+1);}
    else result[current]+=(result[current]?'\n':'')+line;
  }
  for(const [key] of noteSections)result[key]=result[key].trim();return result;
}
export function writeNote(fields:NoteFields){return noteSections.filter(([key])=>fields[key].trim()).map(([key])=>key+'：'+fields[key].trim()).join('\n\n');}
