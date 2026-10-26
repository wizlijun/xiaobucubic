---
type: Intent
id: I-glance
title: 抬头看见额度、天气和有效提醒
layer: L0
status: draft
allocated_to:
- A-scan-1
- A-scan-2
- A-scan-3
generated:
  at: 2026-10-26T14:03:45.008206+00:00
  by: codex-cli/0.163.0
---
# 抬头看见额度、天气和有效提醒

依据根 README.md、apps/xiaobucubic/README.md 与 package/info.html，项目面向 ClocTeck HoloCubic 的 320×240 小屏，让用户看到订阅剩余额度／流量、天气和提醒。订阅按数据动态排列，支持多窗口与分页；没有有效提醒时保持额度页，每条便签最多五行，长内容省略。

分配含义：A-scan-1 提供操作说明，A-scan-2 提供测试和交付支撑，A-scan-3 供给数据。实际 Lua 渲染尚无扫描归属，不能据此认为三个候选模块已完整承接产品意图。

依据提交：`64afeb8a669b29069319e7e7f90e3a952afc07e4`。本文为综合草稿，不授予验证或批准状态。
