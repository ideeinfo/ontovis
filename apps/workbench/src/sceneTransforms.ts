/** Client display/drag previews only; final scene saves still use server GIS checks. */
import proj4, {type Converter} from 'proj4';
import type {AbsoluteHeight, CoordinateFrame, GeographicPosition, GroundHeight,
  KnownVerticalDatum, LocalPosition, LocalRelativeHeight, ProjectedFrame, Vector3} from './sceneTypes';

export type SceneTransformCode = 'INVALID_COORDINATE' | 'UNSUPPORTED_CRS' | 'OUTSIDE_PROJECTION_AREA'
  | 'OUTSIDE_COVERAGE' | 'FRAME_CHANGED' | 'VERTICAL_DATUM_CONFLICT' | 'SCENE_SCOPE_UNSUPPORTED';
export class SceneTransformError extends Error {
  readonly code: SceneTransformCode;
  constructor(code: SceneTransformCode, message: string) {super(message);this.name='SceneTransformError';this.code=code;}
}
export type DisplayCoordinateResult =
  | {position:LocalPosition; heightM:number; verticalDatum:null; heightKind:'local_relative'}
  | {position:GeographicPosition; heightM:number; verticalDatum:KnownVerticalDatum; heightKind:'known_datum'}
  | {position:GeographicPosition; heightM:number; verticalDatum:'UNKNOWN_RELATIVE'; heightKind:'relative_terrain'; relativeReferenceId:string};

const CONVERGENCE_RULE='projected-central-true-north-derivative-v1';
const MAX_RADIUS_M=50_000;
const MAX_HEIGHT_M=100_000;
const KNOWN_DATUMS=new Set(['EGM2008','EGM96','WGS84_ELLIPSOIDAL']);
const WGS84='+proj=longlat +datum=WGS84 +no_defs';
const converters=new Map<string,Converter>();

