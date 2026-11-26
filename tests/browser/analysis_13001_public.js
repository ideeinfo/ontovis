async (page, origin, fixed, mode) => {
  const root = '/api/workbench/analysis-sessions';
  const projectRef = {ontobaseConnectionId:'ontobase-primary',projectCode:'Demo-PDS'};
  const button = (name,within=page) => within.getByRole('button',{name,exact:true});
  const check = (condition,message) => { if (!condition) throw Error(message); };
  const active = await (await page.request.get(origin+'/api/session')).json();
  check(active.state==='active','The fixed evidence check needs an authenticated session');
  const read = async (route,fields) => {
    const response = await page.request.post(origin+root+route,{headers:{Origin:origin},data:{
      expectedSessionRevision:active.sessionRevision,projectRef,analysisSessionId:fixed.analysisSessionId,...fields
    }});
    check(response.ok(), route+' returned HTTP '+response.status());
    return response.json();
  };
  const before = await read('/detail',{analysisRevision:fixed.analysisRevision});
  check(before.analysisRevision===fixed.analysisRevision&&before.contentSha256===fixed.contentSha256
    &&before.snapshot.context.faultCode==='13001'&&before.snapshot.context.datasetId==='SIM-PDS-13001'
    &&before.snapshot.context.datasetRevision===fixed.datasetRevision,'The fixed analysis does not match the 13001 acceptance case');
  const title = before.snapshot.title;
  const {items} = await read('/evidence/batch',{evidenceRefIds:fixed.cards.map(card=>card.evidenceRefId)});
  const sourceFields = {
    document:['documentId','contentVersionId','knowledgeReleaseId','sourceSha256','pageNumber'],
    drawing:['drawingUid','contentSha256','pageNumber'],
    work_order:['orderId','orderRevision'],
  };
  const targets = fixed.cards.map(card=>{
    const pin = before.snapshot.cards.find(row=>row.id===card.cardId);
    const row = items.find(item=>item.evidenceRefId===card.evidenceRefId);
    check(pin?.kind===card.kind&&pin.source?.id===card.evidenceRefId&&pin.source.revision===card.sourceRevision,
      'The canvas reference changed for '+card.kind);
    check(row?.availability==='available'&&row.sourceKind===card.kind&&row.sourceRevision===card.sourceRevision
      &&sourceFields[card.kind].every(key=>row.source[key]===card[key]),
      'The fixed source changed for '+card.kind+' '+(card.pageNumber??card.orderRevision));
    if (card.kind==='work_order') check(row.source.sourceKind==='simulated','The historical work order lost its simulation label');
    return {...card,title:pin.title};
  });
  const writes = [];
  const observe = request => {
    const path = new URL(request.url()).pathname;
    if (request.method()==='POST'&&/\/api\/workbench\/(?:analysis-sessions\/(?:create|save|copy|start|trash|untrash|link-work-order|evidence\/register(?:-batch)?)|work-orders\/(?:workflow|create)|assistant\/(?:task-start|task-prepare|task-apply))$/.test(path)) writes.push(path);
  };
  page.on('request',observe);
  try {
    await page.setViewportSize({width:1500,height:956});
    await page.goto(origin+'/');
    await page.getByRole('button',{name:/^PDS风电场 Demo-PDS/}).click();
    await button('进入项目').click();
    let canvas;
    if (mode==='workbench') {
      await button('分析画布').click();
      canvas = page.getByRole('region',{name:'分析工作空间'});
      const search = canvas.getByRole('textbox',{name:'搜索画布',exact:true});
      await search.fill(title);
      await search.press('Enter');
      await canvas.locator('.ad-list-items .ov-list-main').filter({hasText:title}).click();
      await canvas.locator('.ad-heading').getByText('已保存 · r'+fixed.analysisRevision,{exact:true}).waitFor();
      await button('适应全部',canvas).click();
    } else {
      await button('驾驶舱').click();
      const cockpit = page.getByRole('region',{name:'项目驾驶舱'});
      await button('分析工作台',cockpit).click();
      canvas = cockpit.getByRole('region',{name:'故障分析展示'});
      await canvas.getByLabel('当前故障',{exact:true}).selectOption(JSON.stringify(['SIM-PDS-13001',fixed.datasetRevision]));
      await canvas.getByLabel('推荐分析画布',{exact:true}).selectOption(fixed.analysisSessionId);
      await canvas.locator('.pa-canvas-caption').getByText(title,{exact:true}).waitFor();
      await canvas.locator('.pa-canvas-caption').getByText(new RegExp(' · r'+fixed.analysisRevision+' · ')).waitFor();
      await button('适应全部资料',canvas).click();
    }

    const sources = [];
    for (const target of targets) {
      const card = canvas.locator('[data-card-id="'+target.cardId+'"]');
      const open = button(mode==='workbench'?target.title:'放大查看：'+target.title,card);
      if (mode==='cockpit') await open.focus();
      await open.click();
      const dialog = page.getByRole('dialog',{name:target.title,exact:true});
      await dialog.waitFor();
      const rendered = {
        kind:target.kind,sourceRevision:target.sourceRevision,
        ...Object.fromEntries(sourceFields[target.kind].map(key=>[key,target[key]]))
      };
      if (target.kind==='work_order') {
        const identity = dialog.locator('.ho-identity,.wov-record-identity').filter({hasText:target.orderId});
        await identity.waitFor();
        const text = await identity.innerText();
        check(text.includes('r'+target.orderRevision)&&text.includes('测试'),'The dialog did not show the fixed test work order');
      } else {
        if (target.kind==='document') {
          await dialog.getByRole('tab',{name:'正文',exact:true}).click();
          const pageNumber = await dialog.getByRole('spinbutton',{name:'文档页码'}).inputValue();
          check(Number(pageNumber)===target.pageNumber,'The original viewer opened another manual page');
        }
        const img = dialog.locator('img').first();
        await img.waitFor({timeout:45000});
        rendered.imageSha256 = await img.evaluate(async node=>{
          await node.decode();
          if (node.naturalWidth<1||!node.currentSrc.startsWith('blob:')) throw Error('The preview did not render fixed image content');
          const bytes = await (await fetch(node.currentSrc)).arrayBuffer();
          const digest = await crypto.subtle.digest('SHA-256',bytes);
          return Array.from(new Uint8Array(digest),byte=>byte.toString(16).padStart(2,'0')).join('');
        },undefined,{timeout:30000});
      }
      if (mode==='cockpit') {
        check(await dialog.getByRole('button',{name:/工单进展|打开引用图纸并放入画布|采用此版本|保存/}).count()===0,
          'A cockpit evidence dialog offered an editing action');
      }
      const qualifier = target.pageNumber??target.orderRevision;
      await dialog.screenshot({path:'public-13001-'+mode+'-'+target.kind+'-'+qualifier+'.png'});
      await button('关闭',dialog).click();
      await dialog.waitFor({state:'hidden'});
      sources.push(rendered);
    }
    const after = await read('/detail',{analysisRevision:fixed.analysisRevision});
    check(after.contentSha256===before.contentSha256&&after.headRevision===before.headRevision&&writes.length===0,
      'Viewing fixed evidence changed the canvas or invoked an assistant run');
    return {analysisRevision:fixed.analysisRevision,analysisSha256:fixed.contentSha256,readOnly:true,sources};
  } finally {
    page.off('request',observe);
  }
}
