"""Read-only display representations declared by one adopted equipment configuration."""
from copy import deepcopy

from .authority import PreviewError


def calibrated_representation(model, geographic):
    # Each verified calibration maps its own source coordinates to the equipment
    # root, metric units and canonical forward/up axes; raw matrices may differ.
    return (model.get('state') == 'ready' and model.get('assetState') == 'active'
            and model.get('calibrationState') == 'verified' and model.get('canPlace') is True
            and (not geographic or model.get('canPlaceGeographic') is True)
            and model.get('calibration', {}).get('unit') == 'm'
            and model['calibration'].get('state') == 'verified'
            and model['calibration'].get('axes') == 'Y_UP_RIGHT_HANDED')


def inspection_projection(opened, choice, store, equipment, load_model, authorize):
    """Use only a current root's adopted configuration, preserving the saved scene."""
    authorize()
    if not choice or opened['sceneRevision'] != opened['headRevision']:
        return opened, None
    instance = next((item for item in opened['snapshot']['instances']
                     if item['sceneModelInstanceId'] == choice.get('sceneModelInstanceId')
                     and item['modelVersionId'] == choice.get('modelVersionId')), None)
    if not instance or not instance.get('rootBinding'):
        return opened, None
    base = load_model(instance['modelVersionId'])
    geographic = opened['snapshot']['coordinateFrame']['mode'] == 'projected_site'
    if base.get('representationType') != 'appearance' or not calibrated_representation(base, geographic):
        return opened, None
    uid = instance['rootBinding']['objectRef']['entityUid']
    configuration = store.for_equipment(uid, equipment)
    if (not configuration or not configuration['snapshot'].get('projectApplicationRef')
            or not any(model['modelVersionId'] == instance['modelVersionId'] for model in configuration['snapshot']['models'])):
        return opened, None
    appearances, candidates = [], []
    for entry in configuration['snapshot']['models']:
        target = base if entry['modelVersionId'] == instance['modelVersionId'] else load_model(entry['modelVersionId'])
        if target.get('representationType') == 'appearance':
            appearances.append(target)
        if target.get('representationType') == 'detailed':
            candidates.append(target)
    if len(appearances) != 1 or len(candidates) > 1:
        raise PreviewError(409, 'AMBIGUOUS_REPRESENTATION')
    if not candidates:
        return opened, None
    target = candidates[0]
    if not calibrated_representation(target, geographic):
        raise PreviewError(409, 'MODEL_CALIBRATION_REQUIRED')
    value = deepcopy(opened)
    projected = next(item for item in value['snapshot']['instances']
                     if item['sceneModelInstanceId'] == instance['sceneModelInstanceId'])
    projected['modelVersionId'] = target['modelVersionId']
    # Source keys are version-local. Recompose the detail mapping from its own configuration.
    projected['componentBindings'] = []
    ref = {key: target[key] for key in ('modelAssetId', 'modelVersionId', 'contentRevision', 'sha256')}
    if not any(row['modelVersionId'] == target['modelVersionId'] for row in value['resourceRefs']):
        value['resourceRefs'].append(ref)
    value, uses = store.resolve_scene(value, equipment, authorize)
    use = next((row for row in uses if row['sceneModelInstanceId'] == instance['sceneModelInstanceId']), None)
    if not use or any(use[key] != configuration[key] for key in ('configurationId', 'configurationRevision')):
        raise PreviewError(409, 'REVISION_CONFLICT')
    if store.for_equipment(uid, equipment) != configuration:
        raise PreviewError(409, 'REVISION_CONFLICT')
    authorize()
    return value, uses
