# 修复图纸视口缩放与大连接对象选择时抽动闪烁实施方案

## 1. 背景与问题定义

用户在分析画布的图纸证据查看器中反馈：
> “图纸缩放到某个程度，点击个别连接对象，图纸区域会发生连续抽动闪烁”
> 关联示例：图纸 `机舱动力柜供电`，选中连接 `+CN1-1Q1:5 ↔ +CN1-1U2:L3`（连接编号 `CONN-0011`），缩放比例显示为 `37.85%`。

### 根因深入剖析 (Root Cause Analysis)

1. **死循环自激振荡（Scrollbar Fluttering / Oscillation Thrashing）**：
   - 在 [`WorkOrderPhotoViewport.tsx`](file:///Users/diwei/项目2026/OntoVis/apps/workbench/src/WorkOrderPhotoViewport.tsx) 中：
     - `ResizeObserver` 直接监听带有 `overflow: auto` 的 `.wo-photo-scroll` 视口元素（`scrollRef.current`）；
     - `useLayoutEffect` 依赖 `[natural.width, natural.height, size.width, size.height]`，当 `!changed.current && !restoring.current` 时自动调用 `focusPhoto()`；
     - 当选中的连接对象（例如跨越半幅图纸的 `CONN-0011`，高度包围盒约为 0.35）被聚焦时，`focusFraction = 0.35` 使得 `photoFocusZoom` 计算出的 zoom（如 37.85%）恰好将整张图纸在高度或宽度上缩放到**贴近视口容器边缘的临界尺寸**；
     - 此时形成帧级死循环：
       1. 视口原本无滚动条，`clientWidth = 800px`；
       2. 计算出 `zoom = 0.3785`，图片高度轻微超出视口 2px，浏览器生成垂直滚动条；
       3. 垂直滚动条占用约 15px 宽度，`clientWidth` 缩水至 `785px`；
       4. `ResizeObserver` 触发回调，调用 `setSize({ width: 785, ... })`；
       5. `size.width` 发生改变，重新触发 `useLayoutEffect`，再次调用 `focusPhoto()`；
       6. 此时以 `viewportWidth = 785px` 重新计算 `photoFocusZoom`，计算出的缩放变小为 `zoom = 0.3712`；
       7. 缩放变小后图片高度不再超出视口，垂直滚动条瞬间消失；
       8. 滚动条消失后，`clientWidth` 恢复到 `800px`，`ResizeObserver` 再次被触发；
       9. `ResizeObserver` 更新 `size`，再次触发 `useLayoutEffect`，再次调用 `focusPhoto()`，zoom 又变回 `0.3785`，滚动条再次出现！
       10. 上述过程在每一帧内疯狂交替触发（每秒 60 次），用户肉眼看到视口在 `37.85%` 和 `37.12%` 之间高频剧烈跳动，伴随滚动条闪烁与图面抽动。

2. **组件 Key 暴力重挂载破坏状态连续性**：
   - 在 [`AnalysisEvidenceViewer.tsx`](file:///Users/diwei/项目2026/OntoVis/apps/workbench/src/AnalysisEvidenceViewer.tsx) 第 80 行：
     `key={`${card.source!.id}:${page}:${selected}:${node}:${section}:${JSON.stringify(selector)}`}`
     将 `selected` 与 `JSON.stringify(selector)` 包含在 `key` 中；
   - 每次用户在左侧切换连接或端口时，整个 `WorkOrderPhotoViewport` 组件被完全**销毁（unmount）**并**重新创建（remount）**；
   - 这不仅导致用户的缩放/平移历史状态（`changed.current`）被无情重置为 `false`，而且每次点击都会强行重跑初次聚焦和边缘尺寸探测，直接将大连接对象推入自激死循环。

---

## 2. 涉及文件与具体修改内容

### 2.1 阻断死循环振荡与迟滞死区保护（`WorkOrderPhotoViewport.tsx`）

- **修改文件**：[`apps/workbench/src/WorkOrderPhotoViewport.tsx`](file:///Users/diwei/项目2026/OntoVis/apps/workbench/src/WorkOrderPhotoViewport.tsx)
- **修改说明**：
  1. **引入滚动条波动迟滞过滤（Hysteresis Deadband）**：
     - 在 `ResizeObserver` 监听回调中，比较新尺寸与当前尺寸；
     - 当宽度或高度变化量在滚动条常规宽度范围内（`Math.abs(delta) <= 24px` 且非首次初始化）时，视为滚动条出现/消失引起的微小波动，**不更新 `size` 状态**，彻底从源头切断“滚动条显隐 -> ResizeObserver -> setSize -> focusPhoto”的自激反馈链；
  2. **避免在非宏观尺寸调整时重复触发自动缩放**：
     - 增加初次自适应聚焦标记 `didInitialFocus`，初次加载图片尺寸就绪后只执行一次 `focusPhoto()`；
     - 只有在容器发生宏观尺寸变化（如窗口缩放 `|delta| > 30px`）且用户未手动修改视图（`!changed.current`）时才自适应；
  3. **支持外部 `selector` 变更时的平滑平移居中（不用重挂载）**：
     - 监听 `box` 变化；当从外部切换选中的连接/端口/对象时：
       - 若视口已有稳定缩放（例如用户已调整过视图或当前处于良好视图），保持当前 `zoom`，直接调用 `photoFocusScroll` 平滑平移至目标中心；
       - 若尚未手动调整视图，执行平滑聚焦定位；
     - 避免全组件销毁重建。

### 2.2 稳定化视口 Key，保持组件生命周期连续（`AnalysisEvidenceViewer.tsx`）

- **修改文件**：[`apps/workbench/src/AnalysisEvidenceViewer.tsx`](file:///Users/diwei/项目2026/OntoVis/apps/workbench/src/AnalysisEvidenceViewer.tsx)
- **修改说明**：
  - 将 `WorkOrderPhotoViewport` 的 `key` 精简为稳定 Key：
    ```tsx
    key={`${card.source!.id}:${page}`}
    ```
  - 同一张图纸同一页内切换对象、端口、连接时，复用视口实例，保持 DOM 稳定、图片解码缓存常驻，杜绝重复销毁与重建带来的卡顿、闪白与状态丢失。

### 2.3 增强缩放计算鲁棒性与滚动条安全槽（`workOrderPhoto.ts` 与 CSS）

- **修改文件**：
  1. [`apps/workbench/src/workOrderPhoto.ts`](file:///Users/diwei/项目2026/OntoVis/apps/workbench/src/workOrderPhoto.ts)
     - 在 `photoFocusZoom` 计算中，为视口宽高扣除 24px 的滚动条与边距安全冗余（`usableWidth = viewportWidth - 24`）；
     - 确保计算出的目标缩放比例不低于整图适应比例（`photoFitZoom`），避免超大连接对象算出的比例使图片贴近视口临界点而引起共振。
  2. [`apps/workbench/src/workOrders.css`](file:///Users/diwei/项目2026/OntoVis/apps/workbench/src/workOrders.css)
     - 在 `.wo-photo-scroll` 样式中补充 `scrollbar-gutter: stable;`，在支持的浏览器内核中预留滚动条空间，防止滚动条动态生成时挤压排版宽度。

### 2.4 测试用例更新与回归验证

- **修改文件**：[`apps/workbench/tests/photo-viewport.test.mjs`](file:///Users/diwei/项目2026/OntoVis/apps/workbench/tests/photo-viewport.test.mjs)
- **修改说明**：
  - 增加对“大连接对象聚焦且视口尺寸处在滚动条临界值时不发生组件震荡与死循环（settle within turns）”的单测断言；
  - 验证当外部 `selector` 切换时，组件平滑响应新选区居中而不重置用户 zoom。

---

## 3. 验证与部署计划

1. **本地单元测试与构建验证**：
   - 运行前端专项测试：`node --test apps/workbench/tests/photo-viewport.test.mjs`；
   - 运行前端全局检查：`npm --prefix apps/workbench run check`（包含类型检查、770+ 单元测试与生产构建）；
2. **部署至测试服务器**：
   - 提交并推送至 `codex/design-foundation` 分支；
   - 部署到测试服务器 `root@192.168.2.153`（`https://vis.ontobase.ai`），热发布更新 workbench release 并平滑切换；
3. **真实环境复核验证**：
   - 在线上图纸 `机舱动力柜供电` 中，切换至「连接」标签；
   - 点击容易触发临界抖动的大连接对象 `+CN1-1Q1:5 ↔ +CN1-1U2:L3`（`CONN-0011`），验证图纸平稳平滑居中聚焦，缩放平滑稳定在舒适比例，**彻底消除连续抽动、闪烁与跳跃**；
   - 在不同缩放比例（例如 30%、37.85%、50%、100%）下切换不同连接与端口，验证视口均平稳平移，不再产生重挂载闪烁；
4. **归档与总结**：
   - 任务完成后将 `walkthrough.md` 备份至 `todo/修复图纸视口缩放与大连接对象选择时抽动闪烁_20261105/`。
