const zh={analysisObject:'分析对象',properties:'属性',batch:'批量布置',routesTab:'视点与路线',selection:'多选与编组',selected:'已选',
  selectAll:'全选',clear:'清除选择',selectInstance:'选择实例',groupName:'组名',group:'将所选编组',ungroup:'解组',
  selectionHint:'使用内容列表复选框，或按住 Shift 点选模型。编组只管理场景实例。',
  groupHint:'所选已属于组；先解组再重新编组。',move:'平面批量移动',dx:'ΔX (m)',dz:'ΔZ (m)',heading:'各实例朝向增量 (°)',
  apply:'整批应用',moveHint:'锁定、越界或无高程时整批保留原位；一次撤销。',moveDone:'整批已应用，可一次撤销',
  unchanged:'整批未应用',placement:'连续放置与吸附',continuous:'连续放置',grid:'网格',angle:'角度',off:'关闭',
  placementHint:'从资源中选择模型后点选地面；Esc 结束。每个新实例均无设备关联。吸附不代表现场精度。',
  viewpoints:'命名视点',viewName:'视点名称',capture:'保存当前',recapture:'重存',component:'构件',overview:'远眺',
  componentDwell:'当前构件 · 默认停留 2 秒',overviewDwell:'当前远眺 · 默认停留 3 秒',deleteView:'删除视点',
  inUse:'先移出路线再删除视点',stale:'需重存',routes:'观察路线',routeName:'路线名称',create:'新建',currentRoute:'当前路线',
  flight:'飞行 (秒)',dwell:'停留 (秒)',up:'上移步骤',down:'下移步骤',removeStep:'移除步骤',addView:'添加视点',
  chooseView:'选择视点',preview:'预览',pause:'暂停',resume:'继续',cancel:'取消',deleteRoute:'删除路线',
  playingFlight:'飞行',playingDwell:'停留',paused:'已暂停',complete:'预览结束',checking:'正在核验读取权限',
  routeHint:'预览保留分析对象。取消恢复原视角；后台不计时。视点与路线随场景保存。',
  manual:'已手动接管镜头，路线停止',emptyRoute:'请先添加有效视点',cameraUnavailable:'镜头或资源尚未就绪，请稍后重试',
  viewStale:'视点的坐标系或模型已变化，请重存',invalid:'输入或组织引用无效',locked:'所选包含已锁定实例',
  alreadyGrouped:'实例已属于其他组',capacity:'已达到本场景容量上限',noChange:'位置未改变',closePanel:'关闭详情面板'};
export type SceneOrganizationMessage=keyof typeof zh;
const en:Record<SceneOrganizationMessage,string>={analysisObject:'Analysis object',properties:'Properties',batch:'Batch layout',routesTab:'Views & routes',selection:'Selection & groups',selected:'Selected',
  selectAll:'Select all',clear:'Clear',selectInstance:'Select instance',groupName:'Group name',group:'Group selected',ungroup:'Ungroup',
  selectionHint:'Use list checkboxes or Shift-click models. Groups organize scene instances.',groupHint:'Ungroup selected members before regrouping.',
  move:'Batch planar move',dx:'ΔX (m)',dz:'ΔZ (m)',heading:'Per-instance heading delta (°)',apply:'Apply batch',
  moveHint:'A locked or invalid member blocks the whole batch. One undo.',moveDone:'Batch applied; one undo',unchanged:'Batch unchanged',
  placement:'Continuous placement & snap',continuous:'Keep placing',grid:'Grid',angle:'Angle',off:'Off',
  placementHint:'Choose a resource, then click the ground. Esc ends placement. New instances have no equipment links. Snap is a layout aid.',
  viewpoints:'Named viewpoints',viewName:'Viewpoint name',capture:'Save current',recapture:'Recapture',component:'Component',overview:'Overview',
  componentDwell:'Component · default dwell 2 s',overviewDwell:'Overview · default dwell 3 s',deleteView:'Delete viewpoint',inUse:'Remove route references first',
  stale:'Recapture',routes:'Observation routes',routeName:'Route name',create:'Create',currentRoute:'Current route',flight:'Flight (s)',dwell:'Dwell (s)',
  up:'Move step up',down:'Move step down',removeStep:'Remove step',addView:'Add viewpoint',chooseView:'Choose viewpoint',preview:'Preview',pause:'Pause',resume:'Resume',
  cancel:'Cancel',deleteRoute:'Delete route',playingFlight:'Flight',playingDwell:'Dwell',paused:'Paused',complete:'Preview complete',checking:'Checking read access',
  routeHint:'Preview preserves the selected object. Cancel restores the starting view; background time is paused. Save views and routes with the scene.',
  manual:'Camera taken over; route stopped',emptyRoute:'Add valid viewpoints first',cameraUnavailable:'Camera or resources are not ready. Try again shortly.',
  viewStale:'The viewpoint frame or model changed. Capture it again.',invalid:'Invalid input or organization reference',locked:'The selection contains locked instances',
  alreadyGrouped:'An instance already belongs to a group',capacity:'The scene capacity limit was reached',noChange:'No position change',closePanel:'Close details panel'};
export function organizationText(locale:string,key:SceneOrganizationMessage):string{return (locale==='en'?en:zh)[key];}
export function organizationError(locale:string,error:unknown):string|null {
  const code=error instanceof Error&&'code'in error?String(error.code):'';
  const key:SceneOrganizationMessage|undefined=({INSTANCE_POSITION_LOCKED:'locked',INSTANCE_ALREADY_GROUPED:'alreadyGrouped',
    INVALID_SCENE_ORGANIZATION:'invalid',INVALID_SELECTION:'invalid',INVALID_COORDINATE:'invalid',SCENE_LIMIT_EXCEEDED:'capacity',
    VIEWPOINT_IN_USE:'inUse',VIEWPOINT_STALE:'viewStale',EMPTY_ROUTE:'emptyRoute',CAMERA_UNAVAILABLE:'cameraUnavailable'} as Record<string,SceneOrganizationMessage>)[code];
  return key?organizationText(locale,key):null;
}
