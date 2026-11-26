import type {CanvasCard} from './analysisCanvas';
import {displayText} from './displayText';

const kinds:Record<CanvasCard['kind'],[string,string]>={
 alarm:['故障报警','Alarm'],object:['工程对象','Engineering object'],trend:['趋势','Trend'],drawing:['图纸','Drawing'],
 document:['文档','Document'],photo:['照片','Photo'],model3d:['三维模型','3D model'],work_order:['工单','Work order'],
 analysis:['分析笔记','Analysis note'],
};

export function AssistantCardPicker({cards,selected,groups,label,onSelect,en,locked}:{
 cards:CanvasCard[];selected:string[];groups:Record<string,string>;label:(card:CanvasCard)=>string;
 onSelect:(ids:string[],focused?:CanvasCard)=>void;en:boolean;locked:boolean;
}){
 const t=(zh:string,english:string)=>en?english:zh;
 const current=selected.filter(id=>cards.some(card=>card.id===id));
 if(!cards.length)return <p>{t('当前画布还没有可选的卡片。可先在画布中点击「加入资料」或新建笔记。','Add materials or a note to the canvas to select a card.')}</p>;
 return <div className="as-operation-cards">
  <p>{t('从这里勾选，或在画布上点卡片标题旁的空白处。按住 Shift 可多选。','Check cards here or click beside their titles on the canvas. Hold Shift to select multiple cards.')}</p>
  <div className="as-operation-card-count" aria-live="polite">{t(`已选 ${current.length} 张操作卡片`,`${current.length} cards selected for editing`)}</div>
  <div className="as-materials" role="group" aria-label={t('操作卡片列表','Canvas cards for editing')}>
   {cards.map(card=>{
    const checked=current.includes(card.id);
    return <label className="as-material-row" data-selected={checked} data-disabled={locked} key={card.id}>
     <input type="checkbox" checked={checked} disabled={locked} onChange={()=>onSelect(
      checked?current.filter(id=>id!==card.id):[...current,card.id],checked?undefined:card)}/>
     <span className="as-material-copy"><strong>{displayText(label(card))}</strong><small>
      {kinds[card.kind][en?1:0]}{card.frameId&&groups[card.frameId]?' · '+displayText(groups[card.frameId]):''}
     </small></span>
    </label>;
   })}
  </div>
 </div>;
}
