async (page, facts, phase) => {
  const check = (value, message) => { if (!value) throw Error(message); };
  const button = (name, root = page) => root.getByRole('button', {name, exact:true});
  const watch = (suffix, predicate = () => true) => page.waitForResponse(response =>
    new URL(response.url()).pathname === '/api/workbench/' + suffix &&
    response.request().method() === 'POST' && predicate(response.request().postDataJSON()), {timeout:45000});
  const usage = page.locator('.as-usage-browser').last();
  const read = async (control, status = 200) => {
    const [response] = await Promise.all([watch('assistant/task-page', body => !!body.modelUsage), control.click()]);
    check(response.status() === status, 'Model usage returned HTTP ' + response.status());
    return response.json();
  };
  const sceneButton = revision => button('查看场景 ' + facts.sceneName + ' ' + revision.slice(6,14), usage);
  const subject = usage.locator('.as-usage-card').filter({has:page.locator('small[title="' + facts.versionId + '"]')});
  const title = page.getByRole('textbox', {name:'分析名称', exact:true});
  const modal = page.getByRole('dialog',{name:facts.sceneName,exact:true});
  const selectSecond = async () => {
    const search = modal.getByRole('searchbox',{name:'搜索模型实例'});
    await search.fill('A01 '+facts.instanceId.slice(0,8));
    await modal.getByText('1 个匹配实例',{exact:true}).waitFor();
    await search.press('Enter');
    check(await modal.getByLabel('选择模型实例').inputValue()===facts.instanceId,'Selected another same-name instance');
  };

  if (phase === 'revoke') {
    await read(button('上一页场景', subject),403);
    await usage.getByText('当前无法查看此使用清单。',{exact:true}).waitFor();
    check(!await usage.locator('.as-usage-card').count(), 'Revoked list remained visible');
    check(await title.inputValue() === facts.title + ' · 草稿', 'Revocation discarded the draft');
    return {revokedStatus:403, cleared:true};
  }

  if (phase === 'edit') {
    await read(button('从第一页重新读取',usage));
    await read(button('下一页场景',subject));
    await sceneButton(facts.newRevision).click();
    await selectSecond();
    await button('编辑所选实例',modal).click();
    const leave = page.getByRole('dialog',{name:'分析修改尚未保存'});
    const [opened] = await Promise.all([
      watch('scenes/open',body=>body.sceneId===facts.sceneId),
      button('放弃并离开',leave).click()
    ]);
    check(opened.ok()&&opened.request().postDataJSON().sceneRevision===facts.newRevision,
      'Editor was not opened with the exact scene revision');
    const toolbar = page.locator('.sw-editor-toolbar');
    const instance = page.locator('.sw-instance-overview');
    await instance.getByText(facts.instanceId,{exact:true}).waitFor();
    check(await button('布置',toolbar).getAttribute('aria-pressed')==='true','Scene editor did not enter arrange mode');
    const save = button('保存',toolbar);
    check(await save.isDisabled(),'Opening the editor changed its saved snapshot');
    await page.screenshot({path:'assistant-scene-instance-editor.png'});
    await button('实例位置',page.locator('.sw-inspector')).click();
    const position = page.getByRole('tabpanel',{name:'位置',exact:true});
    const coordinates = position.getByRole('region',{name:'实例位置',exact:true});
    await position.getByRole('region',{name:'场景地理位置',exact:true})
      .getByText('未设置地理位置',{exact:true}).waitFor();
    check(Number(await coordinates.getByLabel('X（米）',{exact:true}).inputValue())===35,
      'Position settings show a different same-name instance');
    check(!await page.locator('.sw-inspector').getByLabel('X（米）',{exact:true}).count(),
      'Placement fields still appear in the inspector');
    await page.route('https://tile.openstreetmap.org/**',route=>route.abort());
    await button('获取公开地形与影像',position).click();
    const acquisition = page.getByRole('dialog',{name:'获取公开地形与影像',exact:true});
    check(await acquisition.getByLabel('中心经度').inputValue()===''&&await acquisition.getByLabel('中心纬度').inputValue()==='',
      'The unanchored scene acquired a location from its selected instance');
    await page.keyboard.press('Escape');
    await acquisition.waitFor({state:'hidden'});
    const heading = coordinates.getByLabel('朝向（°）',{exact:true});
    await heading.fill(String((Number(await heading.inputValue())+15)%360));
    await button('应用',coordinates).click();
    await button('锁定位置',coordinates).click();
    check(await heading.isDisabled()&&await button('应用',coordinates).isDisabled(),'The position lock was ignored');
    const name = instance.getByRole('textbox',{name:'实例名称',exact:true});
    check(await name.inputValue()===facts.instanceName,'Editor displayed a different instance');
    await name.fill(facts.instanceName+' · 编辑验收');
    await name.press('Enter');
    await coordinates.getByText(facts.instanceName+' · 编辑验收',{exact:true}).waitFor();
    await button('解锁位置',coordinates).click();
    const [response] = await Promise.all([watch('scenes/save'),save.click()]);
    const sent = response.request().postDataJSON();
    const saved = await response.json();
    check(response.ok()&&sent.expectedSceneRevision===facts.newRevision&&saved.sceneRevision!==facts.newRevision,
      'The human save did not create a new scene revision from the intended head');
    return {selectedInstance:facts.instanceId,enteredEditor:true,savedRevision:saved.sceneRevision,
      positionTab:true,positionLock:true,unanchoredQuery:true};
  }

  if (phase === 'changed') {
    const old = sceneButton(facts.sceneRevision);
    const [response] = await Promise.all([watch('scenes/open',body => body.sceneId === facts.sceneId),old.click()]);
    check(response.ok() && response.request().postDataJSON().sceneRevision === facts.sceneRevision,
      'A saved link opened a different scene revision');
    const scene = await response.json();
    check(scene.sceneRevision === facts.sceneRevision && scene.headRevision === facts.newRevision,
      'The original fixed revision was not retained');
    await modal.getByText('历史版本',{exact:true}).waitFor();
    const search = modal.getByRole('searchbox',{name:'搜索模型实例'});
    const select = modal.getByLabel('选择模型实例');
    await search.fill('A99');
    await modal.getByText('没有匹配的实例',{exact:true}).waitFor();
    check(await button('定位实例',modal).isDisabled(),'An empty search can still locate a stale selection');
    await search.fill('Ａ０１');
    await modal.getByText('2 个匹配实例',{exact:true}).waitFor();
    const sameNames = await select.locator('option').allTextContents();
    check(sameNames.length===3 && sameNames[1]!==sameNames[2] && sameNames[2].includes(facts.instanceId.slice(0,8)),
      'Identical instance names are ambiguous');
    await search.fill('A01 '+facts.instanceId.slice(0,8));
    await modal.getByText('1 个匹配实例',{exact:true}).waitFor();
    await search.press('Enter');
    check(await select.inputValue()===facts.instanceId,'Keyboard selection did not choose the fixed instance');
    await button('定位实例',modal).click();
    await modal.getByText('已定位 · 固定实例',{exact:true}).waitFor({timeout:45000});
    check(await modal.getByText('实例 · ' + facts.instanceName,{exact:true}).getAttribute('title') === facts.instanceId,
      'Located a different same-name scene instance');
    check(!await modal.getByRole('button',{name:/编辑|保存/}).count(),'The model-use preview was writable');
    await page.evaluate(() => new Promise(resolve => setTimeout(() => requestAnimationFrame(resolve), 1100)));
    await modal.screenshot({path:'assistant-usage-fixed-instance.png'});
    await page.keyboard.press('Escape');
    await modal.waitFor({state:'hidden'});
    const label = await old.getAttribute('aria-label');
    await page.waitForFunction(name => document.activeElement?.getAttribute('aria-label') === name, label);

    const expired = await read(button('上一页场景', subject),409);
    check(expired.code === 'SNAPSHOT_EXPIRED','An obsolete continuation did not expire');
    await usage.getByText('使用清单已变化。',{exact:true}).waitFor();
    check(!await usage.locator('.as-usage-card').count(),'Mixed scene snapshots remained on screen');
    const refreshed = await read(button('从第一页重新读取',usage));
    check(refreshed.page === 1 && refreshed.total === 1,'The original filter did not survive refresh');
    await read(button('下一页场景',subject));
    await sceneButton(facts.newRevision).waitFor();
    check(await title.inputValue() === facts.title + ' · 草稿','The draft changed during navigation');
    return {fixedRevision:scene.sceneRevision, sceneId:scene.sceneId, instanceId:facts.instanceId,
      refreshAfterChange:true, focusedLink:true, draftRetained:true, searchableInstances:true};
  }

  await page.setViewportSize({width:1440,height:960});
  await page.goto(facts.origin + '/');
  await button('登录').click();
  const login = page.getByRole('dialog',{name:'登录 ONTOVis'});
  await login.getByLabel('用户名').fill('writer');
  await login.getByLabel('密码').fill('synthetic-only');
  await button('登录',login).click();
  await page.getByRole('button',{name:/Q-24 合成项目/}).first().click();
  await button('进入项目').click();
  await button('分析画布').click();
  await title.waitFor();
  if (await title.inputValue() !== facts.title) await page.locator('.ad-list button').filter({hasText:facts.title}).first().click();
  await title.fill(facts.title + ' · 草稿');
  const assistant = page.locator('.ad-assistant .as-panel');
  if (!await assistant.isVisible()) await button('分析助手').click();
  await assistant.getByRole('textbox',{name:'向分析助手提问',exact:true}).fill('查询项目采用模型的使用清单');
  await button('发送',assistant).click();
  await button('完整使用清单',usage).waitFor({timeout:45000});
  const first = await read(button('完整使用清单',usage));
  check(first.total === 6 && first.items.length === 4,'The first page was truncated incorrectly');
  check(!first.items.some(row => row.version === facts.versionId),'The fixture target belongs on model page two');
  const second = await read(button('下一页模型',usage));
  check(second.page === 2 && second.items.some(row => row.version === facts.versionId),'The second model page is wrong');
  const next = await read(button('下一页场景',subject));
  check(next.items[0].scenes.length === 1 && next.items[0].scenes[0].sceneId === facts.sceneId,'The later scene was not returned');
  await sceneButton(facts.sceneRevision).waitFor();
  await usage.getByLabel('配置或型号').fill('合成型号 Q24');
  await usage.getByLabel('场景名称').fill('未登记场景');
  check((await read(button('筛选',usage))).total === 0,'An unrelated scene matched');
  await usage.getByLabel('场景名称').fill(facts.sceneName);
  const filtered = await read(button('筛选',usage));
  check(filtered.total === 1 && filtered.items[0].totalScenes === 5,'Combined filters did not narrow the result');
  await read(button('下一页场景',subject));
  await sceneButton(facts.sceneRevision).waitFor();
  await usage.screenshot({path:'assistant-usage-later-scene.png'});
  await sceneButton(facts.sceneRevision).click();
  await selectSecond();
  await button('编辑所选实例',modal).click();
  const leave = page.getByRole('dialog',{name:'分析修改尚未保存'});
  await button('继续编辑',leave).click();
  await leave.waitFor({state:'hidden'});
  check(await modal.getByLabel('选择模型实例').inputValue()===facts.instanceId,'Cancelling the handoff lost the chosen instance');
  await button('关闭',modal).click();
  check(await title.inputValue()===facts.title+' · 草稿','Cancelling the handoff lost the analysis draft');
  return {modelEntries:first.total, matchedScenes:filtered.items[0].totalScenes, modelPage:second.page,
    filtered:true, laterScene:true,cancelledHandoffKeptDraftAndSelection:true};
}
