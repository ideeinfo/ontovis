import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {registerHooks} from 'node:module';
import test from 'node:test';
import {createElement, Fragment} from 'react';
import {renderToStaticMarkup} from 'react-dom/server';
import ts from 'typescript';

const primitivesUrl=new URL('../src/Primitives.tsx',import.meta.url).href;
const preferencesUrl=new URL('../src/Preferences.tsx',import.meta.url).href;
// Render the portal inline so Node can inspect the real Radix dialog markup.
const inlinePortal='data:text/javascript,'+encodeURIComponent(
  `export * from ${JSON.stringify(import.meta.resolve('@radix-ui/react-dialog'))};
   export const Portal=({children})=>children;`
);
const hooks=registerHooks({
  resolve(specifier,context,next){
    if(context.parentURL===primitivesUrl){
      if(specifier==='@radix-ui/react-dialog')return next(inlinePortal,context);
      if(specifier==='./Preferences')return next(preferencesUrl,context);
    }
    if(context.parentURL===preferencesUrl&&specifier==='./messages'){
      return next(new URL('./messages.ts',preferencesUrl).href,context);
    }
    return next(specifier,context);
  },
  load(url,context,next){
    if(url!==primitivesUrl&&url!==preferencesUrl)return next(url,context);
    const source=ts.transpileModule(readFileSync(new URL(url),'utf8'),{
      compilerOptions:{jsx:ts.JsxEmit.ReactJSX,module:ts.ModuleKind.ESNext,target:ts.ScriptTarget.ES2022},
    }).outputText;
    return {format:'module',source,shortCircuit:true};
  },
});
const {Btn,ConfirmationDialog}=await import(primitivesUrl);
hooks.deregister();

const dialog=overrides=>createElement(ConfirmationDialog,{
  title:'将画布移至回收站？',
  subject:'合成画布',
  description:'可在回收站恢复。',
  onClose(){assert.fail('Rendering must not dismiss the dialog');},
  ...overrides,
},createElement(Btn,{primary:true,disabled:overrides.closeDisabled},'移至回收站'));

test('each open confirmation describes its own subject, effects and applicable warning',()=>{
  const markup=renderToStaticMarkup(createElement(Fragment,null,
    dialog({warning:'未保存的修改将丢失。'}),
    dialog({title:'将工单归档？',subject:'合成工单',description:'保留处理记录。'}),
  ));
  const ids=Array.from(markup.matchAll(/aria-describedby="([^"]+)"/g),match=>match[1]);
  assert.equal(ids.length,2);
  assert.notEqual(ids[0],ids[1]);
  assert.ok(markup.includes(`id="${ids[0]}" class="ov-sr-only">合成画布 可在回收站恢复。 未保存的修改将丢失。`));
  assert.ok(markup.includes(`id="${ids[1]}" class="ov-sr-only">合成工单 保留处理记录。</p>`));
  assert.equal(markup.match(/class="ov-confirm-warning"/g)?.length,1);
});

test('a pending confirmation reports its status and disables dismissal and both actions',()=>{
  const markup=renderToStaticMarkup(dialog({
    closeDisabled:true,
    cancelLabel:'继续编辑',
    status:createElement('p',{role:'alert'},'操作结果待确认。'),
  }));
  assert.match(markup,/<p role="alert">操作结果待确认。<\/p>/);
  const actions=Array.from(markup.matchAll(/<button\b([^>]*)>/g),match=>match[1]);
  assert.equal(actions.length,3);
  assert.ok(actions.every(attributes=>attributes.includes(' disabled=""')));
  assert.match(markup,/<footer[^>]*><button[^>]*>继续编辑<\/button><button[^>]*>移至回收站<\/button><\/footer>/);
});
