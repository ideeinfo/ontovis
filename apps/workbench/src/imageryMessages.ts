import {ApiError,failureMessage} from './api';
const messages={
  imagery:['影像','Imagery'],overview:['概览影像','Overview imagery'],noImagery:['未设置影像','No imagery selected'],
  import:['导入影像','Import imagery'],file:['选择GeoTIFF','Choose GeoTIFF'],name:['名称','Name'],source:['来源','Source'],
  license:['许可依据','Licence'],attribution:['署名','Attribution'],date:['采集日期','Acquisition date'],quality:['质量说明','Quality note'],
  rights:['已核对本文件的使用依据','I have checked the use rights for this file'],use:['采用此版本','Use this version'],
  processing:['正在上传并处理…','Uploading and processing…'],submit:['导入并校验','Import and validate'],cancel:['取消','Cancel'],
  loading:['正在读取影像…','Loading imagery…'],empty:['暂无影像资源','No imagery resources'],refresh:['刷新','Refresh'],
  search:['搜索影像','Search imagery'],show:['显示影像','Show imagery'],hide:['隐藏影像','Hide imagery'],remove:['移除影像层','Remove imagery layer'],
  report:['坐标与覆盖','Coordinates and coverage'],details:['影像来源与质量','Imagery source and quality'],
  transparent:['透明/缺测像元','Transparent / missing pixels'],precision:['非工程定位精度','Not engineering positioning accuracy'],
  pinned:['固定版本','Pinned version'],editRequired:['进入布置模式并设置地形后采用','Enter arrange mode and set terrain to use imagery'],
  fileHint:['8位RGB/RGBA、北向上GeoTIFF；WGS84经纬度或UTM，最大64MiB及4096×4096像素。','8-bit RGB/RGBA north-up GeoTIFF; WGS84 geographic or UTM. Maximum 64 MiB and 4096×4096 pixels.'],
  height:['影像提供颜色，高程沿用固定地形。','Imagery supplies colour; elevation uses the pinned terrain.'],
  partial:['影像覆盖部分地形，覆盖外显示原地形。','Imagery covers part of the terrain; uncovered areas show the original terrain.'],
  fileInvalid:['请选择64MiB以内的GeoTIFF，并填写来源、许可、日期、署名和质量说明。','Choose a GeoTIFF within 64 MiB and complete source, licence, date, attribution and quality.'],
} as const;
export type ImageryMessage=keyof typeof messages;
export function imageryText(locale:string,key:ImageryMessage){return messages[key][locale==='en'?1:0];}
export function imageryFailure(error:unknown,locale:string){
  if(error instanceof ApiError){
    if(['UNSUPPORTED_IMAGERY','IMAGERY_NO_VALID_PIXELS'].includes(error.code))return locale==='en'?'Unsupported imagery or no valid pixels. Check RGB bands, masks and geographic reference.':'影像不兼容或没有有效像元，请检查RGB波段、掩膜及地理参考。';
    if(error.code==='IMAGERY_LIMIT_EXCEEDED')return imageryText(locale,'fileHint');
    if(error.code==='IMAGERY_OUTSIDE_TERRAIN')return locale==='en'?'Imagery does not overlap the terrain. Choose another version.':'影像与当前地形没有交集，请选择其他版本。';
    if(error.code==='IMAGERY_BUSY')return locale==='en'?'Another imagery file is being processed. Retry shortly.':'正在处理其他影像，请稍后重试。';
    if(['IMAGERY_STORAGE_BUSY','IMAGERY_STORAGE_UNAVAILABLE'].includes(error.code))return locale==='en'?'Imagery storage is unavailable. Refresh the imagery list and retry.':'影像存储暂不可用，请刷新影像列表后重试。';
  }
  return failureMessage(error,locale);
}
