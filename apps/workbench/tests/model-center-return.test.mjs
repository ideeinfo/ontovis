import assert from 'node:assert/strict';
import test from 'node:test';
import {readFileSync} from 'node:fs';
import {createRequire} from 'node:module';
import ts from 'typescript';

function mount(){
  const states=[],refs=[],memos=[];let si,ri,mi,tree;
  const hooks={lazy:()=>()=>null,Suspense:()=>null,
    useState(initial){const i=si++;if(!(i in states))states[i]=initial;return [states[i],value=>{states[i]=typeof value==='function'?value(states[i]):value;}];},
    useRef(initial){return refs[ri++]||={current:initial};},
    useMemo(fn,deps){const i=mi++,old=memos[i];if(!old||deps.some((v,j)=>!Object.is(v,old.deps[j])))memos[i]={value:fn(),deps};return memos[i].value;}};
  const require=createRequire(import.meta.url),empty=()=>null;
  const dependencies={react:hooks,'./api':{failureMessage:empty},'./Primitives':{Btn:empty},'./Preferences':{usePreferences:()=>({locale:'zh'})},
    './ResourcePanel':{ResourcePanel:empty},'./ModelPreviewInspector':{ModelComponentTree:empty,ModelComponentProperties:empty,ModelPreviewTools:empty,useModelPreview:()=>({})},'./projectModelCenter.css':{}};
  const source=readFileSync(new URL('../src/ProjectModelCenter.tsx',import.meta.url),'utf8');
  const compiled=ts.transpileModule(source,{compilerOptions:{module:ts.ModuleKind.CommonJS,jsx:ts.JsxEmit.ReactJSX}}).outputText;
  const exports={};new Function('require','exports',compiled)(name=>dependencies[name]??require(name),exports);
  const api={epoch:1,revision:1},props={api,onOpenScene:empty,suspended:false};
  function render(){si=ri=mi=0;tree=exports.ProjectModelCenter(props);}
  function nodes(){const result=[];function walk(node){if(!node||typeof node!=='object')return;if(Array.isArray(node)){node.forEach(walk);return;}result.push(node);walk(node.props?.children);}walk(tree);return result;}
  render();return {api,props,render,select(model){nodes().find(n=>n.props?.modelsOnly).props.onPreview(model);render();},viewport:()=>nodes().find(n=>n.props?.onViewChange)?.props};
}
const model=id=>({modelVersionId:id,displayName:id});
const saved={eye:[121,143,-95],target:[0,72,0]};

test('model center restores the live preview camera across cockpit project scope changes',()=>{
  const view=mount();view.select(model('version-a'));assert.equal(view.viewport().initialPreviewView,null);
  view.viewport().onViewChange(saved);view.props.suspended=true;view.api.epoch++;view.render();
  assert.equal(view.viewport().active,false);assert.deepEqual(view.viewport().initialPreviewView,saved);
  view.props.suspended=false;view.api.epoch++;view.render();
  assert.equal(view.viewport().active,true);assert.deepEqual(view.viewport().initialPreviewView,saved);
  assert.deepEqual(view.viewport().snapshot.initialView,saved);
});
test('a different fixed model starts without the previous model camera',()=>{
  const view=mount();view.select(model('version-a'));view.viewport().onViewChange(saved);
  view.select(model('version-b'));assert.equal(view.viewport().initialPreviewView,null);
  assert.notDeepEqual(view.viewport().snapshot.initialView,saved);
});
