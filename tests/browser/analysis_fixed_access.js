async (page, facts, phase) => {
  const root = '/api/workbench/analysis-sessions/evidence/';
  const button = (name,within=page) => within.getByRole('button',{name,exact:true});
  const check = (condition,message) => { if (!condition) throw Error(message); };
  const change = async action => {
    const response = await page.request.post(facts.origin+'/test-evidence/'+action);
    check(response.ok(),'The isolation control failed');
    await page.evaluate(()=>document.dispatchEvent(new Event('visibilitychange')));
  };
  const wait = async (promise,message) => {
    let timer;
    try {
      return await Promise.race([promise,new Promise((_,reject)=>{timer=setTimeout(()=>reject(Error(message)),20000);})]);
    } finally {clearTimeout(timer);}
  };
  const hold = async (suffix,ref) => {
    let deliver, took, completed;
    const captured = new Promise(resolve=>{took=resolve;});
    const done = new Promise(resolve=>{completed=resolve;});
    const release = new Promise(resolve=>{deliver=resolve;});
    const matches = url=>url.pathname===root+suffix;
    const handler = async route => {
      if(route.request().postDataJSON()?.evidenceRefId!==ref)return route.continue();
      const response = await route.fetch({maxRetries:0});
      took(response.status());
      await release;
      // The browser can cancel the held transfer as soon as authorization changes.
      try{await route.fulfill({response});}catch(error){
        if(!/aborted|intercept|cancell|not found|closed|route is already handled/i.test(String(error)))throw error;
      }finally{completed();}
    };
    await page.route(matches,handler);
    return {captured:()=>wait(captured,'Protected request was not intercepted'),
      done:()=>wait(done,'Held response did not finish'),deliver,async close(){deliver();await page.unroute(matches,handler);}};
  };
  const title = facts.title;
  await page.setViewportSize({width:1500,height:956});
  await page.goto(facts.origin+'/');
  await button('登录').click();
  const login = page.getByRole('dialog',{name:'登录 ONTOVis',exact:true});
  await login.getByLabel('用户名').fill('writer');
  await login.getByLabel('密码').fill('synthetic-only');
  await button('登录',login).click();
  await page.getByRole('button',{name:/^Q-26 固定资料试验 Demo-PDS/}).click();
  await button('进入项目').click();
  const cockpit = phase==='expire-session'||phase==='withdraw-project';
  let canvas;
  if(cockpit){
    await button('驾驶舱').click();
    const view=page.getByRole('region',{name:'项目驾驶舱'});
    await button('分析工作台',view).click();
    canvas = view.getByRole('region',{name:'故障分析展示'});
    await canvas.getByLabel('当前故障',{exact:true}).selectOption(JSON.stringify([facts.datasetId,facts.datasetRevision]));
    await canvas.getByLabel('推荐分析画布',{exact:true}).selectOption(facts.analysisId);
    await canvas.locator('.pa-canvas-caption').getByText(title,{exact:true}).waitFor();
    await button('适应全部资料',canvas).click();
  }else{
    await button('分析画布').click();
    canvas = page.getByRole('region',{name:'分析工作空间'});
    await canvas.locator('.ad-list-items .ov-list-main').filter({hasText:title}).click();
    await button('适应全部',canvas).click();
  }
  const kind = phase==='withdraw-document'?'document':phase==='expire-session'?'work_order':'drawing';
  const target=facts.cards[kind];
  const card=canvas.locator('[data-card-id="'+target.id+'"]');
  const open=button((cockpit?'放大查看：':'')+target.title,card);
  const dialog=page.getByRole('dialog',{name:target.title,exact:true});
  if(cockpit) await open.focus();

  if(phase==='switch-project'){
    const held=await hold('content',target.ref);
    try{
      await open.click();
      await dialog.waitFor();
      check(await held.captured()===200,'Expected a genuine protected drawing response before switching');
      await button('关闭',dialog).click();
      await button('项目中心').click();
      await page.getByRole('button',{name:/^Q-26 另一项目 B/}).click();
      await button('进入项目').click();
      await page.getByRole('heading',{name:'场景与可视化',exact:true}).waitFor();
      held.deliver();
      await held.done();
      check(await dialog.count()===0&&await page.locator('.ac-evidence-viewer').count()===0,
        'A drawing returned to a different project');
      return {switched:true,lateDrawingDiscarded:true};
    }finally{await held.close();}
  }
  await open.click();
  await dialog.waitFor();
  if(phase==='withdraw-document'){
    const img=dialog.locator('img').first();
    await img.waitFor({timeout:20000});
    const oldUrl=await img.evaluate(node=>node.currentSrc);
    const held=await hold('preview-content',target.ref);
    try{
      await dialog.getByRole('spinbutton',{name:'文档页码'}).fill('3');
      check(await held.captured()===200,'Expected a genuine protected page before revocation');
      await change(phase);
      const restricted = page.getByRole('dialog',{name:'资料访问已撤销',exact:true});
      await restricted.getByRole('status').getByText('资料访问已撤销',{exact:true}).waitFor();
      held.deliver();
      await held.done();
      check(await restricted.locator('.ac-evidence-viewer').count()===0&&await restricted.locator('img').count()===0,
        'The revoked preview still has content');
      const revoked = await page.evaluate(async url=>{try{await fetch(url);return false;}catch{return true;}},oldUrl);
      check(revoked,'The former image can still be accessed from the workspace cache');
      await restricted.screenshot({path:'isolated-13001-document-revoked.png'});
      return {revoked:true,oldImageRevoked:true,latePageDiscarded:true};
    }finally{await held.close();}
  }
  if(phase==='expire-session'){
    await dialog.getByText(facts.record,{exact:true}).waitFor();
    await change(phase);
    await button('登录').waitFor();
    check(await dialog.count()===0&&await page.getByText(facts.record,{exact:true}).count()===0,
      'Expired session kept fixed order content');
    return {expired:true,orderContentCleared:true};
  }
  if(phase==='withdraw-project'){
    await dialog.locator('img').first().waitFor();
    const rejected=page.waitForResponse(response=>new URL(response.url()).pathname===root+'batch'&&response.status()===403);
    await change(phase);
    await rejected;
    await page.getByRole('heading',{name:'项目中心',exact:true}).waitFor();
    check(await dialog.count()===0&&await page.locator('.ac-evidence-viewer').count()===0,
      'Revoked project kept the cockpit evidence visible');
    return {projectDenied:403,cockpitContentCleared:true};
  }
  throw Error('Unknown evidence access phase');
}
