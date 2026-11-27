import test from 'node:test';
import assert from 'node:assert/strict';
import {adjustAssistantWindow,assistantWindowKeyDelta,fitAssistantWindow} from '../src/assistantWindowGeometry.ts';

test('both resize corners retain their opposite corner within the viewport',()=>{
 const area={x:80,y:50,width:880,height:640},box={x:200,y:180,width:360,height:400};
 assert.deepEqual(adjustAssistantWindow(box,area,'left',-300,400),{x:80,y:180,width:480,height:510});
 assert.deepEqual(adjustAssistantWindow(box,area,'right',800,-200),{x:200,y:180,width:760,height:340});
});

test('an area below the minimum window size keeps every edge visible',()=>{
 const area={x:80,y:120,width:254,height:286},box={x:180,y:320,width:360,height:400};
 assert.deepEqual(fitAssistantWindow(box,area),area);
 assert.deepEqual(adjustAssistantWindow(box,area,'left',50,-50),area);
});

test('resize keys use the same increments on both assistants',()=>{
 assert.deepEqual(assistantWindowKeyDelta('ArrowLeft',false),[-12,0]);
 assert.deepEqual(assistantWindowKeyDelta('ArrowDown',true),[0,40]);
 assert.equal(assistantWindowKeyDelta('Enter',false),undefined);
});
