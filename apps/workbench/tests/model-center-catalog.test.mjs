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
  if(specifier.startsWith('.')&&!/\\.[a-z]+$/i.test(specifier)){
    for(const extension of ['.ts','.tsx']){
      try {return await next(specifier+extension,context);}catch(error){if(error.code!=='ERR_MODULE_NOT_FOUND')throw error;}
    }
  }
  return next(specifier,context);
}
export async function load(url,context,next){
  if(url.endsWith('.css'))return {format:'module',source:'export {};',shortCircuit:true};
  if(/\\.tsx?$/.test(url)){
    const source=await readFile(new URL(url),'utf8');
    return {format:'module',source:ts.transpileModule(source,{compilerOptions:{jsx:ts.JsxEmit.ReactJSX,
      module:ts.ModuleKind.ESNext,target:ts.ScriptTarget.ES2022},fileName:new URL(url).pathname}).outputText,shortCircuit:true};
  }
  return next(url,context);
}`)}`,import.meta.url);

const {ProjectModelCenter}=await import('../src/ProjectModelCenter.tsx');
const {ResourcePanel}=await import('../src/ResourcePanel.tsx');
const {PreferencesProvider}=await import('../src/Preferences.tsx');

function render(Component,props={},locale='zh'){
 const prior=new Map(['localStorage','matchMedia'].map(key=>[key,Object.getOwnPropertyDescriptor(globalThis,key)]));let requests=0;
 Object.defineProperty(globalThis,'matchMedia',{configurable:true,value:()=>({matches:false,addEventListener(){},removeEventListener(){}})});
 Object.defineProperty(globalThis,'localStorage',{configurable:true,value:{getItem:key=>key==='ontovis.locale'?locale:null}});
 try{
  const api={request(){requests++;throw Error('Rendering a catalog must not fetch private models');}};
  const html=renderToStaticMarkup(React.createElement(PreferencesProvider,null,React.createElement(Component,{api,...props})));
  assert.equal(requests,0);return html;
 }finally{for(const [key,descriptor]of prior){if(descriptor)Object.defineProperty(globalThis,key,descriptor);else delete globalThis[key];}}
}
test('model center opens as a resource catalog without mounting preview, tree or inspector',()=>{
 const html=render(ProjectModelCenter,{onOpenScene(){throw Error('No implicit navigation');}});
 assert.match(html,/class="pm-catalog pm-library"/);
 assert.match(html,/aria-label="模型资源目录"/);
 assert.doesNotMatch(html,/class="pm-(?:grid|preview|canvas|inspector|empty)"|<canvas\b|role="tree"/);
});
test('catalog offers named view controls and combined purpose and name retrieval in both languages',()=>{
 for(const locale of ['zh','en']){
  const html=render(ProjectModelCenter,{onOpenScene(){}},locale);
  assert.match(html,new RegExp(`aria-label="${locale==='zh'?'模型目录视图':'Model catalog view'}"`));
  assert.match(html,new RegExp(`aria-label="${locale==='zh'?'模型分类':'Model category'}"`));
  assert.match(html,new RegExp(`aria-label="${locale==='zh'?'搜索模型':'Search models'}"`));
  for(const label of locale==='zh'?['缩略图','列表','全部','设备','简化场景','环境']:['Thumbnails','List','All','Equipment','Simplified scene','Environment'])assert.ok(html.includes(label),label);
  assert.equal([...html.matchAll(/aria-pressed="true"/g)].length,2,'One view and one category are active');
 }
});
test('scene resource sidebar retains its compact placement controls instead of the full-page catalog',()=>{
 const html=render(ResourcePanel,{canPlace:false,onPlace(){},onPreview(){},onTerrainReady(){}});
 assert.doesNotMatch(html,/pm-model-browser|pm-view-switch|aria-label="模型分类"/);
 assert.match(html,/<select[^>]+aria-label="用途"/);
});
