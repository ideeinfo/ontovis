export interface ModelPropertyEvidence {
  value:string|number|boolean|null;rawValue:string;unit:string|null;
  kind:'page_declared'|'program_geometry_parameter'|'simulation_operating_parameter'|'derived_calculation';
  confidence:string;scope:string;note?:string;
  source:{url:string;locator:string;lineStart:number;lineEnd:number;pageSha256:string;fetchedAt:string;localSnapshot?:string};
}
export interface ModelResourceMetadata {
  metadataRevision:string;modelAssetId:string;modelVersionId:string;modelSha256:string;createdAt:string;createdBy:string;
  metadata:{schemaVersion:1;resourceKey:string;displayName:string;resourceClass:string;verificationStatus:string;
    sourcePage:{url:string;sha256:string;fetchedAt:string};fields:Record<string,ModelPropertyEvidence[]|null>;
    cautions:string[];teachingVariants:unknown[];excludedRuntimeValues:unknown[];modelBasis:unknown};
}
const labels:Record<string,string>={manufacturer:'制造商',designer:'设计方',model:'型号',deploymentEnvironment:'应用环境',foundationType:'基础形式',driveTrainType:'传动链',generatorType:'发电机',ratedPowerKw:'额定功率',baseRatedPowerKw:'基型额定功率',siteOperatingPowerKw:'场站运行功率',hubHeightM:'轮毂高度',alternativeHubHeightM:'可选轮毂高度',towerHeightM:'塔高',rotorDiameterM:'叶轮直径',bladeLengthM:'叶片长度',nacelleLengthM:'机舱长度',nacelleWidthM:'机舱宽度',nacelleHeightM:'机舱高度',nacelleMaximumRadiusM:'机舱最大半径',cutInWindSpeedMps:'切入风速',ratedWindSpeedMps:'模型额定风速',cutOutWindSpeedMps:'切出风速',cutOutOptionMaximumMps:'可选切出上限',restartWindSpeedMps:'恢复运行风速',rotorSpeedMinimumRpm:'最低转速',rotorSpeedMaximumRpm:'最高转速',rotorRatedSpeedRpm:'额定转速',gearboxRatio:'齿轮比',gearboxStages:'齿轮级数',designLifetimeYears:'设计寿命',survivalWindSpeed10minMps:'极限风速（10分钟）',survivalWindSpeed3secMps:'极限风速（3秒）',sweptAreaM2:'扫风面积'};
export function modelPropertyLabel(key:string,locale:'zh'|'en') {
  return locale==='zh'?(labels[key]||key):key.replace(/([a-z])([A-Z])/g,'$1 $2').replace(/Kw$/,' (kW)').replace(/Mps$/,' (m/s)').replace(/Rpm$/,' (rpm)');
}
export function metadataSourceUrl(value:string):string|null {
  try{const url=new URL(value);return url.protocol==='https:'&&!url.username&&!url.password?url.href:null;}catch{return null;}
}
