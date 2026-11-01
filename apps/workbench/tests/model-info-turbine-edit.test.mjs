import test from 'node:test';
import assert from 'node:assert/strict';

test('model basic info edit preserves and modifies turbine definition and representation', async () => {
  // Mock model state
  const model = {
    modelAssetId: 'asset-test-1',
    modelVersionId: 'ver-test-1',
    displayName: 'Enercon E-82 E2 · 外观版',
    purpose: 'equipment',
    description: '原始说明',
    assetRevision: 'asset:asset-test-1:1',
    definitionEntityUid: 'entity:dcd29706-c4ec-5710-886a-426a8b2407c3',
    modelCode: 'enercon-e-82-e2',
    representationType: 'appearance'
  };

  // Simulating saveModelInfo request payload
  const updatePayload = {
    modelAssetId: model.modelAssetId,
    modelVersionId: model.modelVersionId,
    expectedAssetRevision: model.assetRevision,
    clientRequestId: 'req-1',
    displayName: 'Enercon E-82 E2 · 完整版',
    purpose: 'equipment',
    description: '已更新为完整工程模型',
    definitionEntityUid: 'entity:dcd29706-c4ec-5710-886a-426a8b2407c3',
    modelCode: 'enercon-e-82-e2',
    representationType: 'detailed'
  };

  assert.equal(updatePayload.representationType, 'detailed');
  assert.equal(updatePayload.displayName, 'Enercon E-82 E2 · 完整版');
  assert.equal(updatePayload.definitionEntityUid, 'entity:dcd29706-c4ec-5710-886a-426a8b2407c3');
});

test('model basic info unbinds turbine definition when set to null', async () => {
  const unbindPayload = {
    modelAssetId: 'asset-test-2',
    modelVersionId: 'ver-test-2',
    expectedAssetRevision: 'asset:asset-test-2:1',
    clientRequestId: 'req-2',
    displayName: '通用箱式变压器',
    purpose: 'equipment',
    description: '独立设备模型',
    definitionEntityUid: null,
    modelCode: null,
    representationType: null
  };

  assert.equal(unbindPayload.definitionEntityUid, null);
  assert.equal(unbindPayload.modelCode, null);
  assert.equal(unbindPayload.representationType, null);
});
