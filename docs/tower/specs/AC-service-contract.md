---
type: Acceptance
id: AC-service-contract
title: 服务数据契约、权限和失败保留
layer: L2
status: draft
module: A-scan-3
criteria:
- GET /v1/display 返回 schema_version=1、响应生成时间、真实源更新时间、排序订阅、至多十二条有效消息与天气；Unix 秒语义保持一致。
- 读取 token 不能写入；写 token 可管理数据；消息 token 只能管理 bot 提醒，默认 TTL 24 小时、最长 7 天。
- 流量窗口校验整数总量／用量并计算剩余量，拒绝不一致 remaining_bytes；倍率、超额、缺失与无效数据由测试覆盖。
- 采集失败不提交伪零或刷新旧数据时间；HTTP 写入后读取及重启恢复由本机测试确认。
- 响应满足客户端 24576 字节上限；当前实现只删除末尾消息，订阅本身过大时没有兜底，本条为已识别缺口。
generated:
  at: 2026-10-26T14:03:45.008206+00:00
  by: codex-cli/0.163.0
---
# 服务数据契约、权限和失败保留

依据 server/display_server.py、display_push.py、banwagong_usage.py、tests/test_banwagong.py 和 apps/xiaobucubic/API.md。

上述为待审阅的验收草稿；本次没有可引用的验证命令，未填 verify，也不宣称条目已经通过。

依据提交：`64afeb8a669b29069319e7e7f90e3a952afc07e4`。本文为综合草稿，不授予验证或批准状态。
