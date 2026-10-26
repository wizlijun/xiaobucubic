---
type: Interface
id: IF-package-info
title: 安装包说明页的文件交付约定
layer: L1
status: draft
from: A-scan-1
to: A-scan-2
contract: A-scan-1 提供 UTF-8 静态 package/info.html；A-scan-2 的 build.py 原样纳入 ZIP 的 apps/xiaobucubic/info.html，deploy.py 上传至 /sd/apps/xiaobucubic/info.html 并回读比较 SHA-256。
generated:
  at: 2026-10-26T14:03:45.008206+00:00
  by: codex-cli/0.163.0
---
# 安装包说明页的文件交付约定

这是文件交付接口，不是 HTTP 调用。源码证据为 tools/build.py 对 package 的递归归档，以及 tools/deploy.py 对相同目录的遍历、路径映射、上传和回读比较；两者都没有排除 info.html。

S3 的共同修改记录只说明历史关联；本接口成立依据是明确的文件生产／消费关系。生产 GET /v1/display 的真正消费方为尚未分配的 Lua 程序，因此没有用 HTML 模块冒充客户端创建服务端接口边。

依据提交：`64afeb8a669b29069319e7e7f90e3a952afc07e4`。本文为综合草稿，不授予验证或批准状态。
