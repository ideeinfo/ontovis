async (page, facts, mode) => {
  const verify=(value,message)=>{if(!value)throw Error(message);};
  const label=(name,root=page)=>root.getByRole('button',{name,exact:true});
  const projectRef={ontobaseConnectionId:'ontobase-primary',projectCode:facts.projectCode};
  const fragments=new URLSearchParams({connection:projectRef.ontobaseConnectionId,project:projectRef.projectCode});
  const assets=facts.origin+'/#cockpit?'+fragments;
  function address(revision,instance){
    const query=new URLSearchParams(fragments);
    query.set('scene',facts.sceneId);query.set('revision',revision);
    if(instance)query.set('instance',instance);
    return facts.origin+'/#cockpit?'+query;
  }
  const root=page.getByRole('region',{name:'项目驾驶舱'}),nav=root.getByRole('navigation',{name:'驾驶舱页面'});
  const stage=name=>label(name,nav).and(nav.locator('[aria-current="page"]'));
  const crumb=root.locator('.pc-breadcrumb');
  const sessionPath='/api/session';
  const catalogPath='/api/workbench/regional-catalog';
  const accessPath='/api/workbench/projects/access';
  async function signIn(){
    await label('登录').click();
    const login=page.getByRole('dialog',{name:'登录 ONTOVis'});
    await login.getByLabel('用户名').fill('writer');
    await login.getByLabel('密码').fill('synthetic-only');
    await label('登录',login).click();
  }
  await page.setViewportSize({width:1440,height:900});
  if(mode==='history'){
    const initial=address(facts.sceneRevision,facts.instanceId);
    await page.goto(initial);
    await label('登录').waitFor();
    verify(!await root.count(),'Signed-out deep link exposed cockpit data');
    await signIn();
    await stage('设备').waitFor({timeout:30000});
    await crumb.getByText(facts.historicalInstance,{exact:true}).waitFor();
    await label(facts.historicalName,crumb).waitFor();
    verify(page.url()===initial,'Login rewrote the fixed location');
    await page.context().grantPermissions(['clipboard-read','clipboard-write']);
    await label('复制位置链接',root).click();
    verify(await page.evaluate(()=>navigator.clipboard.readText())===initial,'Clipboard used a different snapshot');
    await page.reload();
    await crumb.getByText(facts.historicalInstance,{exact:true}).waitFor({timeout:30000});

    await label('项目资产',nav).click();
    await page.waitForURL(assets);
    await page.reload();
    await stage('项目资产').waitFor();
    await label('场景总览',nav).click();
    await label(facts.currentName,root.locator('.pc-selection')).click();
    await page.waitForURL(address(facts.currentRevision));
    const scene=root.locator('.pc-scene-info');
    await label('浏览设备',scene).click();
    const equipment=page.getByRole('dialog',{name:'场景设备'});
    const secondVisible=equipment.getByRole('checkbox',{name:'显示 历史设备 B02',exact:true});
    await secondVisible.uncheck();
    await label(facts.currentInstance,equipment).click();
    await page.waitForURL(address(facts.currentRevision,facts.instanceId));
    await stage('设备').waitFor();
    await page.evaluate(()=>{window.navigationProbe=document.querySelector('.pc-viewport canvas');});
    await page.goBack();
    await page.waitForURL(address(facts.currentRevision));
    await stage('场景总览').waitFor();
    verify(await page.evaluate(()=>window.navigationProbe===document.querySelector('.pc-viewport canvas')),
      'Browser back replaced the scene viewport');
    await label('浏览设备',scene).click();
    verify(!await secondVisible.isChecked(),'Browser back reset a locally hidden instance');
    await label('关闭',equipment).click();
    await page.goForward();
    await stage('设备').waitFor();
    await crumb.getByText(facts.currentInstance,{exact:true}).waitFor();
    await page.screenshot({path:'cockpit-location.png'});

    const lost='00000000-0000-0000-0000-000000000000';
    await page.goto(address(facts.sceneRevision,lost));
    await root.getByRole('status').getByText('保存版本找不到此实例，已打开对应场景。').waitFor();
    await page.waitForURL(address(facts.sceneRevision));
    await page.goto(address('scene:'+lost,facts.instanceId));
    await root.locator('.pc-scene-shell [role=alert]').waitFor();
    verify(!await crumb.getByText(facts.currentInstance,{exact:true}).count(),'Missing revision fell back to a different revision');
    await page.goto(assets+'&revision=latest');
    await page.getByRole('alert').getByText('驾驶舱位置链接无效，请从项目重新进入。').waitFor();
    await page.goto(assets);
    await stage('项目资产').waitFor();
    const session=await (await page.request.get(facts.origin+sessionPath)).json();
    await page.request.post(facts.origin+'/test-navigation/revoke');
    const denied=await page.request.post(facts.origin+catalogPath,{headers:{Origin:facts.origin},data:{
      projectRef,expectedSessionRevision:session.sessionRevision}});
    verify(denied.status()===403,'Revoked project can still access the directory');
    const decision=page.waitForResponse(r=>new URL(r.url()).pathname===accessPath);
    await page.goto(initial);
    verify((await decision).status()===403,'The historical address did not recheck membership');
    await page.getByRole('alert').getByText('资料不可用或无权访问。').waitFor();
    verify(!await root.count(),'Revoked project still renders the cockpit');
    return {historicalRevision:true,restoredAfterLogin:true,clipboard:true,refresh:true,history:true,
      sameViewport:true,retainedVisibility:true,missingInstance:true,missingRevision:true,malformed:true,revoked:403};
  }

  await page.goto(assets);
  if(mode==='directory')await signIn();
  await stage('项目资产').waitFor({timeout:30000});
  await label('区域目录',root).click();
  const modal=page.getByRole('dialog',{name:'区域风电目录'});
  const result=modal.locator('.pc-regional-list li');
  await result.first().waitFor({timeout:20000});
  if(mode==='public'){
    verify(await result.count()===20,'Default directory page is not bounded');
    const first=await result.first().innerText();
    await label('下一页',modal).click();
    await result.first().waitFor();
    verify(await result.first().innerText()!==first,'Next page did not move the directory listing');
    await label('上一页',modal).click();
    await result.first().waitFor();
    verify(await result.first().innerText()===first,'Previous page did not restore the original listing');
  }
  const input=modal.getByRole('textbox',{name:'风场名称'});
  const source=modal.getByRole('combobox',{name:'区域目录来源'});
  await input.fill('No official wind directory entry matches this');
  await label('搜索',modal).click();
  await modal.getByRole('status').getByText('没有符合条件的观测。').waitFor();
  await input.fill(mode==='public'?'':'Gamma');
  await source.selectOption('repd');
  await label('搜索',modal).click();
  await result.first().getByRole('button').click();
  await modal.getByRole('link',{name:'官方来源',exact:true}).waitFor();
  verify(await modal.getByText(/格网坐标待核对/).count()>0&&!await label('在地球上定位',modal).count(),
    'Unverified UK grid coordinates were treated as longitude and latitude');
  await input.fill(mode==='public'?facts.referenceName:'Alpha');
  await source.selectOption('emodnet');
  await label('搜索',modal).click();
  const reference=result.filter({has:page.getByRole('button',{name:/来源参考点/})}).first();
  const name=await reference.locator('strong').innerText();
  await reference.getByRole('button').first().click();
  await label('在地球上定位',modal).waitFor();
  verify((await modal.getByRole('link',{name:'官方来源',exact:true}).getAttribute('href')).includes('emodnet.ec.europa.eu'),
    'An offshore observation lost the source attribution');
  await modal.screenshot({path:'regional-directory.png'});
  await label('在地球上定位',modal).click();
  const mapPoint=root.locator('.pc-globe-reference').filter({hasText:name});
  await mapPoint.waitFor({timeout:15000});
  verify(!await mapPoint.getByRole('button').count()&&page.url()===assets,'A regional marker opened a private scene');
  await stage('项目资产').waitFor();
  await page.screenshot({path:'regional-directory-map.png'});
  return {directory:true,sourceLicence:true,regionalPoint:true,unverifiedGridHeld:true,paginated:mode==='public'};
}
