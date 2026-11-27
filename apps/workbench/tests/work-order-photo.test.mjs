import assert from 'node:assert/strict';
import test from 'node:test';
import {photoBoxes,photoFocusZoom,photoFocusScroll,photoBaseSize,photoFitZoom,photoRestoreZoom,photoWheelZoom,photoZoomScroll,clampPhotoZoom,MAX_PHOTO_ZOOM,MIN_PHOTO_ZOOM} from '../src/workOrderPhoto.ts';
import {WorkbenchApi} from '../src/api.ts';

const analysisPhotoPath = '/api/workbench/analysis-sessions/evidence/content';
const mediaPhotoPath = 'https://vis-media.ontobase.ai/v1/fixed-photo';
const nativePhotoBody = {representation:'full_resolution', analysisSessionId:'fixture', evidenceRefId:'fixed'};
const photoBytes = () => new Response('fixed', {headers:{'Content-Type':'image/jpeg','X-Session-Revision':'r1',
  'X-Content-SHA256':'a'.repeat(64),'X-Fixed-Photo-SHA256':'b'.repeat(64)}});
const jsonReply = (value,status=200) => new Response(JSON.stringify(value), {status,headers:{'Content-Type':'application/json'}});

test('prefetched fixed photo uses only an opaque, credential-free POST to the media host',async()=>{
  const ticket = 'u'.repeat(43), signal = new AbortController().signal;
  const api = new WorkbenchApi(async(path,init)=>{
    assert.equal(path,mediaPhotoPath);
    assert.equal(init.body,ticket);
    assert.equal(init.credentials,'omit');
    assert.equal(init.redirect,'error');
    assert.equal(init.referrerPolicy,'no-referrer');
    assert.equal(init.signal,signal);
    return photoBytes();
  });
  api.session('r1');
  assert.equal(await (await api.analysisPhoto(analysisPhotoPath,nativePhotoBody,signal,ticket)).text(),'fixed');
});

test('expired photo grant is renewed and an unavailable media host falls back to existing data access',async()=>{
  const first='f'.repeat(43), next='n'.repeat(43), calls=[];
  const api=new WorkbenchApi(async(path,init)=>{
    calls.push(path);
    if(path===mediaPhotoPath) return init.body===first?jsonReply({code:'PHOTO_TICKET_EXPIRED'},410):jsonReply({},503);
    if(init.headers['X-Vis-Photo-Read'])return jsonReply({photoTicket:next,sessionRevision:'r1'});
    return photoBytes();
  });
  api.session('r1');
  const img=await api.analysisPhoto(analysisPhotoPath,nativePhotoBody,new AbortController().signal,first);
  assert.equal(await img.text(),'fixed');
  assert.deepEqual(calls,[mediaPhotoPath,analysisPhotoPath,mediaPhotoPath,analysisPhotoPath]);
});

