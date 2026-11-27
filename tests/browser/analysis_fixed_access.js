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
  const drag=async (target,dx,dy,point)=>{
    const box=await target.boundingBox();
    const x=box.x+(point?.x??box.width/2),y=box.y+(point?.y??box.height/2);
    await page.mouse.move(x,y);
    await page.mouse.down();
    await page.mouse.move(x+dx,y+dy,{steps:8});
    await page.mouse.up();
  };
  await page.setViewportSize({width:1500,height:956});
  await page.goto(facts.origin+'/');
  await button('登录').click();
  const login = page.getByRole('dialog',{name:'登录 ONTOVis',exact:true});
  await login.getByLabel('用户名').fill('writer');
  await login.getByLabel('密码').fill('synthetic-only');
  await button('登录',login).click();
  await page.getByRole('button',{name:/^Q-26 固定资料试验 Demo-PDS/}).click();
  await button('进入项目').click();
  const photoPhase=phase==='withdraw-photo'||phase==='switch-photo-project';
  const cockpit = phase==='grouped-layout'||phase==='expire-session'||phase==='withdraw-project'||phase==='withdraw-photo';
  const heldDrawing=phase==='switch-project'?await hold('content',facts.cards.drawing.ref):null;
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
  if(phase==='workbench-defaults-and-group'){
    const tools=canvas.locator('.ad-tools');
    const addBox=await button('加入资料',tools).boundingBox();
    const arrangeBox=await button('整理布局',tools).boundingBox();
    check(await tools.locator('button').evaluateAll(nodes=>
      nodes.length>2&&nodes.every(node=>getComputedStyle(node).userSelect==='none')),
      'Canvas toolbar buttons allow text selection');
    await page.evaluate(()=>window.getSelection().removeAllRanges());
    await page.mouse.move(addBox.x+addBox.width*.58,addBox.y+addBox.height/2);
    await page.mouse.down();
    await page.mouse.move(arrangeBox.x+arrangeBox.width*.8,arrangeBox.y+arrangeBox.height/2,{steps:10});
    await page.mouse.up();
    check(await page.evaluate(()=>window.getSelection().toString()===''),'Dragging across toolbar buttons selected their text');
    check(await canvas.getByRole('textbox',{name:'分析名称'}).evaluate(node=>getComputedStyle(node).userSelect==='text'),
      'The canvas name can no longer be selected independently');

    const card=kind=>canvas.locator('.ad-card[data-card-id="'+facts.cards[kind].id+'"]');
    const previews=['document','photo','drawing'];
    const image=kind=>card(kind).locator('.ac-photo-view img');
    await Promise.all(previews.map(async kind=>{
      await image(kind).waitFor();
      check(await image(kind).evaluate(async node=>{await node.decode();return node.naturalWidth>0;}),
        'The '+kind+' preview did not render automatically');
    }));
    const inlinePhoto=card('photo');
    check(await inlinePhoto.locator('.wo-photo-tools,.wo-photo-hint').count()===0,
      'The inline photo mounted its toolbar or gesture hint');
    check(await inlinePhoto.locator('.wo-photo-scroll').evaluate(view=>{
      const rect=view.getBoundingClientRect();
      const body=view.closest('.ac-source').getBoundingClientRect();
      return rect.height>0 && Math.min(rect.bottom,body.bottom)-rect.top>=rect.height*.85;
    }),'The default photo viewport was mostly clipped by the card body');
    await button('展开查看',inlinePhoto).click();
    const photoDialog=page.getByRole('dialog',{name:facts.cards.photo.title,exact:true});
    await photoDialog.locator('.ac-photo-view img').waitFor();
    await button('照片放大',photoDialog).waitFor();
    await button('适应窗口',photoDialog).waitFor();
    await photoDialog.locator('.wo-photo-hint').waitFor();
    await button('关闭',photoDialog).click();
    await photoDialog.waitFor({state:'hidden'});
    check(await inlinePhoto.locator('.wo-photo-tools,.wo-photo-hint').count()===0,
      'Closing expanded view added tools to the inline photo');
    for(const colorScheme of ['light','dark']){
      await page.emulateMedia({colorScheme});
      await page.locator(`html[data-theme="${colorScheme}"]`).waitFor({state:'attached'});
      for(const kind of previews){
        check(await card(kind).locator('.wo-photo-scroll').evaluate(node=>
          getComputedStyle(node).backgroundColor===getComputedStyle(node.closest('.ad-canvas')).backgroundColor),
          `The ${kind} preview ignored the ${colorScheme} canvas background`);
      }
    }
    await page.emulateMedia({colorScheme:null});
    await button('收起预览：'+facts.cards.photo.title,card('photo')).click();
    await image('photo').waitFor({state:'hidden'});
    await button('打开照片', card('photo')).waitFor();
    check(await image('document').isVisible()&&await image('drawing').isVisible(),'Collapsing a photo closed another preview');
    await button('打开照片',card('photo')).click();
    await image('photo').waitFor();

    const target=card('drawing'),original=facts.cards.drawing;
    const targetGroup=facts.frames.find(group=>group.id!==original.frameId);
    const groupDialog=page.getByRole('dialog',{name:'设置分组',exact:true});
    const group=groupDialog.getByLabel('所属分组',{exact:true});
    const setGroup=page.getByRole('menuitem',{name:'设置分组',exact:true});
    await button('平移工具',canvas).click();
    await target.getByRole('button',{name:'更多操作： '+original.title,exact:true}).click();
    await setGroup.click();
    check(await group.inputValue()===original.frameId,'The dialog reported the wrong starting group');
    await group.selectOption({label:targetGroup.title});
    await button('取消',groupDialog).click();
    check(await target.getAttribute('data-frame-id')===original.frameId,'Cancelling applied a different group');
    await button('选择工具',canvas).click();
    await target.locator('header .ac-card-title').click({button:'right'});
    await setGroup.click();
    await group.selectOption({label:targetGroup.title});
    await button('应用',groupDialog).click();
    check(await target.getAttribute('data-frame-id')===targetGroup.id,'The card did not join the chosen group');
    await button('撤销修改',canvas).click();
    check(await target.getAttribute('data-frame-id')===original.frameId,'Undo did not restore group membership');
    await button('重做修改',canvas).click();
    check(await target.getAttribute('data-frame-id')===targetGroup.id,'Redo did not restore the new group');
    const [saved]=await Promise.all([
      page.waitForResponse(response=>new URL(response.url()).pathname==='/api/workbench/analysis-sessions/save'),
      button('保存',canvas).click()
    ]);
    check(saved.ok(),'Saving the group change failed');
    const revision=await saved.json();
    check(revision.analysisRevision===3,'The group change did not create a new revision');
    const written=saved.request().postDataJSON().snapshot.cards.find(row=>row.id===original.id);
    check(written.frameId===targetGroup.id&&written.source.id===original.ref&&
      ['x','y','width','height'].every(key=>written[key]===original[key]),'Saving the group changed the fixed source or card placement');
    const [reopened]=await Promise.all([
      page.waitForResponse(response=>new URL(response.url()).pathname==='/api/workbench/analysis-sessions/detail'),
      canvas.locator('.ad-list-items .ov-list-main').filter({hasText:title}).click()
    ]);
    const detail=await reopened.json();
    check(reopened.ok()&&detail.analysisRevision===3&&
      detail.snapshot.cards.find(row=>row.id===original.id).frameId===targetGroup.id,'Reopening lost the saved group');

    const materials=canvas.locator('.ac-material-panel');
    const recommendationStyles={};
    const candidateStyle=async candidate=>{
      const styles={};
      for(const theme of ['light','dark']){
        await page.emulateMedia({colorScheme:theme});
        await page.locator(`html[data-theme="${theme}"]`).waitFor({state:'attached'});
        styles[theme]=await candidate.evaluate(row=>{
          const header=row.querySelector('header');
          const style=getComputedStyle(header);
          return {background:style.backgroundColor,padding:style.padding,radius:getComputedStyle(row).borderRadius};
        });
      }
      await page.emulateMedia({colorScheme:null});
      return styles;
    };
    const alarmMenu=button('更多操作： '+facts.cards.alarm.title,card('alarm'));
    await alarmMenu.click();
    await page.getByRole('menuitem',{name:'推荐相关资料',exact:true}).click();
    const alarmGroup=materials.locator('.ac-material-group').filter({has:page.getByRole('heading',{name:facts.cards.alarm.title,exact:true})});
    const drawingGroup=materials.locator('.ac-material-group').filter({has:page.getByRole('heading',{name:facts.cards.drawing.title,exact:true})});
    await alarmGroup.getByRole('checkbox',{name:'选择资料 '+facts.cards.object.title,exact:true}).waitFor();
    await drawingGroup.getByRole('checkbox',{name:'选择资料 '+facts.drawingObjectTitle,exact:true}).waitFor();
    check(await materials.getByRole('checkbox',{name:'选择资料 '+facts.cards.object.title,exact:true}).count()===1,
      'A shared object was listed more than once');
    check(await alarmGroup.getByRole('checkbox',{name:'选择资料 '+facts.cards.object.title,exact:true}).isDisabled(),
      'An existing object could still be selected from the recommendation');
    recommendationStyles.object=await candidateStyle(alarmGroup.locator('.ac-material-result[data-card-kind="object"]').first());
    await alarmGroup.getByText(/也关联/).filter({hasText:facts.cards.drawing.title}).waitFor();
    await button('关闭资料库',materials).click();
    await button('展开查看',target).click();
    const drawingDialog=page.getByRole('dialog',{name:original.title,exact:true});
    await drawingDialog.getByRole('navigation',{name:'图纸内容列表'}).getByRole('button',{name:new RegExp(facts.drawingObjectTitle)}).click();
    await drawingDialog.getByText('可定位',{exact:true}).waitFor();
    await button('推荐照片',drawingDialog).click();
    await drawingDialog.waitFor({state:'hidden'});
    const parentPhoto=materials.locator('.ac-material-result').filter({hasText:facts.cards.photo.title});
    await parentPhoto.getByText('所属设备照片',{exact:true}).waitFor();
    check(await parentPhoto.getByText(/所属设备.*共享照片.*整图/).count()===1,
      'The selected drawing object did not scope photos to its registered parent equipment');
    recommendationStyles.photo=await candidateStyle(parentPhoto);
    await button('关闭资料库',materials).click();
    await button('加入资料',canvas).click();
    const firstCategory=materials.locator('.ac-material-category').first();
    check(await firstCategory.locator('strong').innerText()==='故障报警','Fault alarms were not the first material type');
    check(await materials.getByRole('button',{name:/^当前设备适用资料/}).count()===0,'Equipment material applicability had a second entry');
    await firstCategory.click();
    await materials.locator('.ac-material-result').filter({hasText:'已加入'}).waitFor();
    check(await materials.getByText('测试数据',{exact:false}).count()===0,'The compact alarm list displayed the test-data label');
    check((await materials.locator('.ac-material-result').first().boundingBox()).height<90,'An alarm result occupied too many rows');
    await materials.locator('.ac-material-back').click();
    const drawingCategory=()=>materials.getByRole('button',{name:/^图纸/});
    const drawingResult=materials.locator('.ac-material-result').filter({has:page.getByText(facts.powerDrawingTitle,{exact:true})});
    await drawingCategory().click();
    await drawingResult.first().waitFor();
    check(await drawingResult.count()===1,'Two registered positions returned duplicate drawing rows');
    recommendationStyles.drawing=await candidateStyle(drawingResult);
    await button('加入画布：'+facts.memberDrawingTitle,materials).click();
    const descendantEdge=canvas.getByRole('button',{name:
      '下级对象图纸：'+facts.cards.object.title+' → '+facts.memberDrawingTitle,exact:true});
    await descendantEdge.waitFor({state:'attached'});
    check(await descendantEdge.getAttribute('data-origin')==='source','The new drawing did not use the registered object relationship');
    await button('撤销修改',canvas).click();
    await descendantEdge.waitFor({state:'detached'});
    await materials.locator('.ac-material-back').click();
    await materials.getByRole('button',{name:/^相关资料/}).click();
    const manual=materials.locator('.ac-material-result[data-card-kind="document"]').first();
    await manual.getByText('文档',{exact:true}).waitFor();
    recommendationStyles.document=await candidateStyle(manual);
    for(const theme of ['light','dark']){
      check(new Set(Object.values(recommendationStyles).map(style=>style[theme].background)).size===4,
        'The recommendation list did not use distinct colors for the four material types');
    }
    await materials.locator('.ac-material-back').click();
    await materials.getByRole('button',{name:/^工程对象/}).click();
    for(const title of facts.additionalObjectTitles)await materials.getByRole('checkbox',{name:'选择资料 '+title,exact:true}).check();
    await button('加入所选资料 (2)',materials).click();
    const selectedObject=canvas.locator('.ad-card.selected[data-card-kind="object"]')
      .getByRole('button',{name:facts.additionalObjectTitles.at(-1),exact:true});
    await selectedObject.waitFor({state:'attached'});
    check(await canvas.locator('.ad-card[data-card-kind="object"]').count()===3,'The three alarm objects were not added');
    await materials.locator('.ac-material-back').click();
    await drawingCategory().click();
    await drawingResult.first().waitFor();
    check(await drawingResult.count()===1,'Adding objects changed the original alarm drawing recommendation');
    await button('关闭资料库',materials).click();
    await button('加入资料',canvas).click();
    await drawingCategory().click();
    await drawingResult.first().waitFor();
    check(await drawingResult.count()===1,'Reopening materials switched to the newly selected object');
    await button('撤销修改',canvas).click();
    await selectedObject.waitFor({state:'detached'});
    await materials.locator('.ac-material-back').click();
    await materials.getByRole('button',{name:/^故障报警/}).click();
    const row=materials.locator('.ac-material-result');
    const alreadyAdded=row.filter({has:page.getByText('已加入',{exact:true})});
    await alreadyAdded.waitFor();
    check(await alreadyAdded.getByRole('checkbox').isDisabled()&&await alreadyAdded.getByRole('button').isDisabled()
      &&await alreadyAdded.getAttribute('draggable')==='false','A registered card still offered add controls');
    const candidate=materials.locator('.ac-material-result[draggable=true]').first();
    const name=await candidate.locator('strong').innerText();
    const targetRow=row.filter({has:page.getByText(name,{exact:true})});
    await targetRow.getByRole('checkbox').check();
    await button('加入所选资料 (1)',materials).click();
    await targetRow.getByText('已加入',{exact:true}).waitFor();
    check(await targetRow.getByRole('checkbox').isDisabled()&&await targetRow.getByRole('button').isDisabled(),
      'A newly added material did not update its controls');
    await button('撤销修改',canvas).click();
    await targetRow.locator('input:enabled').waitFor();
    check(await targetRow.getByRole('button').isEnabled(),'Undo did not restore the add controls');
    await button('关闭资料库',materials).click();

    const assistant=canvas.locator('.as-panel');
    await button('分析助手',canvas).click();
    const promptChoices=assistant.getByRole('group',{name:'常用提示词'});
    const composer=assistant.getByRole('textbox',{name:'向分析助手提问',exact:true});
    const starts=[];
    const watchStart=request=>{if(new URL(request.url()).pathname==='/api/workbench/assistant/task-start')starts.push(request);};
    page.on('request',watchStart);
    await promptChoices.getByRole('button',{name:'加入相关的工程对象',exact:true}).waitFor();
    check(await promptChoices.getByRole('button').count()===3,'The assistant did not offer three prompts on open');
    await assistant.getByRole('button',{name:/^分析用资料/}).click();
    for(const [kind,entry] of Object.entries(facts.cards)){
      const choice=assistant.getByRole('checkbox',{name:entry.title,exact:true});
      if(kind==='alarm')await choice.check();
      else await choice.uncheck();
    }
    await promptChoices.getByRole('button',{name:'加入相关的工程对象',exact:true}).click();
    check(await composer.inputValue()==='加入相关的工程对象'&&starts.length===0,
      'Choosing a suggestion should fill the composer without sending');
    await composer.press('Shift+Enter');
    check((await composer.inputValue()).endsWith('\n')&&starts.length===0,'Shift+Enter did not insert a newline');
    await composer.press('Backspace');
    await composer.evaluate(input=>input.dispatchEvent(new KeyboardEvent('keydown',{key:'Enter',bubbles:true,isComposing:true})));
    check(starts.length===0,'An Enter used by the input method sent the question');
    const [ack]=await Promise.all([
      page.waitForResponse(response=>new URL(response.url()).pathname==='/api/workbench/assistant/task-ack'),
      composer.press('Enter'),
    ]);
    check(starts.length===1,'Enter did not send exactly one request');
    page.off('request',watchStart);
    const applied=await ack.json();
    check(ack.ok()&&applied.run.result.modelCalls===0&&applied.receipt.state==='applied_draft'&&applied.receipt.analysisRevision===3,
      'The assistant did not apply the verified additions to the unsaved draft');
    check(applied.receipt.items.filter(item=>item.status==='added').length===2&&
      applied.receipt.items.filter(item=>item.status==='already_present').length===1,
      'The assistant did not preserve the existing object while adding the two missing ones');
    const objectCards=canvas.locator('.ad-card[data-card-kind="object"]');
    for(const title of facts.additionalObjectTitles)await button(title,objectCards).waitFor({state:'attached'});
    check(await objectCards.count()===3,'The assistant draft lacked registered alarm objects');
    const objectEdge=(label,title)=>button(`${label}：${facts.cards.alarm.title} → ${title}`,canvas);
    const mainEdge=objectEdge('报警对象',facts.cards.object.title);
    await mainEdge.waitFor({state:'attached'});
    check(await mainEdge.getAttribute('data-origin')==='source','The configured alarm object lost its source relationship');
    for(const title of facts.additionalObjectTitles){
      const checkEdge=objectEdge('排查参考',title);
      await checkEdge.waitFor({state:'attached'});
      const basis=applied.run.result.task.results.find(row=>row.title===title)?.reason;
      check(!!basis&&(await checkEdge.locator('title').textContent()).includes(basis),
        'A suggested object link did not explain the recommendation');
      check(await checkEdge.getAttribute('data-origin')==='candidate'&&
        await checkEdge.locator('path:not(.ac-link-hit)').evaluate(path=>getComputedStyle(path).strokeDasharray!=='none'),
        'An object suggested for troubleshooting did not use a dashed reference link');
    }

    const nonDrawings=canvas.locator('.ad-card[data-card-kind="document"],.ad-card[data-card-kind="photo"]');
    const materialCount=await nonDrawings.count();
    await assistant.getByRole('textbox',{name:'向分析助手提问',exact:true}).fill('添加相关图纸');
    const [drawingAck]=await Promise.all([
      page.waitForResponse(response=>new URL(response.url()).pathname==='/api/workbench/assistant/task-ack'),
      button('发送',assistant).click(),
    ]);
    const drawingRun=await drawingAck.json();
    const result=drawingRun.run.result;
    check(drawingAck.ok()&&result.modelCalls===0&&result.task.results.length===1&&
      result.task.results[0].kind==='drawing'&&result.task.results[0].title===facts.memberDrawingTitle,
      'The drawing request used the project document catalogue or returned a duplicate drawing');
    check(drawingRun.receipt.state==='applied_draft'&&drawingRun.receipt.items.length===1&&drawingRun.receipt.items[0].status==='added',
      'The assistant did not add exactly the missing drawing to the draft');
    await descendantEdge.waitFor({state:'attached'});
    check(await descendantEdge.getAttribute('data-origin')==='source'&&await nonDrawings.count()===materialCount,
      'The assistant added an unrelated material or lost the registered drawing link');
    await button('撤销修改',canvas).click();
    await descendantEdge.waitFor({state:'detached'});

    await composer.fill('先添加相关图纸，再整理画布布局');
    const [compoundAck]=await Promise.all([
      page.waitForResponse(response=>new URL(response.url()).pathname==='/api/workbench/assistant/task-ack'),
      composer.press('Enter'),
    ]);
    const compound=await compoundAck.json();
    check(compoundAck.ok()&&compound.run.result.modelCalls===1&&
      compound.receipt.items.map(item=>item.kind).join(',')==='add_results,arrange'&&await nonDrawings.count()===materialCount,
      'The compound edit did not bind the drawing and arrangement in one draft batch');
    await descendantEdge.waitFor({state:'attached'});
    await button('撤销修改',canvas).click();
    await descendantEdge.waitFor({state:'detached'});

    await button('撤销修改',canvas).click();
    check(await objectCards.count()===1,'Undo did not remove the assistant additions');
    for(const title of facts.additionalObjectTitles)await objectEdge('排查参考',title).waitFor({state:'detached'});
    await composer.fill('加入报警相关资料卡片，分析处置方案');
    const [mixedAck]=await Promise.all([
      page.waitForResponse(response=>new URL(response.url()).pathname==='/api/workbench/assistant/task-ack'),
      composer.press('Enter'),
    ]);
    const mixed=await mixedAck.json();
    check(mixedAck.ok()&&mixed.receipt.items.some(item=>item.kind==='add_results'&&item.status==='added')&&
      mixed.run.result.task.selectedReads[0].state==='complete'&&mixed.run.result.task.disposition,
      'The compound alarm request did not read the alarm and apply the verified materials');
    const powerEdge=canvas.getByRole('button',{name:
      '图纸定位：'+facts.cards.object.title+' → '+facts.powerDrawingTitle,exact:true});
    await powerEdge.waitFor({state:'attached'});
    await assistant.getByText('核对报警接点及报警时间，记录复测结果。',{exact:false}).last().waitFor({state:'visible'});
    await button('撤销修改',canvas).click();
    await powerEdge.waitFor({state:'detached'});

    await button('关闭助手',canvas).click();
    await button('分析助手',canvas).click();
    await promptChoices.getByRole('button',{name:'添加相关图纸',exact:true}).waitFor();
    check(await promptChoices.getByRole('button').count()===3,'Recent prompts were not shown with the restored conversation');

    await canvas.locator('.ad-canvas').press('Escape');
    const rename='把选中的卡片改名为「现场核查对象」';
    const edits=[];
    const trackEdit=request=>{if(new URL(request.url()).pathname==='/api/workbench/assistant/task-start')edits.push(request);};
    page.on('request',trackEdit);
    await composer.fill(rename);
    await composer.press('Enter');
    const review=assistant.locator('.as-turn').last();
    await review.getByRole('heading',{name:'选择要操作的卡片',exact:true}).waitFor();
    check(await review.getByText('还需补充的依据',{exact:true}).count()===0&&
      await review.getByText('使用这份回答',{exact:true}).count()===0,'An unclear edit was shown as an analysis answer');
    const operationCards=review.getByRole('group',{name:'操作卡片列表',exact:true});
    const objectChoice=operationCards.getByRole('checkbox',{name:new RegExp(facts.cards.object.title)});
    const alarmChoice=operationCards.getByRole('checkbox',{name:new RegExp(facts.cards.alarm.title)});
    await objectChoice.check();
    await alarmChoice.check();
    for(const kind of ['alarm','object'])await canvas.locator('.ad-card.selected[data-card-id="'+facts.cards[kind].id+'"]').waitFor({state:'attached'});
    await alarmChoice.uncheck();
    await canvas.locator('.ad-card.selected[data-card-id="'+facts.cards.alarm.id+'"]').waitFor({state:'detached'});
    check(await objectChoice.isChecked()&&edits.length===1,'Selecting edit targets must not submit a request');
    await button('继续原指令',review).click();
    check(await composer.inputValue()===rename&&edits.length===1,'Continuing must place the original instruction in the input');
    const [renameAck]=await Promise.all([
      page.waitForResponse(response=>new URL(response.url()).pathname==='/api/workbench/assistant/task-ack'),
      composer.press('Enter'),
    ]);
    const renamed=await renameAck.json();
    page.off('request',trackEdit);
    check(renameAck.ok()&&edits[1]?.postDataJSON()?.focusCardIds.join(',')===facts.cards.object.id&&
      renamed.receipt.items[0]?.cardId===facts.cards.object.id,'The edit did not use the selected card');
    await button('现场核查对象',objectCards).waitFor({state:'attached'});
    await button('撤销修改',canvas).click();
    await button(facts.cards.object.title,objectCards).waitFor({state:'attached'});

    const workbenchEdges=canvas.locator('.ad-links [data-relation-id]');
    const edgeIds=locator=>locator.evaluateAll(nodes=>nodes.map(node=>node.dataset.relationId).sort());
    await workbenchEdges.filter({hasText:'同次报警趋势'}).waitFor({state:'attached'});
    await workbenchEdges.filter({hasText:'关联图纸'}).waitFor({state:'attached'});
    await canvas.locator('.ad-links [data-origin="manual"]').waitFor({state:'attached'});
    const expected=await edgeIds(workbenchEdges);

    await button('关闭助手',canvas).click();
    await button('新建分析',canvas).click();
    const discard=page.getByRole('button',{name:'放弃并离开',exact:true});
    if(await discard.isVisible())await discard.click();
    await canvas.locator('.ad-card').first().waitFor({state:'detached'});
    await canvas.locator('.ac-add-materials').click();
    await materials.getByRole('button',{name:/^故障报警/}).click();
    const alarmSource=materials.locator('.ac-material-result').filter({hasText:'13003'}).first();
    await alarmSource.getByRole('button',{name:/^加入画布：/}).click();
    const onlyAlarm=canvas.locator('.ad-card[data-card-kind="alarm"]');
    await onlyAlarm.waitFor({state:'attached'});
    await button('关闭资料库',materials).click();
    await button('分析助手',canvas).click();
    const sendLinked=async phrase=>{
      await composer.fill(phrase);
      await button('发送',assistant).and(page.locator(':enabled')).waitFor();
      await composer.press('Enter');
    };
    const assistantResponse=path=>page.waitForResponse(response=>new URL(response.url()).pathname==='/api/workbench/assistant/'+path);
    const alarmDrawingEdges=canvas.locator('.ac-source-link').filter({hasText:'报警关联图纸'});
    const [materialsAck]=await Promise.all([
      assistantResponse('task-ack'),sendLinked('加入相关文档和图纸'),
    ]);
    const relatedMaterials=await materialsAck.json();
    check(materialsAck.ok()&&relatedMaterials.receipt.items.map(item=>item.sourceKind).sort().join(',')==='document,drawing',
      'Adding a manual and a located drawing did not respect the requested material types');
    await alarmDrawingEdges.waitFor({state:'attached'});
    check(await alarmDrawingEdges.getAttribute('data-origin')==='source'&&await objectCards.count()===0,
      'A located drawing required an intermediate engineering object card');
    const [objectAck]=await Promise.all([
      assistantResponse('task-ack'),sendLinked('加入相关的工程对象'),
    ]);
    check(objectAck.ok(),'The registered object could not be added after its drawing');
    await powerEdge.waitFor({state:'attached'});
    await alarmDrawingEdges.waitFor({state:'detached'});
    await button('撤销修改',canvas).click();
    await alarmDrawingEdges.waitFor({state:'attached'});
    await button('撤销修改',canvas).click();
    await alarmDrawingEdges.waitFor({state:'detached'});

    const [wholeDrawingAck]=await Promise.all([
      assistantResponse('task-ack'),sendLinked('加入相关图纸'),
    ]);
    const wholeDrawings=await wholeDrawingAck.json();
    check(wholeDrawingAck.ok()&&wholeDrawings.receipt.items.length===2&&
      wholeDrawings.receipt.items.every(item=>item.sourceKind==='drawing'&&item.status==='added')&&await objectCards.count()===0,
      'A drawing-only request from an alarm card did not add its registered whole pages');
    await alarmDrawingEdges.nth(1).waitFor({state:'attached'});
    check(await alarmDrawingEdges.count()===2,'A whole drawing page was left disconnected');
    await button('撤销修改',canvas).click();
    await alarmDrawingEdges.first().waitFor({state:'detached'});

    const [linkedStart,linkedResponse]=await Promise.all([
      assistantResponse('task-start'),assistantResponse('task-ack'),sendLinked('添加工程对象和图纸'),
    ]);
    const linkedRequest=linkedStart.request().postDataJSON();
    check(JSON.parse(linkedRequest.snapshotJson).cards.map(item=>item.kind).join(',')==='alarm',
      'The screenshot case must start with only the alarm card');
    const linkedResult=await linkedResponse.json();
    const linkedItems=linkedResult.receipt.items;
    check(linkedResponse.ok()&&linkedResult.run.result.modelCalls===0&&
      linkedItems.map(item=>item.sourceKind).join(',')==='object,drawing'&&linkedItems.every(item=>item.status==='added'),
      'The assistant did not automatically apply exactly the directly related object and unique drawing');
    await powerEdge.waitFor({state:'attached'});
    check(await nonDrawings.count()===0&&await objectCards.count()===1&&await onlyAlarm.count()===1,
      'The assistant added an unrelated object, document or photo');
    const receipt=assistant.locator('.as-execution-receipt').last();
    const locate=name=>assistant.getByRole('button',{name:'在画布中定位 · '+name,exact:true}).last();
    await receipt.getByRole('button',{name:'在画布中定位 · '+facts.cards.object.title,exact:true}).waitFor();
    await locate(facts.powerDrawingTitle).click();
    const located=canvas.locator('.ad-card.selected[data-card-kind="drawing"]');
    await located.getByRole('button',{name:facts.powerDrawingTitle,exact:true}).waitFor();
    await located.locator('.ac-photo-view img').waitFor();
    check((await receipt.innerText()).includes('工程对象 · '+facts.cards.object.title+' · 已加入')&&
      (await receipt.innerText()).includes('图纸 · '+facts.powerDrawingTitle+' · 已加入'),
      'The receipt did not show the name, type and completion state of both cards');
    check(!/fixture-|location:supply-|回执编号|\bR[12]\b/.test(await receipt.innerText()),
      'The execution receipt exposed internal source or operation keys');
    await sendLinked('把图纸和工程对象一并加入画布');
    await assistant.locator('.as-turn').last().getByText('查到的关联资料已在画布上。',{exact:false}).waitFor();
    check(await canvas.locator('.ad-card').count()===3,'Repeating the request created a duplicate');
    await button('撤销修改',canvas).click();
    check(await canvas.locator('.ad-card').count()===1,'The two linked additions were not undone together');

    const [typedResponse]=await Promise.all([
      assistantResponse('task-ack'),sendLinked('添加工程对象、图纸、文档、照片'),
    ]);
    const typedResult=await typedResponse.json();
    check(typedResponse.ok()&&typedResult.run.result.modelCalls===0&&
      typedResult.receipt.items.map(item=>item.sourceKind).join(',')==='object,drawing,document,photo',
      'The four requested types fell back to unrelated catalogue rows');
    await button('撤销修改',canvas).click();

    await change('descendant-drawings');
    const referencePhotos=canvas.locator('.ac-source-link').filter({hasText:'设备参考照片'});
    const [cabinetResponse]=await Promise.all([
      assistantResponse('task-ack'),sendLinked('加入工程对象、图纸、照片'),
    ]);
    const cabinetAdditions=await cabinetResponse.json();
    check(cabinetResponse.ok()&&cabinetAdditions.receipt.items.map(item=>item.sourceKind).join(',')==='object,drawing,photo'&&
      cabinetAdditions.receipt.items.some(item=>item.label===facts.memberDrawingTitle),
      'Mixed addition lost the descendant drawing when the alarm object had no direct drawing');
    await referencePhotos.waitFor({state:'attached'});
    check(await referencePhotos.getAttribute('data-origin')==='candidate',
      'A shared cabinet photo was presented as a localized diagram match');
    await button('撤销修改',canvas).click();
    await referencePhotos.waitFor({state:'detached'});

    const [photoFirst]=await Promise.all([assistantResponse('task-ack'),sendLinked('加入照片')]);
    check(photoFirst.ok()&&await canvas.locator('.ad-card[data-card-kind="drawing"]').count()===0,
      'Adding a shared photo also changed unrelated cards');
    const [drawingLater]=await Promise.all([assistantResponse('task-ack'),sendLinked('加入图纸')]);
    check(drawingLater.ok(),'The assistant did not add the drawing after the photo');
    await referencePhotos.waitFor({state:'attached'});
    check(await referencePhotos.count()===1,'The drawing added later did not connect to the existing photo once');
    await button('撤销修改',canvas).click();
    await referencePhotos.waitFor({state:'detached'});
    check(await canvas.locator('.ad-card[data-card-kind="photo"]').count()===1,'Undo removed the pre-existing photo');
    await button('撤销修改',canvas).click();
    await change('restore-drawing-locations');

    await sendLinked('查找名称含合成的工程对象');
    const directory=assistant.locator('.as-project-results').last();
    const choice=name=>directory.getByRole('button',{name:'加入画布 · 工程对象 · '+name,exact:true});
    const [firstObject,secondObject]=facts.additionalObjectTitles;
    await choice(firstObject).waitFor();
    check(!/fixture-|object:1/.test(await directory.innerText()),'Candidate displayed the raw UID or revision');
    await button('放大画布',canvas).click();
    const firstAck=assistantResponse('task-ack');
    await choice(firstObject).click();
    check((await firstAck).ok(),'A candidate could not be added after zooming the same canvas');
    const firstResult=directory.locator('article').filter({hasText:firstObject});
    await firstResult.getByRole('button',{name:'已处理',exact:true}).waitFor();
    check(await firstResult.getByRole('button',{name:'已处理',exact:true}).isDisabled(),'The completed candidate could be re-added');
    const remainingCount=await directory.getByRole('button',{name:/^加入画布 · /}).count();
    check(remainingCount>=2,'The fixture needs multiple remaining candidates');
    const bulkAck=assistantResponse('task-ack');
    await button('全部加入',assistant.locator('.as-task-result').last()).click();
    const bulkResponse=await bulkAck;
    const bulk=await bulkResponse.json();
    check(bulkResponse.ok()&&bulk.receipt.items.length===remainingCount&&bulk.receipt.items.every(item=>item.status==='added'&&item.label!==firstObject),
      'Add all did not apply exactly the remaining candidates in one operation');
    await locate(secondObject).click();
    await button(secondObject,objectCards).waitFor({state:'attached'});
    check(await objectCards.count()===remainingCount+1,'The batch lost an earlier candidate or created a duplicate');
    await button('撤销修改',canvas).click();
    check(await objectCards.count()===1,'Undo did not remove the whole batch at once');

    await sendLinked('查找四类资料候选');
    const floating=canvas.locator('.ad-assistant-window');
    const header=floating.getByRole('group',{name:'移动助手窗口',exact:true});
    check(await header.getByRole('button').count()===1,'The title bar still includes a separate move button');
    const canvasBefore=await canvas.locator('.ad-canvas').boundingBox();
    const before=(await floating.boundingBox());
    await drag(header,-90,40,{x:8,y:7});
    const moved=await floating.boundingBox();
    check(moved.x<before.x-65&&moved.y>before.y+20,'Dragging the title bar padding did not move the assistant');
    await drag(header.getByText('分析助手',{exact:true}),8-moved.x,8-moved.y);
    const overNavigation=await floating.boundingBox();
    check(overNavigation.x<=10&&overNavigation.y<=10&&overNavigation.x<canvasBefore.x&&overNavigation.y<canvasBefore.y,
      'The assistant could not leave the canvas in both directions');
    check(await header.evaluate(node=>{
      const rect=node.getBoundingClientRect();
      return node.contains(document.elementFromPoint(rect.left+10,rect.top+rect.height/2));
    }),'The assistant stopped receiving input over the workbench navigation');
    await header.press('ArrowRight');
    check(Math.abs((await floating.boundingBox()).x-overNavigation.x-12)<2,'The title bar lost keyboard movement');
    await header.press('ArrowLeft');
    await drag(button('向右缩放助手窗口',floating),65,-40);
    const resized=await floating.boundingBox();
    check(resized.width>overNavigation.width+40&&resized.height<overNavigation.height-20,'The assistant did not resize outside the canvas');
    const canvasAfter=await canvas.locator('.ad-canvas').boundingBox();
    check(canvasBefore.width===canvasAfter.width&&canvasBefore.height===canvasAfter.height,'Resizing the assistant changed the canvas layout');
    const headerBox=await header.boundingBox();
    await drag(header,before.x-resized.x,before.y-resized.y,{x:headerBox.width-8,y:7});
    const returned=await floating.boundingBox();
    check(Math.abs(returned.y-before.y)<2&&returned.x>resized.x+60,'Dragging the padding near the close button did not move the assistant');
    for(const [kind,name] of Object.entries(facts.candidateTitles)){
      const candidate=floating.locator('.ac-material-candidate[data-card-kind="'+kind+'"]').last();
      await candidate.getByText(name,{exact:true}).waitFor();
      check(await candidate.evaluate((node,kind)=>{
        const style=getComputedStyle(node),tint=style.getPropertyValue('--card-tint').trim();
        return !!tint&&tint===style.getPropertyValue('--card-'+kind).trim();
      },kind),'The candidate did not use the matching canvas card colour');
      check(JSON.stringify(await candidateStyle(candidate))===JSON.stringify(recommendationStyles[kind]),
        'The recommendation card differs from the assistant card in light or dark mode');
      const previewRequest=assistantResponse('task-source');
      await button('查看详情 · '+name,candidate).click();
      const preview=await previewRequest;
      check(preview.ok()&&(await preview.json()).kind===kind,'Candidate detail did not read the fixed source type');
      const dialog=page.locator('.ac-source-modal');
      await dialog.getByText(/匹配依据/).waitFor();
      if(kind==='document'){
        check(await dialog.getByRole('spinbutton',{name:'文档页码'}).inputValue()==='2','The manual did not open at the matched page');
      }
      if(kind==='drawing'||kind==='photo')await dialog.locator('.ac-photo-view img').waitFor();
      if(kind==='object')await dialog.getByText(/工程分类/).waitFor();
      await page.keyboard.press('Escape');
      await dialog.waitFor({state:'hidden'});
    }
    check(await floating.locator('.as-turn:visible').count()===1,'Previous candidate lists remained expanded');
    const remembered=await floating.boundingBox();
    await button('关闭助手',floating).click();
    await floating.waitFor({state:'detached'});
    await button('分析助手',canvas).click();
    await floating.waitFor();
    const restored=await floating.boundingBox();
    check(['x','y','width','height'].every(key=>Math.abs(restored[key]-remembered[key])<2),
      'Reopening the assistant lost its last position or size');
    await button('本画布对话',floating).click();
    const currentConversation=floating.getByRole('combobox',{name:'当前对话',exact:true});
    check(!(await currentConversation.locator('option').allTextContents()).some(title=>title.includes('加入相关的工程对象')),
      'The scratch canvas showed a conversation from another canvas');

    await canvas.locator('.ad-list-items .ov-list-main').filter({hasText:title}).click();
    await button('放弃并离开',page.getByRole('dialog',{name:'画布有未保存的修改'})).click();
    await button('本画布对话',floating).click();
    await currentConversation.locator('option').filter({hasText:'加入相关的工程对象'}).waitFor({state:'attached'});
    check(!(await currentConversation.locator('option').allTextContents()).some(title=>title.includes('查找四类资料候选')),
      'The assistant showed a scratch-canvas conversation after switching');

    await button('驾驶舱').click();
    const cockpit=page.getByRole('region',{name:'项目驾驶舱'});
    await button('分析工作台',cockpit).click();
    const view=cockpit.getByRole('region',{name:'故障分析展示'});
    await view.getByLabel('当前故障',{exact:true}).selectOption(JSON.stringify([facts.datasetId,facts.datasetRevision]));
    await view.getByLabel('推荐分析画布',{exact:true}).selectOption(facts.analysisId);
    await view.locator('.pa-canvas-caption').getByText(/ · r3 · /).waitFor();
    await view.locator('.pa-relation-label').filter({hasText:'同次报警趋势'}).waitFor({state:'attached'});
    await view.locator('.pa-relation-label').filter({hasText:'关联图纸'}).waitFor({state:'attached'});
    await view.locator('.pa-links path[data-origin="manual"]').waitFor({state:'attached'});
    check(JSON.stringify(await edgeIds(view.locator('.pa-links path[data-relation-id]')))===JSON.stringify(expected),
      'The cockpit did not display the workbench relationships for the same saved revision');
    return {inlinePreviews:previews,previewThemes:['light','dark'],independentCollapse:true,assignedGroup:true,undoRedo:true,savedRevision:3,groupMenuInPanMode:true,relationshipParity:true,duplicateMaterialsDisabled:true,newDrawingLinkedBeforeSave:true,
      drawingRecommendationsMerged:true,alarmDrawingAfterThreeObjects:true,groupedObjectRecommendations:true,assistantAlarmObjectDraft:true,assistantAlarmObjectCheckLinks:true,
      alarmCategoryFirst:true,unifiedRelatedMaterials:true,assistantDrawingLinked:true,assistantCompoundEdit:true,
      recentAssistantPrompts:true,assistantKeyboard:true,assistantAlarmDisposition:true,assistantCardSelection:true,
      assistantLinkedObjectAndDrawing:true,assistantLinkedDedupAndUndo:true,assistantManualAddAfterZoom:true,assistantAddAll:true,
      drawingObjectParentPhotos:true,assistantWindowRestored:true,assistantWholeHeaderDrag:true,
      mixedDescendantDrawings:true,sharedPhotoLinkedAfterDrawing:true,toolbarTextSelectionPrevented:true,
      recommendationCardStylesMatchAssistant:true,
      inlinePhotoWithoutControls:true,expandedPhotoControls:true,
      assistantFourTypes:true,assistantCandidatePreview:true,assistantFloatingWindow:true,assistantCanvasConversationScope:true,compactMaterialRows:true};
  }
  if(phase==='grouped-layout'){
    const plot=canvas.getByRole('region',{name:'可视化分析画布'});
    const rect=locator=>locator.evaluate(node=>({x:parseFloat(node.style.left),y:parseFloat(node.style.top),
      width:parseFloat(node.style.width),height:parseFloat(node.style.height)}));
    const savedRect=({x,y,width,height})=>({x,y,width,height});
    const same=(a,b)=>JSON.stringify(a)===JSON.stringify(b);
    const contains=(frame,card)=>card.x>=frame.x&&card.y>=frame.y&&
      card.x+card.width<=frame.x+frame.width&&card.y+card.height<=frame.y+frame.height;
    const cardNode=id=>plot.locator(`.pa-card[data-card-id="${id}"]`);
    const frameNode=id=>plot.locator(`.pa-frame[data-frame-id="${id}"]`);
    for(const frame of facts.frames){
      await frameNode(frame.id).getByRole('heading',{name:frame.title,exact:true}).waitFor();
      check(same(await rect(frameNode(frame.id)),savedRect(frame)),'The cockpit moved or resized a saved frame');
    }
    for(const card of Object.values(facts.cards)){
      check(same(await rect(cardNode(card.id)),savedRect(card))&&await cardNode(card.id).getAttribute('data-frame-id')===card.frameId,
        'The cockpit changed a saved card position, size or group');
    }
    const card=facts.cards.document,moving=cardNode(card.id),header=moving.locator('header[data-draggable]');
    const owner=facts.frames.find(frame=>frame.id===card.frameId),ownerNode=frameNode(owner.id);
    const path=plot.locator('.pa-links path[data-origin="manual"]');
    await path.waitFor({state:'attached'});
    const startPath=await path.getAttribute('d');
    const start=await header.boundingBox(),board=await plot.boundingBox();
    const startX=start.x+start.width/5,startY=start.y+start.height/2,targetX=board.x+15;
    check(startX-targetX>60,'The fixture has no clear space for dragging left');
    await page.mouse.move(startX,startY);
    await page.mouse.down();
    await page.mouse.move(targetX,startY,{steps:14});
    const moved=await rect(moving),dragged=await header.boundingBox();
    check(moved.x<owner.x-40&&Math.abs(dragged.x-start.x-(targetX-startX))<2,
      'The card stopped at the saved bounds or moved faster than the pointer');
    const expanded=await rect(ownerNode);
    check(expanded.x<owner.x&&expanded.width>owner.width&&contains(expanded,moved),
      'The group frame did not expand around the card while dragging');
    for(const member of Object.values(facts.cards).filter(item=>item.frameId===owner.id&&item.id!==card.id)){
      check(contains(expanded,await rect(cardNode(member.id))),'The expanding frame left a member outside');
    }
    for(const other of facts.frames.filter(frame=>frame.id!==owner.id)){
      check(same(await rect(frameNode(other.id)),savedRect(other)),'Dragging also resized another group');
    }
    await moving.locator('.pa-card-frame').getByText(owner.title,{exact:true}).waitFor();
    check(await path.getAttribute('d')!==startPath,'The saved link did not follow the card');
    await page.mouse.move((targetX+startX)/2,startY,{steps:8});
    const narrowed=await rect(ownerNode);
    check(narrowed.x>expanded.x&&narrowed.width<expanded.width&&contains(narrowed,await rect(moving)),
      'Moving the card inward did not shrink the frame');
    await page.mouse.up();
    check(same(await rect(ownerNode),narrowed),'The frame moved again when the card was released');
    await button('适应全部资料',canvas).click();
    check(contains(await plot.boundingBox(),await ownerNode.boundingBox()),'Fit all clipped the expanded frame');
    await button('恢复布局',canvas).click();
    check(same(await rect(moving),savedRect(card))&&same(await rect(ownerNode),savedRect(owner)),
      'Reset did not restore the saved card and frame');
    const note=cardNode('note-1').locator('.pa-note p');
    const alarm=cardNode(facts.cards.alarm.id).locator('.ac-source-alarm > p');
    await note.waitFor();
    await alarm.waitFor();
    const textPoint=(locator,fraction)=>locator.evaluate((node,fraction)=>{
      const text=document.createTreeWalker(node,NodeFilter.SHOW_TEXT).nextNode();
      const offset=Math.floor((text.length-1)*fraction),range=document.createRange();
      range.setStart(text,offset);
      range.setEnd(text,offset+1);
      const box=range.getBoundingClientRect();
      return {x:box.x+box.width/2,y:box.y+box.height/2};
    },fraction);
    const selectedText=()=>page.evaluate(()=>window.getSelection().toString());
    const startText=await textPoint(note,.15),endText=await textPoint(note,.85),otherText=await textPoint(alarm,.3);
    const dragText=async(start,end,cardId)=>{
      await page.mouse.move(start.x,start.y);
      await page.mouse.down();
      await page.mouse.move(end.x,end.y,{steps:12});
      const stayedInside=()=>page.evaluate(id=>{
        const card=document.querySelector(`.pa-card[data-card-id="${id}"]`),selection=window.getSelection();
        return !!selection.toString().trim()&&card.contains(selection.anchorNode)&&card.contains(selection.focusNode);
      },cardId);
      check(await stayedInside(),'The selection escaped the starting card during the drag');
      await page.mouse.up();
      check(await stayedInside(),'The selection escaped the starting card after the drop');
    };
    await dragText(startText,endText,'note-1');
    const selected=await selectedText();
    await page.context().grantPermissions(['clipboard-read','clipboard-write']);
    await page.keyboard.press('ControlOrMeta+c');
    check(await page.evaluate(()=>navigator.clipboard.readText())===selected,'Text selected inside the card could not be copied');
    await dragText(startText,otherText,'note-1');
    const empty=await plot.boundingBox();
    await page.mouse.click(empty.x+8,empty.y+empty.height/2);
    check(await selectedText()==='','Clicking the canvas background did not clear the card selection');
    await dragText(otherText,endText,facts.cards.alarm.id);
    await page.mouse.click(endText.x,endText.y);
    check(await selectedText()==='','Clicking another card did not clear the selection');
    const assistant=canvas.getByRole('complementary',{name:'工程助手',exact:true});
    const query=assistant.getByRole('textbox',{name:'向分析助手提问',exact:true});
    await query.fill('拖动验收草稿');
    const assistantHeader=assistant.locator(':scope > header');
    const previousSize=await page.viewportSize(),assistantStart=await assistant.boundingBox(),grip=await assistantHeader.boundingBox();
    const grabX=24,grabY=grip.y-assistantStart.y+grip.height/2;
    await page.mouse.move(assistantStart.x+grabX,assistantStart.y+grabY);
    await page.mouse.down();
    await page.mouse.move(12+grabX,16+grabY,{steps:16});
    await page.mouse.up();
    const outside=await assistant.boundingBox(),canvasBounds=await plot.boundingBox();
    check(outside.x<canvasBounds.x&&outside.y<canvasBounds.y&&Math.abs(outside.x-12)<2&&Math.abs(outside.y-16)<2,
      'The assistant did not follow the pointer beyond the canvas');
    check(await assistantHeader.evaluate(node=>{
      const {x,y,height}=node.getBoundingClientRect();
      return node.contains(document.elementFromPoint(x+24,y+height/2));
    }),'The floated header is clipped or blocked by the cockpit');
    check(await query.inputValue()==='拖动验收草稿','Floating the assistant discarded its draft');
    await page.screenshot({path:'cockpit-assistant-outside-canvas.png'});
    const leftGrip=button('向左缩放助手窗口',assistant),rightGrip=button('向右缩放助手窗口',assistant);
    const near=(a,b)=>Math.abs(a-b)<2;
    await drag(rightGrip,70,-48);
    const wider=await assistant.boundingBox();
    check(near(wider.x,outside.x)&&near(wider.y,outside.y)&&near(wider.width,outside.width+70)&&near(wider.height,outside.height-48),
      'Dragging the lower-right handle did not keep the top-left corner fixed');
    await drag(leftGrip,54,26);
    const narrower=await assistant.boundingBox();
    check(near(narrower.x,wider.x+54)&&near(narrower.width+54,wider.width)&&near(narrower.height,wider.height+26),
      'Dragging the lower-left handle did not keep the right edge fixed');
    await rightGrip.press('Shift+ArrowRight');
    const resized=await assistant.boundingBox();
    check(near(resized.width,narrower.width+40)&&near(resized.height,narrower.height),
      'The resize handle did not respond to the keyboard');
    check(same(await plot.boundingBox(),canvasBounds),'Resizing the assistant also resized the canvas');
    await button('收起工程助手',assistant).click();
    await assistant.waitFor({state:'hidden'});
    await button('展开工程助手',canvas).click();
    const reopened=await assistant.boundingBox();
    check(['x','y','width','height'].every(key=>near(reopened[key],resized[key]))&&await query.inputValue()==='拖动验收草稿',
      'Expanding the floated assistant changed its geometry or discarded its draft');
    await drag(rightGrip,60-reopened.width,60-reopened.height);
    const smallest=await assistant.boundingBox();
    check(near(smallest.width,300)&&near(smallest.height,340),'The assistant could be shrunk beyond its usable size');
    check(await button('发送',assistant).evaluate(node=>{
      const {x,y,width,height}=node.getBoundingClientRect();
      return node.contains(document.elementFromPoint(x+width/2,y+height/2));
    }),'The composer became inaccessible at the minimum size');
    await query.fill('');
    await button('发送',assistant).scrollIntoViewIfNeeded();
    await query.fill('拖动验收草稿');
    await drag(rightGrip,200,270);
    await page.screenshot({path:'cockpit-assistant-resized.png'});
    await page.setViewportSize({width:950,height:540});
    await page.waitForFunction(()=>{
      const {left,top,right,bottom}=document.querySelector('.pa-assistant[data-floating]').getBoundingClientRect();
      return left>=0&&top>=0&&right<=innerWidth&&bottom<=innerHeight;
    });
    await button('恢复停靠至右侧',assistant).click();
    check(await assistant.getAttribute('data-floating')===null&&await rightGrip.count()===0,
      'Docking did not restore the side panel');
    await page.setViewportSize(previousSize);
    return {groups:facts.frames.length,cards:await plot.locator('.pa-card').count(),dragPastBounds:true,
      expands:true,shrinks:true,linkFollows:true,fit:true,reset:true,cardTextSelection:true,copySelectedText:true,
      assistantBeyondCanvas:true,assistantDraftRetained:true,assistantDocked:true,assistantResizable:true,assistantSizeRetained:true};
  }
  const kind = photoPhase?'photo':phase==='withdraw-document'?'document':phase==='expire-session'?'work_order':'drawing';
  const target=facts.cards[kind];
  const card=canvas.locator('[data-card-id="'+target.id+'"]');
  const open=button((cockpit?'放大查看：':'')+target.title,card);
  const dialog=page.getByRole('dialog',{name:target.title,exact:true});
  if(cockpit) await open.focus();

  if(photoPhase){
    await open.click();
    const image=dialog.locator('.ac-photo-view img');
    await image.waitFor();
    const url=await image.evaluate(async node=>{await node.decode();return node.currentSrc;});
    await button('关闭',dialog).click();
    await dialog.waitFor({state:'hidden'});
    const readable=()=>page.evaluate(url=>fetch(url).then(response=>response.ok,()=>false),url);
    check(await readable(),'Closed photo had no retained preview to check');
    if(phase==='withdraw-photo'){
      await change('withdraw-photo');
      await open.click();
      await dialog.getByRole('status').getByText('资料访问已撤销',{exact:true}).waitFor();
      check(await image.count()===0&&!await readable(),'Revoked photo reopened from the old preview cache');
      return {photoDenied:true,cachedPreviewRevoked:true,cockpit:true};
    }
    await button('项目中心').click();
    await page.getByRole('button',{name:/^Q-26 另一项目 B/}).click();
    await button('进入项目').click();
    await page.getByRole('heading',{name:'场景与可视化',exact:true}).waitFor();
    check(await dialog.count()===0&&!await readable(),'The new project retained the previous project photo preview');
    return {photoClearedOnProjectSwitch:true,cachedPreviewRevoked:true,cockpit:false};
  }
  if(phase==='switch-project'){
    const held=heldDrawing;
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
      await restricted.screenshot({path:'isolated-13003-document-revoked.png'});
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
