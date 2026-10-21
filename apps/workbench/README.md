# ONTOVis 正式只读工作台首切

承接原MagicPath工作台修订`463633480128040960`，实现已批准的本人登录、当前安装树/对象与关联图纸预览。其他产品模块保持未开放。布局示意不产生工程几何绑定；确认绑定、发布和现场控制保持禁用。

`src/Workbench.tsx`展示动态安装对象，按服务端游标加载下级；`SourceEvidence.tsx`区分来源对象与分析身份，打开前核验当前图纸，变化后要求重新选择。Radix Dialog/Tabs提供弹窗与页签行为，单页PNG由OntoBase从相同摘要PDF临时生成，使用浏览器图片阅读与滚动/缩放；退出、撤权、对象或修订切换撤销临时对象URL，丢弃旧会话响应。

`src/design.css`来自上述批准的MagicPath工作台，`workbench.css`只适配实际数据树、共享阅读控件和弹窗。Logo直接引用仓库品牌原件。没有合成工程数据、评审状态选择器、空间Demo数据包、远程字体或第三方模型打包。

Node 22：

```sh
npm ci --prefix apps/workbench
npm --prefix apps/workbench run check
npm --prefix apps/workbench run dev
```

验证服务端口4180，代理固定本机18084。检查包含严格类型、9项响应时序/权限单测与构建，构建产物位于`output/current-evidence-preview-20261021/workbench-dist/`，不进入Git。会话服务配置项目及安装范围，详情见[会话层](../README.md)。应用不接收浏览器提供的上游地址、角色或任意文件URI。

此首切仅覆盖同项目、当前内容快照的单页资料，既有来源缺少可信文件摘要锚点时显示整页。20条关联及20MiB单页上限由OntoBase实施；历史归档、正式绑定存储与工程审核发布另排。
