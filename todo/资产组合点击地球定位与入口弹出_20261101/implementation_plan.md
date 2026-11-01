# 资产组合列表点击场景地球定位与入口弹出 实施方案

## 1. 背景与目标

当前用户在项目驾驶舱「项目资产」页的左侧「资产组合」列表中点击任意场景卡片时，系统直接调用 `openScene(id)` 切入三维场景视图。

用户反馈与新需求：
> “资产组合列表里点击场景后，应该先在地球上定位到对应的点位，同时下方弹出场景入口（与点击地球上的点位等效），不要直接进入场景”

本次改动目标：
1. **阻断直接切入三维场景**：点击资产组合列表中的场景卡片（`.pc-scene-card`）时，保留在「项目资产」页面，不再直接触发 `openScene` 离开地球。
2. **地球平滑对准与定位飞入**：读取该场景对应的地理锚点经纬度，驱动地球摄像机平滑自转并飞入对准该点位（`focus(longitude, latitude, targetDistance)`）。
3. **下方弹出场景入口浮层（与点击地球点位等效）**：地球下方立即展开场景参考点入口浮层（`.pc-globe-choice`），展示场景名称、位置参考说明及醒目的橙色高亮「进入场景」按钮，用户在此确认后点击即可进入场景。
4. **资产列表与地球点位双向联动**：卡片列表呈现对应选中状态（`data-selected="true"`），地球点位标记（`.pc-globe-pin`）同步呈现高亮选中状态；点击浮层右上角关闭或切换其他场景时同步联动。

---

## 2. 方案设计与交互联动

### 2.1 状态设计与传递
1. **`ProjectCockpit.tsx`**：
   - 新增状态 `focusedScene: { sceneId: string; token: number } | null`；
   - 资产组合卡片点击事件从直接 `openScene(item.summary.sceneId)` 调整为：
     ```ts
     function focusSceneOnGlobe(sceneId: string) {
       setFocusedScene({ sceneId, token: ++navigationSerial.current });
     }
     ```
   - 卡片增加选中属性：`data-selected={focusedScene?.sceneId === item.summary.sceneId}`；
   - 将 `focusedScene` 传给 `CockpitGlobe` 组件。

2. **`CockpitGlobe.tsx`**：
   - 接收 `focusTarget?: { sceneId: string; token: number } | null` 与 `onSelectScene?: (sceneId: string) => void`；
   - 当 `focusTarget` 变化且有效时：
     - 在当前 `groups` 中查找包含该 `sceneId` 的分组 `group`；
     - 若找到：
       - 设置选中组 `setSelected(group.id)`（触发底层 `.pc-globe-choice` 入口浮层弹出）；
       - 计算最佳视距 `targetDistance = globeClusterFocusDistance(group, height)`；
       - 调用 `runtime.current?.focus(group.longitude, group.latitude, Math.min(currentDistance, targetDistance))` 平滑转动并推进镜头；
     - 若场景属于多场景聚合点（例如 `Hornsea 2` 与 `海上风电·MySE`），将所选场景置顶显示，方便一键点击进入；
   - 用户点击浮层关闭按钮（`X`）时，清空选中并同步重置父级卡片状态。

---

## 3. 涉及文件与修改计划

| 文件 | 变更目的 |
|---|---|
| [`apps/workbench/src/ProjectCockpit.tsx`](file:///Users/diwei/项目2026/OntoVis/apps/workbench/src/ProjectCockpit.tsx) | 将资产组合卡片点击事件改造为地球点位联动；增加卡片选中高亮状态；向 `CockpitGlobe` 传递聚焦目标 |
| [`apps/workbench/src/CockpitGlobe.tsx`](file:///Users/diwei/项目2026/OntoVis/apps/workbench/src/CockpitGlobe.tsx) | 接收父级聚焦场景指令；在地球上自动飞入对准该点位；展开下方 `.pc-globe-choice` 场景入口浮层 |
| [`apps/workbench/src/projectCockpit.css`](file:///Users/diwei/项目2026/OntoVis/apps/workbench/src/projectCockpit.css) | 完善 `.pc-scene-card[data-selected=true]` 选中高亮与平滑过渡样式 |
| [`apps/workbench/tests/cockpit-globe.test.mjs`](file:///Users/diwei/项目2026/OntoVis/apps/workbench/tests/cockpit-globe.test.mjs) | 新增/补充资产卡片联动地球点位与浮层展开测试 |
| [`docs/plans/开发执行记录.md`](file:///Users/diwei/项目2026/OntoVis/docs/plans/开发执行记录.md) & [`docs/plans/工作区交接.md`](file:///Users/diwei/项目2026/OntoVis/docs/plans/工作区交接.md) | 同步执行记录与工作区交接文档 |

---

## 4. 验证计划

1. **自动化测试与构建**：
   - 运行前端单元测试与定向测试；
   - 运行 `tsc --noEmit` 保证 TypeScript 类型检查零错误；
   - 运行 `python3 tools/build_workbench.py` 确保打包无误。
2. **浏览器实机交互截图验证**：
   - 打开项目资产页；
   - 在左侧资产组合列表点击「平顶山夏李风电场」卡片：
     - 验证页面不发生跳转，仍停留在资产页；
     - 验证地球自转并平滑定位到夏李点位；
     - 验证地球下方弹出「平顶山夏李风电场」场景入口浮层，内含橙色高亮「进入场景」按钮；
     - 验证左侧卡片呈现选中高亮状态；
   - 在资产组合列表点击「海上风电· MySE」或「Beck Burn」卡片：
     - 验证地球平滑飞向对应的新点位并更新下方场景入口浮层；
   - 点击浮层中的橙色「进入场景」按钮：
     - 验证正式平滑切入三维场景视图。
3. **远端部署与业务保全**：
   - 部署更新到测试服务器；
   - 验证既有业务数据与配置完整无损。
