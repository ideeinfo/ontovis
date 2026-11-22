async (page, facts, phase) => {
  const button=(name,within=page)=>within.getByRole('button',{name,exact:true});
  const check=(condition,message)=>{if(!condition)throw Error(message);};
  const root='/api/workbench/imagery', chunks=root+'/uploads/chunk', complete=root+'/uploads/complete';
  const chunkSize=facts.chunkBytes;
  const responses=[], attempts=[];
  const stopAt=phase==='disconnect'?chunkSize:phase==='refresh'?chunkSize*2:null;
  const pattern='**'+chunks;
  const dialog=page.getByRole('dialog',{name:'导入影像',exact:true});
  const unfinished=page.getByRole('region',{name:'未完成的上传',exact:true});
  const file=dialog.getByLabel('选择GeoTIFF',{exact:true});
  const catalogue=()=>call(root,{});

  await page.setViewportSize({width:1460,height:920});
  const [bootstrap]=await Promise.all([
    page.waitForResponse(response=>response.url()===facts.origin+'/api/session'&&response.request().method()==='GET'),
    page.goto(facts.origin+'/')
  ]);
  const session=await bootstrap.json();
  if(phase==='restart')check(session.state!=='active','The old process session remained active after restart');
  if(session.state!=='active'){
    await button('登录').click();
    const signIn=page.getByRole('dialog',{name:'登录 ONTOVis'});
    await signIn.getByLabel('用户名').fill('writer');
    await signIn.getByLabel('密码').fill('synthetic-fixture');
    const [login]=await Promise.all([
      page.waitForResponse(response=>response.url()===facts.origin+'/api/session/login'),
      button('登录',signIn).click()
    ]);
    check(login.ok()&&(await login.json()).state==='active','Imagery fixture sign-in failed with HTTP '+login.status());
  }
  await page.getByRole('button',{name:new RegExp('^'+facts.projectTitle+' ')}).click();
  await button('进入项目').click();
  await button('场景与可视化').click();
  await button('打开 '+facts.title).click();
  await button('布置').click();
  await page.getByRole('tab',{name:'模型资源',exact:true}).click();
  await page.getByRole('tab',{name:'影像',exact:true}).click();
  await button('导入影像').waitFor();
  const before=await catalogue();
  if(phase==='disconnect')check(before.items.length===1&&before.uploads.length===0,'The upload fixture is not clean');
  else{
    const previousBytes=phase==='refresh'?chunkSize:2*chunkSize;
    check(before.uploads.length===1&&before.uploads[0].uploadId===facts.uploadId&&
      before.uploads[0].receivedBytes===previousBytes,'The confirmed prefix changed after reloading');
    await button('继续上传',unfinished).click();
    check(Number(await dialog.getByRole('progressbar').getAttribute('value'))===previousBytes,'The resume form showed an incorrect offset');
  }
  if(phase==='disconnect'){
    await button('导入影像').click();
    await file.setInputFiles(facts.file);
    for(const [label,value] of Object.entries({'名称':facts.uploadTitle,'来源':'隔离合成资源','许可依据':'测试生成',
      '署名':'ONTOVis QA','质量说明':'合成像素用于验证续传'})){
      await dialog.getByRole('textbox',{name:label,exact:true}).fill(value);
    }
    await dialog.getByLabel('采集日期',{exact:true}).fill('2026-11-22');
    await dialog.getByRole('checkbox').check();
  }
  await page.route(pattern,async route=>{
    const header=route.request().headers()['x-imagery-chunk'];
    const data=JSON.parse(Buffer.from(header,'base64').toString('utf8'));
    attempts.push({uploadId:data.uploadId,offset:data.offset});
    if(data.offset===stopAt){
      await page.context().setOffline(true);
      await route.abort('internetdisconnected');
    }else await route.continue();
  });
  const onResponse=response=>{
    if(new URL(response.url()).pathname===chunks&&response.ok())responses.push(response);
  };
  page.on('response',onResponse);
  try{
    if(phase==='refresh'){
      await file.setInputFiles(facts.wrongFile);
      await button('继续上传',dialog).click();
      await dialog.getByRole('alert').getByText(/选择原文件/).waitFor();
      check(attempts.length===0,'A different file was sent for the original upload');
    }
    if(phase!=='disconnect')await file.setInputFiles(facts.file);
    if(stopAt!==null){
      await button(phase==='disconnect'?'导入并校验':'继续上传',dialog).click();
      await dialog.getByRole('alert').waitFor({timeout:30000});
      await page.context().setOffline(false);
      const interrupted=await catalogue(), row=interrupted.uploads[0];
      check(interrupted.items.length===1&&interrupted.uploads.length===1&&row.receivedBytes===stopAt,
        'Interrupted upload was partially published or lost the confirmed prefix');
      check(responses.length===1&&(await responses[0].json()).receivedBytes===stopAt,
        'The browser did not receive the expected committed chunk');
      check(attempts.length===2&&attempts[0].offset===stopAt-chunkSize&&attempts[1].offset===stopAt&&
        attempts.every(item=>item.uploadId===row.uploadId),'The resumed browser did not send the expected offsets');
      await dialog.screenshot({path:'imagery-'+phase+'.png'});
      return {uploadId:row.uploadId,receivedBytes:row.receivedBytes,wrongFileRejected:phase==='refresh',offsets:attempts.map(item=>item.offset)};
    }

    const [reply]=await Promise.all([
      page.waitForResponse(response=>new URL(response.url()).pathname===complete,{timeout:60000}),
      button('继续上传',dialog).click()
    ]);
    check(reply.ok(),'Resume did not complete successfully');
    const published=await reply.json();
    check(published.state==='completed'&&published.sha256===facts.sourceSha256,'Published GeoTIFF fingerprint differs');
    await dialog.waitFor({state:'hidden'});
    check(attempts.length===2&&attempts[0].offset===2*chunkSize&&attempts[1].offset===3*chunkSize&&
      attempts.every(item=>item.uploadId===facts.uploadId),'The restarted service did not resume at the committed offset');
    const {uploadId,expectedUploadRevision}=reply.request().postDataJSON();
    const repeated=await call(complete,{uploadId,expectedUploadRevision});
    check(repeated.imageryVersionId===published.imageryVersionId,'Repeating completion created another version');
    const final=await catalogue();
    check(final.uploads.length===0&&final.items.length===2&&
      final.items.filter(item=>item.imageryVersionId===published.imageryVersionId).length===1,'Final version count was incorrect');

    const scene=await call('/api/workbench/scenes/open',{sceneId:facts.sceneId,sceneRevision:facts.pinnedRevision});
    const latest=await call('/api/workbench/scenes/open',{sceneId:facts.sceneId});
    check(scene.sceneRevision===facts.pinnedRevision&&latest.sceneRevision===facts.headRevision&&!latest.snapshot.imagery&&
      Object.entries(facts.reference).every(([key,value])=>scene.snapshot.imagery[key]===value),
      'An existing scene revision or pinned imagery reference changed');
    const historical=await call(root+'/version',{imageryVersionId:facts.historical.imageryVersionId});
    check(Object.entries(facts.historical).every(([key,value])=>historical[key]===value),'Historical imagery metadata changed');
    await readTexture(historical,facts.textureSha256);
    await readTexture(published,published.texture.sha256);
    await page.screenshot({path:'imagery-after-restart.png'});
    return {uploadId,imageryVersionId:published.imageryVersionId,sourceSha256:published.sha256,
      fullBytes:facts.bytes,pinnedRevision:scene.sceneRevision,headRevision:latest.sceneRevision,
      historicalTextureSha256:facts.textureSha256,idempotent:true,offsets:attempts.map(item=>item.offset)};
  }finally{
    await page.context().setOffline(false);
    await page.unroute(pattern);
    page.off('response',onResponse);
  }

  async function request(path, payload){
    const active=await (await page.request.get(facts.origin+'/api/session')).json();
    const response=await page.request.post(facts.origin+path,{headers:{Origin:facts.origin},data:{...payload,
      expectedSessionRevision:active.sessionRevision,projectRef:{ontobaseConnectionId:'ontobase-primary',projectCode:facts.projectCode}}});
    check(response.ok(),path+' returned HTTP '+response.status());
    return response;
  }
  async function call(path,payload){return (await request(path,payload)).json();}
  async function readTexture(image,expected){
    const response=await request(root+'/content',{imageryVersionId:image.imageryVersionId,
      expectedContentRevision:image.contentRevision,expectedSha256:expected});
    const sha=await page.evaluate(async bytes=>Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',Uint8Array.from(bytes))))
      .map(n=>n.toString(16).padStart(2,'0')).join(''),Array.from(await response.body()));
    check(sha===expected&&response.headers()['x-content-sha256']===expected,'A private imagery texture changed');
  }
}
