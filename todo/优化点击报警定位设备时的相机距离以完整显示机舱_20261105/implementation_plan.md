# 优化点击报警定位设备时的相机距离以完整显示机舱 实施方案

## 1. 背景与目标

### 1.1 问题现象
- **用户反馈**：在驾驶舱点击报警定位到设备时（如“本源1号·CN1 机舱动力柜”），默认相机视角距离目标部件过近，几乎被柜体和发电机局部填满视口，机舱轮廓和两端被裁切到屏幕外（见用户上传截图 1）。
- **用户诉求**：希望相机默认视角拉远一些，至少能够看到完整的机舱（见用户手动拉远后的截图 2）。

### 1.2 根因定位
- 在 [`apps/workbench/src/sceneComponentFocus.ts`](file:///Users/diwei/项目2026/OntoVis/apps/workbench/src/sceneComponentFocus.ts#L53) 中，聚焦函数 `componentFocusView` 计算相机与目标的视距公式为：
  ```ts
  const distance = Math.max(
    showContext ? 6 : 3,
    radius / Math.sin(Math.min(halfVertical, halfHorizontal)) * (showContext ? 1.7 : 1.15)
  );
  ```
- 当用户在驾驶舱（`presentation = true`，即 `showContext = true`）点击报警或设备结构树定位到细小部件（例如 CN1 动力柜，外接半径 $radius \approx 1.18\text{m}$）时：
  $radius / \sin(21^\circ) \times 1.7 \approx 1.18 / 0.358 \times 1.7 \approx 5.6\text{m}$；
- 计算结果小于保底值 `6` 米，因此距离直接被截断在 **6 米**。
- 在 $42^\circ$ FOV 下，6 米距离对应的垂直视野仅约 4.6 米，根本无法容纳全长约 12~14 米的风机机舱，导致机舱两端严重出画，视感局促。

---

## 2. 优化方案设计

### 2.1 距离参数优化与黄金视距推导
1. **机舱全景包络视距**：
   - 风机完整机舱全长约为 12~14 米，高约 4~5 米；
   - 界面左侧有设备结构树面板（宽约 280px），右侧有设备详情卡片（宽约 260px），视口中央可用安全宽度约为 70% 左右；
   - 当相机距离设置为 **22 米** 时：
     - 在 $42^\circ$ FOV 下，相机垂直视野高度为 $H = 2 \times 22 \times \tan(21^\circ) \approx 16.9\text{m}$；
     - 在 16:9 屏幕下，水平视野为 $W \approx 30.0\text{m}$，扣除左右遮挡后的安全视口宽度约 $21.6\text{m}$；
     - 14 米长的机舱在视口中横向占比约为 $65\%$，左右两端留有约 3.8 米舒适呼吸余量，完美避开左右侧边面板；
     - 在 16:10（如 MacBook 1440x900）屏幕下，安全视口宽度约 $18.4\text{m}$，机舱横向占比约 $76\%$，同样完整入镜不被切边。
2. **核心代码调整**：
   - 修改 [`apps/workbench/src/sceneComponentFocus.ts`](file:///Users/diwei/项目2026/OntoVis/apps/workbench/src/sceneComponentFocus.ts#L53)：
     ```ts
     /* 优化前 */
     const distance = Math.max(showContext ? 6 : 3, radius / Math.sin(Math.min(halfVertical, halfHorizontal)) * (showContext ? 1.7 : 1.15));

     /* 优化后 */
     const distance = Math.max(showContext ? 22 : 3, radius / Math.sin(Math.min(halfVertical, halfHorizontal)) * (showContext ? 1.7 : 1.15));
     ```
3. **大对象兼容性**：
   - 当定位的目标本身较大（如整台机舱 $radius \approx 7.5\text{m}$，算得距离约 35.6m；整台风机 $radius \approx 50\text{m}$，算得距离约 237m）时，由于公式前半段大于 22 米，`Math.max` 自然采用实际大尺寸，不受 22 米下限限制。

---

## 3. 涉及文件清单

| 文件路径 | 变更目的 |
|---|---|
| [`apps/workbench/src/sceneComponentFocus.ts`](file:///Users/diwei/项目2026/OntoVis/apps/workbench/src/sceneComponentFocus.ts) | 将 `showContext` 模式下部件聚焦的保底距离从 6m 调整为 22m，确保机舱完整呈现 |
| [`apps/workbench/tests/scene-component-focus.test.mjs`](file:///Users/diwei/项目2026/OntoVis/apps/workbench/tests/scene-component-focus.test.mjs) | 补充微小部件展示聚焦保底距离不少于 22 米的单元测试，防止未来意外回退 |

---

## 4. 验证计划

1. **自动化测试**：
   - 运行组件聚焦单元测试：
     ```bash
     node --experimental-strip-types --test apps/workbench/tests/scene-component-focus.test.mjs
     ```
   - 运行驾驶舱仿真与三维视口测试：
     ```bash
     node --experimental-strip-types --test apps/workbench/tests/cockpit-simulation.test.mjs apps/workbench/tests/cockpit-space.test.mjs apps/workbench/tests/project-cockpit.test.mjs
     ```
2. **静态类型检查与构建验证**：
   - 执行 TypeScript 静态类型核验：
     ```bash
     node apps/workbench/node_modules/typescript/bin/tsc --noEmit -p apps/workbench
     ```
   - 执行前端打包构建：
     ```bash
     ONTOVIS_LOGIN_MEDIA_PUBLIC_DIR=/Users/diwei/项目2026/OntoVis/output/scene-info-save-20261105/_work/media-public npm --prefix apps/workbench run build
     ```
3. **视效对照核验**：
   - 对比用户上传的截图 1（贴脸过近）与截图 2（拉远全景），确认新参数下相机聚焦定位时机舱完整入镜、两端不被侧边栏遮挡、且高亮报警标签气泡居中醒目。