function ensure(value:unknown,code:SceneTransformCode,message:string):asserts value {
  if(!value)throw new SceneTransformError(code,message);
}
function finite(value:unknown,limit=1_000_000):number {
  ensure(typeof value==='number' && Number.isFinite(value) && Math.abs(value)<=limit,
    'INVALID_COORDINATE','A finite coordinate within the supported range is required.');return value;
}
function nonempty(value:unknown):value is string {return typeof value==='string' && value.length>0 && value.length<=200;}
function zone(longitude:number) {return Math.min(60,Math.floor((longitude+180)/6)+1);}
function geographic(longitude:unknown,latitude:unknown):[number,number] {
  const lon=finite(longitude,180),lat=finite(latitude,90);
  ensure(lat>=-80 && lat<=84,'OUTSIDE_PROJECTION_AREA','Polar coordinates are outside the regional UTM slice.');
  return [lon,lat];
}
function distance(a:[number,number],b:[number,number]) {
  const radians=Math.PI/180,dlat=(b[1]-a[1])*radians,dlon=(b[0]-a[0])*radians;
  const h=Math.sin(dlat/2)**2+Math.cos(a[1]*radians)*Math.cos(b[1]*radians)*Math.sin(dlon/2)**2;
  return 6_378_137*2*Math.asin(Math.min(1,Math.sqrt(h)));
}
function conversion(crs:unknown) {
  ensure(typeof crs==='string','UNSUPPORTED_CRS','An explicit WGS84 UTM EPSG code is required.');
  const match=/^EPSG:(326|327)(\d{2})$/.exec(crs);
  ensure(match && Number(match[2])>=1 && Number(match[2])<=60,'UNSUPPORTED_CRS','Only WGS84 UTM EPSG codes are supported.');
  const utmZone=Number(match[2]),south=match[1]==='327';
  let converter=converters.get(crs);
  if(!converter) {
    // Construct from numeric whitelist values; never accept grids, URLs or a client PROJ string.
    converter=proj4(WGS84,`+proj=utm +zone=${utmZone}${south?' +south':''} +datum=WGS84 +units=m +no_defs`);
    converters.set(crs,converter);
  }
  return {converter,utmZone,south};
}
function projectedFrame(frame:ProjectedFrame) {
  const result=conversion(frame.horizontalCrs);
  ensure(nonempty(frame.frameRevision) && nonempty(frame.transformId)
    && frame.convergenceRuleId===CONVERGENCE_RULE,'FRAME_CHANGED','A fixed supported scene transform is required.');
  ensure(frame.anchor && Array.isArray(frame.anchor.geographicAnchor) && frame.anchor.geographicAnchor.length===2,
    'FRAME_CHANGED','The projected frame needs its explicit geographic anchor.');
  const anchor=geographic(...frame.anchor.geographicAnchor);
  ensure(zone(anchor[0])===result.utmZone && (anchor[1]<0)===result.south,
    'OUTSIDE_PROJECTION_AREA','The anchor does not match the locked UTM zone and hemisphere.');
  ensure(KNOWN_DATUMS.has(frame.verticalDatum) || frame.verticalDatum==='UNKNOWN_RELATIVE',
    'VERTICAL_DATUM_CONFLICT','The vertical datum is unsupported.');
  if(frame.verticalDatum==='UNKNOWN_RELATIVE')ensure(nonempty(frame.relativeReferenceId),
    'VERTICAL_DATUM_CONFLICT','Relative terrain requires a fixed relative reference.');
  finite(frame.originEasting,20_000_000);finite(frame.originNorthing,20_000_000);finite(frame.originHeight,MAX_HEIGHT_M);
  const anchorHeight=frame.anchor.anchorHeight;
  ensure(anchorHeight && (anchorHeight.mode==='absolute' || anchorHeight.mode==='terrain_ground'),
    'VERTICAL_DATUM_CONFLICT','The frame needs an explicit anchor height strategy.');
  if(anchorHeight.mode==='absolute') {
    ensure(frame.verticalDatum!=='UNKNOWN_RELATIVE' && anchorHeight.verticalDatum===frame.verticalDatum,
      'VERTICAL_DATUM_CONFLICT','The absolute anchor and scene vertical datums must match.');
    ensure(Math.abs(finite(anchorHeight.valueM,MAX_HEIGHT_M)-frame.originHeight)<=1e-6,
      'FRAME_CHANGED','The frame height differs from its absolute anchor.');
  } else finite(anchorHeight.offsetM,MAX_HEIGHT_M);
  const [east,north]=result.converter.forward(anchor);
  ensure(Math.hypot(east-frame.originEasting,north-frame.originNorthing)<=.02,
    'FRAME_CHANGED','The projected origin differs from the fixed geographic anchor.');
  return {...result,anchor};
}
function validateFrame(frame:CoordinateFrame) {
  ensure(frame && typeof frame==='object','SCENE_SCOPE_UNSUPPORTED','A local or regional projected frame is required.');
  if(frame.mode==='local_plane') {
    ensure(nonempty(frame.frameRevision) && frame.unit==='m' && frame.axes==='X_EAST_Y_UP_Z_SOUTH'
      && Array.isArray(frame.origin) && frame.origin.length===3 && frame.origin.every(value=>value===0),
      'FRAME_CHANGED','The local frame must use the fixed metre and display-axis convention.');
    return null;
  }
  ensure(frame.mode==='projected_site','SCENE_SCOPE_UNSUPPORTED','Strict ENU and arbitrary coordinate frames are unavailable.');
  return projectedFrame(frame);
}
function inDomain(point:[number,number],context:ReturnType<typeof projectedFrame>) {
  ensure(zone(point[0])===context.utmZone && (point[1]<0)===context.south,
    'OUTSIDE_PROJECTION_AREA','The point crosses the locked UTM zone or hemisphere.');
  ensure(distance(context.anchor,point)<=MAX_RADIUS_M,'OUTSIDE_COVERAGE','The point exceeds the validated 50 km regional radius.');
}
function heading(value:unknown) {return ((finite(value)%360)+360)%360;}
function point(value:Vector3):Vector3 {
  ensure(Array.isArray(value) && value.length===3,'INVALID_COORDINATE','A display point needs three finite coordinates.');
  return [finite(value[0]),finite(value[1],MAX_HEIGHT_M),finite(value[2])];
}

