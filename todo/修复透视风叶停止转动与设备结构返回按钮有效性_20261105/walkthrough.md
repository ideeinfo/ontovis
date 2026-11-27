# 修复透视风叶停止转动与设备结构返回按钮有效性 验收报告

## 1. 任务概述

用户在工作台三维视口操作中指出两处核心交互体验问题：
1. **进入场景后，没有选择左侧列表中的设备，将下方工具栏切换到“透视”，风叶的转动会停止**；
2. **设备列表上的返回按钮无效**（设备结构顶部 `← 本源1号风机` 返回按钮禁用且无响应）。

已针对上述问题完成系统性排查、逻辑改造、自动化回归测试与测试服务器热发布。

---

## 2. 变更实施内容

### 2.1 修复透视模式下风叶停转问题
- **运动仿真排除逻辑精准化**：
  在 [`apps/workbench/src/ProjectCockpit.tsx`](file:///Users/diwei/项目2026/OntoVis/apps/workbench/src/ProjectCockpit.tsx) 中，将传给 `useCockpitSimulation` 的 `excludedId` 限定为仅在 `modelViewRequest?.mode === 'exploded'` 时排除该风机；在 `xray`（透视）模式下继续为风机生成运动请求。
- **视口动画实例保持流动**：
  在 [`apps/workbench/src/SceneViewport.tsx`](file:///Users/diwei/项目2026/OntoVis/apps/workbench/src/SceneViewport.tsx) 中，仅在 `request.mode === 'exploded'` 时执行 `simulated.clear` 和 `simulatedMotions` 过滤；在 `xray`（透视）模式下保留运动实例 `SceneMotion`，风机叶片旋转与偏航持续进行。
- **解耦透视外壳与运动层级检查**：
  在 [`apps/workbench/src/sceneModelView.ts`](file:///Users/diwei/项目2026/OntoVis/apps/workbench/src/sceneModelView.ts) 中，将 TU-3000 模型的静态树层级检查限制在 `exploded` 模式；在 `xray` 模式下仅将 `tu3000Shell` 对应外壳节点的材质设为半透明（透明度 0.14），与叶片旋转独立并存，呈现半透明机舱外壳下风机内部设备运转、叶片正常旋转的工业透视效果。

### 2.2 激活设备结构面板返回按钮
- **移除硬编码禁用限制**：
  在 [`apps/workbench/src/CockpitDevice.tsx`](file:///Users/diwei/项目2026/OntoVis/apps/workbench/src/CockpitDevice.tsx) 中，移除 `path.length < 2` 对返回按钮的禁用，使返回按钮在根层级依然可用。
- **分级返回交互**：
  为 `CockpitDevice` 接入 `onBack?: () => void` 回调，由 `ProjectCockpit.tsx` 传入 `onBack={() => navigate('scene')}`：
  - 当处于子部件下钻层级时（`path.length > 1`）：点击返回上一级部件；
  - 当处于根设备“本源1号风机”时（`path.length === 1`）：点击直接触发 `onBack()`，视角拉远退出设备聚焦，返回场景总览；
- **标题快捷重选整机**：
  当用户在左侧列表点选了子部件（如“偏航机构”）后，支持直接点击面板标题 `本源1号风机` 重新聚焦并查看整机卡片。

---

## 3. 变更文件清单

| 文件路径 | 变更说明 |
|---|---|
| [`apps/workbench/src/ProjectCockpit.tsx`](file:///Users/diwei/项目2026/OntoVis/apps/workbench/src/ProjectCockpit.tsx) | 1. `simulation` 排除条件仅限定为 `exploded`；<br>2. 传递 `onBack={() => navigate('scene')}` 给 `CockpitDevice` |
| [`apps/workbench/src/CockpitDevice.tsx`](file:///Users/diwei/项目2026/OntoVis/apps/workbench/src/CockpitDevice.tsx) | 1. 移除 `path.length < 2` 限制；<br>2. 接入 `onBack` 回调实现返回场景；<br>3. 标题支持点击重选整机 |
| [`apps/workbench/src/SceneViewport.tsx`](file:///Users/diwei/项目2026/OntoVis/apps/workbench/src/SceneViewport.tsx) | `simulated.clear` 与请求过滤仅在 `request.mode === 'exploded'` 执行，透视模式放行动画 |
| [`apps/workbench/src/sceneModelView.ts`](file:///Users/diwei/项目2026/OntoVis/apps/workbench/src/sceneModelView.ts) | 放宽 `xray` 模式下的模型层级校验，支持与 `SceneMotion` 并发共存 |
| [`apps/workbench/tests/cockpit-simulation.test.mjs`](file:///Users/diwei/项目2026/OntoVis/apps/workbench/tests/cockpit-simulation.test.mjs) | 新增透视模式下运动持续运行、爆炸模式安全复位与清理的单元测试 |

---

## 4. 验证与发布结果

1. **单元测试验证**：
   - 全量 770 项测试全部通过：
     ```bash
     npm --prefix apps/workbench run check
     # ✔ 770 tests passed, 0 failed
     ```
2. **TypeScript 静态检查**：
   - `tsc --noEmit` 0 错误。
3. **前端生产打包**：
   - Vite 打包顺利完成。
4. **测试服务器热发布**：
   - 发布服务器：`192.168.2.153` (`https://vis.ontobase.ai`)
   - 线上健康探针 `curl -k -s https://vis.ontobase.ai/health` 核验：
     ```json
     {
       "status": "ok",
       "release": "32f655b192fb3d91871bb647de951b9fa5f987ee",
       "frontendRelease": "32f655b192fb3d91871bb647de951b9fa5f987ee",
       "cockpitXrayRotorMotionVersion": 1,
       "cockpitDeviceTreeBackBtnVersion": 1
     }
     ```
   - 后台 Python 服务维持 PID `1030278` 稳定运行，无重启中断。
