import assert from 'node:assert/strict';
import test from 'node:test';
import {photoBoxes,photoFocusZoom,photoFocusScroll,MAX_PHOTO_ZOOM} from '../src/workOrderPhoto.ts';
import {WorkbenchApi} from '../src/api.ts';

test('ordinary photo regions stay on the oriented display coordinate space',()=>{
  const bbox={x:.1,y:.2,width:.3,height:.4};
  assert.deepEqual(photoBoxes({kind:'image_bbox',coordinateSpace:'oriented_display_normalized',bbox}),[bbox]);
  assert.deepEqual(photoBoxes({kind:'image_bbox',coordinateSpace:'original',bbox}),[]);
  assert.deepEqual(photoBoxes({kind:'image_bbox',coordinateSpace:'oriented_display_normalized',bbox:{...bbox,width:1}}),[]);
  assert.deepEqual(photoBoxes(null),[]);
});
test('panorama regions split at the seam and preserve source pitch orientation',()=>{
  const selector={kind:'spherical_region',coordinateSpace:'spherical_degrees',sphericalRegion:{yaw_start_deg:170,yaw_span_deg:20,pitch_min_deg:-30,pitch_max_deg:30}};
  const boxes=photoBoxes(selector);
  assert.equal(boxes.length,2);assert.equal(boxes[0].x,350/360);assert.equal(boxes[1].x,0);
  assert.ok(Math.abs(boxes[0].width+boxes[1].width-20/360)<1e-12);
  assert.equal(boxes[0].y,1/3);assert.equal(boxes[0].height,1/3);
  assert.deepEqual(photoBoxes({...selector,sphericalRegion:{...selector.sphericalRegion,yaw_span_deg:361}}),[]);
});
test('small labels on long cabinet photos focus beyond the old three-times limit',()=>{
  const box={x:.4,y:.85,width:.025,height:.004};
  const zoom=photoFocusZoom(box,900,560,2400,12000);
  assert.ok(zoom>3&&zoom<=MAX_PHOTO_ZOOM);
  const width=900*zoom,height=width*5;
  const scroll=photoFocusScroll(box,width,height,900,560);
  assert.ok(Math.abs((box.x+box.width/2)*width-scroll.left-450)<1e-8);
  assert.ok(Math.abs((box.y+box.height/2)*height-scroll.top-280)<1e-8);
});
test('photo focus is bounded for whole-image, seam, and missing-size cases',()=>{
  assert.equal(photoFocusZoom(undefined,900,560,0,0),1);
  assert.equal(photoFocusZoom({x:0,y:0,width:1,height:1},900,560,100,100),1);
  const box={x:0,y:0,width:.0001,height:.0001};
  assert.equal(photoFocusZoom(box,900,560,100,10000),1);
  assert.deepEqual(photoFocusScroll(box,900,900,900,560),{left:0,top:0});
});
test('photo content accepts only bounded image types and a matching display digest',async()=>{
  const bytes=new TextEncoder().encode('synthetic fixed photo');const sha=Buffer.from(await crypto.subtle.digest('SHA-256',bytes)).toString('hex');
  let mime='image/jpeg';let calls=0;
  const api=new WorkbenchApi(async()=>{calls++;return new Response(bytes,{headers:{'Content-Type':mime,'X-Session-Revision':'r1','X-Content-SHA256':sha}});});
  api.session('r1');const descriptor={mime:['image/png','image/jpeg','image/webp'],maxBytes:1024,sha256:sha};
  assert.equal((await api.content('/api/workbench/objects/photos/content',{},descriptor)).type,'image/jpeg');
  mime='text/html';await assert.rejects(api.content('/api/workbench/objects/photos/content',{},descriptor),error=>error.code==='SOURCE_UNAVAILABLE');
  const before=calls;
  for(const invalid of [{...descriptor,mime:['text/html']},{...descriptor,mime:[]},{...descriptor,maxBytes:20*1024*1024+1}])await assert.rejects(api.content('/fixed-photo',{},invalid),error=>error.code==='INVALID_REQUEST');
  assert.equal(calls,before);
});
test('work-order write denial keeps project reads and the signed-in identity available',async()=>{
  const api=new WorkbenchApi(async()=>new Response(JSON.stringify({code:'WORK_ORDER_WRITE_FORBIDDEN'}),{status:403}));
  api.session('r1');api.selectProject({ontobaseConnectionId:'fixture',projectCode:'Demo-PDS'});
  let denied=0;api.onDenied=()=>denied++;api.onProjectDenied=()=>denied++;
  await assert.rejects(api.request('/api/workbench/work-orders/action',{}),error=>error.code==='WORK_ORDER_WRITE_FORBIDDEN');
  assert.equal(denied,0);
});
