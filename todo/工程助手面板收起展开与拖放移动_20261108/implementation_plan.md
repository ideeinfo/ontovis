# 工程助手面板收起、展开与拖放移动实施方案

## 1. 背景与目标

用户需求：
> “让工程助手面板可以收起、展开、拖放移动”
> 附图标注：分析工作台（CockpitAnalysis）右侧的“工程助手”侧边栏面板。

目前工程助手面板固定在分析工作台右侧（`grid-template-columns: minmax(0,1fr) clamp(340px,29%,420px)`），属于静态不可折叠、不可移动的侧边栏。当用户在分析画布上排布大量故障资料卡、浏览复杂对象关系连线时，右侧固定的助手面板会挤占画布视野，且无法根据用户习惯灵活移至其他屏幕区域。

**本次优化目标**：
1. **收起与展开（Collapse & Expand）**：
   - 工程助手面板标题栏提供显式的“收起”操作按钮；
   - 收起后，左侧分析画布（`.pa-evidence`）自动撑满 100% 宽度，享受沉浸式全屏图谱分析；
   - 工作区边缘显示轻量毛玻璃呼出按钮（`✨ 工程助手`），一键快速重新展开面板；
   - 记住用户的收起/展开偏好（支持持久化至 `localStorage`）。
2. **拖放移动（Drag & Drop Move）**：
   - 工程助手面板标题栏（header）支持指针拖拽（Pointer Capture 原生拖动），用户可以按住标题栏将面板拖动到工作区内任意位置；
   - 拖拽离开默认停靠位后，面板自动进入浮动窗口模式（Floating Window），左侧画布自动伸展为全宽；
   - 拖拽过程平滑且具备视口边界约束（Boundary Clamping），绝不飞出视口或被遮挡；
   - 浮动状态下面板标题栏提供“停靠至右侧”（Dock）按钮及双击标题栏复位操作，可随时一键恢复右侧默认停靠；
   - 拖拽与浮动窗口视觉延续驾驶舱通透毛玻璃（`backdrop-filter: var(--pc-blur)`）与悬浮阴影，整体交互细腻自然。

---

## 2. 现状分析与实现机制

### 2.1 组件结构（[`apps/workbench/src/CockpitAnalysis.tsx`](file:///Users/diwei/项目2026/OntoVis/apps/workbench/src/CockpitAnalysis.tsx)）
- 现有结构：
  ```tsx
  <div className="pa-content">
    <main className="pa-evidence">...</main>
    <aside className="pa-record pa-assistant pc-panel">...</aside>
  </div>
  ```
- 现状痛点：
  1. `.pa-content` 使用 CSS Grid 写死两栏，无折叠状态支持；
  2. `<aside className="pa-record pa-assistant">` 无法移动，且 `header` 没有拖拽句柄和收起按钮。

### 2.2 交互设计
1. **状态设计**：
   - `collapsed: boolean`（收起状态，默认 `false`，支持从 `localStorage.getItem('ontovis.cockpit.assistant_collapsed')` 初始化）；
   - `floatingPosition: {x: number; y: number} | null`（浮动坐标，默认为 `null` 代表停靠在右侧网格列；当用户拖拽后记录绝对位置 `{x, y}`）；
   - `isDragging: boolean`（当前是否正在拖动）。
2. **拖拽逻辑（Pointer Event）**：
   - 在标题栏的 `onPointerDownCapture` 中记录初始指针坐标与面板初始位置，并调用 `event.currentTarget.setPointerCapture(event.pointerId)`；
   - `onPointerMove` 时计算位移增量 $\Delta x, \Delta y$，并将面板位置更新为相对于 `.pa-content` 或工作区的偏移量；
   - 结合工作区 `getBoundingClientRect()` 计算最大允许的 $X$ 和 $Y$ 边界，防止拖出屏幕可视区域；
   - 点击标题栏按钮时通过 `.closest('button')` 过滤，避免误触发拖动。
3. **收起与展开流转**：
   - 展开状态：面板正常渲染为侧边栏（`floatingPosition === null` 时）或浮动窗（`floatingPosition !== null` 时），标题栏右侧显示“停靠/复位”和“收起”图标按钮；
   - 收起状态：
     - 若处于侧边栏模式收起，主画布 `.pa-evidence` 占据全宽（`grid-template-columns: 1fr`），右侧边缘呈现优雅的毛玻璃浮动启动条（`✨ 工程助手`）；
     - 若处于浮动模式收起，面板收缩为当前浮动位置（或自动靠边）的迷你药丸按钮，点击立即重新展开为完整面板。

