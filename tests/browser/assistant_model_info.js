async (page, facts, mode) => {
  const button = (name, root=page) => root.getByRole('button',{name,exact:true});
  const check = (value,message) => {if(!value)throw Error(message);};
  const target = facts.info;
  const modelPath = '/api/workbench/resources/model';
  const accessPath = '/api/workbench/projects/access';
  const saveRequests=[];
  page.on('request',request=>{
    if(new URL(request.url()).pathname===modelPath+'/info/save')saveRequests.push(request);
  });
  const watch = (path,predicate=()=>true) => page.waitForResponse(response=>
    new URL(response.url()).pathname===path&&predicate(response.request().postDataJSON()),{timeout:35000});
  const control = async action => {
    const response = await page.request.post(facts.origin+'/test-model-info/'+action);
    check(response.ok(),'The isolation control failed');
    return response.json();
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
  const draftTitle=facts.title+' · 模型编辑草稿';
  await title.fill(draftTitle);
  const assistant=page.locator('.ad-assistant .as-panel');
  if(!await assistant.isVisible())await button('分析助手').click();
  await assistant.getByRole('textbox',{name:'向分析助手提问',exact:true}).fill('查询项目采用模型');
  await button('发送',assistant).click();
  const results=assistant.locator('.as-project-results').last();
  const row=results.locator('article').filter({has:page.locator('small[title="'+target.modelVersionId+'"]')});
  const [opened]=await Promise.all([watch(modelPath,matches),button('查看固定模型',row).click()]);
  const version=await opened.json();
  const turn=results.locator('xpath=../..').locator('.as-turn');
  const runId=await turn.getAttribute('data-run-id');
  check(runId,'The result must belong to a recorded turn');
  check(opened.ok()&&version.sha256===target.sha256,'Assistant opened another model version');
  check(await results.getByText(target.displayName,{exact:true}).count()>1,'Expected similarly named assets');
  const preview=page.getByRole('dialog',{name:target.displayName,exact:true});
  const edit=button('编辑模型基本信息',preview);
  const activePreview=page.locator('.as-fixed-model');
  const form=page.getByRole('dialog',{name:'编辑模型基本信息',exact:true});
  const name=form.getByRole('textbox',{name:'名称',exact:true});
  const back=button('返回分析助手');
  async function verifyReturn(reply,expectedRevision){
    const actual=await reply.json();
    check(reply.ok()&&matches(actual)&&actual.sha256===target.sha256&&
      actual.assetRevision===expectedRevision,'Returned to a different or stale model');
    await activePreview.getByText(target.modelVersionId.slice(0,8),{exact:true}).waitFor();
    await activePreview.locator('.ac-expanded').waitFor();
  }
  async function verifyDraft(){
    await button('关闭',activePreview).click();
    await title.waitFor();
    check(await title.inputValue()===draftTitle,'The round trip discarded canvas edits');
    await button('查看固定模型',row).waitFor();
    await assistant.locator(`.as-turn[data-run-id="${runId}"]`).waitFor();
  }
  await edit.waitFor();
  if(mode==='readonly')await control('viewer');
  if(mode==='stale')await control('revise');
  const [read]=await Promise.all([watch(modelPath,matches),edit.click()]);
  const current=await read.json();
  check(read.ok()&&current.modelAssetId===target.modelAssetId&&current.modelVersionId===target.modelVersionId,
    'Model center did not reopen the exact resource');
  const panel=page.getByRole('region',{name:'共享模型资源',exact:true});
  if(mode==='readonly'){
    await panel.getByText('当前权限仅可查看模型基本信息。',{exact:true}).waitFor();
    check(!await form.count(),'Withdrawn permission still opened the form');
    const session=await (await page.request.get(facts.origin+'/api/session')).json();
    const denied=await page.request.post(facts.origin+modelPath+'/info/save',{headers:{Origin:facts.origin},data:{
      modelAssetId:target.modelAssetId,modelVersionId:target.modelVersionId,expectedAssetRevision:current.assetRevision,
      displayName:'Synthetic denial',description:'',purpose:'equipment',clientRequestId:await page.evaluate(()=>crypto.randomUUID()),
      expectedSessionRevision:session.sessionRevision}});
    check(denied.status()===403,'The model write route granted a viewer access');
    const [returned]=await Promise.all([watch(modelPath,matches),back.click()]);
    await verifyReturn(returned,current.assetRevision);
    check(await edit.count()===0,'Returned preview exposed edit access after downgrade');
    await verifyDraft();
    await control('restore');
    return {accessChanged:true,writeDenied:403,returned:true};
  }
  if(mode==='stale'){
    await panel.getByText('基本信息已更新，请核对当前内容后再编辑。',{exact:true}).waitFor();
    check(!await form.count()&&current.assetRevision!==version.assetRevision,'A stale handoff opened a form');
    const [returned]=await Promise.all([watch(modelPath,matches),back.click()]);
    await verifyReturn(returned,current.assetRevision);
    await verifyDraft();
    return {handoffConflict:true,returned:true};
  }
  await form.waitFor();
  check(await name.inputValue()===target.displayName,'The editor prefilled a different model');
  check(!await title.isVisible(),'The draft is visible behind the temporary model center');
  if(mode==='project-denied'){
    await control('project-denied');
    const [denied]=await Promise.all([watch(accessPath),button('取消',form).click()]);
    check(denied.status()===403,'Return did not check the original project grant');
    await page.getByRole('heading',{name:'项目中心',exact:true}).waitFor();
    check(!await title.count()&&!await activePreview.count(),'Revoked analysis content was restored');
    await control('restore');
    return {projectDenied:403,cachedDraftCleared:true};
  }
  await form.screenshot({path:'assistant-model-info.png'});
  await name.fill(target.displayName+' · 取消');
  const [cancelled]=await Promise.all([watch(modelPath,matches),button('取消',form).click()]);
  await verifyReturn(cancelled,current.assetRevision);
  check(saveRequests.length===0&&await activePreview.locator('.as-model-edit-receipt').count()===0,
    'Cancelling sent a write or reported a save');
  await verifyDraft();
  await button('查看固定模型',row).click();
  await edit.click();
  await name.fill(target.displayName+' · 尝试保存');
  const concurrent = await control('revise');
  const [conflict]=await Promise.all([watch(modelPath+'/info/save',matches),button('保存',form).click()]);
  check(conflict.status()===409,'Concurrent edit did not reject the old revision');
  await form.getByText('基本信息已更新，当前修改已保留。',{exact:true}).waitFor();
  check(await name.inputValue()===target.displayName+' · 尝试保存','Conflict discarded the attempted change');
  await button('重新读取',form).click();
  await form.getByRole('textbox',{name:'说明',exact:true}).waitFor();
  await page.waitForFunction(description=>document.querySelector('.ov-resource-form textarea')?.value===description,concurrent.description);
  await name.fill(target.displayName+' · 人工保存');
  await page.route('**'+accessPath,route=>route.fulfill({status:503,json:{code:'SOURCE_UNAVAILABLE'}}),{times:1});
  const [saved]=await Promise.all([watch(modelPath+'/info/save',matches),button('保存',form).click()]);
  const receipt=await saved.json();
  check(saved.ok()&&receipt.sha256===target.sha256&&receipt.modelVersionId===target.modelVersionId,'Manual save changed the fixed model');
  await page.getByRole('alert').filter({hasText:'模型信息已保存。暂时无法返回，请重试。'}).waitFor();
  const [returned]=await Promise.all([watch(modelPath,matches),back.click()]);
  await verifyReturn(returned,receipt.assetRevision);
  await activePreview.getByRole('heading',{name:receipt.displayName,exact:true}).waitFor();
  const savedStatus=activePreview.locator('.as-model-edit-receipt');
  check(await savedStatus.locator('code').getAttribute('title')===receipt.assetRevision&&
    await savedStatus.locator('code').innerText()==='r'+receipt.assetRevision.split(':').at(-1),
    'The visible receipt does not match the server-confirmed revision');
  await savedStatus.screenshot({path:'assistant-model-info-return.png'});
  await verifyDraft();
  check(saveRequests.length===2,'Retrying the return repeated the save');
  return {modelAssetId:target.modelAssetId,modelVersionId:target.modelVersionId,savedRevision:receipt.assetRevision,
    cancelledDraftKept:true,sameNameChecked:true,conflict:409,returnRetry:true,savedDraftKept:true};
}
