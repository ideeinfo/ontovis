# 资产组合列表点击场景定位地球点位并弹出入口浮层

## 1. 任务背景与核心改进

用户明确提出需求：
> “资产组合列表里点击场景后，应该先在地球上定位到对应的点位，同时下方弹出场景入口（与点击地球上的点位等效），不要直接进入场景”

在此前逻辑中，点击左侧资产卡片（`.pc-scene-card`）会直接调用 `openScene` 离开当前页面切入三维场景；而点击地球上的点位则是飞入定位并弹出入口浮层。本次改造将两处交互完全对齐并实现双向联动。

---

## 2. 核心实现改动

1. **阻断直接切入三维场景**：
   - 在 [`apps/workbench/src/ProjectCockpit.tsx`](file:///Users/diwei/项目2026/OntoVis/apps/workbench/src/ProjectCockpit.tsx) 中引入 `focusedScene: { sceneId: string; token: number } | null` 状态；
   - 资产卡片（`.pc-scene-card`）的点击事件改为 `setFocusedScene({ sceneId: item.summary.sceneId, token: ++navigationSerial.current })`，不再直接调用 `openScene`；
   - 卡片绑定 `data-selected={focusedScene?.sceneId === item.summary.sceneId || undefined}`。

2. **地球平滑自转飞入定位**：
   - 在 [`apps/workbench/src/CockpitGlobe.tsx`](file:///Users/diwei/项目2026/OntoVis/apps/workbench/src/CockpitGlobe.tsx) 中接收 `focusTarget` 与 `onSelectScene`；
   - 监听 `focusTarget` 变化，在当前聚类 `groups` 中通过 `sceneId` 命中对应的地理锚点；
   - 计算最佳对准距离后调用 `runtime.current?.focus(group.longitude, group.latitude, targetDistance)`，通过球面四元数球面插值（slerp）驱动摄像机平滑自转飞入并对准该点位。

3. **弹出场景入口浮层**：
   - 地球下方立即弹出场景参考点浮层（`.pc-globe-choice`），展示场景名称、位置精度提示以及醒目的橙色高亮按钮「进入场景 →」（`.pc-globe-choice-btn`）；
   - 用户在浮层中点击按钮后正式切入三维场景。

4. **双向联动与聚类动态拆分保持**：
   - 解决摄像机从远景飞近时，屏幕聚类算法动态将聚合组拆分成独立点位导致 group.id 改变、浮层闪退的问题：引入 `selectedScene` 状态进行跨缩放层级场景追踪，使得聚合拆分后对应的独立点位始终高亮（橙金水滴加风机图标）、浮层稳定展示；
   - 点击浮层关闭按钮（X）、重置视角按钮（Home）或离开项目资产页时同步清空选中态。

5. **视觉样式增强**：
   - [`apps/workbench/src/projectCockpit.css`](file:///Users/diwei/项目2026/OntoVis/apps/workbench/src/projectCockpit.css)：
     - 新增 `.pc-scene-card[data-selected=true]` 样式：绿色微光边框、微光背景深浅适配以及右侧绿色高亮箭头。

---

## 3. 测试与部署验证

- **单元测试**：
  - 定向空间测试 `apps/workbench/tests/cockpit-space.test.mjs`（`9/9` 项全部通过）；
  - 全量前端测试套件（`660/660` 项全部通过，0 失败）；
  - TypeScript 严格类型检查无任何错误。
- **远端生产环境发布**：
  - 远端服务器：`root@192.168.2.153`（`https://vis.ontobase.ai/`）；
  - 最新发布 Release：`e778513543b59fbba1bf2a26c483a9eeaf487a31`；
  - 健康检查接口 `/health` 校验通过（`portfolioGlobeFocus: true`），服务运行正常。

---

## 4. 实机截图验证

通过无头浏览器 CDP 自动化完整演练了全部交互流程：

### 阶段 1：项目资产初始状态
地球全览自转中，左侧资产卡片未选中，地球下方无浮层。
![初始状态](/Users/diwei/.gemini/antigravity/brain/12df916c-7cc1-4971-9bfd-d74a3b191320/portfolio-initial.png)

### 阶段 2：点击资产组合卡片（Beck Burn）
阻断直接进入三维场景；左侧卡片高亮选中；地球平滑自转飞入对准英国点位群；下方弹出场景参考点浮层，包含醒目的橙色「进入场景 →」按钮。
![聚焦定位与入口弹出](/Users/diwei/.gemini/antigravity/brain/12df916c-7cc1-4971-9bfd-d74a3b191320/portfolio-scene-focused.png)

### 阶段 3：点击入口浮层中的橙色按钮
正式切入三维场景总览。
![进入三维场景](/Users/diwei/.gemini/antigravity/brain/12df916c-7cc1-4971-9bfd-d74a3b191320/scene-entered-from-globe-choice.png)

### 阶段 4：返回项目资产页并点击夏李风电场
翻到第 3 页点击「平顶山夏李风电场」，卡片高亮选中，地球平滑自转飞入对准河南平顶山点位，下方弹出平顶山夏李风电场景入口浮层。
![夏李场景定位与入口弹出](/Users/diwei/.gemini/antigravity/brain/12df916c-7cc1-4971-9bfd-d74a3b191320/portfolio-xiali-focused.png)

---

## 5. 交付物归档

- 备份文档路径：`todo/资产组合点击地球定位与入口弹出_20261101/walkthrough.md`
- 交付与测试脚本：`output/portfolio-globe-focus-20261101/README.md`
- 受保护文件（`README.md` 与 `docs/references/夏李风场空间导航验证.md`）保持 0 修改、0 暂存。
