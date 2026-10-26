import assert from 'node:assert/strict';
import test from 'node:test';
import {canNavigate,workbenchHeader} from '../src/workbenchNavigation.ts';
import {translate} from '../src/messages.ts';

const scoped={bindings:'componentBinding',hierarchy:'equipmentHierarchy',scene:'sceneSettings',orders:'projectWorkOrders',analysis:'analysisDrafts'};
test('before project entry only project and model centers are available',()=>{
  assert.equal(canNavigate('project',false),true);assert.equal(canNavigate('models',false),true);
  for(const page of Object.keys(scoped))assert.equal(canNavigate(page,false),false,page);
});
test('project entry unlocks implemented project modules while unavailable modules stay disabled',()=>{
  for(const page of ['project','models',...Object.keys(scoped)])assert.equal(canNavigate(page,true),true,page);
  for(const page of ['data','ai','audit','unknown'])for(const entered of [false,true])assert.equal(canNavigate(page,entered),false,page);
});
test('global headers name the current center even when a previous project remains selected',()=>{
  for(const locale of ['zh','en']){
    assert.equal(workbenchHeader('project',translate(locale,'projectAccess'),'Previous project'),locale==='zh'?'项目中心':'Project center');
    assert.equal(workbenchHeader('models',translate(locale,'modelCenter'),'Previous project'),locale==='zh'?'模型中心':'Model center');
  }
});
test('each project module header includes its module and the exact source project name',()=>{
  const project='北苑路北联锁区铁路信号图纸 MVP';
  for(const locale of ['zh','en'])for(const [page,key] of Object.entries(scoped)){
    const module=translate(locale,key);assert.equal(workbenchHeader(page,module,project),`${module} - ${project}`);
  }
});
test('an absent project name never leaves a dangling header separator',()=>{
  assert.equal(workbenchHeader('scene','场景与可视化',''),'场景与可视化');
});
