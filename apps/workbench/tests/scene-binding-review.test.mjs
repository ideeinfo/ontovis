import assert from 'node:assert/strict';
import test from 'node:test';
import {register} from 'node:module';
import React from 'react';
import {renderToStaticMarkup} from 'react-dom/server';

// Node 22 strips plain TypeScript; this narrow test loader also handles TSX and
// the component's CSS import. Production builds continue to use the Vite setup.
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

const {bindingReviewPlan,bindingReviewRefKey,readBindingReviewNames,BindingReviewDetails}=await import('../src/SceneBindingReview.tsx');
const {PreferencesProvider}=await import('../src/Preferences.tsx');
const {ApiError}=await import('../src/api.ts');

const ref=(uid)=>({ontobaseConnectionId:'private-connection',projectCode:'private-project',entityUid:uid});
const old=ref('private-old-root'),next=ref('private-new-root'),removed=ref('private-cabinet');
const instance={sceneModelInstanceId:'private-instance',displayName:'风机 A · 东侧'};
const impact={sceneModelInstanceId:instance.sceneModelInstanceId,from:old,to:next,
  clearOldComponentBindings:true,reviewedRemovedBindingsDigest:'private-hash',removedBindings:[
    {objectRef:removed,componentKeys:['private-component-1','private-component-2']},
    {objectRef:old,componentKeys:['private-component-3']},
  ]};
const check=()=>({rootBindingImpact:structuredClone([impact]),validation:{},rootBindingChanges:[{private:'unchanged'}],
  reviewedEngineering:[{private:'original-server-proof'}]});
const value=(requested,name='业务设备名称')=>({objectRef:{...requested},item:{entityUid:requested.entityUid,displayName:name},sessionRevision:'session:1'});
function apiWith(request){return {epoch:1,revision:'session:1',request};}
const deferred=()=>{let resolve,reject;const promise=new Promise((yes,no)=>{resolve=yes;reject=no;});return {promise,resolve,reject};};
const isAbort=error=>error.name==='AbortError';

test('review plan keeps complete business rows, deduplicates reads, and leaves approvals untouched',()=>{
  const source=check(),before=structuredClone(source),plan=bindingReviewPlan(source,[instance],[]);
  assert.deepEqual(plan.rows,[{instanceId:instance.sceneModelInstanceId,instanceName:instance.displayName,from:old,to:next,
    removed:[{objectRef:removed,componentCount:2},{objectRef:old,componentCount:1}]}]);
  assert.deepEqual(plan.refs,[old,next,removed]);assert.deepEqual(source,before);
});

test('removed instances use their previous business name and unlinking has no invented new object',()=>{
  const source=check();source.rootBindingImpact[0].to=null;
  const plan=bindingReviewPlan(source,[],[instance]);
  assert.equal(plan.rows[0].instanceName,instance.displayName);assert.equal(plan.rows[0].to,null);
  assert.deepEqual(plan.refs,[old,removed]);
});

test('missing instance names, empty impacts and malformed component sets never become a review',()=>{
  for(const invalid of [()=>bindingReviewPlan(check(),[],[]),()=>bindingReviewPlan({validation:{},rootBindingImpact:[]},[instance],[]),
    ()=>{const source=check();source.rootBindingImpact[0].removedBindings[0].componentKeys=[];return bindingReviewPlan(source,[instance],[]);},
    ()=>bindingReviewPlan(check(),[{...instance,displayName:' '}],[])]){
    assert.throws(invalid,error=>error.code==='SOURCE_UNAVAILABLE');
  }
});

test('names use actual object context reads, full references and one request per duplicate',async()=>{
  const calls=[];
  const api=apiWith(async(path,body)=>{calls.push({path,body});return value(ref(body.entityUid),`业务 ${body.entityUid}`);});
  const names=await readBindingReviewNames(api,[old,next,old,removed],new AbortController().signal);
  assert.equal(calls.length,3);assert.ok(calls.every(call=>call.path==='/api/workbench/objects/context'));
  assert.deepEqual(calls.map(call=>call.body),[old,next,removed].map(row=>({entityUid:row.entityUid})));
  assert.equal(names.get(bindingReviewRefKey(removed)),`业务 ${removed.entityUid}`);
});

test('name reads have at most four live requests for a larger removal list',async()=>{
  let active=0,maximum=0,calls=0;
  const api=apiWith(async(_path,body)=>{active++;calls++;maximum=Math.max(maximum,active);
    await new Promise(resolve=>setTimeout(resolve,3));active--;return value(ref(body.entityUid));});
  const refs=Array.from({length:17},(_,index)=>ref(`private-${index}`));
  const names=await readBindingReviewNames(api,refs,new AbortController().signal);
  assert.equal(names.size,17);assert.equal(calls,17);assert.equal(maximum,4);assert.equal(active,0);
});