---

## 3. 具体修改设计与代码清单

### 3.1 增加面板收起与拖动逻辑（[`apps/workbench/src/CockpitAnalysis.tsx`](file:///Users/diwei/项目2026/OntoVis/apps/workbench/src/CockpitAnalysis.tsx)）
1. **引入图标**：
   - 从 `lucide-react` 引入 `PanelRightClose`、`PanelRightOpen`、`GripHorizontal`、`RotateCcw`、`Pin` 等图标；
2. **状态定义与持久化**：
   - `const [assistantCollapsed, setAssistantCollapsed] = useState<boolean>(() => { try { return localStorage.getItem('ontovis.cockpit.assistant_collapsed') === 'true'; } catch { return false; } });`
   - `const [assistantFloating, setAssistantFloating] = useState<{x: number; y: number} | null>(null);`
   - `const [assistantDragging, setAssistantDragging] = useState(false);`
3. **实现标题栏拖拽处理函数**：
   - `startAssistantDrag(event: ReactPointerEvent<HTMLElement>)`
   - `moveAssistantDrag(event: ReactPointerEvent<HTMLElement>)`
   - `endAssistantDrag()`
   - 双击标题栏或点击“恢复停靠”按钮重置 `assistantFloating` 为 `null`。
4. **渲染条件控制**：
   - 当 `assistantCollapsed === true` 时，渲染轻量悬浮触发条 `<button className="pa-assistant-launcher" onClick={()=>setAssistantCollapsed(false)}>...`；
   - 面板应用 `data-floating={!!assistantFloating}`、`data-dragging={assistantDragging}` 属性与动态内联位置样式（`style={assistantFloating ? { left: assistantFloating.x, top: assistantFloating.y } : undefined}`）。

### 3.2 布局样式重构（[`apps/workbench/src/cockpitAnalysis.css`](file:///Users/diwei/项目2026/OntoVis/apps/workbench/src/cockpitAnalysis.css)）
1. **主网格列自适应**：
   - 当处于 `.pa-content[data-assistant-collapsed=true]` 或 `.pa-content[data-assistant-floating=true]` 时，网格布局自动调整为：
     `grid-template-columns: 1fr;`，主画布无缝平滑铺满全宽；
2. **工程助手面板浮动样式**：
   - `.pa-assistant[data-floating=true]`：
     `position: absolute; width: clamp(340px, 29%, 430px); height: min(720px, calc(100% - 32px)); z-index: 15; box-shadow: 0 18px 48px #00000040, 0 0 0 1px var(--pc-border);`；
   - 拖拽中激活态：
     `.pa-assistant[data-dragging=true]{ user-select: none; transition: none; }`；
   - 标题栏拖拽光标与控制按钮组：
     `.pa-assistant > header { cursor: grab; }`、`.pa-assistant[data-dragging=true] > header { cursor: grabbing; }`、`.pa-assistant-actions` 按钮排布；
3. **收起后的浮动触发条（`.pa-assistant-launcher`）**：
   - 定位在工作区右侧或右上侧（如 `position: absolute; right: 24px; top: 18px; z-index: 10;`），带有毛玻璃效果 `background: var(--pc-panel); backdrop-filter: var(--pc-blur); border: 1px solid var(--pc-border); border-radius: 20px; box-shadow: 0 6px 20px #00000028;`，hover 呼吸高亮反馈。

---

## 4. 验证与部署流程

1. **功能与交互验证**：
   - 点击收起按钮，工程助手收起为右侧毛玻璃悬浮胶囊，画布自动平滑全屏；
   - 点击悬浮胶囊，工程助手完整展开；
   - 按住工程助手标题栏拖拽，面板平滑跟随光标移动并进入浮动窗口模式，且不越界；
   - 点击“恢复停靠”或双击标题栏，面板一键停靠回右侧；
   - 刷新页面，验证收起/展开状态的跨会话保存。
2. **测试与构建**：
   - 运行 `npm --prefix apps/workbench run check` 确保类型检查、全部单元测试及 Vite 打包通过。
3. **Git 提交与服务器部署**：
   - 提交修改并推送到远程分支 `codex/design-foundation`；
   - 发布至测试服务器 `192.168.2.153` (`https://vis.ontobase.ai`)，并归档 `walkthrough.md`。
