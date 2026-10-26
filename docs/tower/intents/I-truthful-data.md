---
type: Intent
id: I-truthful-data
title: 失联或未知时仍如实展示数据状态
layer: L0
status: draft
allocated_to:
- A-scan-2
- A-scan-3
generated:
  at: 2026-10-26T14:03:45.008206+00:00
  by: codex-cli/0.163.0
---
# 失联或未知时仍如实展示数据状态

依据 apps/xiaobucubic/API.md、README.md 及 server/README.md，未知量不伪造为零，额度显示剩余比例而非虚构 token 总数；源时间不随读取伪更新，过期、离线、鉴权失败和演示状态必须可辨识。采集失败保留上次成功数据；客户端错误响应不覆盖有效缓存，离线与暂停轮播时仍过滤到期消息。

A-scan-3 承担采集、时间和错误语义，A-scan-2 对这些行为提供客户端回归和实机检查支撑；Lua 运行实现的归属待确认。

依据提交：`64afeb8a669b29069319e7e7f90e3a952afc07e4`。本文为综合草稿，不授予验证或批准状态。
