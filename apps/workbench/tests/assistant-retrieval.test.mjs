import assert from 'node:assert/strict';
import test from 'node:test';
import {assistantSourceAnchor,defaultAssistantEvidence} from '../src/assistantApi.ts';
const source={kind:'document',retrieval:{version:1,anchor:{nodeId:'fault-13002',pageNumber:49}}};
test('retrieved citations preserve a node and page within the original fixed document',()=>assert.deepEqual(assistantSourceAnchor(source),source.retrieval.anchor));
test('legacy and non-document sources do not acquire a document locator',()=>{
 assert.equal(assistantSourceAnchor({kind:'document'}),null);assert.equal(assistantSourceAnchor({...source,kind:'photo'}),null);
});
test('invalid or unknown retrieval locators cannot override original citation navigation',()=>{
 for(const anchor of [{nodeId:'',pageNumber:49},{nodeId:'x',pageNumber:0},{nodeId:'x',pageNumber:1.5}])assert.equal(assistantSourceAnchor({...source,retrieval:{...source.retrieval,anchor}}),null);
 assert.equal(assistantSourceAnchor({...source,retrieval:{...source.retrieval,version:2}}),null);
});

test('initial material selection covers distinct evidence types and leaves retrieval budget',()=>{
 const cards=['object','object','object','alarm','document','trend','work_order','drawing','photo'].map((kind,i)=>({id:String(i),kind,source:{id:String(i)},historical:false}));
 const selected=defaultAssistantEvidence(cards);assert.equal(selected.length,6);assert.ok(selected.includes('4'));assert.ok(selected.includes('3'));assert.ok(selected.includes('5'));assert.equal(new Set(selected).size,6);
});
