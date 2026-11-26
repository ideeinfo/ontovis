async (page, facts, phase) => {
  const savePath = '/api/workbench/analysis-sessions/save';
  const workspace = page.getByRole('region',{name:'分析工作空间'});
  const title = workspace.getByRole('textbox',{name:'分析名称'});
  const button = (name, within=workspace) => within.getByRole('button',{name,exact:true});
  const check = (value,message) => { if (!value) throw Error(message); };
  const waitForSave = () => page.waitForResponse(response=>
    new URL(response.url()).pathname===savePath&&response.request().method()==='POST');
  const send = async label => {
    const pending = waitForSave();
    await button(label).click();
    const response = await pending;
    return {status:response.status(),body:await response.json(),request:response.request().postDataJSON()};
  };
  const status = text => workspace.getByRole('status').filter({hasText:text}).waitFor();
  const busyTitle = facts.title+' · 暂忙期间草稿';
  const lostTitle = facts.title+' · 回执丢失草稿';
  const conflictTitle = facts.title+' · 版本冲突草稿';
  if (phase==='open') {
    await page.setViewportSize({width:1440,height:960});
    await page.goto(facts.origin+'/');
    await button('登录',page).click();
    const login = page.getByRole('dialog',{name:'登录 ONTOVis',exact:true});
    await login.getByLabel('用户名').fill('writer');
    await login.getByLabel('密码').fill('synthetic-only');
    await button('登录',login).click();
    await page.getByRole('button',{name:/^Q-13 合成项目 Demo-PDS/}).click();
    await button('进入项目',page).click();
    const navigation = page.getByRole('navigation',{name:'项目管理'});
    const collapse = button('收起导航',navigation), expand = button('展开导航',navigation);
    const analysisItem = button('分析画布',navigation);
    check(await collapse.getAttribute('aria-expanded')==='true'&&await analysisItem.locator('span').isVisible(),
      'The workbench did not open with navigation labels visible');
    await collapse.click();
    check(await expand.getAttribute('aria-expanded')==='false'&&!(await analysisItem.locator('span').isVisible()),
      'The navigation did not fold when requested');
    await expand.click();
    check(await collapse.getAttribute('aria-expanded')==='true','The navigation did not reopen');
    await button('分析画布',page).click();
    await workspace.locator('.ad-list-items .ov-list-main').filter({hasText:facts.title}).click();
    check(await title.inputValue()===facts.title,'The isolated canvas was not opened');
    check(await button('保存当前视图').isDisabled(),'An unchanged canvas could be saved again');
    await button('放大画布').click();
    check(await button('保存当前视图').isEnabled(),'A viewport-only edit could not be saved');
    await title.fill(busyTitle);
    return {opened:true,navigationDefaultExpanded:true};
  }
  if (phase==='busy') {
    const response = await send('保存');
    check(response.status===503&&response.body.code==='ANALYSIS_BUSY','The save did not encounter real saturation');
    await status('保存繁忙，修改已保留');
    check(await title.inputValue()===busyTitle,'Busy save lost the draft');
    await page.screenshot({path:'isolated-analysis-save-busy.png'});
    return {status:response.status,originalRequest:response.request};
  }
  if (phase==='retry-busy') {
    const response = await send('重试保存');
    check(JSON.stringify(response.request)===JSON.stringify(facts.originalRequest),'Busy retry changed the original request');
    check(response.status===200&&response.body.analysisRevision===2,'Busy retry did not save revision 2');
    await workspace.locator('.ad-heading').getByText('已保存 · r2',{exact:true}).waitFor();
    return {revision:2,sameRequest:true,sha256:response.body.contentSha256};
  }
  if (phase==='disconnect') {
    await title.fill(lostTitle);
    const routePattern = '**'+savePath;
    let sent, committed, committedStatus;
    const hideReceipt = async route => {
      sent = route.request().postDataJSON();
      try {
        const reply = await route.fetch({maxRetries:0});
        committedStatus = reply.status();
        committed = await reply.json();
      } finally {
        await route.abort('failed');
      }
    };
    await page.route(routePattern,hideReceipt,{times:1});
    try {
      await button('保存').click();
      await status('保存结果尚未确认');
    } finally {
      await page.unroute(routePattern,hideReceipt);
    }
    check(committedStatus===200&&committed?.analysisRevision===3,'The server did not save before the lost response');
    check(await title.inputValue()===lostTitle,'Lost response discarded the draft');
    await page.screenshot({path:'isolated-analysis-save-unconfirmed.png'});
    return {revision:3,sha256:committed.contentSha256,originalRequest:sent};
  }
  if (phase==='retry-disconnect') {
    const response = await send('重试保存');
    check(JSON.stringify(response.request)===JSON.stringify(facts.originalRequest),'Disconnect retry changed the original request');
    check(response.status===200&&response.body.analysisRevision===3
      &&response.body.contentSha256===facts.committedSha,'The retry returned a different commit');
    await workspace.locator('.ad-heading').getByText('已保存 · r3',{exact:true}).waitFor();
    await title.fill(conflictTitle);
    return {revision:3,sameRequest:true,sameCommit:true};
  }
  if (phase==='conflict') {
    const response = await send('保存');
    check(response.status===409&&response.body.code==='ANALYSIS_CHANGED'
      &&response.request.expectedAnalysisRevision===3,'A stale write did not return the real revision conflict');
    await workspace.getByRole('alert').filter({hasText:'分析已有新修订'}).waitFor();
    check(await title.inputValue()===conflictTitle&&await title.isEnabled(),'The version conflict lost or locked the draft');
    check(await button('另存副本').isVisible()&&await button('重新读取').isVisible(),'Conflict recovery controls are missing');
    await page.screenshot({path:'isolated-analysis-save-conflict.png'});
    return {status:response.status,draftRetained:true};
  }
  throw Error('Unknown analysis save phase');
}