export function toDisplay(frame:CoordinateFrame,position:LocalPosition|GeographicPosition,
  height:LocalRelativeHeight|GroundHeight|AbsoluteHeight):Vector3 {
  const context=validateFrame(frame);
  ensure(position && height,'INVALID_COORDINATE','Position and height strategies are required.');
  if(frame.mode==='local_plane') {
    ensure(position.mode==='local' && height.mode==='local_relative','VERTICAL_DATUM_CONFLICT','Local coordinates require a local relative height.');
    return [finite(position.xM),finite(height.relativeHeightM,MAX_HEIGHT_M),finite(position.zM)];
  }
  ensure(context && position.mode==='geographic' && position.frameRevision===frame.frameRevision
    && position.transformId===frame.transformId,'FRAME_CHANGED','The position belongs to another scene frame.');
  const location=geographic(position.longitude,position.latitude);inDomain(location,context);
  ensure(height.mode!=='local_relative' && height.verticalDatum===frame.verticalDatum,
    'VERTICAL_DATUM_CONFLICT','The height and scene vertical datums must match.');
  let elevation:number;
  if(height.mode==='absolute') {
    ensure(frame.verticalDatum!=='UNKNOWN_RELATIVE','VERTICAL_DATUM_CONFLICT','Unknown relative terrain cannot declare an absolute elevation.');
    elevation=finite(height.valueM,MAX_HEIGHT_M);
  } else elevation=finite(finite(height.sampledHeightM,MAX_HEIGHT_M)+finite(height.offsetM,MAX_HEIGHT_M),MAX_HEIGHT_M);
  const [east,north]=context.converter.forward(location);
  return [finite(east-frame.originEasting),elevation-frame.originHeight,finite(frame.originNorthing-north)];
}

/** Returned height is a datum value, never an automatically accepted absolute-height strategy. */
export function fromDisplay(frame:CoordinateFrame,display:Vector3):DisplayCoordinateResult {
  const context=validateFrame(frame),[x,y,z]=point(display);
  if(frame.mode==='local_plane')return {position:{mode:'local',xM:x,zM:z},heightM:y,verticalDatum:null,heightKind:'local_relative'};
  ensure(context,'FRAME_CHANGED','A projected display needs its fixed transform.');
  const [longitude,latitude]=context.converter.inverse([frame.originEasting+x,frame.originNorthing-z]);
  const location=geographic(longitude,latitude);inDomain(location,context);
  const position:GeographicPosition={mode:'geographic',longitude:location[0],latitude:location[1],
    transformId:frame.transformId,frameRevision:frame.frameRevision};
  const heightM=finite(frame.originHeight+y,MAX_HEIGHT_M);
  if(frame.verticalDatum==='UNKNOWN_RELATIVE')return {position,heightM,verticalDatum:frame.verticalDatum,
    heightKind:'relative_terrain',relativeReferenceId:frame.relativeReferenceId};
  return {position,heightM,verticalDatum:frame.verticalDatum,heightKind:'known_datum'};
}

export function trueHeadingToThreeYaw(frame:CoordinateFrame,headingDeg:number,longitude?:number,latitude?:number):number {
  const context=validateFrame(frame),normalized=heading(headingDeg);
  if(frame.mode==='local_plane')return -normalized*Math.PI/180;
  ensure(context,'FRAME_CHANGED','A projected heading needs its fixed transform.');
  const location=geographic(longitude,latitude);inDomain(location,context);
  const delta=1e-5;
  const south=context.converter.forward([location[0],location[1]-delta]);
  const north=context.converter.forward([location[0],location[1]+delta]);
  const convergence=Math.atan2(north[0]-south[0],north[1]-south[1])*180/Math.PI;
  return -heading(normalized+convergence)*Math.PI/180;
}
