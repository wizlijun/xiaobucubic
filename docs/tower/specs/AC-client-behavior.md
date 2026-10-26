---
type: Acceptance
id: AC-client-behavior
title: 客户端回归覆盖显示与恢复行为
layer: L2
status: draft
module: A-scan-2
criteria:
- 现有 Lua 回归应覆盖未知与零值区分、百分比向下取整、流量字段、任意提供商双窗口、全部额度分页及增删重排。
- 回归应覆盖消息单便签五行省略、过期消息移除、离线／暂停／不可信时钟以及退出资源清理。
- 回归应覆盖错误响应保留缓存、不重叠请求、迟到回调、5/10/20/40/80/160/300 秒退避、Wi-Fi 恢复与局部刷新不清屏。
- 模拟接口测试应确认配置 token 时拒绝未授权读取、保留示例相对时间，并始终标记 demo=true。
generated:
  at: 2026-10-26T14:03:45.008206+00:00
  by: codex-cli/0.163.0
---
# 客户端回归覆盖显示与恢复行为

依据 tests/test_display.py、tests/test_mock_api.py、tools/mock_api.py 与 API.md；这是测试模块的覆盖与预期行为，不把被测 Lua 文件划入该模块。

上述为待审阅的验收草稿；本次没有可引用的验证命令，未填 verify，也不宣称条目已经通过。

依据提交：`64afeb8a669b29069319e7e7f90e3a952afc07e4`。本文为综合草稿，不授予验证或批准状态。
