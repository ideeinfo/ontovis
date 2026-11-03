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
const {CockpitDevice}=await import('../src/CockpitDevice.tsx');
const {CockpitModelView}=await import('../src/CockpitModelView.tsx');
const {SceneLoadingProgress}=await import('../src/SceneLoadingProgress.tsx');
const {CockpitAlarmCard}=await import('../src/CockpitAlarmSummary.tsx');
const h=React.createElement,render=(component,props)=>renderToStaticMarkup(h(component,props));
const noop=()=>{};
const base={api:{request(){throw Error('SSR must not fetch');}},uid:'synthetic',en:false,representationUid:'root',
 onSelect:noop,onAnalyze:noop,onChoose:noop,onIsolate:noop,onFocus:noop,selectionToken:1,
 location:{status:'located',mode:'direct'},locating:false,previewing:false,locationError:null,isolated:false,preparationState:'ready'};
const button=(html,label)=>html.match(new RegExp('<button[^>]*aria-label="'+label+'"[^>]*>'))?.[0];
test('device navigation waits for actual model readiness even when location already succeeded',()=>{
 const ready=render(CockpitDevice,base),waiting=render(CockpitDevice,{...base,preparationState:'loading'});
 for(const label of ['定位所选','隔离所选']){
  assert.doesNotMatch(button(ready,label),/disabled/);assert.match(button(waiting,label),/disabled/);
 }
 assert.match(waiting,/aria-busy="true"/);assert.match(waiting,/正在切换模型/);
 assert.match(waiting,/<button disabled="" class="pc-text-action">切换/);
 assert.doesNotMatch(ready,/<button disabled="" class="pc-text-action">切换/);
});
test('an early visual preview cannot enable isolation while the location proof is pending',()=>{
 const html=render(CockpitDevice,{...base,locating:true,previewing:true});
 assert.match(button(html,'隔离所选'),/disabled/);assert.match(button(html,'定位所选'),/disabled/);
 assert.match(html,/<button disabled="" class="pc-text-action">切换/);
});
test('failed model allows choosing another device, while spatial operations stay blocked',()=>{
 const html=render(CockpitDevice,{...base,preparationState:'error'});
 assert.match(html,/模型加载失败/);assert.doesNotMatch(html,/<button disabled="" class="pc-text-action">切换/);
 assert.match(button(html,'定位所选'),/disabled/);assert.match(button(html,'隔离所选'),/disabled/);
});
test('all model-view modes wait, including solid, then restore after a successful switch',()=>{
 const props={instanceId:'i',modelVersionId:'v',contentRevision:'r1',sha256:'a'.repeat(64),en:false,onChange:noop,status:'ready',canInspect:true};
 assert.equal((render(CockpitModelView,{...props,pending:true}).match(/disabled=""/g)||[]).length,3);
 assert.equal((render(CockpitModelView,{...props,pending:false}).match(/disabled=""/g)||[]).length,0);
});
test('model waiting uses indeterminate progress; known steps remain factual in both languages',()=>{
 for(const locale of ['zh','en']){
  const waiting=render(SceneLoadingProgress,{locale,phase:'model'});
  assert.match(waiting,locale==='zh'?/正在切换模型/:/Switching model/);
  assert.match(waiting,/<progress[^>]*max="1"/);assert.doesNotMatch(waiting,/<progress[^>]*value=/);assert.doesNotMatch(waiting,/<small>/);
  const display=render(SceneLoadingProgress,{locale,phase:'model',state:{completed:2,total:3,stage:'display'}});
  assert.match(display,locale==='zh'?/正在生成画面/:/Generating the view/);assert.match(display,/2\/3/);assert.match(display,/value="2"/);
 }
});
test('scene alarm location buttons honor the shared preparation lock',()=>{
 const row={dataset:{datasetId:'d',datasetRevision:'r1',faultCode:'13001',title:'Synthetic alarm',timeFrom:'2026-11-03T00:00:00Z'},
  detail:{alarms:[{state:'active',severity:'warning',sourceTime:'2026-11-03T00:00:30Z',updatedAt:'2026-11-03T00:00:30Z'}]},target:{displayName:'Synthetic device'}};
 assert.doesNotMatch(render(CockpitAlarmCard,{row,en:false,compact:true,onOpen:noop}),/<button[^>]*disabled=""/);
 const html=render(CockpitAlarmCard,{row,en:false,compact:true,disabled:true,onOpen:noop});
 assert.match(html,/<button[^>]*disabled=""/);
});
