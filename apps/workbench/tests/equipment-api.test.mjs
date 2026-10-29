import assert from 'node:assert/strict';
import test from 'node:test';
import {WorkbenchApi} from '../src/api.ts';
import {EquipmentApi} from '../src/equipmentApi.ts';

const selection={entityUid:'shared-sensor',expectedEntityRevision:'entity:4',installationContextId:null,
  expectedHierarchyRevision:null,photoPurpose:'object_location'};
const photo={evidenceRef:'photo:fixture',sourceRevision:'a'.repeat(64),contentVersionId:'fixed-photo',
  sourceSha256:'b'.repeat(64),selector:{displayRevision:'c'.repeat(64)}};
const project={ontobaseConnectionId:'fixture-source',projectCode:'fixture-project'};

test('equipment photos accept JPEG previews and PNG originals with the fixed reference and project scope',async()=>{
  for(const [full,mime] of [[false,'image/jpeg'],[false,'image/webp'],[true,'image/png']]){
    let sent;
    const api=new WorkbenchApi(async(path,options)=>{sent={path,body:JSON.parse(options.body)};
      return new Response('synthetic-image',{headers:{'Content-Type':mime,'X-Session-Revision':'session:1'}});});
    api.session('session:1');api.selectProject(project);
    const blob=await new EquipmentApi(api).photoContent(selection,photo,full);
    assert.equal(blob.type,mime);assert.equal(await blob.text(),'synthetic-image');
    assert.equal(sent.path,'/api/workbench/objects/photos/content');
    assert.deepEqual(sent.body,{...selection,evidenceRef:photo.evidenceRef,expectedSourceRevision:photo.sourceRevision,
      expectedContentVersionId:photo.contentVersionId,expectedSourceSha256:photo.sourceSha256,
      expectedDisplayRevision:photo.selector.displayRevision,representation:full?'display':'preview',
      projectRef:project,expectedSessionRevision:'session:1'});
  }
});

test('a late equipment photo is discarded after project selection changes',async()=>{
  let finish;
  const api=new WorkbenchApi(()=>new Promise(resolve=>{finish=resolve;}));api.session('session:1');api.selectProject(project);
  const pending=new EquipmentApi(api).photoContent(selection,photo);
  api.selectProject({...project,projectCode:'another-project'});
  finish(new Response('synthetic-image',{headers:{'Content-Type':'image/jpeg','X-Session-Revision':'session:1'}}));
  await assert.rejects(pending,{name:'AbortError'});
});

test('source application binding writes only its fixed reference and geometry mappings',async()=>{
  let sent;
  const api=new WorkbenchApi(async(path,options)=>{sent={path,body:JSON.parse(options.body)};return new Response('{}',{headers:{'Content-Type':'application/json','X-Session-Revision':'session:1'}});});
  api.session('session:1');api.selectProject(project);
  const projectApplicationRef={applicationId:'source-application',applicationRevisionId:'fixed-application',specificationRevisionId:'fixed-specification'};
  const models=[{modelVersionId:'fixed-model',mappings:[]}];
  await new EquipmentApi(api).save('binding','binding:1',{displayName:'Never write source names',objectKind:'pump',rootDefinition:null,projectApplicationRef,models});
  assert.equal(sent.path,'/api/workbench/equipment/configurations/save');assert.deepEqual(sent.body.snapshot,{projectApplicationRef,models});assert.deepEqual(sent.body.projectRef,project);
});

test('shared photo pages and renditions keep source identity and request limits',async()=>{
  const sent=[];
  const api=new WorkbenchApi(async(path,options)=>{sent.push({path,body:JSON.parse(options.body)});return new Response(path.endsWith('/content')?'image':'{}',{headers:{'Content-Type':path.endsWith('/content')?'image/jpeg':'application/json','X-Session-Revision':'session:1'}});});
  api.session('session:1');api.selectProject(project);
  const service=new EquipmentApi(api),{photoPurpose,...identity}=selection;
  const shared={documentId:'doc',contentVersionId:'version',renditionId:'display',displayRevision:'digest'};
  await service.sharedPhotos(identity);await service.sharedRegions(identity,shared);await service.sharedContent(identity,shared,'thumbnail');
  assert.equal(sent[0].body.limit,12);assert.equal(sent[1].body.limit,50);assert.equal(sent[2].body.representation,'thumbnail');assert.equal(sent[2].body.expectedDisplayRevision,'digest');assert.equal(sent[2].body.contentVersionId,'version');
  assert.ok(sent.every(call=>call.body.entityUid===identity.entityUid&&call.body.projectRef.projectCode===project.projectCode));
});


