import assert from 'node:assert/strict';
import test from 'node:test';
import {readFileSync} from 'node:fs';
import {createRequire} from 'node:module';
import {renderToStaticMarkup} from 'react-dom/server';
import ts from 'typescript';
import {ApiError,WorkbenchApi,cancelled} from '../src/api.ts';
import {SceneApi} from '../src/sceneApi.ts';
import * as inspection from '../src/modelInspection.ts';
import {ResourceRequestGate,privateDenial} from '../src/resourceForms.ts';

const version={modelVersionId:'fixed-v1',contentRevision:'content:1',sha256:'a'.repeat(64),displayName:'合成设备',calibrationState:'verified'};
function fixture(count=6){
  const sourceNodes=Array.from({length:count},(_,nodeIndex)=>({nodeIndex,componentKey:`${version.sha256}:node:${nodeIndex}`,keyStability:'version_local',
    name:`合成节点 ${nodeIndex}`,sourceIdentityState:inspection.identityStates[nodeIndex%5],sourceIdentityVerified:false,activeScene:nodeIndex%2===0,
    sourceExtrasPresent:nodeIndex!==0,sourceExtras:nodeIndex===1?null:{html:'<script>alert(1)</script>',flag:false,number:42,array:[' A ',null]},
    sourceIdentityClaim:nodeIndex===3?{sourceModelKey:'Model A',sourceElementId:'Source 3',placementId:'main'}:null,
    sourceIdentityMissingFields:nodeIndex%5===1?['sourceModelKey']:[],sourceIdentityInvalidFields:nodeIndex%5===2?['placementId']:[]}));
  const sourceIdentityStates={};for(const row of sourceNodes)sourceIdentityStates[row.sourceIdentityState]=(sourceIdentityStates[row.sourceIdentityState]??0)+1;
  return {...version,schemaVersion:1,profileVersion:'source-nodes-v1',scope:'fixed_glb_source_local_only',processorSha256:'b'.repeat(64),catalogSha256:'c'.repeat(64),
    sourceValidation:{nodes:count,coordinateVerification:'unverified',sourceIdentityVerified:false},sourceNodes,sourceIdentityStates,
    sourceIdentityVerified:false,geometryCorrespondenceVerified:false,bindingMigrationApproved:false,releaseReadiness:{eligible:false,G2Passed:false}};
}
const json=value=>new Response(JSON.stringify(value),{headers:{'Content-Type':'application/json'}});
test('report uses only the existing shared fixed-version read and preserves raw source properties',async()=>{
  const calls=[],report=fixture();const transport=new WorkbenchApi(async(path,options)=>{calls.push({path,options});return json({...report,sessionRevision:'session:1'});});
  transport.session('session:1');transport.project={ontobaseConnectionId:'connection',projectCode:'project'};
  const signal=new AbortController().signal,result=await new SceneApi(transport).modelInspection(version,signal);
  assert.equal(calls.length,1);assert.equal(calls[0].path,'/api/workbench/resources/model/inspection');
  assert.deepEqual(JSON.parse(calls[0].options.body),{modelVersionId:'fixed-v1',expectedContentRevision:'content:1',expectedSha256:version.sha256,expectedSessionRevision:'session:1'});
  assert.equal(calls[0].options.signal,signal);assert.equal(calls[0].options.cache,'no-store');
  assert.deepEqual(result.sourceNodes,report.sourceNodes);assert.equal(result.sourceIdentityVerified,false);
});
test('wrong fixed version, content revision or file identity never becomes a visible report',()=>{
  for(const changes of [{modelVersionId:'other'},{contentRevision:'content:2'},{sha256:'d'.repeat(64)}])
    assert.throws(()=>inspection.checkedModelInspection({...fixture(),...changes},version),error=>error.code==='RESOURCE_CHANGED');
});
test('malformed or falsely verified reports and inconsistent node counts are refused',()=>{
  const cases=[{sourceIdentityVerified:true},{geometryCorrespondenceVerified:true},{bindingMigrationApproved:true},{releaseReadiness:{eligible:true,G2Passed:false}},
    {sourceIdentityStates:{missing:6}},{sourceNodes:[]},{profileVersion:'unknown'},{catalogSha256:'invalid'}];
  for(const changes of cases)assert.throws(()=>inspection.checkedModelInspection({...fixture(),...changes},version),error=>error.code==='MODEL_INSPECTION_UNAVAILABLE');
  for(const changes of [{nodeIndex:9},{componentKey:'component:0'},{sourceIdentityVerified:true},{sourceIdentityMissingFields:'wrong'},{activeScene:'false'}]){
    const report=fixture();Object.assign(report.sourceNodes[0],changes);assert.throws(()=>inspection.checkedModelInspection(report,version));
  }
});
test('filters retain outside-scene duplicates and search only node identity without rewriting claims',()=>{
  const report=fixture(10),before=JSON.stringify(report);
  assert.deepEqual(inspection.filterSourceNodes(report.sourceNodes,'','collision','inactive').map(row=>row.nodeIndex),[9]);
  assert.deepEqual(inspection.filterSourceNodes(report.sourceNodes,' model a ','','all').map(row=>row.nodeIndex),[3]);
  assert.equal(inspection.filterSourceNodes(report.sourceNodes,'<script>','','all').length,0);
  assert.equal(JSON.stringify(report),before);assert.equal(inspection.sourceIdentityLabel('unverified_claim','en'),'Complete claim · Unverified');
});
test('session invalidation rejects a completed late inspection response',async()=>{
  let release;const transport=new WorkbenchApi(()=>new Promise(resolve=>{release=resolve;}));transport.session('session:1');
  const pending=new SceneApi(transport).modelInspection(version);transport.invalidate();release(json({...fixture(),sessionRevision:'session:1'}));
  await assert.rejects(pending,error=>cancelled(error));
});

