import assert from 'node:assert/strict';
import test from 'node:test';
import {register} from 'node:module';
import React from 'react';
import {renderToStaticMarkup} from 'react-dom/server';
const tsUrl=new URL('../node_modules/typescript/lib/typescript.js',import.meta.url).href;
register(`data:text/javascript,${encodeURIComponent(`
import ts from ${JSON.stringify(tsUrl)};
import {readFile} from 'node:fs/promises';
export async function resolve(specifier,context,next){
 if(specifier.startsWith('.')&&!/\\.[a-z]+$/i.test(specifier))for(const extension of ['.ts','.tsx']){
  try{return await next(specifier+extension,context);}catch(error){if(error.code!=='ERR_MODULE_NOT_FOUND')throw error;}
 }
 return next(specifier,context);
}
export async function load(url,context,next){
 if(url.endsWith('.css'))return {format:'module',source:'export {};',shortCircuit:true};
 if(/\\.(?:png|svg|webp)$/.test(url))return {format:'module',source:'export default "synthetic-asset";',shortCircuit:true};
 if(/\\.tsx?$/.test(url))return {format:'module',source:ts.transpileModule(await readFile(new URL(url),'utf8'),{compilerOptions:{jsx:ts.JsxEmit.ReactJSX,module:ts.ModuleKind.ESNext,target:ts.ScriptTarget.ES2022},fileName:new URL(url).pathname}).outputText,shortCircuit:true};
 return next(url,context);
}`)}`,import.meta.url);

const {CockpitAnalysisRecordContent,cockpitRecordWindow}=await import('../src/CockpitAnalysisRecord.tsx');
const noop=()=>{},detail={analysisRevision:8,snapshot:{title:'Fixed analysis',context:{timeFrom:'2026-10-25T00:00:00Z',timeTo:'2026-10-25T00:03:00Z',timezone:'Asia/Shanghai'}}};
const groups=[{id:'observations',title:'已知情况',rows:[{text:'模拟事件，不是现场结论。',refs:['E1']},{text:'第二条依据。',refs:['E2']}]},{id:'hypotheses',title:'待验证假设',rows:[{text:'仍须核验。',refs:['E1']}]}];
const run={state:'complete',question:'核对 <script>private</script> 与依据',conversationVersion:2,result:{},sources:[{},{}]};
const base={detail,run,groups,reason:'本次事件',references:{E1:{title:'原固定报警',available:true},E2:{title:'不可用资料',available:false}},en:false,onReference:noop,onAsk:noop,onEdit:noop};
const render=(overrides={})=>renderToStaticMarkup(React.createElement(CockpitAnalysisRecordContent,{...base,...overrides}));
test('full records separate question, fixed scope and numbered sections without clipping any items',()=>{
 const html=render();
 assert.match(html,/本轮问题/);assert.match(html,/核对 &lt;script&gt;private&lt;\/script&gt; 与依据/);assert.doesNotMatch(html,/<script>/);
 assert.match(html,/分析记录目录/);assert.match(html,/固定时间窗/);assert.match(html,/r8/);
 assert.match(html,/第二条依据。/);assert.equal((html.match(/data-record-section=/g)||[]).length,2);
 assert.match(html,/第2轮/);assert.match(html,/待人工核验/);
});
test('unavailable fixed references stay disabled and no write or adoption controls appear',()=>{
 const html=render();
 assert.match(html,/<button[^>]*disabled=[^>]*title="不可用资料"[^>]*>E2/);
 assert.match(html,/<button[^>]*title="原固定报警"[^>]*>E1/);
 assert.match(html,/基于当前资料提问/);assert.doesNotMatch(html,/加入本次分析笔记|整理到工单|<textarea|contenteditable/);
});
test('manual notes and empty records do not claim a validated model answer',()=>{
 const manual=render({run:undefined});assert.match(manual,/已保存分析笔记/);assert.doesNotMatch(manual,/已保存回答|本轮问题|第2轮/);
 const empty=render({run:undefined,groups:[]});assert.match(empty,/暂无可展示的已保存记录/);
});
test('record windows display the configured timezone and preserve malformed legacy text safely',()=>{
 const window=cockpitRecordWindow(detail.snapshot.context,false);assert.match(window,/08:00/);assert.match(window,/08:03/);assert.doesNotMatch(window,/00:00/);
 assert.equal(cockpitRecordWindow({...detail.snapshot.context,timezone:'invalid-zone'},true),'2026-10-25T00:00:00Z — 2026-10-25T00:03:00Z');
});
test('English records keep the same sections, reference scope and read-only action boundary',()=>{
 const html=render({en:true});for(const text of ['Question','Analysis record contents','Fixed time window','Ask about these materials','Fixed revision · read only'])assert.ok(html.includes(text),text);
});
