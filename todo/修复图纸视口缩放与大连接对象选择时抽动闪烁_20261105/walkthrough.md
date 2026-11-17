# 修复图纸视口缩放与大连接对象选择时抽动闪烁变更总结

## 1. 任务概述

用户反馈在分析画布的图纸证据查看器中：
> “图纸缩放到某个程度，点击个别连接对象，图纸区域会发生连续抽动闪烁”
> 对应示例：图纸 `机舱动力柜供电`，选中连接 `+CN1-1Q1:5 ↔ +CN1-1U2:L3`（连接编号 `CONN-0011`），缩放比例显示为 `37.85%`。

本次修复彻底排查并根治了由于 `ResizeObserver` 遇滚动条动态显隐引发的正反馈自激振荡死循环（Oscillation Thrashing / Scrollbar Fluttering），以及组件 Key 破坏状态连续性导致的频繁销毁重建问题。

---

## 2. 根因剖析与修复实现

### 2.1 死循环自激振荡（Scrollbar Fluttering）根因与阻断
- **根因**：
  视口组件中的 `ResizeObserver` 监听带有 `overflow: auto` 的 `.wo-photo-scroll` 元素。当选中的连接对象（如 `CONN-0011`）跨度较大时，计算出的聚焦缩放（`37.85%`）恰好处于图片高宽贴合视口边沿的临界点：
  1. 视口原本无滚动条，`clientWidth = 800px`；
  2. 计算 `zoom = 0.3785`，图片高度轻微超出视口 2px，浏览器产生垂直滚动条；
  3. 滚动条占用 15px 宽度，`clientWidth` 缩水至 `785px`；
  4. `ResizeObserver` 捕获到尺寸变化，触发 `setSize({ width: 785 })`；
  5. `size` 状态更新，重新触发 `useLayoutEffect` 中的 `focusPhoto()`；
  6. 宽度为 785px 时重新计算 `photoFocusZoom`，缩放缩小到 `0.3712`；
  7. 缩放变小后图片不再超出视口，垂直滚动条瞬间消失；
  8. 滚动条消失导致 `clientWidth` 恢复为 `800px`，`ResizeObserver` 再次触发；
  9. 再次触发 `useLayoutEffect`，再次放大至 `0.3785`，滚动条再次出现……
  10. 每一帧内疯狂交替，表现为视口连续剧烈抽动、跳跃闪烁。
- **修复**：
  1. **滚动条迟滞死区（Deadband）**：在 `ResizeObserver` 回调中，当宽度或高度变化量在滚动条常规宽度范围内（`Math.abs(delta) <= 24px` 且非初次挂载）时，视为滚动条出现/消失引起的微小抖动，**不触发 `setSize`**，从底层彻底切断自激反馈链；
  2. **初次自适应标记**：引入 `didInit` 标记，仅在首批图片就绪或宏观窗口缩放时自适应，避免非必要的重复计算；
  3. **CSS 槽位预留**：在 `.wo-photo-scroll` 样式中补充 `scrollbar-gutter: stable;`，在支持的浏览器内核中预留滚动条空间，防止滚动条动态生成时挤压排版宽度。

### 2.2 稳定组件 Key，避免无意义的组件销毁重建
- **根因**：
  [`AnalysisEvidenceViewer.tsx`](file:///Users/diwei/项目2026/OntoVis/apps/workbench/src/AnalysisEvidenceViewer.tsx) 的 `key` 中包含了 `${selected}:${JSON.stringify(selector)}`，导致每次用户在左侧列表切换连接或端口时，视口组件都被完全卸载并重新挂载，不仅将用户的交互状态（如手动缩放倍数）暴力清零，而且每次都会重新执行挂载初始化，极易直接触发临界死循环。
- **修复**：
  1. 将 `key` 调整为稳定 Key：`${card.source!.id}:${page}`；
  2. 在 `WorkOrderPhotoViewport.tsx` 中增加对 `box` 变化的监听（`prevBox`）：
     - 当切换选中的连接/端口时，组件保持常驻不重载；
     - 若用户已通过滚轮放大看细节或处于较好视口比例，**保持当前 zoom 不变**，仅平滑平移（`view.scrollTo({ behavior: 'smooth' })`）将新目标居中；
     - 若处于全景视图，执行平滑聚焦定位；
     - 彻底消除切换条目时的黑屏、闪白与重挂载开销。

---

## 3. 涉及文件与修改清单

| 文件路径 | 类型 | 修改要点 |
| :--- | :--- | :--- |
| [`apps/workbench/src/WorkOrderPhotoViewport.tsx`](file:///Users/diwei/项目2026/OntoVis/apps/workbench/src/WorkOrderPhotoViewport.tsx) | 前端组件 | 1. `ResizeObserver` 增加 $\le 24\text{px}$ 滚动条死区过滤，彻底阻止自激抖动；<br>2. 增加 `didInit` 标记避免重复聚焦；<br>3. 监听 `box` 变更，选区切换时平滑居中平移，不重置用户当前的放大倍数；<br>4. `focusPhoto` 读取实时 DOM `view.clientWidth/Height`，保证计算准确。 |
| [`apps/workbench/src/AnalysisEvidenceViewer.tsx`](file:///Users/diwei/项目2026/OntoVis/apps/workbench/src/AnalysisEvidenceViewer.tsx) | 前端组件 | 精简视口组件 `key` 为 `${card.source!.id}:${page}`，保持视口生命周期连续，同一图纸同一页内切换对象复用视口。 |
| [`apps/workbench/src/workOrders.css`](file:///Users/diwei/项目2026/OntoVis/apps/workbench/src/workOrders.css) | 前端样式 | 在 `.wo-photo-scroll` 样式中增加 `scrollbar-gutter: stable;`，稳定视口宽度。 |
| [`apps/workbench/tests/photo-viewport.test.mjs`](file:///Users/diwei/项目2026/OntoVis/apps/workbench/tests/photo-viewport.test.mjs) | 单元测试 | 1. 增加 `mount` 对象的 `update` 方法支持动态变更 props；<br>2. 新增临界滚动条尺寸反复切换时不触发振荡死循环的测试断言；<br>3. 新增在大连接对象间切换时视口平稳稳定且保持用户当前放大比例的测试断言。 |

---

## 4. 验证结果

### 4.1 本地测试与构建验证
1. **视口专项单元测试**：
   运行 `node --test apps/workbench/tests/photo-viewport.test.mjs`：
   全部 14 项单元测试（含 2 项新增防震荡与平滑切换测试）全部秒级通过（0 fail）：
   - `critical scrollbar flutter does not trigger oscillation loop` ✔
   - `large connection selection settles without flutter and maintains user zoom on switching` ✔
2. **全量 Workbench 检查**：
   运行 `npm --prefix apps/workbench run check`：
   - TypeScript 类型检查通过；
   - 全部 774 项单元测试全部通过；
   - Vite 生产构建打包成功。

### 4.2 测试服务器部署验证
1. 代码提交至 Git 分支 `codex/design-foundation`，Commit 为 `cc80959`；
2. 构建产物同步至测试服务器 `192.168.2.153`：
   `/data/ontovis/workbench-releases/cc8095946d8418f511d194d98737ec5b5668bafe`；
3. 更新软链接 `/data/ontovis/workbench-current` 指向新版本，服务已平滑重载；
4. 线上入口 `https://vis.ontobase.ai` 静态资源哈希已更新为 `index-DjvNxknz.js`，新代码已 100% 在线生效。