test('photo grant revocation and user cancellation never retry the protected read',async()=>{
  for(const cancel of [false,true]){
    const control=new AbortController();
    let calls=0;
    const api=new WorkbenchApi(async(path)=>{
      calls++;
      assert.equal(path,mediaPhotoPath);
      if(cancel){control.abort();throw new TypeError('cancelled');}
      return jsonReply({code:'SESSION_EXPIRED'},401);
    });
    api.session('r1');
    await assert.rejects(api.analysisPhoto(analysisPhotoPath,nativePhotoBody,control.signal,'t'.repeat(43)),
      error=>cancel?error.name==='AbortError':error.status===401);
    assert.equal(calls,1);
  }
});

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
test('photos fit both viewport axes while annotation focus uses actual image pixels',()=>{
  const box={x:.4,y:.85,width:.025,height:.004};
  const base=photoBaseSize(900,560,2400,12000);
  assert.deepEqual(base,{width:105.6,height:528});
  const zoom=photoFocusZoom(box,900,560,2400,12000);
  assert.equal(zoom,1.05);
  const scroll=photoFocusScroll(box,2400*zoom,12000*zoom,900,560);
  assert.ok(Math.abs(16+(box.x+box.width/2)*2400*zoom-scroll.left-450)<1e-8);
  assert.ok(Math.abs(16+(box.y+box.height/2)*12000*zoom-scroll.top-280)<1e-8);
  assert.equal(photoFocusZoom(undefined,900,560,0,0),1);
  assert.equal(photoFocusZoom({x:0,y:0,width:1,height:1},900,560,100,100),.504);
  assert.equal(clampPhotoZoom(0),MIN_PHOTO_ZOOM);assert.equal(clampPhotoZoom(100),MAX_PHOTO_ZOOM);
});
test('preview and original fit below true 100% and legacy saved views retain their old meaning',()=>{
  const preview=photoFitZoom(1066,432,1962,4096),original=photoFitZoom(1066,432,5076,10599);
  assert.ok(Math.abs(preview*4096-400)<.01);assert.ok(Math.abs(original*10599-400)<.01);
  assert.ok(preview<.1&&original<.04);
  assert.equal(photoFitZoom(1066,432,100,100),1,'small images are not enlarged by Fit');
  assert.equal(photoRestoreZoom({zoom:1,zoomBasis:'pixels',centerX:.5,centerY:.5},1066,432,5076,10599),1);
  assert.ok(Math.abs(photoRestoreZoom({zoom:8,centerX:.5,centerY:.5},1066,432,5076,10599)*10599-3200)<.01);
  assert.equal(photoFocusZoom(undefined,1066,432,1962,4096),preview);
});
test('wheel zoom is continuous, normalized by event mode and anchored on the image',()=>{
  assert.equal(photoWheelZoom(2,100,0,560),1.809675);
  assert.equal(photoWheelZoom(2,1,1,560),photoWheelZoom(2,16,0,560));
  assert.equal(photoWheelZoom(2,1,2,560),photoWheelZoom(2,560,0,560));
  assert.equal(photoWheelZoom(16,-500,0,560),16);
  assert.equal(photoWheelZoom(MIN_PHOTO_ZOOM,500,0,560),MIN_PHOTO_ZOOM);
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
test('verified photo transport keeps headers and size checks without a second browser digest',async t=>{
  const bytes=new TextEncoder().encode('server-verified fixture');
  const sha=Buffer.from(await crypto.subtle.digest('SHA-256',bytes)).toString('hex');
  const original=crypto.subtle.digest;
  const digest=t.mock.method(crypto.subtle,'digest',(...args)=>original.apply(crypto.subtle,args));
  let headerSha=sha,length=String(bytes.length);
  const api=new WorkbenchApi(async()=>new Response(bytes,{headers:{'Content-Type':'image/jpeg','Content-Length':length,'X-Session-Revision':'r1','X-Content-SHA256':headerSha}}));
  api.session('r1');const descriptor={mime:['image/jpeg'],maxBytes:1024,sha256:sha};
  assert.equal((await api.content('/api/workbench/objects/photos/content',{},descriptor)).size,bytes.length);
  assert.equal(digest.mock.calls.length,0);
  await api.content('/another-protected-image',{},descriptor);
  assert.equal(digest.mock.calls.length,1);
  headerSha='a'.repeat(64);
  await assert.rejects(api.content('/api/workbench/objects/photos/content',{},descriptor),e=>e.code==='RESOURCE_CHANGED');
  headerSha=sha;length=String(bytes.length+1);
  await assert.rejects(api.content('/api/workbench/objects/photos/content',{},descriptor),e=>e.code==='SOURCE_UNAVAILABLE');
});

test('full-resolution delivery checks the fixed photo digest separately from the delivered bytes',async()=>{
  const bytes=new TextEncoder().encode('compressed fixture');
  const digest=Buffer.from(await crypto.subtle.digest('SHA-256',bytes)).toString('hex');
  const fixed='a'.repeat(64);
  let fixedHeader=fixed,contentHeader=digest;
  const api=new WorkbenchApi(async()=>new Response(bytes,{headers:{'Content-Type':'image/jpeg','X-Session-Revision':'r1',
    'X-Content-SHA256':contentHeader,'X-Fixed-Photo-SHA256':fixedHeader}}));
  api.session('r1');
  const path='/api/workbench/objects/photos/content';
  const descriptor={mime:['image/jpeg'],maxBytes:1024,sha256:fixed,fixedPhoto:true};
  assert.equal((await api.content(path,{},descriptor)).size,bytes.length);
  fixedHeader='b'.repeat(64);
  await assert.rejects(api.content(path,{},descriptor),e=>e.code==='RESOURCE_CHANGED');
  fixedHeader=fixed;contentHeader='unavailable';
  await assert.rejects(api.content(path,{},descriptor),e=>e.code==='RESOURCE_CHANGED');
});

test('AVIF is negotiated only for a full-resolution photo and a browser that can decode it',async()=>{
  const previousImage=globalThis.Image;
  let decodes=0;
  let returned='image/jpeg';
  const requests=[];
  const sha='a'.repeat(64);
  const api=new WorkbenchApi(async(_path,init)=>{
    requests.push(JSON.parse(init.body).representation);
    return new Response(new Uint8Array([1]),{headers:{'Content-Type':returned,'X-Session-Revision':'r1',
      'X-Content-SHA256':'b'.repeat(64),'X-Fixed-Photo-SHA256':sha}});
  });
  api.session('r1');
  const path='/api/workbench/objects/photos/content';
  const full={representation:'full_resolution'};
  const fixed={mime:['image/jpeg'],maxBytes:1024,sha256:sha,fixedPhoto:true};
  try{
    globalThis.Image=undefined;
    await api.content(path,full,fixed);
    globalThis.Image=class {
      naturalWidth=2;
      naturalHeight=2;
      async decode(){decodes++;}
    };
    returned='image/avif';
    assert.equal((await api.content(path,full,fixed)).type,'image/avif');
    assert.equal((await api.request(path,full,undefined,'source')).type,'image/avif');
    await assert.rejects(api.request(path,{representation:'preview'},undefined,'source'),e=>e.code==='SOURCE_UNAVAILABLE');
    returned='image/jpeg';
    await api.content(path,full,fixed);
    assert.equal(decodes,1);
    assert.deepEqual(requests,['full_resolution','full_resolution_avif','full_resolution_avif','preview','full_resolution_avif']);
  }finally{globalThis.Image=previousImage;}
});
