import assert from 'node:assert/strict';
import test from 'node:test';
import {photoBoxes,photoFocusZoom,photoFocusScroll,photoBaseSize,photoWheelZoom,photoZoomScroll,clampPhotoZoom,MAX_PHOTO_ZOOM} from '../src/workOrderPhoto.ts';
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
test('photos fit both viewport axes and use OntoBase focus and zoom bounds',()=>{
  const box={x:.4,y:.85,width:.025,height:.004};
  const base=photoBaseSize(900,560,2400,12000);
  assert.deepEqual(base,{width:105.6,height:528});
  const zoom=photoFocusZoom(box,900,560,2400,12000);
  assert.equal(zoom,16);
  const scroll=photoFocusScroll(box,base.width*zoom,base.height*zoom,900,560);
  assert.ok(Math.abs(16+(box.x+box.width/2)*base.width*zoom-scroll.left-450)<1e-8);
  assert.ok(Math.abs(16+(box.y+box.height/2)*base.height*zoom-scroll.top-280)<1e-8);
  assert.equal(photoFocusZoom(undefined,900,560,0,0),1);
  assert.equal(photoFocusZoom({x:0,y:0,width:1,height:1},900,560,100,100),.5);
  assert.equal(clampPhotoZoom(0),.5);assert.equal(clampPhotoZoom(100),MAX_PHOTO_ZOOM);
});
test('wheel zoom is continuous, normalized by event mode and anchored on the image',()=>{
  assert.equal(photoWheelZoom(2,100,0,560),1.8097);
  assert.equal(photoWheelZoom(2,1,1,560),photoWheelZoom(2,16,0,560));
  assert.equal(photoWheelZoom(2,1,2,560),photoWheelZoom(2,560,0,560));
  assert.equal(photoWheelZoom(16,-500,0,560),16);
  assert.equal(photoWheelZoom(.5,500,0,560),.5);
  const target=photoZoomScroll(2,2.6,528,528,900,560,300,400,250,180);
  assert.ok(Math.abs((300+250-16)/2-(target.left+250-16)/2.6)<1e-8);
  assert.ok(Math.abs((400+180-16)/2-(target.top+180-16)/2.6)<1e-8);
  assert.deepEqual(photoZoomScroll(2,1,105.6,528,900,560,0,264,450,280),{left:0,top:0});
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
