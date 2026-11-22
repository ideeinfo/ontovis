async (page, origin, evidence, mode) => {
  const button=(name,root=page)=>root.getByRole('button',{name,exact:true});
  const check=(condition,message)=>{if(!condition)throw Error(message);};
  const path='/api/workbench/resources/model';
  const watch=(suffix,predicate)=>page.waitForResponse(response=>{
    const request=response.request();
    return request.method()==='POST'&&new URL(response.url()).pathname===suffix&&predicate(request.postDataJSON());
  },{timeout:45000});
  const writes=[];
  const observe=request=>{
    if(/\/(model\/info|analysis-sessions|scenes)\/save$/.test(new URL(request.url()).pathname))writes.push(request.method());
  };
  page.on('request',observe);
  try{
    await page.setViewportSize({width:1480,height:980});
    await page.goto(origin+'/');
    await page.getByRole('button',{name:/^PDS风电场 Demo-PDS/}).first().click();
    await button('进入项目').click();
    const cockpit=mode==='cockpit_query';
    const panel=page.locator(cockpit?'#pa-chat-panel':'.ad-assistant .as-panel');
    const title=page.getByRole('textbox',{name:'分析名称',exact:true});
    let originalTitle='';
    if(cockpit){
      await button('驾驶舱').click();
      const root=page.getByRole('region',{name:'项目驾驶舱'});
      await button('分析工作台',root).click();
      await root.getByLabel('当前故障',{exact:true}).selectOption(JSON.stringify(['SIM-PDS-13001',evidence.datasetRevision]));
      await root.getByLabel('推荐分析画布',{exact:true}).selectOption(evidence.analysisSessionId);
      await root.getByRole('tab',{name:'问答',exact:true}).click();
    }else{
      await button('分析画布').click();
      await title.waitFor();
      const selected=page.locator('.ad-list-items .ov-list-main').filter({hasText:'13001 · 多来源证据公网验收'}).first();
      await selected.click();
      originalTitle=await title.inputValue();
      await title.fill(originalTitle+' · 取消验收草稿');
      if(!await panel.isVisible())await button('分析助手').click();
    }
    await button('新对话',panel).click();
    const task=panel.getByLabel('助手任务',{exact:true});
    if(await task.count()&&await task.inputValue()!=='query')await task.selectOption('query');
    await panel.getByRole('textbox',{name:'向分析助手提问',exact:true})
      .fill('查询项目采用的固定模型及其使用清单，列出已保存场景引用');
    const [started]=await Promise.all([watch('/api/workbench/assistant/task-start',body=>body.mode===mode),button('发送',panel).click()]);
    check(started.ok(),'Public assistant request did not start');
    const {runId}=await started.json();
    const turn=panel.locator('.as-turn[data-run-id="'+runId+'"]').locator('xpath=..');
    const show=button('查看固定模型',turn).first();
    await show.waitFor({timeout:85000});
    const [opened]=await Promise.all([watch(path,body=>!!body.modelVersionId),show.click()]);
    const model=await opened.json();
    check(opened.ok()&&opened.request().postDataJSON().modelVersionId===model.modelVersionId&&model.sha256,
      'The assistant did not read the selected fixed model');
    const preview=page.locator('.as-fixed-model');
    const entry=button('编辑模型基本信息',preview);
    await preview.getByText(model.modelVersionId.slice(0,8),{exact:true}).waitFor();
    if(cockpit){
      await preview.locator('.ac-expanded').waitFor();
      check(await entry.count()===0,'Cockpit exposed the model editor');
    }else{
      const [read]=await Promise.all([watch(path,body=>body.modelVersionId===model.modelVersionId),entry.click()]);
      const current=await read.json();
      check(read.ok()&&current.modelAssetId===model.modelAssetId&&current.contentRevision===model.contentRevision&&
        current.sha256===model.sha256&&current.assetRevision===model.assetRevision,'The editor read a different model or revision');
      const form=page.getByRole('dialog',{name:'编辑模型基本信息',exact:true});
      await form.waitFor();
      check(await form.getByRole('textbox',{name:'名称',exact:true}).inputValue()===model.displayName,
        'The original edit form did not show the fixed model');
      await form.screenshot({path:'public-model-info.png'});
      const [returned]=await Promise.all([watch(path,body=>body.modelVersionId===model.modelVersionId),button('取消',form).click()]);
      const reopened=await returned.json();
      check(returned.ok()&&reopened.sha256===model.sha256&&reopened.assetRevision===model.assetRevision,
        'Cancelling did not restore the same fixed model');
      await preview.locator('.ac-expanded').waitFor();
      check(await preview.locator('.as-model-edit-receipt').count()===0,'Cancelling displayed a saved receipt');
      await button('关闭',preview).click();
      check(await title.inputValue()===originalTitle+' · 取消验收草稿','Cancelling removed the canvas draft');
      await show.waitFor();
      await title.fill(originalTitle);
    }
    check(writes.length===0,'The public navigation unexpectedly sent a save request');
    return {mode,modelVersionId:model.modelVersionId,assetRevision:model.assetRevision,sha256:model.sha256,
      editorOpened:!cockpit,returnedToOriginal:!cockpit,domainWrites:0};
  }finally{
    page.off('request',observe);
  }
}
