import assert from 'node:assert/strict';
import test from 'node:test';
import {readFileSync} from 'node:fs';
import {createRequire} from 'node:module';
import ts from 'typescript';
import {createElement} from 'react';
import {renderToStaticMarkup} from 'react-dom/server';
import * as history from '../src/workOrderHistory.ts';

const fixture=()=>({orderId:'DEMO-WO-024',orderRevision:5,faultCode:'DEMO-01',title:'设备温度异常',state:'closed',
 investigation:{conclusion:'',reviewBasis:'',hypotheses:[{id:'h1',description:'待核温度读数',status:'candidate',basis:''}],steps:Array.from({length:7},(_,i)=>({id:'s'+i,title:'核对步骤'+(i+1),targetKey:'',outcome:'pending',result:''}))},
 diagnosis:{gap:'缺少独立参照记录'},events:['seed_demo','accept','investigate','submit','close'].map((action,i)=>({recordedAt:`2026-10-30T0${i}:00:00Z`,action,note:i<3?'':('保留原始处理内容'+i)}))});

test('closed order retains pending steps, evidence gaps and candidate hypotheses without inferring completion',()=>{
 const source=fixture(),before=JSON.stringify(source),view=history.historicalOrderView(source);
 assert.deepEqual(view.counts,{pending:7,observed:0,gap:0,notApplicable:0});assert.equal(view.gap,source.diagnosis.gap);
 assert.equal(view.hypotheses[0].status,'candidate');assert.equal(view.summary.text,'保留原始处理内容4');assert.equal(view.simulated,true);assert.equal(JSON.stringify(source),before);
});
test('overview prefers a recorded conclusion but retains every original event, including repeated notes',()=>{
 const source=fixture();source.investigation.conclusion='记录结论';source.events[3].note=source.events[4].note;
 const view=history.historicalOrderView(source);assert.equal(view.summary.kind,'conclusion');assert.equal(view.summary.text,'记录结论');
 assert.equal(view.events.length,5);assert.deepEqual(view.events.map(e=>e.action),['close','submit','investigate','accept','seed_demo']);assert.equal(view.events[0].note,view.events[1].note);
});
test('missing records use explicit empty states and unknown actions or dates do not leak internal names',()=>{
 const view=history.historicalOrderView({});assert.equal(view.summary.kind,'empty');assert.deepEqual(view.events,[]);assert.equal(view.simulated,false);
 assert.equal(history.orderStateLabel(undefined,false),'状态未提供');assert.equal(history.orderActionLabel('internal_unknown_action',false),'更新记录');
 assert.equal(history.orderActionLabel('seed_demo',false),'创建演示工单');assert.equal(history.orderRecordTime('invalid',true),'Time unavailable');
 assert.equal(history.orderOutcomeLabel('gap',false),'资料缺口');assert.equal(history.orderOutcomeLabel('supported',true),'Support recorded');
});

