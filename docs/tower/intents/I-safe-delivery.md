---
type: Intent
id: I-safe-delivery
title: 保留配置地交付 Lua 应用并分离读写权限
layer: L0
status: draft
allocated_to:
- A-scan-2
- A-scan-3
generated:
  at: 2026-10-26T14:03:45.008206+00:00
  by: codex-cli/0.163.0
---
# 保留配置地交付 Lua 应用并分离读写权限

依据 apps/xiaobucubic/README.md 的安装、配置段与 API.md，应用升级无需重新烧录整机固件，默认保留设备接口地址、读取 token 和缓存；部署前备份、部署后回读校验。账户登录凭据留在服务侧，设备使用读取 token；读取权限不能修改服务数据。

A-scan-2 承担打包／部署与配置保护，A-scan-3 承担写权限校验与采集凭据访问。本条是已有文档意图，不表示固定提交中的凭据管理和所有失败恢复路径已经通过安全验证。

依据提交：`64afeb8a669b29069319e7e7f90e3a952afc07e4`。本文为综合草稿，不授予验证或批准状态。