function mount(){
  const states=[],memos=[],effects=[],requests=[];let si,mi,ei,dirty,tree,closed=0,denied=0;
  const hooks={useState(initial){const i=si++;if(!(i in states))states[i]=initial;return [states[i],value=>{states[i]=typeof value==='function'?value(states[i]):value;dirty=true;}];},
    useMemo(fn,deps){const i=mi++;if(!memos[i]||deps.some((v,j)=>!Object.is(v,memos[i].deps[j])))memos[i]={deps,value:fn()};return memos[i].value;},
    useEffect(fn,deps){const i=ei++,old=effects[i];if(!old||deps.some((v,j)=>!Object.is(v,old.deps[j])))effects[i]={fn,deps,pending:true,cleanup:old?.cleanup};}};
  const require=createRequire(import.meta.url),dependencies={react:hooks,'./api':{ApiError,cancelled},'./Primitives':{Btn:'button',Modal:'dialog'},
    './Preferences':{usePreferences:()=>({locale:'zh'})},'./resourceForms':{ResourceRequestGate,privateDenial,resourceFailure:error=>error?.code??'',resourceCalibrationKey:value=>value},
    './resourceMessages':{resourceText:(_locale,key)=>key},'./modelInspection':inspection,'./modelSourceReport.css':{}};
  const source=readFileSync(new URL('../src/ModelSourceReport.tsx',import.meta.url),'utf8');
  const compiled=ts.transpileModule(source,{compilerOptions:{module:ts.ModuleKind.CommonJS,jsx:ts.JsxEmit.ReactJSX}}).outputText,exports={};
  new Function('require','exports',compiled)(name=>dependencies[name]??require(name),exports);
  const props={version,api:{modelInspection(_version,signal){return new Promise((resolve,reject)=>requests.push({signal,resolve,reject}));}},onClose(){closed++;},onPrivateDenied(){denied++;}};
  const nodes=()=>{const found=[];function walk(value){if(Array.isArray(value)){value.forEach(walk);return;}if(!value||typeof value!=='object')return;found.push(value);walk(value.props?.children);}walk(tree);return found;};
  function render(){let rounds=0;do{assert.ok(rounds++<20);dirty=false;si=mi=ei=0;tree=exports.ModelSourceReport(props);for(const effect of effects)if(effect.pending){effect.pending=false;effect.cleanup?.();effect.cleanup=effect.fn();}}while(dirty);}
  render();return {requests,nodes,props,render,get closed(){return closed;},get denied(){return denied;},
    async settle(){await new Promise(resolve=>setImmediate(resolve));render();},
    close(){tree.props.onClose();},destroy(){for(const effect of effects)effect.cleanup?.();}};
}
test('production report closes and cancels without displaying a late result',async()=>{
  const view=mount();try{view.close();assert.equal(view.closed,1);assert.equal(view.requests[0].signal.aborted,true);
    view.requests[0].resolve(fixture());await view.settle();assert.equal(view.nodes().filter(node=>node.type==='pre').length,0);
  }finally{view.destroy();}
});
test('production report clears old content when the fixed version changes and denies a new read',async()=>{
  const view=mount();try{view.requests[0].resolve(fixture());await view.settle();
    view.props.version={...version,modelVersionId:'next-version'};view.render();assert.equal(view.requests[0].signal.aborted,true);
    assert.equal(view.nodes().filter(node=>node.type==='pre').length,0);assert.equal(view.requests.length,2);
    view.requests[1].reject(new ApiError(403,'FORBIDDEN'));await view.settle();assert.equal(view.denied,1);
    assert.equal(view.nodes().filter(node=>node.type==='pre').length,0);
  }finally{view.destroy();}
});
test('production report bounds its list, preserves null and escapes all original JSON text',async()=>{
  const view=mount();try{view.requests[0].resolve(fixture(101));await view.settle();
    const rows=()=>view.nodes().filter(node=>node.type==='button'&&Object.hasOwn(node.props,'aria-pressed'));
    assert.equal(rows().length,50);rows()[1].props.onClick();view.render();
    assert.equal(view.nodes().find(node=>node.type==='pre').props.children,'null');
    rows()[2].props.onClick();view.render();const pre=view.nodes().find(node=>node.type==='pre');
    const html=renderToStaticMarkup(pre);assert.ok(html.includes('&lt;script&gt;'));assert.ok(!html.includes('<script>'));
    view.nodes().find(node=>node.type==='button'&&node.props.children==='再显示50项').props.onClick();view.render();assert.equal(rows().length,100);
    view.nodes().find(node=>node.type==='input').props.onChange({target:{value:'没有匹配'}});view.render();assert.equal(rows().length,0);
    view.nodes().find(node=>node.type==='button'&&node.props.children==='清除筛选').props.onClick();view.render();assert.equal(rows().length,50);
  }finally{view.destroy();}
});
