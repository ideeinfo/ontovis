# 排查与修复三维视口实体透视操作逻辑与切换抖动 验收报告

## 1. 任务概述

用户反馈三维视口在设备视图下的两个重要问题：
1. **操作逻辑认知与实际脱节**：用户预期底部的“实体 / 透视”按钮应该是一个统一控制风机外壳透明度的开关，但实际操作时发现它与选中的构件强耦合（选中部件时点击实体不生效、点击透视又清空构件高亮）；
2. **切换风机后发生来回跳动与切换异常**：现场视频 `1105_(1).mp4` 显示，点击“实体”或“透视”时，相机在整机远景和机舱近景之间疯狂拉扯跳动，外壳状态反复反弹。

---

## 2. 根因与修复实施

### 2.1 根因总结
1. **两套渲染逻辑互斥打架**：构件高亮 (`SceneCabinetAppearance`) 强制打透外壳，而宏观模型查看 (`SceneModelView`) 只要遇到构件聚焦 (`componentFocus`) 就粗暴自我销毁并强制回退相机。
2. **退出透视强制回弹相机视角**：`clearModelView(true)` 内部执行了 `moveView(saved.view)`，只要退出透视就把相机强行甩回几百米外的整机远景，而构件定位机制又在下一刻把相机甩回机舱特写，导致镜头严重振荡。
3. **按钮状态非受控**：`CockpitModelView` 内部使用非受控 `useState`，内外状态失步脱节，且组件卸载时触发有害竞态清空。

### 2.2 核心改造
1. **外壳模式受控化与心智模型统一**：
   - 在 [`apps/workbench/src/ProjectCockpit.tsx`](file:///Users/diwei/项目2026/OntoVis/apps/workbench/src/ProjectCockpit.tsx) 中引入统一受控的 `activeMode ('solid' | 'xray' | 'exploded')`；
   - 构件查看模式下默认高亮“透视”，整机模式下默认高亮“实体”，按钮高亮与三维视口呈现 100% 吻合；
   - 切换风机时重置为 `solid`，防止残留。
2. **构件查看与外壳模式解耦协同**：
   - 改造 [`apps/workbench/src/sceneCabinetAppearance.ts`](file:///Users/diwei/项目2026/OntoVis/apps/workbench/src/sceneCabinetAppearance.ts) 与 [`apps/workbench/src/sceneComponentFocus.ts`](file:///Users/diwei/项目2026/OntoVis/apps/workbench/src/sceneComponentFocus.ts)，支持 `fadeShell` 动态控制：
     - 用户在构件模式下点“实体”：外壳恢复实体白壳，构件选中保持；
     - 用户点“透视”：外壳恢复半透明，内部构件高亮透视可见；
     - 用户点“爆炸示意”：模型沿轴向位移展开，构件高亮保持。
3. **彻底消除相机拉扯震荡**：
   - 改造 [`apps/workbench/src/SceneViewport.tsx`](file:///Users/diwei/项目2026/OntoVis/apps/workbench/src/SceneViewport.tsx)：
     - 移除退出透视时强制 `moveView(saved.view)` 的回弹逻辑；
     - 移除因 `componentFocus` 存在而强制销毁 `modelView` 的互斥条件；
     - 构件模式下材质平滑切换，相机稳定保持在当前机位。
4. **组件纯受控化**：
   - 改造 [`apps/workbench/src/CockpitModelView.tsx`](file:///Users/diwei/项目2026/OntoVis/apps/workbench/src/CockpitModelView.tsx)，支持外部传入受控 `mode`，并移除 unmount cleanup 时的强制清空竞态。

---

## 3. 验证结果

### 3.1 自动化测试
1. **定向模块测试**：
   ```bash
   node --experimental-strip-types --test apps/workbench/tests/cockpit-model-view.test.mjs apps/workbench/tests/scene-cabinet-appearance.test.mjs apps/workbench/tests/scene-component-focus.test.mjs apps/workbench/tests/cockpit-simulation.test.mjs apps/workbench/tests/cockpit-space.test.mjs
   ```
   **结果**：51 / 51 tests 全部通过。
2. **全量自动化测试**：
   ```bash
   node --experimental-strip-types --test apps/workbench/tests/*.test.mjs
   ```
   **结果**：769 / 769 tests 全部通过，零失败。

### 3.2 静态检查与打包构建
1. **TypeScript 检查**：
   ```bash
   node apps/workbench/node_modules/typescript/bin/tsc --noEmit -p apps/workbench
   ```
   **结果**：0 错误，类型推导完全一致。
2. **生产环境前端打包**：
   ```bash
   ONTOVIS_LOGIN_MEDIA_PUBLIC_DIR=... npm --prefix apps/workbench run build
   ```
   **结果**：Vite 生产包构建成功，生成 assets 清单完整。
