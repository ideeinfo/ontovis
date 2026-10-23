"""Bounded local/projected scene geometry checks in the trusted GIS runtime.

This module does not authenticate, save scenes, resolve engineering objects or
fetch any network source. Resource paths and hashes are server-provided inputs;
public scene JSON contains only fixed resource identifiers.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
import os
from pathlib import Path
import sys
from uuid import UUID

from .terrain_coordinates import (ProjectedFrame, LocalPlacement, TerrainHeight,
    CoordinateError, CONVERGENCE_RULE, VERTICAL_DATUMS, normalize_heading, preview_anchor)
from .terrain_validation import sample_mesh, PLACEMENT_SAMPLING_RULE, TerrainError
from tools.model_probe import strict_json, ProbeError
from .scene_organization import OrganizationError, validate_organization

MAX_REQUEST_BYTES=1024*1024
MAX_OUTPUT_BYTES=2*1024*1024
MAX_INSTANCES=100
MAX_COORDINATE_M=1_000_000
SAMPLE_EPSILON_M=1e-6


class GeometryError(ValueError):
    def __init__(self,code,message):
        super().__init__(message);self.code=code


def _require(value,code='INVALID_REQUEST',message='The geometry request is invalid.'):
    if not value:raise GeometryError(code,message)


def _fields(value,required,optional=()):
    _require(type(value) is dict and set(required)<=set(value)<=set(required)|set(optional))


def _text(value,limit=200):
    _require(isinstance(value,str) and 0<len(value.strip())<=limit and all(ord(c)>=32 for c in value))
    return value


def _number(value,limit=MAX_COORDINATE_M):
    _require(type(value) in (int,float) and math.isfinite(value) and abs(value)<=limit,'INVALID_COORDINATE','A coordinate is outside the finite numeric range.')
    return float(value)


def _uuid(value):
    try:identifier=str(UUID(value))
    except (ValueError,TypeError,AttributeError):raise GeometryError('INVALID_REQUEST','A canonical UUID is required.') from None
    _require(identifier==value)
    return identifier


def _digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode()).hexdigest()


def _sha(value):
    _require(isinstance(value,str) and len(value)==64 and all(c in '0123456789abcdef' for c in value))
    return value


def _file_hash(path):
    result=hashlib.sha256()
    with path.open('rb') as file:
        for chunk in iter(lambda:file.read(65536),b''):result.update(chunk)
    return result.hexdigest()


def _bounded_copy(value):
    nodes=0
    def visit(item,depth=0):
        nonlocal nodes
        nodes+=1
        _require(depth<=24 and nodes<=150000,'SCENE_LIMIT_EXCEEDED','The snapshot structure exceeds its budget.')
        if type(item) is dict:
            for key,child in item.items():
                _require(isinstance(key,str) and len(key)<=200);visit(child,depth+1)
        elif type(item) is list:
            for child in item:visit(child,depth+1)
        elif type(item) is float:_require(math.isfinite(item),'INVALID_REQUEST','Non-finite JSON is not allowed.')
        elif type(item) is int:_require(item.bit_length()<=64)
        else:_require(item is None or type(item) in (str,bool))
    visit(value)
    try:raw=json.dumps(value,ensure_ascii=False,allow_nan=False,separators=(',',':')).encode()
    except (ValueError,TypeError,OverflowError,UnicodeError):raise GeometryError('INVALID_REQUEST','The snapshot cannot be encoded.') from None
    _require(len(raw)<=MAX_REQUEST_BYTES,'SCENE_LIMIT_EXCEEDED','The snapshot exceeds one MiB.')
    return json.loads(raw)


@dataclass(frozen=True)
class TrustedTerrain:
    """Construct only after current resource authorization and DB lookup."""
    version_id:str
    content_revision:str
    sha256:str
    report_sha256:str
    directory:Path


class _Terrain:
    def __init__(self,trusted):
        _require(isinstance(trusted,TrustedTerrain));self.trusted=trusted
        _uuid(trusted.version_id);_text(trusted.content_revision);_sha(trusted.sha256);_sha(trusted.report_sha256)
        directory=Path(trusted.directory)
        _require(directory.is_absolute() and directory.is_dir() and not directory.is_symlink() and not directory.parent.is_symlink(),'RESOURCE_CHANGED','A fixed private terrain directory is required.')
        path=directory/'report.json'
        _require(path.is_file() and not path.is_symlink() and path.stat().st_size<=65536,'RESOURCE_CHANGED','The trusted terrain report changed.')
        raw=path.read_bytes()
        _require(len(raw)<=65536 and hashlib.sha256(raw).hexdigest()==trusted.report_sha256,'RESOURCE_CHANGED','The trusted terrain report changed.')
        try:report=strict_json(raw)
        except (ProbeError,ValueError,UnicodeError):raise GeometryError('INVALID_TERRAIN','The terrain report is invalid.') from None
        _require(type(report) is dict and report.get('state')=='ready' and report.get('schemaVersion')==1,'INVALID_TERRAIN','A ready fixed terrain is required.')
        source,mesh=report['source'],report['mesh']
        _require(type(source) is dict and type(mesh) is dict,'INVALID_TERRAIN','The terrain metadata is invalid.')
        _require(source.get('sha256')==trusted.sha256 and source.get('heightUnit')=='m','RESOURCE_CHANGED','The resource source identity changed.')
        self.datum=source.get('verticalDatum')
        _require(isinstance(self.datum,str) and self.datum in VERTICAL_DATUMS,'VERTICAL_DATUM_CONFLICT','The terrain datum is unsupported.')
        self.relative_reference=source.get('relativeReferenceId')
        if self.datum=='UNKNOWN_RELATIVE':_text(self.relative_reference)
        _require(mesh.get('placementSamplingRule')==PLACEMENT_SAMPLING_RULE,'RESOURCE_CHANGED','The terrain needs processing with the current safe cell-mask rule.')
        rows,columns=mesh.get('rows'),mesh.get('columns')
        _require(type(rows) is int and type(columns) is int and 2<=rows<=501 and 2<=columns<=501,'INVALID_TERRAIN','The mesh dimensions are invalid.')
        _require(type(mesh.get('triangles')) is int and 0<mesh['triangles']<=500000,'INVALID_TERRAIN','The mesh triangle budget is invalid.')
        sizes={'heights.f64':rows*columns*8,'mask.u8':rows*columns,'positions.f32':rows*columns*12,
               'triangles.u32':mesh['triangles']*12,'cells.u8':(rows-1)*(columns-1)}
        artifacts=report.get('artifacts')
        _require(type(artifacts) is list and len(artifacts)==len(sizes),'INVALID_TERRAIN','The fixed artifact set is incomplete.')
        seen=set()
        for artifact in artifacts:
            _fields(artifact,('artifactId','bytes','sha256','format'))
            name=artifact['artifactId'];_require(isinstance(name,str) and name in sizes and name not in seen,'INVALID_TERRAIN','An artifact identifier is unsupported.')
            seen.add(name);item=directory/name
            _require(not item.is_symlink() and item.is_file() and item.stat().st_size==sizes[name] and artifact['bytes']==sizes[name] and _file_hash(item)==_sha(artifact['sha256']),
                     'RESOURCE_CHANGED','A fixed terrain artifact changed.')
        coverage=source.get('samplingCentreCoverageWgs84')
        _require(type(coverage) is list and len(coverage)==4)
        west,south,east,north=map(_number,coverage)
        self.frame=ProjectedFrame((west+east)/2,(south+north)/2,mesh['frame']['originHeight'],self.datum,mesh['frame']['frameRevision'])
        record=self.frame.record();actual=mesh['frame']
        _require(all(actual.get(key)==record[key] for key in ('horizontalCrs','verticalDatum','transformId','convergenceRuleId'))
                 and abs(actual['originEasting']-record['originEasting'])<=1e-6 and abs(actual['originNorthing']-record['originNorthing'])<=1e-6,
                 'TRANSFORM_UNAVAILABLE','The terrain transformation runtime does not match its fixed report.')
        self.directory=directory;self.report=report;self.samples={}

    def sample(self,longitude,latitude):
        key=(float(longitude),float(latitude))
        if key not in self.samples:
            east,north=self.frame.project(*key)
            self.samples[key]=sample_mesh(self.directory,east,north,expected_report_sha256=self.trusted.report_sha256)
        return self.samples[key]

    def reference(self):
        return {'terrainVersionId':self.trusted.version_id,'contentRevision':self.trusted.content_revision,
                'sha256':self.trusted.sha256,'reportSha256':self.trusted.report_sha256}


def _terrain(terrains,identifier):
    _uuid(identifier)
    _require(type(terrains) is dict and identifier in terrains,'NOT_FOUND_OR_FORBIDDEN','The fixed terrain is not in the authorized resource manifest.')
    value=_Terrain(terrains[identifier])
    _require(value.trusted.version_id==identifier,'RESOURCE_CHANGED','The resource identifier differs from its trusted manifest.')
    return value


def _base_snapshot(snapshot):
    value=_bounded_copy(snapshot)
    _fields(value,('displayName','coordinateFrame','terrain','instances','initialView','defaults'),('organization','imagery'))
    image=value.get('imagery')
    if image is not None:
        _fields(image,('imageryVersionId','expectedContentRevision','expectedReportSha256','visible'))
        _uuid(image['imageryVersionId']);_text(image['expectedContentRevision'])
        _require(type(image['expectedReportSha256']) is str and len(image['expectedReportSha256'])==64
                 and all(c in '0123456789abcdef' for c in image['expectedReportSha256']) and type(image['visible']) is bool)
        _require(type(value['coordinateFrame']) is dict and value['coordinateFrame'].get('mode')=='projected_site'
                 and value['terrain'] is not None,'SCENE_SCOPE_UNSUPPORTED','Imagery needs a georeferenced terrain.')
    _text(value['displayName']);_require(type(value['instances']) is list and len(value['instances'])<=MAX_INSTANCES,'SCENE_LIMIT_EXCEEDED','At most 100 instances are accepted.')
    identifiers=set();bindings=0
    for item in value['instances']:
        _fields(item,('sceneModelInstanceId','displayName','modelVersionId','placement','visible','positionLocked','rootBinding','componentBindings'))
        identifier=_uuid(item['sceneModelInstanceId']);_require(identifier not in identifiers,'DUPLICATE_INSTANCE','An instance identifier is duplicated.');identifiers.add(identifier)
        _uuid(item['modelVersionId']);_text(item['displayName'])
        _require(type(item['visible']) is bool and type(item['positionLocked']) is bool)
        _require(item['rootBinding'] is None or type(item['rootBinding']) is dict)
        _require(type(item['componentBindings']) is list);bindings+=len(item['componentBindings'])
        _fields(item['placement'],('position','height','headingDeg'))
        item['placement']['headingDeg']=normalize_heading(_number(item['placement']['headingDeg']))
    _require(bindings<=1000,'SCENE_LIMIT_EXCEEDED','The aggregate component association budget is exceeded.')
    _fields(value['initialView'],('eye','target'))
    for key in ('eye','target'):
        vector=value['initialView'][key];_require(type(vector) is list and len(vector)==3)
        value['initialView'][key]=[_number(x) for x in vector]
    _require(sum((a-b)**2 for a,b in zip(value['initialView']['eye'],value['initialView']['target']))>1e-12,'INVALID_COORDINATE','The camera and target cannot coincide.')
    _fields(value['defaults'],('background','lighting','terrainMaterial'))
    _require(value['defaults']['background'] in ('plain','sky') and value['defaults']['lighting'] in ('neutral','dusk') and value['defaults']['terrainMaterial'] in ('solid','grass'))
    if 'organization' in value:
        try:value['organization']=validate_organization(value['organization'],identifiers)
        except OrganizationError as error:raise GeometryError(error.code,'The scene groups, viewpoints or routes are invalid.') from None
    return value


def _local(value):
    frame=value['coordinateFrame']
    _fields(frame,('mode','frameRevision','origin','unit','axes'))
    _require(frame['mode']=='local_plane' and frame['origin']==[0,0,0] and all(type(x) is int for x in frame['origin']) and frame['unit']=='m' and frame['axes']=='X_EAST_Y_UP_Z_SOUTH')
    _text(frame['frameRevision']);_require(value['terrain'] is None,'SCENE_SCOPE_UNSUPPORTED','A local layout does not silently adopt georeferenced terrain.')
    displays=[]
    for item in value['instances']:
        placement=item['placement'];position=placement['position'];height=placement['height']
        _fields(position,('mode','xM','zM'));_fields(height,('mode','relativeHeightM'))
        _require(position['mode']=='local' and height['mode']=='local_relative','VERTICAL_DATUM_CONFLICT','Local layouts only accept relative positions and heights.')
        displays.append({'sceneModelInstanceId':item['sceneModelInstanceId'],
            'position':[_number(position['xM']),_number(height['relativeHeightM'],100000),_number(position['zM'])],
            'threeYawRad':-math.radians(placement['headingDeg'])})
    return displays


def _anchor(anchor,terrain):
    _fields(anchor,('localAnchor','geographicAnchor','trueNorthHeadingDeg','anchorHeight','heightStrategy'))
    for key in ('localAnchor','geographicAnchor'):
        _require(type(anchor[key]) is list and len(anchor[key])==2)
        for number in anchor[key]:_number(number)
    _require(anchor['heightStrategy'] in ('keep_relative_to_anchor','resample_each_ground'))
    _number(anchor['trueNorthHeadingDeg'])
    height=anchor['anchorHeight']
    _require(type(height) is dict)
    if height.get('mode')=='terrain_ground':
        _fields(height,('mode','terrainVersionId','offsetM'),('offsetCompensationM',))
        _require(height['terrainVersionId']==terrain.trusted.version_id,'RESOURCE_CHANGED','The anchor uses a different terrain version.')
        ground=terrain.sample(*anchor['geographicAnchor']);offset=_number(height['offsetM'],100000)
        result=ground+offset
        if 'offsetCompensationM' in height:
            compensation=_number(height['offsetCompensationM'],1)
            _require(terrain.datum=='UNKNOWN_RELATIVE' and abs(compensation)<=max(math.ulp(ground),math.ulp(offset)),
                     'INVALID_COORDINATE','The preserved relative origin compensation exceeds floating-point roundoff.')
            result=math.fsum((ground,offset,compensation))
    else:
        _fields(height,('mode','valueM','verticalDatum','sourceNote'))
        _require(height['mode']=='absolute' and terrain.datum!='UNKNOWN_RELATIVE' and height['verticalDatum']==terrain.datum,'VERTICAL_DATUM_CONFLICT','The absolute anchor datum is incompatible.')
        _text(height['sourceNote'],2000);result=_number(height['valueM'],100000)
    _number(result,100000)
    return result


def _scene_frame(anchor,terrain):
    height=_anchor(anchor,terrain)
    terrain.frame.project(*anchor['geographicAnchor'])
    revision='scene-frame:'+_digest({'anchor':anchor,'terrain':terrain.reference(),'convergenceRuleId':CONVERGENCE_RULE})[:32]
    frame=ProjectedFrame(*anchor['geographicAnchor'],height,terrain.datum,revision)
    _require(frame.horizontal_crs==terrain.frame.horizontal_crs and frame.transform_id==terrain.frame.transform_id,'TRANSFORM_UNAVAILABLE','Scene and terrain must use the same verified regional transformation.')
    record={key:frame.record()[key] for key in ('mode','frameRevision','horizontalCrs','verticalDatum','transformId','originEasting','originNorthing','originHeight','convergenceRuleId')}
    record['anchor']=json.loads(json.dumps(anchor))
    if terrain.datum=='UNKNOWN_RELATIVE':record['relativeReferenceId']=terrain.relative_reference
    return frame,record


def _geometry_check(snapshot,trusted_terrains,expected_frame,resample_ground):
    _require(type(resample_ground) is bool)
    value=_base_snapshot(snapshot)
    _require(type(value['coordinateFrame']) is dict)
    mode=value['coordinateFrame'].get('mode')
    if mode=='local_plane':
        display=_local(value)
        if expected_frame is not None:_require(value['coordinateFrame']==expected_frame,'FRAME_CHANGED','The scene frame changed without an anchor operation.')
        return {'snapshot':value,'heightProvenance':[], 'displayPlacements':display,'resourceRefs':{'models':sorted({item['modelVersionId'] for item in value['instances']}),'terrains':[]},
                'geometrySummary':{'mode':'local_plane','instanceCount':len(display),'fieldAccuracyVerified':False,'engineeringValidationPerformed':False}}
    _require(mode=='projected_site','SCENE_SCOPE_UNSUPPORTED','Only local or verified regional projected scenes are supported.')
    _fields(value['terrain'],('terrainVersionId','expectedContentRevision'))
    terrain=_terrain(trusted_terrains,value['terrain']['terrainVersionId'])
    _require(value['terrain']['expectedContentRevision']==terrain.trusted.content_revision,'RESOURCE_CHANGED','The expected terrain content revision changed.')
    frame_data=value['coordinateFrame']
    _fields(frame_data,('mode','frameRevision','horizontalCrs','verticalDatum','transformId','originEasting','originNorthing','originHeight','convergenceRuleId','anchor'),('relativeReferenceId',))
    for key in ('originEasting','originNorthing','originHeight'):_number(frame_data[key],20000000)
    frame,record=_scene_frame(frame_data['anchor'],terrain)
    _require(frame_data==record,'FRAME_CHANGED','The projected frame differs from the verified anchor transformation.')
    if expected_frame is not None:_require(record==expected_frame,'FRAME_CHANGED','An ordinary save cannot replace the established scene frame.')
    provenance=[];display=[]
    for item in value['instances']:
        placement=item['placement'];position=placement['position'];height=placement['height']
        _require(type(height) is dict)
        _fields(position,('mode','longitude','latitude','transformId','frameRevision'))
        _require(position['mode']=='geographic' and position['transformId']==frame.transform_id and position['frameRevision']==frame.frame_revision,'FRAME_CHANGED','The instance refers to another coordinate frame.')
        longitude=_number(position['longitude'],180);latitude=_number(position['latitude'],90)
        frame.project(longitude,latitude)
        if height.get('mode')=='terrain_ground':
            _fields(height,('mode','terrainVersionId','terrainSha256','sampleLongitude','sampleLatitude','sampledHeightM','offsetM','verticalDatum','samplingRule'))
            _require(height['terrainVersionId']==terrain.trusted.version_id and height['terrainSha256']==terrain.trusted.sha256,'RESOURCE_CHANGED','The ground reference uses another fixed terrain.')
            _require(height['verticalDatum']==frame.vertical_datum,'VERTICAL_DATUM_CONFLICT','The ground height datum differs from the scene.')
            _require(height['samplingRule']==PLACEMENT_SAMPLING_RULE,'RESOURCE_CHANGED','The ground sampling rule differs from the fixed display surface.')
            sample_longitude=_number(height['sampleLongitude'],180);sample_latitude=_number(height['sampleLatitude'],90)
            returned_height=_number(height['sampledHeightM'],100000)
            offset=_number(height['offsetM'],100000)
            if not resample_ground:
                _require(abs(sample_longitude-longitude)<=1e-10 and abs(sample_latitude-latitude)<=1e-10,'TERRAIN_SAMPLE_CHANGED','The returned sample position differs from the model position.')
            sampled=terrain.sample(longitude,latitude)
            if not resample_ground:
                _require(abs(returned_height-sampled)<=SAMPLE_EPSILON_M,'TERRAIN_SAMPLE_CHANGED','The returned height does not match the trusted fixed display mesh.')
            height['sampleLongitude']=longitude;height['sampleLatitude']=latitude
            height['sampledHeightM']=sampled
            absolute=sampled+offset
            note={'sceneModelInstanceId':item['sceneModelInstanceId'],'kind':'terrain_estimate','terrainVersionId':terrain.trusted.version_id,'reportSha256':terrain.trusted.report_sha256,'sampledHeightM':sampled,'offsetM':height['offsetM'],'verticalDatum':terrain.datum}
            if terrain.datum=='UNKNOWN_RELATIVE':note['relativeReferenceId']=terrain.relative_reference
        else:
            _fields(height,('mode','valueM','verticalDatum','sourceNote'))
            _require(height['mode']=='absolute' and frame.vertical_datum!='UNKNOWN_RELATIVE' and height['verticalDatum']==frame.vertical_datum,'VERTICAL_DATUM_CONFLICT','An absolute height requires the same known scene datum.')
            _text(height['sourceNote'],2000);absolute=_number(height['valueM'],100000)
            note={'sceneModelInstanceId':item['sceneModelInstanceId'],'kind':'declared_absolute','sourceNote':height['sourceNote'],'verticalDatum':height['verticalDatum']}
        _number(absolute,100000)
        display.append({'sceneModelInstanceId':item['sceneModelInstanceId'],'position':list(frame.to_display(longitude,latitude,absolute,vertical_datum=terrain.datum)),
                        'heightM':absolute,'gridHeadingDeg':frame.true_heading_to_grid(placement['headingDeg'],longitude,latitude),
                        'threeYawRad':frame.true_heading_to_three_yaw(placement['headingDeg'],longitude,latitude)})
        provenance.append(note)
    resource_frame=terrain.frame
    return {'snapshot':value,'heightProvenance':provenance,'displayPlacements':display,
            'resourceRefs':{'models':sorted({item['modelVersionId'] for item in value['instances']}),'terrains':[terrain.reference()]},
            'terrainDisplayTransform':{'translation':[resource_frame.origin_easting_m-frame.origin_easting_m,resource_frame.origin_height_m-frame.origin_height_m,frame.origin_northing_m-resource_frame.origin_northing_m],'rotationY':0,'scale':1},
            'geometrySummary':{'mode':'projected_site','instanceCount':len(display),'transformId':frame.transform_id,'samplingRule':PLACEMENT_SAMPLING_RULE,'fieldAccuracyVerified':False,'engineeringValidationPerformed':False}}


def geometry_check(snapshot,trusted_terrains,*,expected_frame=None,resample_ground=False):
    """Check a snapshot; only the server's read-only edit preview may resample.

    Ordinary save must keep the default strict sample/version conditions. The
    preview returns canonical sample fields for that subsequent strict save.
    """
    try:return _geometry_check(snapshot,trusted_terrains,expected_frame,resample_ground)
    except GeometryError:raise
    except (CoordinateError,TerrainError) as error:raise GeometryError(error.code,str(error)) from error
    except (OSError,ValueError,TypeError,KeyError,IndexError,OverflowError,RecursionError):raise GeometryError('INVALID_REQUEST','The fixed geometry input is invalid.') from None


def anchor_preview(local_snapshot,candidate_terrain_version_id,anchor,trusted_terrains):
    """Transform all placements and the initial camera, without persisting them."""
    try:
        value=_base_snapshot(local_snapshot);_local(value)
        _fields(anchor,('localAnchor','geographicAnchor','trueNorthHeadingDeg','anchorHeight','heightStrategy'))
        _require(type(anchor['anchorHeight']) is dict and 'offsetCompensationM' not in anchor['anchorHeight'],
                 'INVALID_REQUEST','Origin compensation is generated only by a checked terrain replacement.')
        terrain=_terrain(trusted_terrains,candidate_terrain_version_id)
        frame,record=_scene_frame(anchor,terrain)
        anchor_h=frame.origin_height_m
        ground_offset=anchor_h-terrain.sample(*anchor['geographicAnchor']) if anchor['heightStrategy']=='resample_each_ground' else 0
        local=[LocalPlacement(item['sceneModelInstanceId'],item['placement']['position']['xM'],item['placement']['position']['zM'],item['placement']['height']['relativeHeightM'],item['placement']['headingDeg']) for item in value['instances']]
        placed=preview_anchor(local,frame,local_anchor=anchor['localAnchor'],geographic_anchor=anchor['geographicAnchor'],true_north_heading_deg=anchor['trueNorthHeadingDeg'],anchor_height=TerrainHeight(anchor_h,terrain.datum),
                              height_strategy=anchor['heightStrategy'],ground_offset_m=ground_offset,terrain_sample=lambda lon,lat:TerrainHeight(terrain.sample(lon,lat),terrain.datum))
        for item,result in zip(value['instances'],placed):
            old_height=item['placement']['height']['relativeHeightM']
            item['placement']['position']={'mode':'geographic','longitude':result.longitude,'latitude':result.latitude,'transformId':frame.transform_id,'frameRevision':frame.frame_revision}
            item['placement']['headingDeg']=result.heading_deg
            if anchor['heightStrategy']=='resample_each_ground' or terrain.datum=='UNKNOWN_RELATIVE':
                sampled=terrain.sample(result.longitude,result.latitude)
                offset=ground_offset+old_height if anchor['heightStrategy']=='resample_each_ground' else result.height_m-sampled
                item['placement']['height']={'mode':'terrain_ground','terrainVersionId':terrain.trusted.version_id,'terrainSha256':terrain.trusted.sha256,'sampleLongitude':result.longitude,'sampleLatitude':result.latitude,'sampledHeightM':sampled,'offsetM':offset,'verticalDatum':terrain.datum,'samplingRule':PLACEMENT_SAMPLING_RULE}
            else:
                item['placement']['height']={'mode':'absolute','valueM':result.height_m,'verticalDatum':terrain.datum,'sourceNote':'Relative layout from the explicitly reviewed geographic anchor; not a surveyed foundation height.'}
        camera=[LocalPlacement(key,*[value['initialView'][key][index] for index in (0,2,1)]) for key in ('eye','target')]
        transformed=preview_anchor(camera,frame,local_anchor=anchor['localAnchor'],geographic_anchor=anchor['geographicAnchor'],true_north_heading_deg=anchor['trueNorthHeadingDeg'],anchor_height=TerrainHeight(anchor_h,terrain.datum),height_strategy='keep_relative_to_anchor')
        value['initialView']={key:list(result.display) for key,result in zip(('eye','target'),transformed)}
        value['coordinateFrame']=record
        value['terrain']={'terrainVersionId':terrain.trusted.version_id,'expectedContentRevision':terrain.trusted.content_revision}
        result=geometry_check(value,trusted_terrains)
        for note in result['heightProvenance']:
            note['anchorSource']=json.loads(json.dumps(anchor['anchorHeight']));note['kind']='relative_layout_from_anchor' if anchor['heightStrategy']=='keep_relative_to_anchor' else 'terrain_estimate_from_anchor_offset'
        grid_heading=frame.true_heading_to_grid(anchor['trueNorthHeadingDeg'],*anchor['geographicAnchor'])
        angle=math.radians(grid_heading);lx,lz=anchor['localAnchor']
        result['anchorTransform']={'gridHeadingDegAtAnchor':grid_heading,'rotationYRad':-angle,
            'translationM':[-lx*math.cos(angle)+lz*math.sin(angle),0,-lx*math.sin(angle)-lz*math.cos(angle)],
            'heightStrategy':anchor['heightStrategy'],'anchorHeightM':anchor_h,
            'verticalTransform':'rigid_relative' if anchor['heightStrategy']=='keep_relative_to_anchor' else 'per_instance_fixed_mesh'}
        result['impact']={'kind':'first_geographic_anchor','instanceIds':[item['sceneModelInstanceId'] for item in value['instances']],'oldFrameRevision':local_snapshot['coordinateFrame']['frameRevision'],'newFrameRevision':record['frameRevision'],'explicitConfirmationRequired':True}
        return result
    except GeometryError:raise
    except (CoordinateError,TerrainError) as error:raise GeometryError(error.code,str(error)) from error
    except (OSError,ValueError,TypeError,KeyError,IndexError,OverflowError,RecursionError):raise GeometryError('INVALID_REQUEST','The geographic anchor input is invalid.') from None


def terrain_replacement_preview(snapshot,candidate_terrain_version_id,strategy,trusted_terrains):
    """Preview one fixed terrain replacement without moving geographic identity.

    The old snapshot is checked strictly before deriving any proposed fields.
    Optional diagnostic samples never turn a declared absolute height into a
    ground constraint; required ground samples retain the normal NoData rules.
    """
    try:
        _require(strategy in ('keep_height','resample_ground'))
        _uuid(candidate_terrain_version_id)
        _require(type(trusted_terrains) is dict and len(trusted_terrains)<=2)
        previous=geometry_check(snapshot,trusted_terrains)
        value=previous['snapshot'];old_frame=value['coordinateFrame']
        _require(old_frame['mode']=='projected_site','SCENE_SCOPE_UNSUPPORTED','Terrain replacement requires an already anchored scene.')
        old_id=value['terrain']['terrainVersionId']
        _require(candidate_terrain_version_id!=old_id)
        _require(set(trusted_terrains)=={old_id,candidate_terrain_version_id},'NOT_FOUND_OR_FORBIDDEN','Exactly the old and candidate fixed terrains must be authorized.')
        old=_terrain(trusted_terrains,old_id);new=_terrain(trusted_terrains,candidate_terrain_version_id)
        _require(old.datum==new.datum,'VERTICAL_DATUM_CONFLICT','Terrain replacement does not perform a vertical datum conversion.')
        if old.datum=='UNKNOWN_RELATIVE':
            _require(old.relative_reference==new.relative_reference,'VERTICAL_DATUM_CONFLICT','Unknown terrains require the same explicit relative height reference.')
        _require(old.frame.horizontal_crs==new.frame.horizontal_crs and old.frame.transform_id==new.frame.transform_id,
                 'TRANSFORM_UNAVAILABLE','The candidate terrain requires another regional transformation.')
        old_ref=old.reference();new_ref=new.reference()
        anchor=json.loads(json.dumps(old_frame['anchor']))
        old_anchor_source=json.loads(json.dumps(anchor['anchorHeight']))
        if new.datum=='UNKNOWN_RELATIVE':
            anchor_sample=new.sample(*anchor['geographicAnchor'])
            offset=old_frame['originHeight']-anchor_sample
            anchor['anchorHeight']={'mode':'terrain_ground','terrainVersionId':candidate_terrain_version_id,
                'offsetM':offset,'offsetCompensationM':math.fsum((old_frame['originHeight'],-anchor_sample,-offset))}
        else:
            anchor['anchorHeight']={'mode':'absolute','valueM':old_frame['originHeight'],'verticalDatum':old.datum,
                'sourceNote':'Preserved scene height origin from the reviewed old terrain '+old_id+' and its anchor; not a surveyed height.'}
        def browser_stable_numbers(item):
            if type(item) is float and item.is_integer():return int(item)
            if type(item) is list:return [browser_stable_numbers(child) for child in item]
            if type(item) is dict:return {key:browser_stable_numbers(child) for key,child in item.items()}
            return item
        # Only new replacement anchors change their number spelling. Existing
        # frame digests retain their original integer/float encoding semantics.
        anchor=browser_stable_numbers(anchor)
        frame,record=_scene_frame(anchor,new)
        fixed_keys=('horizontalCrs','verticalDatum','transformId','originEasting','originNorthing','originHeight','convergenceRuleId')
        _require(all(record[key]==old_frame[key] for key in fixed_keys),'FRAME_CHANGED','The candidate cannot preserve the exact established scene origin and datum.')
        _require(record['frameRevision']!=old_frame['frameRevision'],'FRAME_CHANGED','A terrain replacement requires a new fixed frame revision.')
        sample_issues=[];changes=[];old_notes={note['sceneModelInstanceId']:note for note in previous['heightProvenance']}
        old_displays={item['sceneModelInstanceId']:item for item in previous['displayPlacements']}
        def diagnostic_sample(terrain,longitude,latitude,identifier,role,required):
            try:return terrain.sample(longitude,latitude)
            except (CoordinateError,TerrainError) as error:
                if required or error.code not in ('NO_DATA','OUTSIDE_COVERAGE','OUTSIDE_PROJECTION_AREA'):raise
                sample_issues.append({'sceneModelInstanceId':identifier,'terrainVersionId':terrain.trusted.version_id,
                                      'role':role,'code':error.code})
                return None
        previous_heights={}
        for item in value['instances']:
            identifier=item['sceneModelInstanceId'];placement=item['placement'];position=placement['position'];height=placement['height']
            previous_heights[identifier]=json.loads(json.dumps(height))
            longitude,latitude=position['longitude'],position['latitude'];old_mode=height['mode']
            old_h=old_displays[identifier]['heightM']
            old_sample=diagnostic_sample(old,longitude,latitude,identifier,'old',old_mode=='terrain_ground')
            required=old_mode=='terrain_ground' and (strategy=='resample_ground' or new.datum=='UNKNOWN_RELATIVE')
            new_sample=diagnostic_sample(new,longitude,latitude,identifier,'new',required)
            if old_mode=='terrain_ground':
                if strategy=='keep_height' and new.datum!='UNKNOWN_RELATIVE':
                    placement['height']={'mode':'absolute','valueM':old_h,'verticalDatum':new.datum,
                        'sourceNote':'Height preserved from old terrain estimate '+old_id+'; not a surveyed foundation height.'}
                else:
                    offset=height['offsetM'] if strategy=='resample_ground' else old_h-new_sample
                    placement['height']={'mode':'terrain_ground','terrainVersionId':candidate_terrain_version_id,
                        'terrainSha256':new.trusted.sha256,'sampleLongitude':longitude,'sampleLatitude':latitude,
                        'sampledHeightM':new_sample,'offsetM':offset,'verticalDatum':new.datum,'samplingRule':PLACEMENT_SAMPLING_RULE}
            position['frameRevision']=record['frameRevision']
            new_height=placement['height'];new_h=new_height['valueM'] if new_height['mode']=='absolute' else new_height['sampledHeightM']+new_height['offsetM']
            _number(new_h,100000)
            _require(not item['positionLocked'] or abs(new_h-old_h)<=SAMPLE_EPSILON_M,'INSTANCE_POSITION_LOCKED','The locked instance would change its actual height.')
            changes.append({'sceneModelInstanceId':identifier,'oldHeightMode':old_mode,'newHeightMode':new_height['mode'],
                'oldSampledHeightM':old_sample,'newSampledHeightM':new_sample,
                'sampledHeightDeltaM':None if old_sample is None or new_sample is None else new_sample-old_sample,
                'oldHeightM':old_h,'newHeightM':new_h,'heightDeltaM':new_h-old_h})
        value['coordinateFrame']=record
        value['terrain']={'terrainVersionId':new.trusted.version_id,'expectedContentRevision':new.trusted.content_revision}
        result=geometry_check(value,trusted_terrains)
        for note in result['heightProvenance']:
            identifier=note['sceneModelInstanceId'];old_height=previous_heights[identifier]
            note['replacementStrategy']=strategy
            note['previousHeight']=old_height;note['previousHeightProvenance']=old_notes[identifier]
            note['previousTerrainRef']=old_ref;note['previousAnchorHeight']=old_anchor_source
            if old_height['mode']=='terrain_ground':
                note['kind']='terrain_estimate_preserved_as_absolute' if strategy=='keep_height' and new.datum!='UNKNOWN_RELATIVE' else 'terrain_estimate_on_replacement'
        result['impact']={'kind':'terrain_replacement','strategy':strategy,'oldTerrainVersionId':old_id,
            'newTerrainVersionId':candidate_terrain_version_id,'oldTerrainRef':old_ref,'newTerrainRef':new_ref,
            'oldFrameRevision':old_frame['frameRevision'],'newFrameRevision':record['frameRevision'],
            'instanceIds':[item['sceneModelInstanceId'] for item in value['instances']],
            'instances':changes,'sampleIssues':sample_issues,'explicitConfirmationRequired':True}
        return result
    except GeometryError:raise
    except (CoordinateError,TerrainError) as error:raise GeometryError(error.code,str(error)) from error
    except (OSError,ValueError,TypeError,KeyError,IndexError,OverflowError,RecursionError):raise GeometryError('INVALID_REQUEST','The fixed terrain replacement input is invalid.') from None


def main(argv=None):
    import argparse
    import resource
    import signal
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('request',type=Path);parser.add_argument('--terrain-root',type=Path)
    args=parser.parse_args(argv)
    resource.setrlimit(resource.RLIMIT_CPU,(30,30))
    if sys.platform.startswith('linux'):resource.setrlimit(resource.RLIMIT_AS,(512*1024*1024,512*1024*1024))
    os.environ['PROJ_NETWORK']='OFF'
    for key in ('OPENBLAS_NUM_THREADS','OMP_NUM_THREADS','MKL_NUM_THREADS'):os.environ[key]='1'
    def expired(*_):raise GeometryError('SCENE_LIMIT_EXCEEDED','The geometry wall clock budget expired.')
    signal.signal(signal.SIGALRM,expired);signal.alarm(60)
    try:
        _require(args.request.is_file() and not args.request.is_symlink() and args.request.stat().st_size<=MAX_REQUEST_BYTES)
        raw=args.request.read_bytes();_require(len(raw)<=MAX_REQUEST_BYTES)
        request=strict_json(raw);_require(type(request) is dict);kind=request.get('kind')
        keys=('kind','snapshot','trustedTerrains')
        _require(kind in ('validate','anchor','terrain_replacement'))
        if kind=='validate':_fields(request,keys,('expectedFrame','resampleGround'))
        elif kind=='anchor':_fields(request,keys+('candidateTerrainVersionId','anchor'))
        else:_fields(request,keys+('candidateTerrainVersionId','strategy'))
        manifests=request['trustedTerrains'];_require(type(manifests) is list and len(manifests)<=(2 if kind=='terrain_replacement' else 1))
        terrains={}
        if manifests:
            _require(args.terrain_root is not None and args.terrain_root.is_absolute() and args.terrain_root.is_dir() and not args.terrain_root.is_symlink())
            for item in manifests:
                _fields(item,('terrainVersionId','contentRevision','sha256','reportSha256'))
                version=_uuid(item['terrainVersionId'])
                _require(version not in terrains)
                _text(item['contentRevision']);_sha(item['sha256']);_sha(item['reportSha256'])
                terrains[version]=TrustedTerrain(version,item['contentRevision'],item['sha256'],item['reportSha256'],args.terrain_root/version/'derived')
        if kind=='validate':result=geometry_check(request['snapshot'],terrains,expected_frame=request.get('expectedFrame'),resample_ground=request.get('resampleGround',False))
        elif kind=='anchor':result=anchor_preview(request['snapshot'],request['candidateTerrainVersionId'],request['anchor'],terrains)
        else:result=terrain_replacement_preview(request['snapshot'],request['candidateTerrainVersionId'],request['strategy'],terrains)
        encoded=json.dumps(result,ensure_ascii=False,allow_nan=False,separators=(',',':'))
        _require(len(encoded.encode())<=MAX_OUTPUT_BYTES,'SCENE_LIMIT_EXCEEDED','The geometry result exceeds its output budget.')
        print(encoded);return 0
    except (GeometryError,ProbeError,MemoryError,ValueError,TypeError,KeyError,OSError,RecursionError) as error:
        print(json.dumps({'code':getattr(error,'code','INVALID_REQUEST')}));return 2
    finally:signal.alarm(0)


if __name__=='__main__':sys.exit(main())