test('fixed application reads accept independent models without retired configuration labels',async()=>{
  const fixed={applicationId:'application',revisionId:'application:r2',specificationRevisionId:'specification:r1'};
  const summary={...fixed,revision:2,name:'Project engineering mapping',specificationName:'Independent geared model',equipmentCount:15};
  const bundle={application:{...fixed,headRevisionId:'application:r3',snapshot:{name:summary.name,specificationRevisionId:fixed.specificationRevisionId,mappings:[]}},specification:{revisionId:fixed.specificationRevisionId,snapshot:{name:summary.specificationName}}};
  const requests=[];
  const api=new WorkbenchApi(async(path,options)=>{requests.push({path,body:JSON.parse(options.body)});return new Response(JSON.stringify(path.endsWith('/detail')?bundle:{items:[summary],total:1,offset:0,limit:50}),{headers:{'Content-Type':'application/json','X-Session-Revision':'session:1'}});});
  api.session('session:1');api.selectProject(project);
  const service=new EquipmentApi(api);
  assert.deepEqual((await service.applications()).items,[summary]);
  assert.deepEqual(await service.application(fixed.revisionId),bundle);
  assert.equal(requests[1].body.applicationRevisionId,fixed.revisionId);
  assert.deepEqual(requests[1].body.projectRef,project);
  assert.equal(bundle.application.snapshot.specificationRevisionId,'specification:r1');
  assert.notEqual(bundle.application.revisionId,bundle.application.headRevisionId);
});

test('material catalogues use explicit bounded read routes and current device context',async()=>{
  const sent=[];
  const api=new WorkbenchApi(async(path,options)=>{sent.push({path,body:JSON.parse(options.body)});return new Response('{}',{headers:{'Content-Type':'application/json','X-Session-Revision':'session:1'}});});
  api.session('session:1');api.selectProject(project);const service=new EquipmentApi(api);
  const identity={entityUid:'device',expectedEntityRevision:'entity:7',installationContextId:'context',expectedHierarchyRevision:'tree:3'};
  await service.modelMaterials('model','role:CN2','photo','opaque:page');
  await service.materialCandidates('model',4,'model','needle','pdf');
  await service.deviceMaterials(identity,'next');await service.attributeForm('device');
  assert.equal(sent[0].path,'/api/workbench/equipment/materials/models');
  assert.deepEqual({...sent[0].body,projectRef:undefined,expectedSessionRevision:undefined},{specificationId:'model',scope:'role:CN2',kind:'photo',cursor:'opaque:page',limit:20,projectRef:undefined,expectedSessionRevision:undefined});
  assert.equal(sent[1].body.revision,4);assert.equal(sent[1].body.q,'needle');
  assert.equal(sent[2].path,'/api/workbench/equipment/materials/resolve');
  for(const [key,value] of Object.entries(identity))assert.equal(sent[2].body[key],value);
  assert.equal(sent[3].path,'/api/workbench/equipment/attribute-form');
  assert.deepEqual(Object.keys(sent[3].body).sort(),['entityUid','expectedSessionRevision','projectRef']);
  assert.ok(sent.every(call=>call.body.projectRef.projectCode===project.projectCode));
});

test('fixed document bytes retain content version and hash for every PDF page or photo MIME',async()=>{
  const fixed={documentId:'doc',contentVersionId:'fixed-version',sourceSha256:'a'.repeat(64)};
  for(const mime of ['image/png','image/jpeg','image/webp']){
    let sent;const api=new WorkbenchApi(async(path,options)=>{sent={path,body:JSON.parse(options.body)};return new Response('image',{headers:{'Content-Type':mime,'X-Session-Revision':'session:1'}});});
    api.session('session:1');api.selectProject(project);
    assert.equal((await new EquipmentApi(api).materialContent(fixed,3)).type,mime);
    assert.equal(sent.path,'/api/workbench/equipment/materials/content');
    assert.equal(sent.body.contentVersionId,'fixed-version');assert.equal(sent.body.pageNumber,3);
    assert.equal(sent.body.sourceSha256,fixed.sourceSha256);assert.equal(sent.body.renditionId,undefined);
  }
});

test('material responses are discarded after cancellation, project switch, logout or access revision change',async()=>{
  for(const action of ['cancel','project','logout','revision']){
    let finish;const api=new WorkbenchApi(()=>new Promise(resolve=>{finish=resolve;}));api.session('session:1');api.selectProject(project);
    const abort=new AbortController(),pending=new EquipmentApi(api).deviceMaterials({entityUid:'device'},null,abort.signal);
    if(action==='cancel')abort.abort();else if(action==='project')api.selectProject({...project,projectCode:'elsewhere'});else api.session(action==='logout'?null:'session:2');
    finish(new Response('{}',{headers:{'Content-Type':'application/json','X-Session-Revision':'session:1'}}));
    await assert.rejects(pending,{name:'AbortError'});
  }
});

test('material error responses preserve source conflict and authorization status',async()=>{
  for(const [status,code] of [[401,'SESSION_EXPIRED'],[403,'FORBIDDEN'],[409,'SOURCE_CHANGED']]){
    const api=new WorkbenchApi(async()=>new Response(JSON.stringify({code}),{status,headers:{'Content-Type':'application/json'}}));api.session('session:1');api.selectProject(project);
    await assert.rejects(new EquipmentApi(api).modelMaterials('model'),error=>error.status===status&&error.code===code);
  }
});
