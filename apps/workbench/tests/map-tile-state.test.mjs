import assert from 'node:assert/strict';
import test from 'node:test';
import {tileLoadResult,visibleTileFailures} from '../src/mapTileState.ts';
import {mapPixel} from '../src/publicGeoApi.ts';

const url=(z,x,y)=>`https://tile.openstreetmap.org/${z}/${x}/${y}.png`;
function visible(longitude,latitude,width=400,zoom=6){
 const [cx,cy]=mapPixel(longitude,latitude,zoom),urls=new Set();
 for(let y=Math.floor((cy-115)/256);y<=Math.floor((cy+115)/256);y++)for(let x=Math.floor((cx-width/2)/256);x<=Math.floor((cx+width/2)/256);x++)urls.add(url(zoom,x,y));
 return urls;
}
test('a coordinate edit within the same visible tile URLs retains the existing failed tile',()=>{
 const before=visible(113.18,33.45),after=visible(113.18001,33.45001);
 assert.deepEqual(after,before,'the regression must reuse the already-failed image nodes');
 const failedUrl=[...before][0],failed=tileLoadResult(new Set(),before,failedUrl,false);
 const next=visibleTileFailures(failed,after);
 assert.equal(next.has(failedUrl),true);
 assert.equal(next,failed,'a camera coordinate change cannot substitute for an image load');
});
test('a changed visible set removes only failures whose resource URLs left the viewport',()=>{
 const west=url(6,50,25),middle=url(6,51,25),east=url(6,52,25);
 const failures=new Set([west,middle]),moved=visibleTileFailures(failures,new Set([middle,east]));
 assert.deepEqual([...moved],[middle]);assert.deepEqual([...failures],[west,middle]);
 assert.equal(visibleTileFailures(moved,new Set([middle,east])),moved);
});
test('a real successful load clears only that URL and a later error can report it again',()=>{
 const a=url(6,51,25),b=url(6,51,26),viewport=new Set([a,b]);
 let failures=new Set([a,b]);
 const loaded=tileLoadResult(failures,viewport,a,true);
 assert.deepEqual([...loaded],[b]);assert.deepEqual([...failures],[a,b]);
 assert.equal(tileLoadResult(loaded,viewport,a,true),loaded,'repeated loads keep the same state');
 const failedAgain=tileLoadResult(loaded,viewport,a,false);
 assert.deepEqual(new Set(failedAgain),new Set([a,b]));
 assert.equal(tileLoadResult(failedAgain,viewport,a,false),failedAgain,'duplicate errors do not create updates');
});
test('late events for a removed tile never introduce a stale map failure',()=>{
 const old=url(6,51,25),current=url(7,102,50),viewport=new Set([current]),empty=new Set();
 assert.equal(tileLoadResult(empty,viewport,old,false),empty);
 const failed=new Set([current]);assert.equal(tileLoadResult(failed,viewport,old,true),failed);
});
