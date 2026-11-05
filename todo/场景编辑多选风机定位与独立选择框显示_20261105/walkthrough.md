# 场景编辑多选风机定位与独立选择框显示 实施与验收记录 (Walkthrough)

## 1. 任务概述

用户在使用“场景与可视化”工作台进行场景编辑时，反馈了如下体验问题：
- 在左侧“场景内容”面板多选风机（如勾选 1号、4号、5号风机）时，模型中所有风机都不会出现选择框，且视角未定位到选中的风机组；
- 要求：在列表选中单个风机时，模型平滑定位到该风机；选择多个风机时，模型平滑定位聚焦到所选的所有风机；同时每个选中的风机都出现独立可见的选择框。

---

## 2. 变更实施内容

### 2.1 单选与多选智能定位实现 ([`apps/workbench/src/SceneWorkspace.tsx`](file:///Users/diwei/项目2026/OntoVis/apps/workbench/src/SceneWorkspace.tsx))
- **复选框点击定位**：将列表行复选框 `<input className="so-select" ... />` 的 `onChange` 改为调用 `selectInstance(item.sceneModelInstanceId, true, true)`，确保勾选/多选均派发聚焦请求；
- **多目标聚焦派发**：升级 `selectInstance` 函数，当 `locate === true` 时：
  - 若 `ids.length === 1`，派发单目标聚焦：`setFocus({token: Date.now(), instanceId: ids[0]})`；
  - 若 `ids.length > 1`，派发多目标联合聚焦：`setFocus({token: Date.now(), instanceId: null, instanceIds: [...ids]})`；
  - 自动更新当前高亮对象 `nextSelected`，保证取消某项时属性面板依然对应仍然选中的风机。
- **批量全选定位**：升级 `selectMany(ids: string[], locate = true)` 函数，支持在“全选模型”或按“资源组”多选时，同步平滑定位到所选所有风机。

### 2.2 独立选择框高亮与动画每帧贴合 ([`apps/workbench/src/sceneModelFocus.ts`](file:///Users/diwei/项目2026/OntoVis/apps/workbench/src/sceneModelFocus.ts) & [`apps/workbench/src/SceneViewport.tsx`](file:///Users/diwei/项目2026/OntoVis/apps/workbench/src/SceneViewport.tsx))
- **鲜亮高亮色与深度设置**：
  - 为 `SceneModelSelectionBoxes.update` 新增 `color` 参数，接入当前视口高亮色 `selectionColor()`；
  - 设置 `Box3Helper` 的材质层级 `renderOrder = 2`，并将深度属性设为 `depthTest = false, depthWrite = false`，保证远景和山丘遮挡下依然鲜亮清晰；
  - 增加 `setColor(color)` 方法支持在主题或模式切换时动态刷新颜色。
- **动画循环每帧贴合更新**：
  - 在 `SceneViewport.tsx` 的每帧渲染分支中，同步遍历 `selectionBoxes.helpers`，调用 `helper.box.setFromObject(entry.root)`，确保风机转动、仿真运行、相机缓动时，每个选中的独立选择框均紧密跟随。

---

## 3. 验证与测试结果

1. **类型检查与全量单元测试**：
   - 运行 `npm --prefix apps/workbench run check`；
   - 770+ 项单元测试全部通过（包含 `scene-model-focus.test.mjs` 中新增的对多选独立框、高亮颜色应用及 `setColor` 的断言）；
   - Vite 生产构建与 `model-thumbnail-renderer` 生成全部成功，0 Error，0 Warning。
2. **测试服务器部署验证**：
   - 代码提交至分支 `codex/design-foundation`，Commit: `9ef59062c4875ac320ffeba9cc40cee22df013e4`；
   - 前端发布至测试服务器 `/data/ontovis/workbench-releases/9ef59062c4875ac320ffeba9cc40cee22df013e4/public`，并原子切换当前软链接 `/data/ontovis/workbench-current`；
   - 健康检查验证：`curl -k -s https://vis.ontobase.ai/health` 返回 `200 OK`，状态正常；
   - 页面访问验证：`curl -k -s -I https://vis.ontobase.ai/` 返回 `HTTP/2 200`。
