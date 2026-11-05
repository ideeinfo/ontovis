# 模型工具条选中态橙色高亮 实施方案

## 1. 背景与目标

用户要求：
“点击实体、透视、爆炸示意，选中的文字和图标应该橙色高亮，无需审核直接实施并部署”

当前 `.pc-model-view button[aria-pressed=true]` 使用的是绿色主题色（`var(--pc-green)` 和 `#458f7940`），需要将其统一调整为项目的橙色高亮体系（`--pc-orange` / `--pc-orange-text` / `--pc-orange-tint` / `--pc-orange-border`），与左侧设备树部件选中态保持一致，使选中的状态在暗色视口中更加突出醒目。

---

## 2. 详细改造方案

1. **更新 `apps/workbench/src/cockpitSpace.css`**：
   - 将 `.pc-model-view button[aria-pressed=true]` 的配色由绿色改为橙色体系：
     ```css
     .pc-model-view button[aria-pressed=true]{background:var(--pc-orange-tint,rgba(196,83,0,.22));color:var(--pc-orange-text,var(--pc-orange,#ff790d));box-shadow:0 0 0 1px var(--pc-orange-border,#ff790d70)}
     .pc-model-view button[aria-pressed=true]>svg{color:var(--pc-orange-text,var(--pc-orange,#ff790d))}
     ```
2. **在 `apps/workbench/src/projectCockpit.css` 中增强特异性样式**：
   - 为底部控制坞 `.pc-model-dock .pc-model-view` 提供明确的橙色高亮支持：
     ```css
     .pc-model-dock .pc-model-view button[aria-pressed=true]{background:var(--pc-orange-tint);color:var(--pc-orange-text)!important;box-shadow:0 0 0 1px var(--pc-orange-border)}
     .pc-model-dock .pc-model-view button[aria-pressed=true]>svg{color:var(--pc-orange-text)!important}
     ```
   - 深色模式下为明亮橙色（`#ff790d`），浅色模式下为稳重橙色（`#b65308`），自适应主题。

---

## 3. 涉及文件清单

| 文件路径 | 变更目的 |
|---|---|
| [`apps/workbench/src/cockpitSpace.css`](file:///Users/diwei/项目2026/OntoVis/apps/workbench/src/cockpitSpace.css) | 将模型查看栏选中态基础样式设为橙色背景与文字 |
| [`apps/workbench/src/projectCockpit.css`](file:///Users/diwei/项目2026/OntoVis/apps/workbench/src/projectCockpit.css) | 增强底部控制坞选中态橙色样式与图标颜色 |

---

## 4. 验证与部署计划

1. 运行全量测试套件（769+ 项用例）：`node --experimental-strip-types --test apps/workbench/tests/*.test.mjs`
2. 执行 TypeScript 静态检查：`tsc --noEmit -p apps/workbench`
3. 执行前端生产构建打包
4. Git 提交并推送至 `origin/codex/design-foundation`
5. 通过 `remote_deploy.py` 原子无缝发布到测试服务器 `192.168.2.153`
6. 线上调用 `/health` 验证服务状态
