async (page, {origin, release}) => {
  const check = (value, message) => { if (!value) throw Error(message); };
  const healthResponse = await page.request.get(origin + '/health');
  check(healthResponse.ok(), 'Could not read the deployed version');
  const health = await healthResponse.json();
  check(health.status === 'ok' && health.frontendRelease === release && health.backendRelease === release,
    'The deployed version differs from the release under test');
  const active = await (await page.request.get(origin + '/api/session')).json();
  check(active.state === 'active', 'The browser session is not active');
  const projectRef = {ontobaseConnectionId:'ontobase-primary',projectCode:'Demo-PDS'};
  const orders = '/api/workbench/work-orders';
  const analyse = '/api/workbench/analysis-sessions';
  const call = async (path, fields, status = 200) => {
    const reply = await page.request.post(origin + path, {headers:{Origin:origin}, data:{
      ...fields,projectRef,expectedSessionRevision:active.sessionRevision}});
    check(reply.status() === status, path + ' returned HTTP ' + reply.status());
    return reply.json();
  };
  const before = await retained();
  const readOnly = {orderId:before[0].orderId,workOrderView:'cockpit'};
  const detail = await call(orders+'/workflow-detail',readOnly);
  check(!detail.canManage && !detail.canProcess && !detail.canAttach, 'Cockpit returned writable capabilities');
  const denied = await call(orders+'/workflow',readOnly,403);
  check(denied.code === 'WORK_ORDER_QUERY_ONLY', 'The cockpit write guard did not run');
  const catalogue = await call(analyse+'/simulation/catalogue',{});
  const alarmSource = catalogue.items.find(item=>item.datasetId === 'SIM-PDS-13002');
  check(alarmSource?.faultCode === '13002' && alarmSource.sourceKind === 'simulated', 'The 13002 simulation is unavailable');
  const replaySource = await call(analyse+'/simulation/detail',{
    datasetId:alarmSource.datasetId,datasetRevision:alarmSource.datasetRevision
  });
  check(replaySource.alarms.map(event=>event.state).join(',') === 'active,cleared','The fixed alarm events changed');

  await page.setViewportSize({width:1500,height:956});
  await page.goto(origin+'/');
  const button = (name, within=page) => within.getByRole('button',{name,exact:true});
  await page.getByRole('button',{name:/Demo-PDS/}).first().click();
  await button('进入项目').click();
  await button('驾驶舱').click();
  const root = page.getByRole('region',{name:'项目驾驶舱'});
  const nav = root.getByRole('navigation',{name:'驾驶舱页面'});
  const alarms = root.getByRole('complementary',{name:'模拟报警概览'});
  const alarm = alarms.getByRole('button',{name:/^13002 · 柜温低报警/});
  const selector = alarms.getByLabel('报警目标设备');
  await selector.waitFor({timeout:30000});
  await selector.selectOption({label:'本源1号风机'});
  if (!await alarm.isVisible()) {
    const more = alarms.getByRole('button',{name:/下|Next/}).last();
    if(await more.isVisible()) await more.click();
  }
  await alarms.getByRole('button',{name:/^13002 · 柜温低报警.*CN1/}).waitFor({timeout:45000});
  const label = await alarm.getAttribute('aria-label');
  if (!label.includes('CN1')) throw Error('The alarm equipment must be CN1');
  await alarm.click({timeout:25000});
  const spatial = root.locator('.pc-spatial');
  const deviceCard = spatial.locator('.pc-device-card');
  const equipment = deviceCard.getByRole('heading',{name:/CN1 机舱动力柜/});
  await equipment.waitFor({timeout:45000});
  const status = spatial.locator('.pc-tree-tools [role=status]');
  await status.getByText('已定位',{exact:true}).waitFor({timeout:45000});
  await spatial.locator('.pc-model-dock').waitFor({timeout:30000});
  await page.screenshot({path:'public-13002-device.png'});
  await button('报警详情',root).click();
  const replay = page.getByRole('dialog',{name:'模拟报警回放',exact:true});
  await replay.getByRole('heading',{name:/柜温低报警/}).waitFor({timeout:20000});
  await button('相关工单', replay).click();
  const orderQuery = root.getByRole('textbox',{name:'搜索工单',exact:true});
  await orderQuery.waitFor({timeout:25000});
  if (await orderQuery.inputValue() !== '13002') throw Error('The alarm code is missing in related orders');
  for (const label of ['新建工单','从报警发起工单','保存记录','归档']) {
    if (await button(label,root).isVisible()) throw Error('Write control appeared in the cockpit');
  }
  await page.screenshot({path:'public-13002-orders.png'});
  const after = await retained();
  check(JSON.stringify(after) === JSON.stringify(before), 'A previously saved order or analysis reference changed');
  return {equipment:label.split(' · ').at(-1),code:'13002',located:true,readOnly:true,cockpitWriteStatus:403,
    sourceRelease:health.sourceRelease,datasetRevision:alarmSource.datasetRevision,orders:before};

  async function retained() {
    const scoped = {q:'13002',limit:30};
    const workbench = await call(orders,scoped);
    const cockpit = await call(orders,{...scoped,workOrderView:'cockpit'});
    check(workbench.items.length > 0 && !cockpit.capabilities.canWrite &&
      JSON.stringify(workbench.items) === JSON.stringify(cockpit.items), 'Order visibility differs between the two views');
    const originals = [];
    for (const {orderId} of workbench.items) {
      const value = await call(orders+'/workflow-detail',{orderId});
      const analyses = await call(orders+'/analyses',{orderId});
      const revisions = analyses.items.filter(item=>item.sameCode).map(
        ({analysisSessionId,analysisRevision,analysisSha256})=>({analysisSessionId,analysisRevision,analysisSha256}));
      originals.push({orderId,orderRevision:value.orderRevision,snapshotSha256:value.snapshotSha256,revisions});
    }
    const first = originals.flatMap(order=>order.revisions)[0];
    check(first, 'An accessible same-code fixed analysis is required for the check');
    const reference = await call(orders+'/analysis-reference',first);
    check(reference.analysisSessionId === first.analysisSessionId && reference.analysisRevision === first.analysisRevision
      && reference.analysisSha256 === first.analysisSha256,'The fixed analysis reference did not match');
    return originals;
  }
}
