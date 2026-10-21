import assert from 'node:assert/strict';
import test from 'node:test';
import {bindingNeedsReview,modelLocation} from '../src/modelLocation.ts';
import {messages,translate} from '../src/messages.ts';
const obj=(uid,revision='r1')=>({entityUid:uid,entityRevision:revision,installationContextId:'equipment',lifecycle:'active'});
const binding=(uid,key)=>({entityUid:uid,entityRevision:'r1',componentKey:key,geometryQuality:'source_candidate'});
const model={bindings:[binding('near','CN'),binding('far','CT')]};
const detail={item:obj('child'),ancestors:{completeness:'complete',path:[{object:obj('near')},{object:obj('far')}]}};

test('child locates nearest recorded bound parent without replacing selected identity',()=>{
 const result=modelLocation(detail,model);
 assert.equal(result.binding.entityUid,'near');assert.equal(result.mode,'ancestor');assert.equal(detail.item.entityUid,'child');
});
test('definition and incomplete physical paths cannot borrow a cabinet',()=>{
 assert.equal(modelLocation({...detail,item:{...detail.item,installationContextId:null}},model),null);
 assert.equal(modelLocation({...detail,ancestors:{...detail.ancestors,completeness:'incomplete'}},model),null);
});
test('merged identity and changed binding revision never highlight stale geometry',()=>{
 assert.equal(modelLocation({...detail,item:{...detail.item,lifecycle:'merged'}},model),null);
 assert.equal(modelLocation({item:obj('near','r2'),ancestors:{completeness:'complete',path:[]}},model),null);
 assert.equal(modelLocation({...detail,ancestors:{completeness:'complete',path:[{object:obj('near','r2')}]}},model),null);
});
test('direct cabinet match uses exact UID and revision',()=>{
 assert.equal(modelLocation({item:obj('near'),ancestors:{path:[]}},model).mode,'direct');
 assert.equal(modelLocation({item:obj('NEAR'),ancestors:{path:[]}},model),null);
});
test('a stale nearest host never silently jumps to a farther cabinet',()=>{
 const changed={...detail,ancestors:{...detail.ancestors,path:[{object:obj('near','r2')},{object:obj('far')}]}};
 assert.equal(modelLocation(changed,model),null);assert.equal(bindingNeedsReview(changed,model),true);
 assert.equal(modelLocation(detail,{...model,bindings:[binding('far','CT')],bindingWarnings:[{entityUid:'near',code:'MODEL_BINDING_CHANGED'}]}),null);
});
test('review indicators concern the selected object and its own physical ancestors',()=>{
 assert.equal(bindingNeedsReview(detail,{...model,bindingWarnings:[{entityUid:'unrelated'}]}),false);
 assert.equal(bindingNeedsReview(detail,{...model,bindingWarnings:[{entityUid:'near'}]}),true);
 assert.equal(modelLocation({...detail,ancestors:{...detail.ancestors,path:[{object:{...obj('near'),lifecycle:'merged'}},{object:obj('far')}]}},model),null);
});
test('locale resources cover the same business states and preserve interpolation',()=>{
 assert.deepEqual(Object.keys(messages.zh).sort(),Object.keys(messages.en).sort());
 assert.equal(translate('en','loadedCount',{number:51}),'51 objects loaded');
 assert.equal(translate('zh','page',{number:6}),'第 6 页');
});
