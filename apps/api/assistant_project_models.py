"""Bounded assistant catalogue of current project applications and saved model references."""
import json

from .assistant_store import digest, require
from .assistant_summaries import redact
from .equipment_reader import EquipmentReader
from .project_application_models import current_applications

LIMIT = 4
SCENE_LIMIT = 4
SCOPE = '当前项目采用配置及已保存活动场景对固定模型的引用'
DEVICE_SCOPE = '当前项目安装设备及其当前采用的固定配置'


def device_catalogue(reader, configurations, guard, query):
    """Use source equipment identities, including separate results for same-name devices."""
    guard()
    equipment = EquipmentReader(reader)
    request = dict(q=query, limit=LIMIT, rootsOnly=True)
    page = equipment.catalogue(request)
    devices = equipment.resolve([item['entityUid'] for item in page['items']]) if page['items'] else {}
    applications = current_applications(equipment)
    configured = configurations.catalogue(guard)['items']
    current = {(item['applicationId'], item['revisionId'], item['specificationRevisionId']) for item in applications}
    by_application = {}
    for config in configured:
        ref = config['snapshot'].get('projectApplicationRef')
        if ref:
            by_application[(ref['applicationId'], ref['applicationRevisionId'], ref['specificationRevisionId'])] = config
    items = []
    for item in page['items']:
        device = devices[item['entityUid']]
        require(device['item']['entityRevision']==item['entityRevision']
                and device['item']['equipmentState']=='active','ENGINEERING_CHANGED',409)
        adoption = device['adoption'] or {}
        key = tuple(adoption.get(k) for k in ('applicationId','applicationRevisionId','specificationRevisionId'))
        config = by_application.get(key) if key in current else None
        code = next((entry['value'] for entry in item['identifiers']
                     if entry['role']=='primary' and entry['status']=='accepted' and entry['scheme']=='RDS'
                     and entry['scopeType']=='project' and entry['scopeKey']==reader.project_code), None)
        items.append(dict(title=item['displayName'], identifier=item['entityUid'], version=item['entityRevision'],
            deviceCode=code, installation=device['context']['displayName'],
            configuration=config['snapshot']['displayName'] if config else None,
            configurationId=config['configurationId'] if config else None,
            configurationRevision=config['configurationRevision'] if config else None,
            modelCount=len(config['snapshot']['models']) if config else 0))
    require(equipment.catalogue(request)==page,'ENGINEERING_CHANGED',409)
    if devices:
        latest = equipment.resolve(list(devices))
        for uid, device in devices.items():
            require(all(latest[uid][field]==device[field] for field in ('item','adoption','context')),'ENGINEERING_CHANGED',409)
    require(current_applications(equipment)==applications,'ENGINEERING_CHANGED',409)
    require(configurations.catalogue(guard)['items']==configured,'REVISION_CONFLICT',409)
    guard()
    return dict(items=items, truncated=page['nextCursor'] is not None,
                snapshotRevision=digest([page['snapshotRevision'],items]))


def catalogue(reader, configurations, scenes, models, actor, guard, access_revision, query):
    equipment = EquipmentReader(reader)
    applications = current_applications(equipment)
    configured = configurations.catalogue(guard)['items']
    by_application = {(row['applicationId'], row['revisionId'], row['specificationRevisionId']): row
                      for row in applications}
    matches = []
    needle = query.casefold().strip()
    for config in configured:
        snapshot = config['snapshot']
        ref = snapshot.get('projectApplicationRef')
        if not ref:
            continue
        application = by_application.get((ref['applicationId'],ref['applicationRevisionId'],ref['specificationRevisionId']))
        if not application:
            continue
        if needle and not any(needle in text.casefold() for text in (
            snapshot['displayName'],application['name'],application['specificationName'])):
            continue
        for model in snapshot['models']:
            matches.append((config,model['modelVersionId']))

    uses, versions, items, scene_revision = {}, {}, [], None
    for config,version_id in matches[:LIMIT]:
        if version_id not in uses:
            versions[version_id] = models.fixed_version_metadata(version_id,guard)
            uses[version_id] = scenes.uses(version_id,actor,guard,access_revision=access_revision,
                                          scope='current',limit=SCENE_LIMIT)
        report = uses[version_id]
        require(scene_revision is None or report['snapshotRevision']==scene_revision,'SNAPSHOT_CHANGED',409)
        scene_revision = report['snapshotRevision']
        model = versions[version_id]
        items.append(dict(title=model['displayName'],identifier=model['modelAssetId'],version=version_id,
            configuration=config['snapshot']['displayName'],configurationRevision=config['configurationRevision'],
            configurationId=config['configurationId'],
            representation=model['representationType'],state=model['assetState'],
            instanceCount=report['currentInstanceCount'],moreScenes=report['nextCursor'] is not None,
            scenes=[dict(title=row['displayName'],instanceCount=row['currentInstanceCount'],
                         sceneId=row['sceneId'],sceneRevision=row['currentSceneRevision']) for row in report['items']]))

    require(current_applications(equipment)==applications,'ENGINEERING_CHANGED',409)
    require(configurations.catalogue(guard)['items']==configured,'REVISION_CONFLICT',409)
    for version_id, model in versions.items():
        require(models.fixed_version_metadata(version_id,guard)==model,'MODEL_ASSET_CHANGED',409)
    if scene_revision is not None:
        latest = scenes.listing(actor,guard,access_revision=access_revision,limit=1)
        require(latest['snapshotRevision']==scene_revision,'SNAPSHOT_CHANGED',409)
    guard()
    total = len(matches)
    revision = digest([scene_revision, total, items])
    return dict(items=items, total=total, snapshotRevision=revision, truncated=total>LIMIT,
                sceneUsageTruncated=any(row['moreScenes'] for row in items))


def summary(value, private):
    def short(name, maximum):
        return ''.join(char if char.isprintable() else ' ' for char in redact(name,private))[:maximum]

    rows = [[short(item['configuration'],24),short(item['title'],24),item['version'][:8],
             item['representation'],item['state'],item['instanceCount'],
             [short(scene['title'],16) for scene in item['scenes'][:2]],
             item['moreScenes'] or len(item['scenes'])>2] for item in value['items']]
    columns = ['采用配置','模型','固定版本','表示用途','资源状态','保存实例数','使用场景','更多场景']
    return json.dumps(dict(scope=SCOPE,total=value['total'],columns=columns,items=rows),
                      ensure_ascii=False,separators=(',',':'))
