---
type: Module
id: A-scan-3
title: 显示数据服务与用量、天气采集
layer: L1
status: draft
name: 显示数据服务与用量、天气采集
paths:
- server/banwagong_usage.py
- server/claude_usage.py
- server/codex_usage.py
- server/display_push.py
- server/display_server.py
- server/grok_usage.py
- server/start.sh
- server/tests/test_banwagong.py
- server/weather_shenzhen.py
verify: []
confidence: 0.9
rationale: display_server.py 定义 schema v1 HTTP API、Store 与 Scheduler；五个采集器共享 display_push.py 以 HTTP PUT 写入本机服务，start.sh 管理 frpc 和服务进程，test_banwagong.py 覆盖转换与本机 HTTP 持久化。源码和 server/README.md 对职责相互印证。
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
# 显示数据服务与用量、天气采集

负责聚合订阅额度、搬瓦工月流量、深圳天气与提醒，持久化并向显示端提供 schema_version=1 JSON。使用 Python 标准库；外部依赖来自各提供商查询接口、本机登录凭据、Codex CLI 以及启动脚本使用的 frpc／openssl。

数据链路：Claude／Codex／Grok／KiwiVM／Open-Meteo → 各采集器 → display_push 的带写 token HTTP PUT → display_server.Store → GET /v1/display → Lua 设备客户端（后者尚未被扫描分配）。采集器与服务均在本模块内，不能将它们画成未经扫描产生的新模块。

- `display_server.py` 校验订阅窗口、整数流量、提醒 TTL 和天气，按 order／默认提供商顺序返回数据；每次响应生成 generated_at，保留数据源 updated_at。
- 读 token 只读；写 token 管理数据；消息 token 只能管理 sender=bot 的提醒集合，默认 24 小时、最长 7 天。当前没有逐个机器人的身份隔离。
- Store 以锁保护内存数据，通过同目录临时文件与 os.replace 持久化。这里确认写盘方式，不承诺写盘失败时内存修改具备事务回滚。
- Scheduler 根据显示请求调整采集间隔，空闲时翻倍；采集脚本顺序执行，每个最多 90 秒。失败或超时保留上次成功数据，不把缺失量写为零。
- 搬瓦工使用固定提交中的 `banwagong` 命名，查询当前计费月、倍率与重置时间；没有引入脏工作树中的新命名或新实现。天气 updated_at 使用上游观测时刻。
- `start.sh` 生成缺少的 token、启动 frpc 并等待代理成功，然后在本机监听显示服务；进程生命周期、反向代理与生产凭据不在本次只读综合中实际运行。

依据：`server/README.md`、全部已分配服务端源码，重点为 `display_server.py`、`display_push.py` 和 `tests/test_banwagong.py`；接口语义另见 `apps/xiaobucubic/API.md`。本次 S5 为 no_tests，现有测试文件不等于已获取本次验证证据。

依据提交：`64afeb8a669b29069319e7e7f90e3a952afc07e4`。本文为综合草稿，不授予验证或批准状态。
