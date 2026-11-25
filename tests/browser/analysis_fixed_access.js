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
    const card=kind=>canvas.locator('.ad-card[data-card-id="'+facts.cards[kind].id+'"]');
    const previews=['document','photo','drawing'];
    const image=kind=>card(kind).locator('.ac-photo-view img');
    await Promise.all(previews.map(async kind=>{
      await image(kind).waitFor();
      check(await image(kind).evaluate(async node=>{await node.decode();return node.naturalWidth>0;}),
        'The '+kind+' preview did not render automatically');
    }));
    await button('收起预览：'+facts.cards.photo.title,card('photo')).click();
    await image('photo').waitFor({state:'hidden'});
    await button('打开照片', card('photo')).waitFor();
    check(await image('document').isVisible()&&await image('drawing').isVisible(),'Collapsing a photo closed another preview');
    await button('打开照片',card('photo')).click();
    await image('photo').waitFor();

    const target=card('drawing'),original=facts.cards.drawing;
    const targetGroup=facts.frames.find(group=>group.id!==original.frameId);
    await target.getByRole('button',{name:'更多操作： '+original.title,exact:true}).click();
    await page.getByRole('menuitem',{name:'设置分组',exact:true}).click();
    const group=canvas.getByLabel('所属分组',{exact:true});
    check(await group.inputValue()===original.frameId,'The inspector reported the wrong starting group');
    await group.selectOption({label:targetGroup.title});
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
    return {inlinePreviews:previews,independentCollapse:true,assignedGroup:true,undoRedo:true,savedRevision:3};
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
    return {groups:facts.frames.length,cards:await plot.locator('.pa-card').count(),dragPastBounds:true,
      expands:true,shrinks:true,linkFollows:true,fit:true,reset:true,cardTextSelection:true,copySelectedText:true};
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
