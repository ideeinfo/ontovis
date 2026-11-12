import assert from 'node:assert/strict';
import test from 'node:test';
import {register} from 'node:module';
import React from 'react';
import {renderToStaticMarkup} from 'react-dom/server';
const tsUrl=new URL('../node_modules/typescript/lib/typescript.js',import.meta.url).href;
register(`data:text/javascript,${encodeURIComponent(`
import ts from ${JSON.stringify(tsUrl)};
import {readFile} from 'node:fs/promises';
export async function load(url,context,next){
 if(/\\.tsx?$/.test(url)){const source=await readFile(new URL(url),'utf8');return {format:'module',source:ts.transpileModule(source,{compilerOptions:{jsx:ts.JsxEmit.ReactJSX,module:ts.ModuleKind.ESNext,target:ts.ScriptTarget.ES2022},fileName:new URL(url).pathname}).outputText,shortCircuit:true};}
 return next(url,context);
}`)}`,import.meta.url);
const {RowActions,RowContext}=await import('../src/ListMenus.tsx');
const h=React.createElement;
function actions(){return [{id:'open',label:'打开',icon:null,onSelect(){throw Error('Rendering must not execute a business action');}},
 {id:'delete',label:'移至回收站',icon:null,danger:true,disabled:true,onSelect(){throw Error('A disabled action must not execute');}}];}
test('row action triggers name the exact object in Chinese and English and remain keyboard focusable',()=>{
 for(const locale of ['zh','en']){
  const html=renderToStaticMarkup(h(RowActions,{name:'长工程名称 <A> / 机舱信号柜',locale,actions:actions()}));
  assert.match(html,/<button[^>]+type="button"/);assert.match(html,/aria-haspopup="menu"/);assert.match(html,/aria-expanded="false"/);
  assert.ok(html.includes(locale==='zh'?'更多操作：':'More actions for'));
  assert.ok(html.includes('长工程名称 &lt;A&gt; / 机舱信号柜'));
  assert.doesNotMatch(html,/tabindex="-1"/);
 }
});
test('a busy list disables its more trigger without creating a writable row action',()=>{
 const html=renderToStaticMarkup(h(RowActions,{name:'Synthetic row',disabled:true,actions:actions()}));
 assert.match(html,/<button[^>]*\bdisabled=""/);assert.doesNotMatch(html,/role="menuitem"/);
});
test('context wrapping preserves a table row and does not insert invalid wrapper elements',()=>{
 const html=renderToStaticMarkup(h('table',null,h('tbody',null,h(RowContext,{name:'Synthetic scene',actions:actions()},h('tr',null,h('td',null,'Scene'))))));
 assert.match(html,/<tbody><tr\b[^>]*><td>Scene<\/td><\/tr><\/tbody>/);
 assert.doesNotMatch(html,/<span|<div|role="menuitem"/);
});
test('a list row keeps its primary control and more control as separate buttons',()=>{
 const html=renderToStaticMarkup(h('ul',null,h(RowContext,{name:'Synthetic project',actions:actions()},h('li',null,
  h('button',{type:'button'},'选择项目'),h(RowActions,{name:'Synthetic project',actions:actions()})))));
 assert.equal([...html.matchAll(/<button\b/g)].length,2);
 assert.doesNotMatch(html,/<button\b[^>]*>(?:(?!<\/button>).)*<button\b/s);
});
