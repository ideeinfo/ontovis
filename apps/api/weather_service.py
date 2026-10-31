"""Existing session, project authorization, scene ownership and CAS for weather."""
from .assistant_store import require, identifier
from .weather_store import WeatherStore, validate_config
from .weather_source import ENDPOINT, SOURCE


def request(sessions, sid, path, payload):
    row = sessions._session(sid, payload)
    project = sessions._ref(payload.get('projectRef'))
    access = sessions._access(sid, row, project)
    action = path.removeprefix('/api/workbench/weather/')
    require(action in ('config', 'save', 'test', 'current'))
    writing = action in ('save', 'test')
    if writing: require(access.get('role') == 'admin', 'WEATHER_WRITE_FORBIDDEN', 403)
    body = {k: v for k, v in payload.items() if k not in ('expectedSessionRevision', 'projectRef')}
    expected = {'config': set(), 'save': {'config', 'expectedRevision', 'expectedAccessRevision', 'requestId'},
                'test': {'config', 'sceneId', 'expectedAccessRevision'}, 'current': {'sceneId'}}[action]
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

    def check_scene(scene_id):
        identifier(scene_id)
        workspace = sessions.registry.lookup(project)
        require(workspace is not None, 'NOT_FOUND_OR_FORBIDDEN', 404)
        library = sessions._workspace(workspace).library
        with library.connect() as db:
            found = db.execute('''select s.id from scenes s left join scene_lifecycle l on l.scene_id=s.id
                where s.id=? and s.project_code=? and coalesce(l.state,'active')='active' ''', (scene_id, project)).fetchone()
        require(found is not None, 'NOT_FOUND_OR_FORBIDDEN', 404)

    if action == 'config': value = store.config(project)
    elif action == 'save':
        config = validate_config(body['config'])
        for point in config['points']: check_scene(point['sceneId'])
        value = store.save(project, row.authority.username, body, authorize)
    else:
        check_scene(body['sceneId'])
        saved = store.config(project)
        config = validate_config(body['config']) if action == 'test' else saved['config']
        point = next((p for p in config['points'] if p['sceneId'] == body['sceneId']), None)
        if not point: value = dict(status='unconfigured', source=SOURCE)
        elif not config['enabled'] and action != 'test': value = dict(status='disabled', source=SOURCE)
        else: value = store.current(config, point, authorize)
        if action == 'current':
            require(store.config(project)['revision'] == saved['revision'], 'WEATHER_CONFIG_CHANGED', 409)
        value.update(revision=saved['revision'], preview=action == 'test')
    authorize()
    return {**value, 'endpoint': ENDPOINT, 'canManage': access.get('role') == 'admin',
            'accessRevision': access['accessRevision'], 'projectRef': payload['projectRef'], 'sessionRevision': row.revision}
