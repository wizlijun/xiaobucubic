---
type: Module
id: A-scan-2
title: 客户端测试、打包与设备运维工具
layer: L1
status: draft
name: 客户端测试、打包与设备运维工具
paths:
- apps/xiaobucubic/tests/test_display.py
- apps/xiaobucubic/tests/test_mock_api.py
- apps/xiaobucubic/tools/build.py
- apps/xiaobucubic/tools/check_live.py
- apps/xiaobucubic/tools/check_retry.py
- apps/xiaobucubic/tools/deploy.py
- apps/xiaobucubic/tools/device_smoke.py
- apps/xiaobucubic/tools/mock_api.py
- apps/xiaobucubic/tools/set_autostart.py
verify: []
confidence: 0.78
rationale: test_display.py 通过 lupa 执行 Lua 模型和应用，mock API 与测试提供模拟数据；设备检查及自启动工具引用 deploy.py，构建工具产出 SD 卡 ZIP。这些用途由源码确认，但测试与设备写入工具合并为一组是否合适仍需人确认。
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
# 客户端测试、打包与设备运维工具

负责主机侧 Lua 行为回归、模拟显示接口、安装包构建、设备部署与检查。保留扫描分配的九个 Python 文件，不将测试所读取的 Lua 文件自动计入归属。

- `tests/test_display.py` 用 lupa 加载 `package/display_model.lua` 和 `package/main.lua`，模拟固件／LVGL，覆盖额度与流量计算、动态分页、消息过期、局部刷新、HTTP 错误、重试、Wi-Fi 恢复和退出清理。
- `tools/mock_api.py` 从示例构造 schema v1 数据并强制 demo=true，可选 Bearer token；`tests/test_mock_api.py` 检查鉴权和时间偏移。
- `tools/build.py` 从 app.info 读取版本，遍历 package 生成 apps/xiaobucubic 路径布局的 ZIP，排除 cache.json 和 diagnostics.json；仍会包含 config.json，不能据此推定任何本地配置都适合发布。
- `tools/deploy.py` 在写入前备份，默认保留设备 config.json，逐文件读取比较 SHA-256；出错时尝试恢复旧文件。`set_autostart.py` 另会修改设备 Launcher 和 settings，职责超出应用目录。
- `device_smoke.py`、`check_live.py`、`check_retry.py` 使用设备探针和 DevTools；check_live 检查两次真实响应、55–75 秒间隔及第二次响应不清屏，并在 finally 尝试恢复正式应用。这些工具涉及设备写入，不能当作无副作用单测。

产品运行上下文（未分配文件，不是本模块新增边界）：Lua 主程序轮询服务端 GET /v1/display，模型做 schema／时间／额度归一化，LVGL 展示额度、天气和便签；成功数据落缓存，失败退避至 300 秒，消息依服务时间加单调时钟到期。服务端入口归属 A-scan-3，客户端主入口目前未归属；不能把 A-scan-1 的 HTML 当作 HTTP 消费者。

依据：本模块 paths 内源码、`apps/xiaobucubic/API.md`、`README.md`、`VALIDATION.md` 及上述 Lua 文件。VALIDATION.md 记载 43 项 Lua 测试等历史结果，仅作历史文档；本次 S5 没有运行任何验证命令，verify 保持空列表。

依据提交：`64afeb8a669b29069319e7e7f90e3a952afc07e4`。本文为综合草稿，不授予验证或批准状态。
