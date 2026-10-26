---
type: Acceptance
id: AC-device-delivery
title: 安装和设备检查保留用户状态
layer: L2
status: draft
module: A-scan-2
criteria:
- 构建版本来自 app.info，ZIP 采用 apps/xiaobucubic 路径，排除 cache.json 和 diagnostics.json；发布前确认包内 config.json 不含真实凭据。
- 普通升级默认保留设备 config.json，先备份后写入，逐文件回读比较；失败恢复与恢复失败均须有可追溯结果。
- 实机检查需在明确设备操作范围后验证真实响应间隔、字体／天气背景及第二次轮询不清屏，并恢复正式应用；不能用历史截图替代本次结果。
- 自启动修改须识别 Launcher 版本、保留其他设置并校验回读；未知源码停止，重复运行不重复打补丁。
generated:
  at: 2026-10-26T14:03:45.008206+00:00
  by: codex-cli/0.163.0
---
# 安装和设备检查保留用户状态

依据 tools/build.py、deploy.py、check_live.py、set_autostart.py 和 README.md。实机命令有写入副作用，本次未执行。

上述为待审阅的验收草稿；本次没有可引用的验证命令，未填 verify，也不宣称条目已经通过。

依据提交：`64afeb8a669b29069319e7e7f90e3a952afc07e4`。本文为综合草稿，不授予验证或批准状态。
