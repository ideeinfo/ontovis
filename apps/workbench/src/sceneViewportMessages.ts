const zh={view:'场景视图',loading:'正在读取模型与地形',retry:'重试',fit:'显示全部',focus:'定位所选模型',
  zoomIn:'放大',zoomOut:'缩小',preview:'模型预览',unverified:'未校准 · 仅预览',
  place:'点击地形或平面放置模型',drag:'拖动已解锁模型调整位置；Esc 取消',browse:'拖动旋转 · 滚轮缩放',
  empty:'还没有放置模型',moveFailed:'位置调整未通过，已还原',dropInvalid:'模型拖放信息无效',
  unavailable:'三维视图无法打开',moving:'正在核验位置',modelReferenceRequired:'模型引用不完整，请重新选择资源',
  invalidCalibration:'模型校准无效，请重新核对单位、基点和正面朝向'};
export type SceneViewportMessage=keyof typeof zh;
const en:Record<SceneViewportMessage,string>={view:'Scene view',loading:'Loading models and terrain',retry:'Retry',
  fit:'Show all',focus:'Locate selected model',zoomIn:'Zoom in',zoomOut:'Zoom out',preview:'Model preview',
  unverified:'Uncalibrated · preview only',place:'Click the terrain or plane to place the model',
  drag:'Drag an unlocked model to move it; Esc cancels',browse:'Drag to orbit · scroll to zoom',
  empty:'No models placed yet',moveFailed:'Position check failed; movement reverted',
  dropInvalid:'Invalid model drop data',unavailable:'The 3D view is unavailable',moving:'Checking position',
  modelReferenceRequired:'The model reference is incomplete. Select the resource again.',
  invalidCalibration:'The model calibration is invalid. Recheck its units, base point and forward direction.'};
export const sceneViewportMessages={zh,en};
export function sceneViewportMessage(locale:string,key:SceneViewportMessage) {return (locale==='en'?en:zh)[key];}
