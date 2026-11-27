"""Placement catalogue from existing project application geometry configurations."""
from .authority import PreviewError
from .equipment_reader import EquipmentReader


def require(value):
    if not value:
        raise PreviewError(502, 'SOURCE_UNAVAILABLE')


def current_applications(equipment):
    result, identifiers, offset, total = [], set(), 0, None
    while True:
        page = equipment.applications({'offset':offset,'limit':50})
        rows = page.get('items')
        require(type(rows) is list and len(rows)<=50 and type(page.get('total')) is int
                and 0<=page['total']<=500 and page.get('offset')==offset and page.get('limit')==50)
        require(total is None or total==page['total'])
        total = page['total']
        for row in rows:
            require(type(row) is dict)
            identifier = EquipmentReader.identifier(row.get('applicationId'))
            EquipmentReader.identifier(row.get('revisionId'))
            require(identifier not in identifiers)
            identifiers.add(identifier); result.append(row)
        if len(result)==total:
            return result
        require(len(rows)==50 and len(result)<total)
        offset += 50


def application_model_catalogue(store, reader, models, authorize):
    """No engineering object is inferred from a model name or an application ID."""
    authorize()
    equipment = EquipmentReader(reader)
    current = current_applications(equipment)
    configured = store.catalogue(authorize)['items'] if store else []
    by_revision = {}
    for item in configured:
        ref = item['snapshot'].get('projectApplicationRef')
        if ref:
            require(ref['applicationRevisionId'] not in by_revision)
            by_revision[ref['applicationRevisionId']] = item
    items, covered_definitions, captured, model_states = [], set(), [], {}
    for summary in current:
        configuration = by_revision.get(summary['revisionId'])
        if configuration is None:
            continue
        application = equipment.application(summary['revisionId'])
        source, specification = application['snapshot'], application['specification']
        require(application['applicationId']==summary['applicationId']
                and application.get('headRevisionId')==summary['revisionId'])
        ref = {'applicationId':application['applicationId'],'applicationRevisionId':application['revisionId'],
               'specificationRevisionId':source['specificationRevisionId']}
        require(configuration['snapshot']['projectApplicationRef']==ref)
        if specification.get('objectKind')!='turbine' or specification.get('status')!='active':
            continue
        require(specification.get('revisionId')==ref['specificationRevisionId'])
        code, title = specification.get('code'), specification.get('name')
        require(isinstance(code,str) and bool(code) and isinstance(title,str) and bool(title))
        root = source.get('rootDefinition')
        item = {'catalogueKey':'application:'+ref['applicationRevisionId'],
                'definitionEntityUid':root['entityUid'] if root else None,
                'projectApplicationRef':ref,'configurationId':configuration['configurationId'],
                'configurationRevision':configuration['configurationRevision'],
                'modelCode':code,'displayName':title,'manufacturer':specification.get('manufacturer'),
                'appearanceModel':None,'detailedModel':None,'associationBasis':'user_declared'}
        versions = []
        for entry in configuration['snapshot']['models']:
            identity = models.content_identity(entry['modelVersionId'])
            version = models.model(identity['modelAssetId'],entry['modelVersionId'],authorize)
            if version.get('assetState')=='deleted':
                continue
            versions.append(version)
            model_states[version['modelVersionId']] = {key:version.get(key) for key in
                ('modelAssetId','contentRevision','sha256','assetRevision','assetState','representationType','calibrationState')}
        # The configuration fixes versions; the asset's representation is a declaration.
        for version in sorted(versions,key=lambda value:(value['calibrationState']=='verified',value['createdAt']),reverse=True):
            key = {'appearance':'appearanceModel','detailed':'detailedModel'}.get(version.get('representationType'))
            if key and item[key] is None:
                item[key] = {name:version[name] for name in ('modelAssetId','modelVersionId','contentRevision','sha256','displayName','calibrationState')}
                item[key]['representationType'] = version['representationType']
                if 'thumbnail' in version:
                    item[key]['thumbnail'] = version['thumbnail']
        if item['appearanceModel'] or item['detailedModel']:
            items.append(item)
            if root:
                covered_definitions.add(root['entityUid'])
            captured.append((application,configuration))
    # Recheck source heads and local configuration heads before returning a mixed catalogue.
    if captured:
        if current_applications(equipment)!=current:
            raise PreviewError(409,'ENGINEERING_CHANGED')
        latest = {item['configurationId']:item for item in store.catalogue(authorize)['items']}
        for application,configuration in captured:
            if equipment.application(application['revisionId'])!=application:
                raise PreviewError(409,'ENGINEERING_CHANGED')
            if latest.get(configuration['configurationId'])!=configuration:
                raise PreviewError(409,'REVISION_CONFLICT')
        for version,state in model_states.items():
            latest_model = models.model(state['modelAssetId'],version,authorize)
            if any(latest_model.get(key)!=value for key,value in state.items()):
                raise PreviewError(409,'MODEL_ASSET_CHANGED')
    authorize()
    return items, covered_definitions