test('wrong connection, project, ref identity, selected UID or empty name rejects the complete read',async()=>{
  for(const change of [response=>{response.objectRef.ontobaseConnectionId='other';},response=>{response.objectRef.projectCode='other';},
    response=>{response.objectRef.entityUid='other';},response=>{response.item.entityUid='other';},response=>{response.item.displayName='';}]){
    const api=apiWith(async()=>{const response=value(old);change(response);return response;});
    await assert.rejects(readBindingReviewNames(api,[old],new AbortController().signal),error=>error.code==='SOURCE_UNAVAILABLE');
  }
});

test('one unreadable object rejects all names and aborts the other in-flight read',async()=>{
  let otherAborted=false;
  const api=apiWith(async(_path,body,signal)=>{
    if(body.entityUid===old.entityUid)throw new ApiError(403,'FORBIDDEN');
    return new Promise((_resolve,reject)=>signal.addEventListener('abort',()=>{otherAborted=true;reject(new DOMException('Aborted','AbortError'));},{once:true}));
  });
  await assert.rejects(readBindingReviewNames(api,[old,next],new AbortController().signal),error=>error.code==='FORBIDDEN');
  assert.equal(otherAborted,true);
});

test('retry is a new complete read rather than accepting a prior partial name map',async()=>{
  let failed=true,calls=0;
  const api=apiWith(async(_path,body)=>{calls++;if(failed&&body.entityUid===next.entityUid)throw new ApiError(503,'SOURCE_UNAVAILABLE');return value(ref(body.entityUid));});
  await assert.rejects(readBindingReviewNames(api,[old,next],new AbortController().signal));failed=false;
  const names=await readBindingReviewNames(api,[old,next],new AbortController().signal);
  assert.equal(names.size,2);assert.equal(calls,4);
});

test('a cancelled read discards a late response even if transport ignores AbortSignal',async()=>{
  const pending=deferred(),controller=new AbortController(),api=apiWith(()=>pending.promise);
  const promise=readBindingReviewNames(api,[old],controller.signal);controller.abort();pending.resolve(value(old));
  await assert.rejects(promise,isAbort);
});

test('session epoch, revision and newer check intent each discard late names',async()=>{
  for(const mutate of [api=>{api.epoch++;},api=>{api.revision='session:2';},(_api,current)=>{current.value=false;}]){
    const pending=deferred(),api=apiWith(()=>pending.promise),current={value:true};
    const promise=readBindingReviewNames(api,[old],new AbortController().signal,()=>current.value);
    mutate(api,current);pending.resolve(value(old));await assert.rejects(promise,isAbort);
  }
});

test('already-cancelled input starts no requests',async()=>{
  let calls=0;const controller=new AbortController();controller.abort();
  await assert.rejects(readBindingReviewNames(apiWith(async()=>{calls++;return value(old);}),[old],controller.signal),isAbort);
  assert.equal(calls,0);
});

test('ready details render full business names and component counts without private identifiers',()=>{
  const plan=bindingReviewPlan(check(),[instance],[]),names=new Map([
    [bindingReviewRefKey(old),'原设备完整业务名称'],[bindingReviewRefKey(next),'新设备完整业务名称'],
    [bindingReviewRefKey(removed),'轮毂变桨系统24V及控制信号接口\n第二行完整工程名称 <测试>'],
  ]);
  const markup=renderToStaticMarkup(React.createElement(BindingReviewDetails,{plan,names}));
  for(const expected of ['风机 A · 东侧','原设备完整业务名称','新设备完整业务名称','轮毂变桨系统24V及控制信号接口','第二行完整工程名称 &lt;测试&gt;','2 个构件','1 个构件'])assert.ok(markup.includes(expected));
  for(const privateText of ['private-instance','private-old-root','private-new-root','private-cabinet','private-component','private-hash','original-server-proof'])assert.ok(!markup.includes(privateText));
});

test('ready details use the English preference and show a readable unlink empty state',()=>{
  const originalStorage=globalThis.localStorage,originalMedia=globalThis.matchMedia;
  globalThis.localStorage={getItem:key=>key==='ontovis.locale'?'en':'light'};
  globalThis.matchMedia=()=>({matches:false});
  try {
    const source=check();source.rootBindingImpact[0].to=null;source.rootBindingImpact[0].removedBindings=[];
    const plan=bindingReviewPlan(source,[instance],[]),names=new Map([[bindingReviewRefKey(old),'Old business equipment']]);
    const markup=renderToStaticMarkup(React.createElement(PreferencesProvider,null,React.createElement(BindingReviewDetails,{plan,names})));
    for(const expected of ['Previous equipment','New equipment','No linked equipment','No internal links to clear'])assert.ok(markup.includes(expected));
    assert.ok(!markup.includes('private-old-root'));
  } finally {globalThis.localStorage=originalStorage;globalThis.matchMedia=originalMedia;}
});
