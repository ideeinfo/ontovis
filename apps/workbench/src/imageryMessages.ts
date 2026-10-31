import {ApiError,failureMessage} from './api.ts';
const messages={
  imagery:['影像','Imagery'],overview:['概览影像','Overview imagery'],noImagery:['未设置影像','No imagery selected'],
  import:['导入影像','Import imagery'],file:['选择GeoTIFF','Choose GeoTIFF'],name:['名称','Name'],source:['来源','Source'],
  license:['许可依据','Licence'],attribution:['署名','Attribution'],date:['采集日期','Acquisition date'],quality:['质量说明','Quality note'],
  rights:['已核对本文件的使用依据','I have checked the use rights for this file'],use:['采用此版本','Use this version'],
  processing:['正在上传并处理…','Uploading and processing…'],submit:['导入并校验','Import and validate'],cancel:['取消','Cancel'],
  checkResult:['核对上传结果','Check upload result'],retryOriginal:['按原请求重试','Retry original upload'],
  checking:['正在核对上传结果…','Checking upload result…'],
  pause:['暂停上传','Pause upload'],resume:['继续上传','Continue upload'],discard:['放弃本次上传','Discard this upload'],
  unfinished:['未完成的上传','Unfinished uploads'],confirmed:['已确认','Confirmed'],validating:['文件已接收，正在校验…','File received; validating…'],
  sameFile:['重新选择同一文件继续；已确认的部分保留24小时。','Select the same file to continue; confirmed data is retained for 24 hours.'],
  paused:['上传已暂停，已确认部分和原文件保持，可继续上传。','Upload paused. Confirmed data and the original file are retained; continue when ready.'],
  unconfirmed:['上传结果尚未确认。先核对结果；未查到记录不代表上传失败。当前文件与说明已保留，重试沿用原请求。','Upload result is unconfirmed. Check the result first; no record does not mean failure. The file and details are retained for the original request.'],
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
    if(error.code==='IMAGERY_UPLOAD_PAUSED')return imageryText(locale,'paused');
    if(['IMAGERY_UPLOAD_CHANGED','IMAGERY_CHUNK_CHANGED'].includes(error.code))return locale==='en'?'The upload or file changed. Check its current state or select the original file.':'上传状态或文件已变化，请核对当前状态或选择原文件。';
    if(error.code==='IMAGERY_UPLOAD_EXPIRED')return locale==='en'?'The temporary upload expired. Import the file again.':'临时上传已过期，请重新导入文件。';
    if(error.code==='IMAGERY_UPLOAD_UNCONFIRMED')return imageryText(locale,'unconfirmed');
    if(['UNSUPPORTED_IMAGERY','IMAGERY_NO_VALID_PIXELS'].includes(error.code))return locale==='en'?'Unsupported imagery or no valid pixels. Check RGB bands, masks and geographic reference.':'影像不兼容或没有有效像元，请检查RGB波段、掩膜及地理参考。';
    if(error.code==='IMAGERY_LIMIT_EXCEEDED')return imageryText(locale,'fileHint');
    if(error.code==='IMAGERY_OUTSIDE_TERRAIN')return locale==='en'?'Imagery does not overlap the terrain. Choose another version.':'影像与当前地形没有交集，请选择其他版本。';
    if(error.code==='IMAGERY_BUSY')return locale==='en'?'Another imagery file is being processed. Retry shortly.':'正在处理其他影像，请稍后重试。';
    if(['IMAGERY_STORAGE_BUSY','IMAGERY_STORAGE_UNAVAILABLE'].includes(error.code))return locale==='en'?'Imagery storage is unavailable. Refresh the imagery list and retry.':'影像存储暂不可用，请刷新影像列表后重试。';
  }
  return failureMessage(error,locale);
}
