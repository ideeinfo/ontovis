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

  if (phase === 'revoke') {
    await read(button('上一页场景', subject),403);
    await usage.getByText('当前无法查看此使用清单。',{exact:true}).waitFor();
    check(!await usage.locator('.as-usage-card').count(), 'Revoked list remained visible');
    check(await title.inputValue() === facts.title + ' · 草稿', 'Revocation discarded the draft');
    return {revokedStatus:403, cleared:true};
  }

  if (phase === 'changed') {
    const old = sceneButton(facts.sceneRevision);
    const [response] = await Promise.all([watch('scenes/open',body => body.sceneId === facts.sceneId),old.click()]);
    check(response.ok() && response.request().postDataJSON().sceneRevision === facts.sceneRevision,
      'A saved link opened a different scene revision');
    const scene = await response.json();
    check(scene.sceneRevision === facts.sceneRevision && scene.headRevision === facts.newRevision,
      'The original fixed revision was not retained');
    const modal = page.getByRole('dialog',{name:facts.sceneName,exact:true});
    await modal.getByText('历史版本',{exact:true}).waitFor();
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
      refreshAfterChange:true, focusedLink:true, draftRetained:true};
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
  return {modelEntries:first.total, matchedScenes:filtered.items[0].totalScenes, modelPage:second.page,
    filtered:true, laterScene:true};
}
