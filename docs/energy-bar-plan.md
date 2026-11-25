# 「人的能量」进度条规划与数据预留

## 1. 设计目标

在现有信息面板（HoloCubic Lua、ESP32-S3 原生屏、StandIt iOS）中增加一项独立的**个人能量**进度条，同时保持 `GET /v1/display` 的 `schema_version: 1` 向后兼容：

- **展示形式**：服务端在响应 `GET /v1/display` 时将非空的 `energy` 自动投影为 `subscriptions` 数组的首项（`id: "energy"`），**所有现有客户端（HoloCubic、ESP32-S3、StandIt App 与小组件）无需升级即可动态显示**；低于 20% 自动警告黄，低于 5% 警戒红，缺失显示 `--`。
- **无数据时隐藏**：服务端 `energy` 为 `null` 时不投影到 `subscriptions`，三端自动隐藏；写入能量数据后自动显示，所有卡片始终按单列同屏呈现（每页最多 6 项）。
- **独立语义与有效期**：人体能量直接使用剩余能量 `level_percent`（0–100，服务端换算为 `used_percent = 100 - level_percent`），并支持独立 `stale_after_seconds`（如 4 小时 / 12 小时 / 24 小时），在有效期内由服务端维持新鲜时间戳，避免低频更新的健康数据 15 分钟就变灰过期。

## 2. 接口与数据格式预留

### 2.1 `GET /v1/display` 中的 `energy` 字段

位于响应顶层，未配置或已清除时为 `null`：

```json
{
  "schema_version": 1,
  "generated_at": 1795581200,
  "stale_after_seconds": 900,
  "subscriptions": [],
  "energy": {
    "name": "HP",
    "level_percent": 78,
    "status": "充沛",
    "trend": "steady",
    "note": "睡眠 7.5h · HRV 62",
    "source": "manual",
    "updated_at": 1795581000,
    "updated_at_utc": "2026-11-25T04:30:00Z",
    "stale_after_seconds": 14400
  },
  "messages": [],
  "weather": null
}
```

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `name` | string (≤40) | 否 | 卡片标题，默认 `"HP"`（可自定义如 `"Human"`、`"Carbon"`、`"Stamina"`） |
| `level_percent` | number (0–100) / `null` | 否 | 当前剩余能量百分比（0 耗尽，100 满电；`null` 显示 `--`） |
| `status` | string (≤16) | 否 | 简短状态标签（如 `"充沛"`、`"正常"`、`"偏低"`、`"午休后"`），显示在副行左侧 |
| `trend` | `"charging"` / `"draining"` / `"steady"` / `null` | 否 | 趋势标识；当未填 `status` 时自动映射为 `"回血中"` / `"消耗中"` / `"平稳"` |
| `note` | string (≤80) | 否 | 补充说明（如 `"睡眠 7.5h · HRV 62"`），显示在副行右侧 |
| `source` | `"official"` / `"manual"` / `"estimated"` / `"unknown"` | 否 | 数据来源声明，默认 `"unknown"` |
| `updated_at` | int (Unix 秒) | 否 | 真实采集时间，缺省由服务端补当前时间；响应自动附带 `updated_at_utc` |
| `stale_after_seconds` | int (60–604800) | 否 | 能量数据独立有效期（1 分钟至 7 天），缺省沿用全局 `stale_after_seconds` |

### 2.2 服务端写入与清除接口

均需写权限 token（`DISPLAY_WRITE_TOKEN`），与 `/v1/weather` 保持对称：

- `PUT /v1/energy`：写入或更新能量数据（请求体为 `null` 时等价于清除）。
- `DELETE /v1/energy`：清除能量数据（恢复 `energy: null`，界面自动隐藏）。

### 2.3 命令行辅助脚本

`server/energy_usage.py` 已预留，用于快速验证或接入外部脚本 / 快捷指令：

```sh
# 写入示例数据（推送后三端立即显示能量卡片）
python3 server/energy_usage.py --level 78 --status 充沛 --note "睡眠 7.5h" --source manual --stale-after 14400 --push

# 清除能量数据（恢复隐藏）
python3 server/energy_usage.py --clear --push
```

> 暂不加入 `display_server.py` 的自动采集器列表 `COLLECTORS`，待确定真实数据源后再接入按需调度。

## 3. 后续可选数据源方向

确定方向后，只需按第 2 节格式向 `PUT /v1/energy` 推送即可，**无需再次修改三端客户端**：

1. **Apple Health + iOS 快捷指令（零服务器依赖，推荐）**
   - 早上起床或定时触发快捷指令，读取「睡眠时长」「HRV」「静息心率」「活动能量」做加权打分，直接 HTTP `PUT /v1/energy`（设置 `source: "official"`，`stale_after_seconds: 28800`）。
2. **穿戴设备直接拉取（Garmin Body Battery / Oura Readiness / Whoop Recovery）**
   - 写一个采集函数集成到 `server/energy_usage.py`，接入 `display_push.py` 调度协议并注册进 `COLLECTORS`，由服务端按需定时刷新。
3. **作息 + 日间耗电估算模型（`source: "estimated"`）**
   - 以早晨初始值（睡眠分数或固定满电）为起点，结合日间工作时长、会议日程或番茄钟逐步衰减，午休/散步回充，设置 `trend: "draining" / "charging"`。
4. **轻量手动打卡 / 机器人指令（`source: "manual"`）**
   - 通过手机快捷指令菜单（如 90% 满血 / 70% 正常 / 40% 疲惫 / 15% 急需休息）或聊天机器人一键更新。

## 4. 三端渲染规则摘要

- **位置**：当 `energy != null` 时插入首页卡片首位，订阅卡片原有顺序与配色不变。
- **进度与告警**：进度条宽度为 `floor(level_percent)%`；正常为薄荷绿，`< 20%` 为黄，`< 5%` 为红；超过 `energy.stale_after_seconds`（或全局 TTL）显示 `已过期` 并转为灰态。
- **StandIt 小组件**：`Stand It 余量` 小组件当前仍聚焦 `subscriptions`（AI 订阅额度），等正式数据源确定后可按需决定是否加入能量条目。
