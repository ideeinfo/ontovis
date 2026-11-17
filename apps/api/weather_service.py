"""Existing session, project authorization, scene ownership and CAS for weather."""
import json
import math
from .assistant_store import require, identifier
from .weather_store import WeatherStore, validate_config
from .weather_source import ENDPOINT, SOURCE


def _point_from_snapshot(scene_id, text):
    snapshot = json.loads(text)
    frame = snapshot.get('coordinateFrame') if isinstance(snapshot, dict) else None
    if not isinstance(frame, dict) or frame.get('mode') != 'projected_site': return None
    anchor = (frame.get('anchor') or {}).get('geographicAnchor')
    if not isinstance(anchor, list) or len(anchor) != 2: return None
    lon, lat = anchor
    if type(lat) not in (int, float) or type(lon) not in (int, float) or not (math.isfinite(lat) and math.isfinite(lon)): return None
    if not (-90 <= lat <= 90 and -180 <= lon <= 180): return None
    return dict(sceneId=scene_id, latitude=math.trunc(float(lat) * 10000) / 10000, longitude=math.trunc(float(lon) * 10000) / 10000)


def request(sessions, sid, path, payload):
    row = sessions._session(sid, payload)
    project = sessions._ref(payload.get('projectRef'))
    access = sessions._access(sid, row, project)
    action = path.removeprefix('/api/workbench/weather/')
    require(action in ('config', 'save', 'test', 'current'))
    writing = action in ('save', 'test')
    if writing: require(access.get('role') == 'admin', 'WEATHER_WRITE_FORBIDDEN', 403)
    body = {k: v for k, v in payload.items() if k not in ('expectedSessionRevision', 'projectRef')}
    if action == 'test':
        require(set(body) in ({'config', 'expectedAccessRevision'}, {'config', 'sceneId', 'expectedAccessRevision'}))
    else:
        expected = {'config': set(), 'save': {'config', 'expectedRevision', 'expectedAccessRevision', 'requestId'},
                    'current': {'sceneId'}}[action]
        require(set(body) == expected)

    def authorize():
        sessions.guard(sid, row)
        current = sessions._access(sid, row, project)
        require(current['accessRevision'] == access['accessRevision'] and
                (not writing or current.get('role') == 'admin'), 'ACCESS_CHANGED', 409)
        sessions.guard(sid, row)

    if writing: require(body['expectedAccessRevision'] == access['accessRevision'], 'ACCESS_CHANGED', 409)
    with sessions.registry.lock:
        if sessions.weather is None: sessions.weather = WeatherStore(sessions.shared.library, sessions.connection_id)
    store = sessions.weather

    scene_states = {}

    def check_scene(scene_id):
        identifier(scene_id)
        workspace = sessions.registry.lookup(project)
        require(workspace is not None, 'NOT_FOUND_OR_FORBIDDEN', 404)
        library = sessions._workspace(workspace).library
        with library.connect() as db:
            found = db.execute('''select s.id, s.head_revision, r.snapshot from scenes s
                join scene_revisions r on r.revision=s.head_revision
                left join scene_lifecycle l on l.scene_id=s.id
                where s.id=? and s.project_code=? and coalesce(l.state,'active')='active' ''', (scene_id, project)).fetchone()
        require(found is not None, 'NOT_FOUND_OR_FORBIDDEN', 404)
        scene_states[scene_id] = found['head_revision']
        return _point_from_snapshot(found['id'], found['snapshot'])

    def first_project_point(allowed=None):
        workspace = sessions.registry.lookup(project)
        if workspace is None: return None
        library = sessions._workspace(workspace).library
        with library.connect() as db:
            rows = db.execute('''select s.id, s.head_revision, r.snapshot from scenes s
                join scene_revisions r on r.revision=s.head_revision
                left join scene_lifecycle l on l.scene_id=s.id
                where s.project_code=? and coalesce(l.state,'active')='active'
                order by s.updated_at desc, s.id''', (project,)).fetchall()
        for item in rows:
            if allowed is not None and item['id'] not in allowed: continue
            point = _point_from_snapshot(item['id'], item['snapshot'])
            if point:
                scene_states[item['id']] = item['head_revision']
                return point
        return None

    if action == 'config': value = store.config(project)
    elif action == 'save':
        value = store.save(project, row.authority.username, body, authorize)
    else:
        saved = store.config(project)
        allowed = saved.get('legacySceneIds')
        if action == 'test':
            config = validate_config(body['config'])
            if 'points' in config: allowed = [point['sceneId'] for point in config['points']]
            point = check_scene(body['sceneId']) if 'sceneId' in body else first_project_point(allowed)
            if point and allowed is not None and point['sceneId'] not in allowed: point = None
            require(point is not None, 'WEATHER_POINT_REQUIRED', 422)
            value = store.current(config, point, authorize)
        else:
            point = check_scene(body['sceneId'])
            config = saved['config']
            if saved['revision'] == 0: value = dict(status='unconfigured', source=SOURCE)
            elif not config['enabled']: value = dict(status='disabled', source=SOURCE)
            elif allowed is not None and body['sceneId'] not in allowed:
                value = dict(status='unconfigured', error='WEATHER_SCENE_NOT_ENABLED', source=SOURCE)
            elif not point: value = dict(status='unconfigured', source=SOURCE)
            else: value = store.current(config, point, authorize)
            require(store.config(project)['revision'] == saved['revision'], 'WEATHER_CONFIG_CHANGED', 409)
        value.update(revision=saved['revision'], preview=action == 'test')
    for scene_id, revision in list(scene_states.items()):
        check_scene(scene_id)
        require(scene_states[scene_id] == revision, 'SCENE_CHANGED', 409)
    authorize()
    return {**value, 'endpoint': ENDPOINT, 'canManage': access.get('role') == 'admin',
            'accessRevision': access['accessRevision'], 'projectRef': payload['projectRef'], 'sessionRevision': row.revision}
