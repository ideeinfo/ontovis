# 场景编辑多选风机定位与独立选择框显示 实施方案

## 1. 背景与目标

在“场景与可视化”工作台的场景编辑模式下，用户提出了明确的交互体验诉求：
1. **多选风机定位**：在左侧列表中单选风机时，三维视口模型需定位到该风机；选择多个风机时（无论是复选框多选、全选模型还是资源组批量选择），三维相机需平滑定位并聚焦到所选风机的联合空间包围盒，确保所有选中风机均完整呈现在视口中；
2. **独立选择框高亮显示**：单选风机时，该风机显示选择框；多选风机时，每个被选中的风机都必须在视口中显示各自独立、鲜亮可见的选择框，且选择框在叶片仿真转动和相机移动时每帧贴合模型；
3. **保持状态与属性协同**：右侧属性面板与顶部“已选 N”状态栏在多选、取消选择时保持正确同步。

---

## 2. 根因剖析与方案设计

### 2.1 定位逻辑缺失分析与修复
#### 现状根因：
1. **复选框点击未触发定位**：
   在 [`apps/workbench/src/SceneWorkspace.tsx`](file:///Users/diwei/项目2026/OntoVis/apps/workbench/src/SceneWorkspace.tsx) 中，列表每一行复选框的 `onChange` 回调硬编码为：
   ```tsx
   onChange={() => selectInstance(item.sceneModelInstanceId, false, true)}
   ```
   这里的 `locate` 参数传了 `false`，导致用户点击勾选任何风机时均不触发相机定位。
2. **多选时强制拦截定位请求**：
   在 `selectInstance` 函数中：
   ```typescript
   if(locate && ids.length <= 1) setFocus({token: Date.now(), instanceId: id});
   ```
   `ids.length <= 1` 将多选场景全部拦截，即便传入 `locate = true` 也无法定位。
3. **批量选择未派发聚焦请求**：
   全选模型和资源组选择调用的 `selectMany(ids)` 函数仅更新了选中 ID 集合，未设置 `setFocus`。

#### 修复方案：
1. **升级 `selectInstance` 支持单选与多选定位**：
   当 `locate === true` 时：
   - 若 `ids.length === 1`：派发 `{token: Date.now(), instanceId: ids[0]}` 单目标定位；
   - 若 `ids.length > 1`：派发 `{token: Date.now(), instanceId: null, instanceIds: [...ids]}` 多目标定位；
   - 若 `ids.length === 0`：不触发定位。
2. **复选框传入 `locate = true`**：
   勾选框 `onChange` 改为 `selectInstance(item.sceneModelInstanceId, true, true)`，使单选/多选勾选均即时触发相机定位。
3. **`selectMany` 支持定位**：
   在 `selectMany(ids: string[], locate = true)` 中，同样在 `locate` 为真时根据 `ids.length` 派发多目标或单目标聚焦请求。
4. **底层多目标视角平滑过渡**：
   [`apps/workbench/src/SceneViewport.tsx`](file:///Users/diwei/项目2026/OntoVis/apps/workbench/src/SceneViewport.tsx) 底层的 `focus` 和 `fit` 函数已经支持 `string[]` 数组传入，会计算所有选中实例的联合世界包围盒 `selectedModelBounds(entries, ids)`，并由 `selectedModelView` 计算最佳视距与视点，执行平滑插值移动。

---

### 2.2 独立选择框显示与动画同步修复
#### 现状根因：
1. **多选框颜色暗淡且未跟随主题**：
   [`apps/workbench/src/sceneModelFocus.ts`](file:///Users/diwei/项目2026/OntoVis/apps/workbench/src/sceneModelFocus.ts) 的 `SceneModelSelectionBoxes` 中，LineHelper 的颜色写死为暗绿色 `0x38ad97`，在真实山地地形及天空背景下几乎不可见；而在 `SceneViewport.tsx` 的 `appearance()` 中，仅更新了单选 `selectedBox` 的材质颜色，未更新 `selectionBoxes` 的材质颜色。
2. **动画循环未更新多选框包围盒**：
   在 `SceneViewport.tsx` 的 `render` 动画循环中，当风机旋转运动（`simulated.size > 0`）或相机移动渲染时，只对单选的 `selectedBox` 执行了 `setFromObject`，未对 `selectionBoxes.helpers` 中的各个 helper 进行更新，导致多选选择框与旋转中的风机脱离。
3. **材质层级与深度测试**：
   确保多选 helper 的材质深度写入与测试配置正确（`depthTest = false`, `depthWrite = false`, `renderOrder = 2`），确保远景和山体遮挡时清晰浮现。

#### 修复方案：
1. **增强 `SceneModelSelectionBoxes`**：
   - `update(entries, ids, color?: number | THREE.Color | string)` 支持传入当前视口高亮色 `selectionColor()`；
   - 创建 `Box3Helper` 时应用该高亮色，并在复用已有 helper 时同步更新材质颜色；
   - 材质统一设置 `depthTest = false`, `depthWrite = false`, `renderOrder = 2`。
2. **动画循环中同步更新所有选中的多选框**：
   在 `SceneViewport.tsx` 的动画渲染分支中，遍历 `selectionBoxes.helpers`，对每一项实时同步执行 `helper.box.setFromObject(entry.root)`。
3. **在 `appearance()` 中同步更新所有多选 helper 颜色**：
   确保主题切换或演示模式切换时色彩瞬时响应。

---

## 3. 详细实施步骤

1. **修改 [`apps/workbench/src/sceneModelFocus.ts`](file:///Users/diwei/项目2026/OntoVis/apps/workbench/src/sceneModelFocus.ts)**：
   - 为 `SceneModelSelectionBoxes.update` 增加可选 `color` 参数；
   - 创建新 helper 或更新现有 helper 时设置其材质颜色，确保高亮鲜明；
   - 设置 `renderOrder = 2`。

2. **修改 [`apps/workbench/src/SceneWorkspace.tsx`](file:///Users/diwei/项目2026/OntoVis/apps/workbench/src/SceneWorkspace.tsx)**：
   - 优化 `selectInstance`：支持在 `locate = true` 且 `ids.length > 1` 时设置 `setFocus({token: Date.now(), instanceId: null, instanceIds: [...ids]})`；取消选中时合理回退 `selected`；
   - 优化 `selectMany`：在批量选择时支持可选 `locate = true` 并触发对应 `setFocus`；
   - 列表复选框 `onChange` 传入 `locate = true`。

3. **修改 [`apps/workbench/src/SceneViewport.tsx`](file:///Users/diwei/项目2026/OntoVis/apps/workbench/src/SceneViewport.tsx)**：
   - 在 `highlight()` 中调用 `selectionBoxes.update(entries, ..., selectionColor())`；
   - 在 `appearance()` 中同步刷新 `selectionBoxes.helpers` 各材质颜色；
   - 在动画循环（`simulated.size > 0` 或 `dirtyFrame`）中，同步更新 `selectionBoxes.helpers` 各项包围盒 `setFromObject(entry.root)`。

4. **测试与回归验证**：
   - 运行 `npm --prefix apps/workbench run check`，验证 TypeScript、全部单元测试及生产构建；
   - 验证多选勾选、单选切换、全选模型等不同场景下的相机定位与线框贴合。

5. **部署与交付**：
   - 构建并将最新前端发布到测试服务器 `root@192.168.2.153` (`https://vis.ontobase.ai`)；
   - 生成 `walkthrough.md` 备份至任务文件夹，提交 git 变更。

---

## 4. 审核与确认

按照工作流规范，实施计划需经审核确认后方可执行。请您审阅上述方案，确认后我们将立即实施代码修改、验证并部署上线。
