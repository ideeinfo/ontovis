async (page, facts, mode) => {
  const button = (name, root=page) => root.getByRole('button',{name,exact:true});
  const check = (value,message) => {if(!value)throw Error(message);};
  const target = facts.info;
  const modelPath = '/api/workbench/resources/model';
  const watch = (path,predicate=()=>true) => page.waitForResponse(response=>
    new URL(response.url()).pathname===path&&predicate(response.request().postDataJSON()),{timeout:35000});
  const control = async action => {
    const response = await page.request.post(facts.origin+'/test-model-info/'+action);
    check(response.ok(),'The isolation control failed');
  };
  const matches = body => body?.modelAssetId===target.modelAssetId&&body.modelVersionId===target.modelVersionId;

  await page.setViewportSize({width:1450,height:900});
  await page.goto(facts.origin+'/');
  await button('登录').click();
  const login=page.getByRole('dialog',{name:'登录 ONTOVis'});
  await login.getByLabel('用户名').fill('writer');
  await login.getByLabel('密码').fill('synthetic-only');
  await button('登录',login).click();
  await page.getByRole('button',{name:/^Q-24 合成项目 /}).click();
  await button('进入项目').click();
  await button('分析画布').click();
  const title=page.getByRole('textbox',{name:'分析名称',exact:true});
  await title.waitFor();
  if(await title.inputValue()!==facts.title)await page.locator('.ad-list-items .ov-list-main').filter({hasText:facts.title}).click();
  await title.fill(facts.title+' · 模型编辑草稿');
  const assistant=page.locator('.ad-assistant .as-panel');
  if(!await assistant.isVisible())await button('分析助手').click();
  await assistant.getByRole('textbox',{name:'向分析助手提问',exact:true}).fill('查询项目采用模型');
  await button('发送',assistant).click();
  const results=assistant.locator('.as-project-results').last();
  const row=results.locator('article').filter({has:page.locator('small[title="'+target.modelVersionId+'"]')});
  const [opened]=await Promise.all([watch(modelPath,matches),button('查看固定模型',row).click()]);
  const version=await opened.json();
  check(opened.ok()&&version.sha256===target.sha256,'Assistant opened another model version');
  check(await results.getByText(target.displayName,{exact:true}).count()>1,'Expected similarly named assets');
  const preview=page.getByRole('dialog',{name:target.displayName,exact:true});
  const edit=button('编辑模型基本信息',preview);
  await edit.waitFor();
  if(mode==='readonly')await control('viewer');
  if(mode==='stale')await control('revise');
  await edit.click();
  const leave=page.getByRole('dialog',{name:'分析修改尚未保存',exact:true});
  if(mode==='edit'){
    await button('继续编辑',leave).click();
    await preview.getByText(target.modelVersionId.slice(0,8),{exact:true}).waitFor();
    await button('关闭',preview).click();
    check(await title.inputValue()===facts.title+' · 模型编辑草稿','Cancelling the handoff discarded the draft');
    await button('查看固定模型',row).click();
    await edit.click();
  }
  const [read]=await Promise.all([watch(modelPath,matches),button('放弃并离开',leave).click()]);
  const current=await read.json();
  check(read.ok()&&current.modelAssetId===target.modelAssetId&&current.modelVersionId===target.modelVersionId,
    'Model center did not reopen the exact resource');
  const panel=page.getByRole('region',{name:'共享模型资源',exact:true});
  const form=page.getByRole('dialog',{name:'编辑模型基本信息',exact:true});
  if(mode==='readonly'){
    await panel.getByText('当前权限仅可查看模型基本信息。',{exact:true}).waitFor();
    check(!await form.count(),'Withdrawn permission still opened the form');
    const session=await (await page.request.get(facts.origin+'/api/session')).json();
    const denied=await page.request.post(facts.origin+modelPath+'/info/save',{headers:{Origin:facts.origin},data:{
      modelAssetId:target.modelAssetId,modelVersionId:target.modelVersionId,expectedAssetRevision:current.assetRevision,
      displayName:'Synthetic denial',description:'',purpose:'equipment',clientRequestId:await page.evaluate(()=>crypto.randomUUID()),
      expectedSessionRevision:session.sessionRevision}});
    check(denied.status()===403,'The model write route granted a viewer access');
    await control('restore');
    return {accessChanged:true,writeDenied:403};
  }
  if(mode==='stale'){
    await panel.getByText('基本信息已更新，请核对当前内容后再编辑。',{exact:true}).waitFor();
    check(!await form.count()&&current.assetRevision!==version.assetRevision,'A stale handoff opened a form');
    return {handoffConflict:true};
  }
  await form.waitFor();
  const name=form.getByRole('textbox',{name:'名称',exact:true});
  check(await name.inputValue()===target.displayName,'The editor prefilled a different model');
  await form.screenshot({path:'assistant-model-info.png'});
  await name.fill(target.displayName+' · 尝试保存');
  await control('revise');
  const [conflict]=await Promise.all([watch(modelPath+'/info/save',matches),button('保存',form).click()]);
  check(conflict.status()===409,'Concurrent edit did not reject the old revision');
  await form.getByText('基本信息已更新，当前修改已保留。',{exact:true}).waitFor();
  check(await name.inputValue()===target.displayName+' · 尝试保存','Conflict discarded the attempted change');
  await button('重新读取',form).click();
  await form.getByRole('textbox',{name:'说明',exact:true}).waitFor();
  await page.waitForFunction(()=>document.querySelector('.ov-resource-form textarea')?.value==='另一会话更新');
  await name.fill(target.displayName+' · 人工保存');
  const [saved]=await Promise.all([watch(modelPath+'/info/save',matches),button('保存',form).click()]);
  const receipt=await saved.json();
  check(saved.ok()&&receipt.sha256===target.sha256&&receipt.modelVersionId===target.modelVersionId,'Manual save changed the fixed model');
  await form.waitFor({state:'hidden'});
  return {modelAssetId:target.modelAssetId,modelVersionId:target.modelVersionId,savedRevision:receipt.assetRevision,
    cancelledDraftKept:true,sameNameChecked:true,conflict:409};
}
