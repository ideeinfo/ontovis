async (page, facts, phase) => {
  const origin = facts.origin;
  const root = '/api/workbench/work-orders';
  const button = (name, within=page) => within.getByRole('button',{name,exact:true});
  const dialog = name => page.getByRole('dialog',{name,exact:true});
  const detail = page.locator('.wov-detail');
  const check = (value, message) => { if(!value) throw Error(message); };
  const ordered = value => {
    if (Array.isArray(value)) return value.map(ordered);
    if (!value || typeof value !== 'object') return value;
    return Object.fromEntries(Object.keys(value).sort().map(key=>[key,ordered(value[key])]));
  };
  const read = async (body, route='workflow-detail') => {
    const response = await post(route,body);
    check(response.status===200, route+' was refused: '+response.status+' '+response.body.code);
    return response.body;
  };
  const post = async (route,body) => {
    const active = await (await page.request.get(origin+'/api/session')).json();
    const response = await page.request.post(origin+root+(route?'/'+route:''),{headers:{Origin:origin},
      data:{expectedSessionRevision:active.sessionRevision,
        projectRef:{ontobaseConnectionId:'ontobase-primary',projectCode:facts.projectCode},...body}});
    return {status:response.status(), body:await response.json()};
  };
  const waitReply = (route, exactAction) => page.waitForResponse(response => (
    new URL(response.url()).pathname===root+'/'+route&&response.request().method()==='POST'
    &&(!exactAction||response.request().postDataJSON().action===exactAction)));
  const noControls = async (labels, within=page) => {
    for(const label of labels) check(!await button(label,within).isVisible(),'Unexpected control '+label);
  };
  const open = async user => {
    await page.setViewportSize({width:1440,height:960});
    await page.goto(origin+'/');
    await button('登录').click();
    const login=dialog('登录 ONTOVis');
    await login.getByLabel('用户名').fill(user);
    await login.getByLabel('密码').fill('synthetic-only');
    await button('登录',login).click();
    await page.getByRole('button',{name:/Demo-PDS/}).first().click();
    await button('进入项目').click();
  };
  const selected = async () => {
    await button('工单').click();
    const row = page.locator('.wov-order-list button').filter({hasText:'Q-26 隔离验收 · 13002 来自报警'});
    await row.click();
    await detail.getByRole('heading',{name:'Q-26 隔离验收 · 13002 来自报警'}).waitFor();
  };
  const orderId = facts.orderId;
  if (phase==='create') {
    await open('writer');
    await button('数据与告警').click();
    const alarms=page.getByRole('region',{name:'数据与告警'});
    await alarms.getByRole('button',{name:/^13002 · 柜温低报警/}).click();
    await alarms.getByRole('heading',{name:/柜温低报警/}).waitFor();
    await button('相关工单',alarms).click();
    check(await page.getByLabel('搜索工单').inputValue()==='13002','Search should carry the fault code');
    await button('从报警发起工单').click();
    const modal=dialog('新建工单');
    const code=modal.getByLabel('故障码（选填）');
    check(await code.inputValue()==='13002'&&await code.isDisabled(),'Alarm fault code is not fixed');
    check(await modal.getByRole('checkbox',{name:'模拟工单'}).isChecked(),'Simulation label is missing');
    await modal.getByLabel('标题').fill('Q-26 隔离验收 · 13002 来自报警');
    await modal.getByLabel('问题说明').fill('来自现有 13002 模拟报警。用于隔离软件验收。');
    await page.screenshot({path:'isolated-13002-prefill.png'});
    const wait=waitReply('create');
    await button('提交工单',modal).click();
    const reply=await wait;
    const body=reply.request().postDataJSON();
    const created=await reply.json();
    check(reply.status()===200&&created.orderRevision===1&&!created.existing,'Creation failed');
    check(body.alarm.datasetId===facts.alarm.datasetId&&body.alarm.datasetRevision===facts.alarm.datasetRevision,
      'Alarm source revision is missing');
    const orderId=created.orderId;
    const replay=await read(body,'create');
    const newRequest=await read({...body,requestId:crypto.randomUUID()},'create');
    check(replay.orderId===orderId&&replay.orderRevision===1&&!replay.existing,'Exact replay changed result');
    check(newRequest.orderId===orderId&&newRequest.existing,'Same alarm created a duplicate');
    const listing=await read({q:'13002',limit:20},'');
    check(listing.total===1&&listing.items[0].orderId===orderId,'Unexpected order count');
    const order=await read({orderId});
    check(order.sourceKind==='simulated'&&order.workflow.source.identity.datasetId===facts.alarm.datasetId
      &&order.workflow.source.identity.datasetRevision===facts.alarm.datasetRevision
      &&order.workflow.equipment==='=WEC+CN1-1B4'&&order.state==='pending'&&order.events.length===1,
      'The order lost alarm context');
    await detail.locator('.wov-header').getByText('待处理',{exact:true}).waitFor();
    await detail.getByText('更多操作',{exact:true}).click();
    await button('分派',detail).click();
    const assign=dialog('分派处理人');
    await assign.locator('option').filter({hasText:'other'}).waitFor({state:'attached'});
    await assign.getByRole('combobox',{name:'处理人',exact:true}).selectOption({label:'other'});
    const assignment=waitReply('workflow','assign');
    await button('确认分派',assign).click();
    const assigned=await assignment;
    const treatment=await assigned.json();
    check(assigned.status()===200&&treatment.state==='processing'&&treatment.handler.name==='other'
      &&treatment.orderRevision===2,'Wrong assignment result');
    await detail.getByText('处理人 other',{exact:true}).waitFor();
    await noControls(['保存记录','完成处理'],detail);
    const unassigned=await post('workflow',{orderId,expectedOrderRevision:2,requestId:crypto.randomUUID(),
      action:'record',text:'unassigned write'});
    check(unassigned.status===403&&unassigned.body.code==='WORK_ORDER_HANDLER_REQUIRED',
      'An unassigned admin could process this order');
    const readOnly=await read({orderId,workOrderView:'cockpit'});
    check(!readOnly.canManage&&!readOnly.canProcess&&!readOnly.canAttach,'Cockpit response exposed capabilities');
    const cockpit=await post('workflow',{orderId,expectedOrderRevision:2,action:'record',
      requestId:crypto.randomUUID(),text:'query only',workOrderView:'cockpit'});
    check(cockpit.status===403&&cockpit.body.code==='WORK_ORDER_QUERY_ONLY','Cockpit write was allowed');
    return {orderId,createdRevision:1,assignedRevision:2,duplicateSubmissions:2,
      unassignedAdminStatus:unassigned.status,cockpitWriteStatus:cockpit.status,
      source:order.workflow.source.identity,sourceTime:order.alarmAt,initialSha256:order.snapshotSha256};
  }
  if (phase==='treat') {
    await open('other');
    await selected();
    await button('相关分析',detail).click();
    const candidate=detail.locator('article').filter({hasText:facts.title});
    await candidate.getByText(/r2.*同故障码.*同代码体系.*同设备标记/).waitFor();
    await button('采纳此分析',candidate).click();
    const adoption=waitReply('workflow','adopt_analysis');
    await button('确认采纳此版本',dialog('采纳分析')).click();
    const adopted=await adoption, choice=await adopted.json();
    const fixed=choice.workflow.adoptedAnalysis;
    check(adopted.status()===200&&choice.orderRevision===3&&fixed.analysisSha256===facts.analysis.analysisSha256
      &&fixed.analysisRevision===2&&fixed.analysisSessionId===facts.analysis.analysisSessionId,'Adoption picked an incorrect revision');
    await detail.getByText(/本单采用 · r2/).waitFor();
    await page.screenshot({path:'isolated-13002-adopted.png'});
    await button('处理记录',detail).click();
    await detail.getByLabel('新增处置记录').fill(facts.text);
    const workflowRoute='**'+root+'/workflow';
    let originalBody, unreceived;
    const dropReceipt=async route=>{
      const body=route.request().postDataJSON();
      if(body.action!=='record'||originalBody) return route.continue();
      originalBody=body;
      const committed=await route.fetch({maxRetries:0});
      check(committed.status()===200,'The record did not commit before disconnect');
      unreceived=await committed.json();
      await route.abort('failed');
    };
    await page.route(workflowRoute,dropReceipt);
    try {
      await button('保存记录',detail).click();
      await page.getByRole('alert').filter({hasText:'提交结果待确认'}).waitFor();
      check(await detail.getByLabel('新增处置记录').inputValue()===facts.text,'The failed receipt discarded the input');
      await page.screenshot({path:'isolated-13002-lost-receipt.png'});
    } finally {
      await page.unroute(workflowRoute,dropReceipt);
    }
    const saved=waitReply('workflow','record');
    await button('检查结果').click();
    const savedReply=await saved;
    const savedBody=savedReply.request().postDataJSON();
    const record=await savedReply.json();
    check(savedBody.requestId===originalBody.requestId&&JSON.stringify(savedBody)===JSON.stringify(originalBody),
      'Checking the result did not send the original request');
    check(JSON.stringify(ordered(record))===JSON.stringify(ordered(unreceived)),
      'The replay receipt differed from the committed result');
    check(savedReply.status()===200&&record.orderRevision===4&&record.workflow.records.length===1
      &&record.workflow.records[0].basis.analysisSha256===fixed.analysisSha256,'Treatment receipt is missing evidence');
    const [r1,r2]=await Promise.all([read(savedBody,'workflow'),read(savedBody,'workflow')]);
    check(r1.orderRevision===4&&r2.orderRevision===4&&r1.workflow.records[0].recordId===r2.workflow.records[0].recordId,
      'Replayed submissions created duplicate records');
    const stale=await post('workflow',{...savedBody,requestId:crypto.randomUUID(),text:'stale request'});
    check(stale.status===409&&stale.body.code==='WORK_ORDER_CHANGED','Stale revision write was allowed');
    await detail.getByText(facts.text,{exact:true}).waitFor();
    await button('完成处理',detail).click();
    const modal=dialog('完成处理');
    await modal.getByRole('combobox',{name:'使用已保存记录',exact:true}).selectOption(record.workflow.records[0].recordId);
    const completion=waitReply('workflow','complete');
    await button('确认完成',modal).click();
    const done=await completion, state=await done.json();
    check(done.status()===200&&state.state==='completed'&&state.orderRevision===5
      &&state.workflow.result.text===facts.text,'The saved record did not become the result');
    await detail.locator('.wov-header').getByText('已完成',{exact:true}).waitFor();
    await noControls(['归档','重新处理'],detail);
    return {revisions:[3,4,5],analysisRevision:fixed.analysisRevision,analysisSha256:fixed.analysisSha256,
      disconnectedAfterCommit:true,originalRequestRetried:true,replayCount:3,staleStatus:stale.status,
      recordId:record.workflow.records[0].recordId,replayBody:savedBody};
  }
  if (phase==='revoke') {
    const denied=await post('workflow',facts.replayBody);
    check(denied.status===403&&denied.body.code==='FORBIDDEN','Revoked account replay was allowed');
    await button('重新读取工单',detail).click();
    await page.getByRole('heading',{name:'项目中心',exact:true}).waitFor();
    check(!await detail.isVisible()&&!await page.getByText(facts.text,{exact:true}).isVisible(),
      'Protected details remained visible after revocation');
    return {revokedReplayStatus:denied.status,protectedUIAbsent:true};
  }
  if (phase==='archive') {
    await button('重新读取工单',detail).click();
    await detail.locator('.wov-header').getByText('已完成',{exact:true}).waitFor();
    await button('归档',detail).click();
    const modal=dialog('将工单归档？');
    const archive=waitReply('workflow','archive');
    await button('归档工单',modal).click();
    const receipt=await archive, body=receipt.request().postDataJSON(), value=await receipt.json();
    check(receipt.status()===200&&value.orderRevision===6&&value.state==='archived','Archive failed');
    const replay=await read(body,'workflow');
    check(replay.orderRevision===6&&value.events.length===6&&replay.events.length===6,
      'An archive replay appended another event');
    const archived=await read({orderId});
    const fixed=await read({orderId,orderRevision:6,snapshotSha256:archived.snapshotSha256},'snapshot');
    check(fixed.workflow.adoptedAnalysis.analysisSha256===facts.analysis.analysisSha256
      &&fixed.workflow.result.recordId===facts.recordId&&fixed.workflow.result.text===facts.text,
      'Archived work order did not retain the fixed analysis and result');
    const old = await read({orderId,orderRevision:1,snapshotSha256:facts.initialSha256},'snapshot');
    check(old.state==='pending'&&old.workflow.records.length===0,'The old revision changed');
    await detail.locator('.wov-header').getByText('已归档',{exact:true}).waitFor();
    await page.screenshot({path:'isolated-13002-archived.png'});
    return {archiveRevision:6, events:fixed.events.map(event=>event.action), oldRevision:old.orderRevision,
      archiveSha256:archived.snapshotSha256, resultMatches:true, replayMatches:true};
  }
  if (phase==='view') {
    await open('reader');
    await selected();
    await detail.locator('.wov-header').getByText('已归档',{exact:true}).waitFor();
    check(await detail.getByText(facts.text,{exact:true}).count()>0,'The viewer lost the archived treatment');
    await noControls(['新建工单','保存记录','归档','重新处理','添加附件']);
    await button('相关分析',detail).click();
    await button('查看分析',detail).click();
    const ref=page.getByRole('dialog').getByText(/r2/);
    await ref.first().waitFor();
    const info=await read({orderId});
    check(!info.canManage&&!info.canProcess&&!info.canAttach&&info.orderRevision===6,'Viewer capabilities incorrect');
    const denied=await post('workflow',{orderId,expectedOrderRevision:6,requestId:crypto.randomUUID(),
      action:'reopen',reason:'read-only validation'});
    check(denied.status===403&&denied.body.code==='WORK_ORDER_WRITE_FORBIDDEN','Viewer could reopen order');
    return {viewerRevision:info.orderRevision,viewerWriteStatus:denied.status,fixedAnalysisVisible:true};
  }
  throw Error('Unknown test phase');
}
