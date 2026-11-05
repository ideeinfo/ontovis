# 修复透视风叶停止转动与设备结构返回按钮有效性 实施方案

## 1. 背景与目标

用户在使用工作台“设备”与“场景总览”三维视口时，提出了两项明确的问题：
1. **进入场景后，没有选择左侧列表中的设备，将下方工具栏切换到“透视”，风叶的转动会停止**。
2. **设备列表上的返回按钮无效**（截图粉圈所标注的设备结构顶部 `← 本源1号风机` 返回按钮点击无响应）。

本方案旨在精准修复上述两个问题：
- 在未选择子部件的整机查看状态下，切换到“透视”时机舱外壳半透明，内部设备显露，同时**风机叶片保持正常转动与偏航动画**；
- 激活设备结构顶部的返回按钮，支持下级钻取时回退上级部件，在根节点时**点击返回场景总览**。

---

## 2. 根因剖析与方案设计

### 2.1 问题一：透视模式下风叶停转问题
#### 根因：
1. **动画排除过度宽泛**：
   在 [`apps/workbench/src/ProjectCockpit.tsx`](file:///Users/diwei/项目2026/OntoVis/apps/workbench/src/ProjectCockpit.tsx) 第 157 行中：
   ```typescript
   const simulation = useCockpitSimulation(..., modelViewRequest ? selected?.sceneModelInstanceId ?? null : null);
   ```
   只要 `modelViewRequest` 存在（即使 `mode === 'xray'`），就会将风机作为 `excludedId` 排除在动画生成之外。
2. **视口驱动强制清理与过滤**：
   在 [`apps/workbench/src/SceneViewport.tsx`](file:///Users/diwei/项目2026/OntoVis/apps/workbench/src/SceneViewport.tsx) 第 273 行和 284 行中：
   ```typescript
   simulated.clear(request.instanceId);
   const requests = (state.simulatedMotions ?? []).filter(r => r.instanceId !== state.modelView?.instanceId);
   ```
   不管模式是一刀切地清除了动画实例并过滤掉了运动请求。
3. **层级结构校验阻断**：
   在 [`apps/workbench/src/sceneModelView.ts`](file:///Users/diwei/项目2026/OntoVis/apps/workbench/src/sceneModelView.ts) 第 42~43 行中，对 TU-3000 进行硬性父子关系检查，而运动模拟会将节点挂载到动态 `yaw` 组，导致透视模式无法创建。

#### 修复方案：
1. **精确定位排除条件**：
   在 `ProjectCockpit.tsx` 中，将排除条件限定为仅在爆炸模式：
   `modelViewRequest?.mode === 'exploded' ? selected?.sceneModelInstanceId ?? null : null`；
2. **保持视口模拟请求流动**：
   在 `SceneViewport.tsx` 中，仅在 `request.mode === 'exploded'` 时才执行 `simulated.clear` 和 `requests` 过滤，透视模式下放行；
3. **解耦透视与运动层级检查**：
   在 `sceneModelView.ts` 中，将 TU-3000 原始层级校验仅保留给 `request.mode === 'exploded'`。在 `xray` 模式下只更新外壳材质透明度，与叶片旋转独立并存。

---

### 2.2 问题二：设备列表顶部返回按钮无效问题
#### 根因：
1. 在 [`apps/workbench/src/CockpitDevice.tsx`](file:///Users/diwei/项目2026/OntoVis/apps/workbench/src/CockpitDevice.tsx) 第 42 行中：
   ```tsx
   <button aria-label={t('返回上级','Parent level')} disabled={navigationBusy||path.length<2} onClick={...}>
     <ArrowLeft size={16}/>
   </button>
   ```
   按钮被 `path.length < 2` 硬编码禁用；当用户在“本源1号风机”根节点时，`path.length === 1`，按钮处于永久禁用状态；
2. 缺少向外层传递“返回场景”的回调能力。

#### 修复方案：
1. **增加返回回调**：
   在 `CockpitDevice` 的 props 中增加 `onBack?: () => void`，在 `ProjectCockpit.tsx` 中传入 `onBack={() => navigate('scene')}`；
2. **改造按钮响应逻辑**：
   移除 `path.length < 2` 禁用条件：
   - 当 `path.length > 1` 时：回退到上一级路径，并选中上一级部件；
   - 当 `path.length === 1` 时：触发 `onBack()` 返回场景总览，视角拉远退出设备聚焦；
3. **支持根设备快捷重选**：
   当用户在左侧列表选中了某个零件时，点击面板标题 `本源1号风机`，可直接重选根设备，恢复整机卡片与视角。

---

## 3. 涉及修改文件清单

| 文件路径 | 修改内容 |
|---|---|
| [`apps/workbench/src/ProjectCockpit.tsx`](file:///Users/diwei/项目2026/OntoVis/apps/workbench/src/ProjectCockpit.tsx) | 1. 运动仿真仅在 `exploded` 模式排除风机；<br>2. 传递 `onBack={() => navigate('scene')}` 给 `CockpitDevice` |
| [`apps/workbench/src/CockpitDevice.tsx`](file:///Users/diwei/项目2026/OntoVis/apps/workbench/src/CockpitDevice.tsx) | 1. 移除 `path.length < 2` 禁用限制；<br>2. 根层级点击触发 `onBack`；<br>3. 标题支持点击重选整机 |
| [`apps/workbench/src/SceneViewport.tsx`](file:///Users/diwei/项目2026/OntoVis/apps/workbench/src/SceneViewport.tsx) | 仅在 `mode === 'exploded'` 时清除和过滤运动仿真实例，透视模式下保持运动 |
| [`apps/workbench/src/sceneModelView.ts`](file:///Users/diwei/项目2026/OntoVis/apps/workbench/src/sceneModelView.ts) | 将 TU-3000 模型的静态树层级检查限制在 `exploded` 模式，透视模式支持与动画共存 |

---

## 4. 验证计划

1. **自动化测试与构建校验**：
   - 执行 `npm --prefix apps/workbench run check`，确保 TypeScript 检查、单元测试及 Vite 生产打包 100% 通过。
2. **功能与交互验证**：
   - 进入驾驶舱设备页面，在未选择左侧列表部件的前提下，点击“透视”，检查风机叶片是否持续转动，机舱外壳是否正常半透明；
   - 切换到“爆炸示意”，检查风叶是否正确暂停旋转并完成爆炸展开；切回“透视”或“实体”后是否恢复旋转；
   - 在“本源1号风机”页面点击设备列表顶部的 `←` 按钮，检查是否能够正常返回场景总览；
   - 深入子部件时，检查返回按钮是否逐层返回；在子部件选中态下点击标题文字是否能快速重选风机整机。
3. **部署与验收**：
   - 打包构建产物并部署至测试服务器 `root@192.168.2.153`；
   - 验证生产环境工作台体验，输出 `walkthrough.md` 并汇报。
