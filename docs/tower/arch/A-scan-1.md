---
type: Module
id: A-scan-1
title: 安装包说明页
layer: L1
status: draft
name: 安装包说明页
paths:
- apps/xiaobucubic/package/info.html
verify: []
confidence: 0.5
rationale: 固定提交的 info.html 是安装包内静态说明；build.py 与 deploy.py 遍历 package 将其打包和部署。职责明确，但扫描只分配了这一个 HTML 文件，未纳入真正运行的 Lua 与资源，因此不能代表完整设备应用。
source_revision: 64afeb8a669b29069319e7e7f90e3a952afc07e4
initial_evidence:
  actor: process:towermd-verifier
  cleanup_complete: true
  commands: []
  finished_at: 2026-10-26T13:58:07.991559+00:00
  report_sha256: 171e3098b03f16d58fcde1420c7906300ee2b701db779b61909b43179ef30603
  revision: 64afeb8a669b29069319e7e7f90e3a952afc07e4
  scan: 01a17881-1158-7427-a6b6-e49148363ffe
  shared: false
  started_at: 2026-10-26T13:58:07.866715+00:00
  status: no_tests
  tree: a1470858faf2e5b6ca5c8961eb67d68e7daade73
verification: no_tests
verification_commands: []
generated:
  at: 2026-10-26T14:03:45.008206+00:00
  by: codex-cli/0.163.0
---
# 安装包说明页

负责随安装包交付的中文介绍、按键说明和配置入口提示。当前唯一归属文件是 `apps/xiaobucubic/package/info.html`；它说明额度与天气主页、有消息才出现的消息页、左右／上／下／Home 操作以及 `demo=true` 标识。

该页由 A-scan-2 的构建／部署工具作为普通静态文件携带，不提供 HTTP 服务，也不承担 Lua 数据解析或渲染。页面仍标注 1.0.0，而已提交 README 的安装说明为 1.1.6，存在说明同步问题。

`package/main.lua`、`display_model.lua`、字体、图片和配置实际属于设备运行交付物，但未进入本次扫描模块的 paths；此处仅记录上下文，不扩大该模块边界。需要人工决定补入设备应用模块还是调整扫描分组。

依据：`apps/xiaobucubic/package/info.html`、`tools/build.py`、`tools/deploy.py`、`apps/xiaobucubic/README.md`（tools 路径均相对 apps/xiaobucubic）。本次未发现验证命令，S5 为 no_tests。

依据提交：`64afeb8a669b29069319e7e7f90e3a952afc07e4`。本文为综合草稿，不授予验证或批准状态。