function mount(source,{full=true,en=false}={}){
 const states=[],refs=[];let si,ri,dirty,tree;
 const hooks={useState(initial){const i=si++;if(!(i in states))states[i]=initial;return [states[i],v=>{const next=typeof v==='function'?v(states[i]):v;if(!Object.is(next,states[i])){states[i]=next;dirty=true;}}];},useRef(initial){return refs[ri++]||={current:initial};}};
 const require=createRequire(import.meta.url),module=ts.transpileModule(readFileSync(new URL('../src/HistoricalWorkOrder.tsx',import.meta.url),'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,jsx:ts.JsxEmit.ReactJSX}}).outputText,exports={};
 const icons=new Proxy({},{get:()=>()=>null});new Function('require','exports',module)(name=>name==='react'?hooks:name==='lucide-react'?icons:name==='./workOrderHistory'?history:name.endsWith('.css')?{}:require(name),exports);
 function nodes(){const out=[];function walk(n){if(n==null||typeof n==='boolean')return;if(Array.isArray(n)){n.forEach(walk);return;}if(typeof n!=='object'){out.push(n);return;}if(typeof n.type==='function'){walk(n.type(n.props));return;}out.push(n);walk(n.props?.children);}walk(tree);return out;}
 const text=value=>value==null||typeof value==='boolean'?'':Array.isArray(value)?value.map(text).join(''):typeof value==='object'?text(value.props?.children):String(value);
 function render(){let turns=0;do{assert.ok(turns++<20);si=ri=0;dirty=false;tree=exports.HistoricalWorkOrder({source,en,full});}while(dirty);}
 render();return {text:()=>nodes().filter(n=>typeof n==='string'||typeof n==='number').join(' '),buttons:()=>nodes().filter(n=>n.type==='button'),
 click(name){const button=nodes().find(n=>n.type==='button'&&(n.props['aria-label']===name||text(n.props.children)===name));assert.ok(button,`button ${name}`);assert.ok(!button.props.disabled);button.props.onClick();render();}};
}
test('compact historical card shows a summary and current state without dumping the event list',()=>{
 const view=mount(fixture(),{full:false});assert.match(view.text(),/已关闭/);assert.match(view.text(),/保留原始处理内容4/);assert.match(view.text(),/缺少独立参照记录/);assert.doesNotMatch(view.text(),/保留原始处理内容3/);assert.equal(view.buttons().length,0);
});
test('detail pages expose investigation statuses and paginate without editing the source',()=>{
 const source=fixture(),before=JSON.stringify(source),view=mount(source);assert.match(view.text(),/最近处理记录/);assert.doesNotMatch(view.text(),/核对步骤1/);
 view.click('排查记录7');assert.match(view.text(),/核对步骤1/);assert.match(view.text(),/待排查/);assert.doesNotMatch(view.text(),/核对步骤4/);
 view.click('下一组记录');assert.match(view.text(),/核对步骤4/);view.click('上一组记录');assert.match(view.text(),/核对步骤1/);
 view.click('故障假设1');assert.match(view.text(),/待核假设/);assert.match(view.text(),/尚无依据记录/);assert.equal(JSON.stringify(source),before);
});
test('timeline uses newest-first events, readable actions and pages back to the original creation event',()=>{
 const view=mount(fixture());view.click('查看完整时间线');assert.match(view.text(),/保留原始处理内容4/);assert.match(view.text(),/提交复核/);assert.doesNotMatch(view.text(),/创建演示工单/);
 view.click('下一组记录');view.click('下一组记录');assert.match(view.text(),/创建演示工单/);assert.doesNotMatch(view.text(),/保留原始处理内容4/);assert.match(view.text(),/此事件未附备注/);
});
test('read full record selects the latest nonempty event even if it is on an older page',()=>{
 const source=fixture();source.events.forEach((e,i)=>e.note=i===0?'仅创建时附有备注':'');const view=mount(source);view.click('查看处理原文');assert.match(view.text(),/创建演示工单/);assert.match(view.text(),/仅创建时附有备注/);
});
test('empty order and English views remain read only and show explicit missing data',()=>{
 const view=mount({},{en:true});assert.match(view.text(),/Order ID unavailable/);assert.match(view.text(),/No conclusion or treatment record/);view.click('Timeline0');assert.match(view.text(),/No timeline recorded/);
 assert.ok(view.buttons().every(b=>!/save|edit|confirm/i.test(b.props['aria-label']||'')));
});
test('record text is escaped instead of being interpreted as markup',()=>{
 const source=fixture();source.events[4].note='<img src=x onerror=alert(1)>';
 // A server render exercises React escaping with the actual component.
 const require=createRequire(import.meta.url),compiled=ts.transpileModule(readFileSync(new URL('../src/HistoricalWorkOrder.tsx',import.meta.url),'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,jsx:ts.JsxEmit.ReactJSX}}).outputText,exports={};new Function('require','exports',compiled)(name=>name==='./workOrderHistory'?history:name.endsWith('.css')?{}:require(name),exports);
 const html=renderToStaticMarkup(createElement(exports.HistoricalWorkOrder,{source,en:false}));assert.match(html,/&lt;img src=x onerror=alert\(1\)&gt;/);assert.doesNotMatch(html,/<img src=x/);
});
