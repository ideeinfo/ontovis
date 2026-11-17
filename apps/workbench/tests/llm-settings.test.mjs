import test from 'node:test';
import assert from 'node:assert/strict';
import {llmTaskNames,modelTaskState,modelConfigurationApi,capabilitySettings,capabilityProblems} from '../src/llmSettings.ts';
import {WorkbenchApi} from '../src/api.ts';
const settings={enabled:true,connectionId:null,modelId:'',timeoutSeconds:50,concurrency:2,reasoningEffort:'default',goal:'按资料核对',focus:'',readLimit:8,readParallel:2,tools:['selected_sources']};
test('capabilities have no provider or execution decision and accept source connection IDs',async()=>{
 assert.deepEqual(Object.keys(llmTaskNames),['analysis','query','work_order']);assert.deepEqual(capabilityProblems(settings),[]);
 const calls=[],client=modelConfigurationApi({request:async(path,body)=>{calls.push({path,body});return {};}}),view={revision:4,accessRevision:'grant',connections:[{id:'shared',version:3}]};
 await client.save(view,'query',{...settings,connectionId:'shared',modelId:'future-provider-model'},'request');
 assert.equal(calls[0].body.change.expectedConnectionVersion,3);assert.equal(calls[0].body.expectedRevision,4);assert.equal(calls[0].body.expectedAccessRevision,'grant');
 assert.equal('provider' in calls[0].body.change.settings,false);assert.equal('execution' in calls[0].body.change.settings,false);assert.equal('apiKey' in calls[0].body.change.settings,false);
 await client.catalogue(view,view.connections[0]);assert.equal(calls[1].body.connectionId,'shared');assert.equal(calls[1].body.expectedConnectionVersion,3);assert.equal('question' in calls[1].body,false);
});
test('invalid runtime, instructions and tools cannot be saved',()=>{
 for(const change of [{timeoutSeconds:51},{concurrency:3},{readLimit:9},{readParallel:0},{goal:' '},{tools:[]},{tools:['selected_sources','write']},{connectionId:'shared',modelId:''}])assert.ok(capabilityProblems({...settings,...change}).length);
 assert.deepEqual(capabilitySettings({...settings,id:'query',legacyNeedsReview:false}),settings);
});
test('source availability, capability switch and legacy review have distinct states',()=>{
 assert.equal(modelTaskState({enabled:true,legacyNeedsReview:false},{enabled:true}),'ready');
 assert.equal(modelTaskState({enabled:true,legacyNeedsReview:false},{enabled:false}),'unavailable');
 assert.equal(modelTaskState({enabled:false,legacyNeedsReview:false}),'off');
 assert.equal(modelTaskState({enabled:false,legacyNeedsReview:true}),'review');
});
test('captured capability settings stay scoped to the original project',async()=>{
 const calls=[],api=new WorkbenchApi(async(path,options)=>{calls.push(JSON.parse(options.body));return new Response(JSON.stringify({sessionRevision:'session'}),{headers:{'Content-Type':'application/json'}});});
 api.session('session');api.selectProject({ontobaseConnectionId:'source',projectCode:'A'});const service=modelConfigurationApi(api);api.selectProject({ontobaseConnectionId:'source',projectCode:'B'});
 await service.save({revision:0,accessRevision:'A:admin',connections:[]},'analysis',settings);
 assert.equal(calls[0].projectRef.projectCode,'A');assert.equal(api.project.projectCode,'B');
});
