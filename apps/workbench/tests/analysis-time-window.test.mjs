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

const {timeWindowInput,timeWindowUtc,timeWindowValue,timeWindowLabel,timeZoneLabel,intersectTimeWindows}=await import('../src/analysisTimeWindow.ts');
const {AnalysisTimeWindowForm}=await import('../src/AnalysisTrendTimeForm.tsx');
const initial={from:'2026-10-25T00:00:00Z',to:'2026-10-25T00:03:00Z'},noop=()=>{};

test('display and edits use the saved zone and round-trip milliseconds across midnight and leap days',()=>{
 for(const zone of ['UTC','Asia/Shanghai'])for(const value of ['2026-10-25T00:00:00Z','2026-12-31T20:12:34.123Z','2024-02-29T23:59:59.999Z']){
  assert.equal(timeWindowUtc(timeWindowInput(value,zone),zone),new Date(value).toISOString());
 }
 assert.equal(timeWindowInput(initial.from,'Asia/Shanghai'),'2026-10-25T08:00:00');
 assert.equal(timeWindowLabel(initial.from,'Asia/Shanghai'),'2026/10/25 08:00:00');
 assert.equal(timeWindowUtc('2026-10-25T08:00','Asia/Shanghai'),'2026-10-25T00:00:00.000Z');
 assert.match(timeZoneLabel('Asia/Shanghai',true),/UTC\+08:00/);
});
test('calendar overflow and ambiguous free-text inputs are rejected instead of normalised',()=>{
 for(const value of ['2026-02-29T08:00','2024-02-30T08:00','2026-13-01T08:00','2026-10-25T24:00','2026-10-25T08:60','2026-10-25T08:00:60','2026-10-25','10/25/2026 08:00','2026-10-25T08:00Z','0000-01-01T00:00'])assert.equal(timeWindowUtc(value,'Asia/Shanghai'),null,value);
 assert.equal(timeWindowUtc('2026-10-25T08:00','unsupported'),null);
});
test('invalid, empty, reversed and unavailable intervals cannot be submitted; exact data boundaries are valid',()=>{
 const read=(from,to)=>timeWindowValue(from,to,'Asia/Shanghai',initial);
 assert.equal(read('','').issue,'empty');assert.equal(read('bad','bad').issue,'invalid');
 for(const [from,to] of [['08:00','08:00'],['08:02','08:01']])assert.equal(read('2026-10-25T'+from,'2026-10-25T'+to).issue,'order');
 assert.equal(read('2026-10-25T07:59','2026-10-25T08:03').issue,'outside');
 assert.equal(read('2026-10-25T08:00','2026-10-25T08:04').issue,'outside');
 assert.deepEqual(read('2026-10-25T08:00','2026-10-25T08:03').value,{from:'2026-10-25T00:00:00.000Z',to:'2026-10-25T00:03:00.000Z'});
});
test('several current trends share only their available intersection; absent bounds are not invented',()=>{
 assert.deepEqual(intersectTimeWindows([initial,{from:'2026-10-25T00:01:00Z',to:'2026-10-25T00:04:00Z'}]),{from:'2026-10-25T00:01:00.000Z',to:'2026-10-25T00:03:00.000Z'});
 assert.equal(intersectTimeWindows([]),null);assert.equal(intersectTimeWindows([{from:'invalid',to:initial.to}]),null);
});
const render=(props={})=>renderToStaticMarkup(React.createElement(AnalysisTimeWindowForm,{initial,zone:'Asia/Shanghai',currentCount:2,historicalCount:1,limits:initial,onApply:noop,onCancel:noop,...props}));
test('optional trend form explains scope and shows labelled date controls, explicit zone and balanced actions',()=>{
 const html=render();assert.match(html,/更新 2 条本次趋势/);assert.match(html,/1 条历史参考保留原时间/);assert.match(html,/北京时间/);
 assert.equal((html.match(/type="datetime-local"/g)||[]).length,2);assert.match(html,/value="2026-10-25T08:00:00"/);
 assert.match(html,/取消/);assert.match(html,/应用到画布/);assert.match(html,/应用后还需保存画布/);assert.match(html,/type="submit"[^>]*disabled/);
 assert.doesNotMatch(html,/输入UTC时间|2026-10-25T00:00:00Z/);
});
test('unread or missing current trends, busy work and server failures retain explicit inline feedback',()=>{
 assert.match(render({unavailable:true}),/请先展开本次趋势卡/);assert.match(render({currentCount:0}),/加入本次趋势后/);
 assert.match(render({busy:true}),/正在更新/);assert.match(render({error:'资料版本已变化'}),/role="alert">资料版本已变化/);
 const html=render({en:true,zone:'UTC'});assert.match(html,/Start time/);assert.match(html,/Historical|historical/);assert.match(html,/Apply to canvas/);
});
