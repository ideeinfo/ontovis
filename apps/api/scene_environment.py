"""Versioned visual environment configuration; never alters engineering geometry."""
import math
import re
from .authority import PreviewError


def require(ok, code='INVALID_SCENE_ENVIRONMENT', status=422):
    if not ok:
        raise PreviewError(status, code)


def fields(value, names):
    require(type(value) is dict and set(value) == set(names.split()))


def number(value, low, high, *, upper_open=False):
    require(type(value) in (int, float) and low <= value
            and (value < high if upper_open else value <= high) and math.isfinite(value))


def color(value):
    require(type(value) is str and re.fullmatch(r'#[0-9a-fA-F]{6}', value) is not None)


def validate_environment(snapshot):
    if 'environment' not in snapshot or snapshot['environment'] is None:
        return
    v = snapshot['environment']
    require(type(v) is dict and type(v.get('schemaVersion')) is int and v['schemaVersion'] == 1,
            'UNSUPPORTED_SCENE_ENVIRONMENT')
    fields(v, 'schemaVersion renderProfile presetId color lighting atmosphere shadows surface water animation')
    require(v['renderProfile'] == 'standard-v1' and v['presetId'] in
            ('land-day-v1', 'offshore-overview-v1', 'dusk-v1', 'custom-v1'))
    fields(v['color'], 'toneMapping exposure')
    require(v['color']['toneMapping'] in ('none', 'aces'));number(v['color']['exposure'], .25, 2.5)
    light=v['lighting'];fields(light, 'hemisphereIntensity environment sun')
    number(light['hemisphereIntensity'], 0, 5)
    fields(light['environment'], 'source intensity')
    require(light['environment']['source'] == 'procedural-sky-v1');number(light['environment']['intensity'], 0, 3)
    sun=light['sun'];fields(sun, 'enabled azimuthDeg elevationDeg intensity color')
    require(type(sun['enabled']) is bool);number(sun['azimuthDeg'], 0, 360, upper_open=True)
    number(sun['elevationDeg'], 5, 85);number(sun['intensity'], 0, 5);color(sun['color'])
    sky=v['atmosphere'];fields(sky, 'sky topColor horizonColor fog')
    require(sky['sky'] == 'gradient-v1');color(sky['topColor']);color(sky['horizonColor'])
    fog=sky['fog'];fields(fog, 'mode nearM farM')
    require(fog['mode'] in ('off', 'linear'));number(fog['nearM'], 0, 100000);number(fog['farM'], 0, 100000)
    require(fog['nearM'] < fog['farM'])
    shadow=v['shadows'];fields(shadow, 'mode quality radiusM')
    require(shadow['mode'] in ('off', 'sun-local') and shadow['quality'] == 'balanced');number(shadow['radiusM'], 100, 1000)
    surface=v['surface'];fields(surface, 'imageryShading textureSet terrainRoughness textureRepeatM')
    require(surface['imageryShading'] in ('source-color', 'lit') and surface['textureSet'] is None)
    number(surface['terrainRoughness'], .2, 1);number(surface['textureRepeatM'], 1, 200)
    water=v['water'];fields(water, 'enabled baseSurface mode travelHeadingDeg rippleStrength amplitudeM wavelengthM travelSpeedMps color roughness reflection seed')
    require(type(water['enabled']) is bool)
    require(water['baseSurface'] == 'active-flat-relative-terrain' and water['mode'] == 'normal-waves'
            and water['reflection'] == 'procedural-sky' and type(water['amplitudeM']) in (int,float) and water['amplitudeM'] == 0)
    number(water['travelHeadingDeg'], 0, 360, upper_open=True);number(water['rippleStrength'], 0, 1)
    number(water['wavelengthM'], 5, 200);number(water['travelSpeedMps'], 0, 5)
    color(water['color']);number(water['roughness'], .1, 1)
    require(type(water['seed']) is int and 0 <= water['seed'] <= 2147483647)
    if water['enabled']:
        frame=snapshot.get('coordinateFrame', {})
        require(type(frame) is dict and frame.get('mode') == 'projected_site' and frame.get('verticalDatum') == 'UNKNOWN_RELATIVE'
                and snapshot.get('terrain') is not None, 'WATER_SURFACE_NOT_SUPPORTED')
    animation=v['animation'];fields(animation, 'defaultPlayback initialPhase')
    require(animation['defaultPlayback'] in ('playing', 'paused'))
    number(animation['initialPhase'], 0, 1000)


def environment_write(body, previous):
    """Old clients cannot silently omit an adopted environment, including explicit legacy."""
    candidate=body['snapshot']
    if 'environment' in previous or 'environment' in candidate or 'environmentWriteVersion' in body:
        require(type(body.get('environmentWriteVersion')) is int and body['environmentWriteVersion'] == 1,
                'ENVIRONMENT_WRITE_VERSION_REQUIRED', 409)
        require('environment' not in previous or 'environment' in candidate,
                'ENVIRONMENT_FIELD_REQUIRED', 409)


def preserve_environment(before, after):
    require(('environment' in before) == ('environment' in after)
            and before.get('environment') == after.get('environment'), 'INVALID_GEOMETRY_RESULT')
