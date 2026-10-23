# 读取显示接口

显示端只调用一个接口，不负责登录订阅平台或采集用量。

```http
GET /v1/display
Accept: application/json
Authorization: Bearer <read_token>
```

`Authorization` 仅在设备配置了 `read_token` 时发送。返回 HTTP 200、UTF-8 JSON；建议不压缩，正文不超过 24 KB。默认每 60 秒请求一次，失败后按 5、10、20、40、80、160、300 秒等待重试，此后保持每 5 分钟重试一次（从失败或超时结束时计时）；成功后恢复配置的正常刷新间隔（默认 60 秒），并重置失败计数。10 秒网络超时，15 秒应用兜底超时。只读 token 不应具备修改服务数据的权限。

最小响应：

```json
{
  "schema_version": 1,
  "generated_at": 1792659600,
  "stale_after_seconds": 900,
  "subscriptions": [],
  "messages": [],
  "weather": null
}
```

所有时间均为 **Unix 秒**，不是毫秒；`generated_at` 应为本次响应生成时间。每个数据源的 `updated_at` 是真正采集时间，不能随着响应伪更新。各层对象的未知字段均忽略；`*_utc` 调试文本不参与解析或时间判断。

| 字段 | 内容 |
|---|---|
| `schema_version` | 必填，固定 `1` |
| `generated_at` | 必填，响应生成时间 |
| `stale_after_seconds` | 可选，数据有效期，默认 900 秒，范围 30–86400 |
| `demo` | 可选，`true` 显示醒目的“演示”标识；生产数据设 `false` 或省略 |
| `subscriptions` | 必填数组，主页显示前 3 项，按服务端数组顺序显示，不重新按 `order` 排序 |
| `messages` | 必填数组，最多 12 条，在同一个消息页依次展示；`[]` 时只显示主页 |
| `weather` | 对象或 `null`；融合在主页，不设独立天气页 |

订阅项：

```json
{
  "id": "claude",
  "name": "Claude",
  "plan": "Max",
  "source": "official",
  "updated_at": 1792659540,
  "windows": [
    {"label": "5小时", "used_percent": 62, "reset_at": 1792666800},
    {"label": "7天", "used_percent": 41, "reset_at": 1792832400}
  ]
}
```

- `id` 是稳定标识，内置 Claude / Codex / Grok 配色；也支持其他订阅。
- `windows[1]` 为主窗口，`windows[2]` 为次窗口；上键切换，最多 2 个窗口。Claude 有两个窗口时，当前窗口显示为大面积填充，另一个窗口显示为卡片底部 4px 半透明细条及标签 / 剩余百分比，上键交换大小窗口。Claude 双窗口时省略重复的“官方”来源字样，保留窗口和重置时间；下方两段文字固定显示，过长时省略，不滚动。按数组顺序选取，默认第一项为大窗口，第二项为细条；不根据标签文字猜测窗口。只有一个窗口的订阅始终显示它；所有订阅都只有一个窗口时，上键不切换。`label` 仅作显示，支持任意 N 天 / 小时 / 分钟及“本期”等文字。
- `used_percent` 是 **已用百分比**。显示端转换成 **剩余百分比** `floor(max(0, 100 - used_percent))`。支持小数：33.5 显示剩余 66%，99.6 显示剩余 0%；例如 62 显示剩余 38%。`0` 是确实未用，显示剩余 100%；未知用 `null` 或省略，显示 `--`。这不是精确剩余 token 数。
- 剩余比例 `< 20%` 为警告黄，`< 5%` 为警戒红；恰好 20% 使用正常配色，恰好 5% 为黄色。卡片填充始终半透明，从上向下渐淡；0% 无填充、数字为红色，未知值仍显示 `--`。
- `source` 可为 `official`、`manual`、`estimated`、`unknown`，对应官方、手动、估算、待接入。这是接口的来源声明，设备不独立验证。
- 缺失或过期的 `updated_at`、已到期的 `reset_at` 会标记过期 / 待刷新，不擅自将用量归零。
- `plan`、`note` 为预留说明字段；当前小屏总览只显示名称、百分比、窗口、来源和重置倒计时。

提醒项：

```json
{"id":"reminder-1","title":"记得出门","text":"带上钥匙。\n记得拿雨伞。","priority":"high","due_at":1792661400,"updated_at":1792659600,"expires_at":1792663200,"sender":"bot"}
```

`text` 必填，空白内容会忽略；`title` 保留兼容解析，但不显示，`priority` 为 `normal` 或 `high`；`due_at` 可省略。`due_at` 只用于到期提示，不删除提醒；可选 `expires_at` 才是消息失效时间。显示端每秒以及切换前过滤 `expires_at <= 当前时间` 的消息，断网和暂停轮播时仍生效。成功响应以 `generated_at + 收到响应后的本地单调时钟增量` 判断时间，避免设备 RTC 偏差；冷启动只有缓存且时钟不可信时，暂不显示带过期时间的消息。缓存内容不因本地过滤而重写。

可选 `id` 用于保持当前轮播位置，`updated_at` 表示消息更新时间，同 id 更新只刷新改变的内容；`sender == "bot"` 显示 `Bot`。按接口数组顺序在消息页轮换。消息页不显示标题，正文最多 180 字，保留 `\n` / CRLF 换行，22px 中文字体自动换行，每段最多 7 行。长正文在同一个消息视图分段展示。没有有效消息时（包括 `[]`）立即关闭消息页并保持主页。

天气项：

```json
{
  "city":"深圳","condition":"多云","temperature_c":27.8,"feels_like_c":29.2,
  "low_c":23,"high_c":29,"humidity_percent":68,"rain_percent":20,"wind_kmh":8,"pressure_hpa":1011.4,
  "condition_now":"晴","forecast_hours":12,
  "source":"你的天气服务","updated_at":1792659300
}
```

主页显示城市、预报天气、当前温度、最低 / 最高温、湿度和气压。“已过期”等天气状态单独放在预报天气上方，不拼接到天气文字。城市、湿度、气压在中间一列统一居中对齐，湿度（如 `51%`）显示在城市下方；下沿依次显示温度范围（`23–32°C`）、气压（`1011 hPa`）和预报天气。不显示“湿度”“气压”文字。温度单位 °C，湿度 %，气压 hPa；数字字段支持小数，显示时取整，缺失数字使用 `null`。`pressure_hpa` 为可选字段，旧响应缺失时显示“-- hPa”。没有温度时显示天气待同步。`feels_like_c`、`rain_percent`、`wind_kmh`、`source` 是兼容预留字段，当前两页布局不展示这些详情。

`condition` 是未来 `forecast_hours` 小时内最显著的天气（当前为 12 小时），`condition_now` 是当前实况；空间有限，主页显示 `condition`。`rain_percent` 是预报时段内的最高降水概率。背景按优先级匹配：包含“雨”或“冰雹”（包括雷阵雨）→ 雨；包含“雪” → 雪；“云” → 多云，“阴” / “雾” → 阴云；“晴”且不含云 → 晴；未知 → 阴云。晴间多云使用云背景。可选 `is_day: false` 在晴天使用晴夜图片，省略时不猜测昼夜。

401 / 403 显示鉴权失败，其余非 200、错误 JSON、未知版本均保留上一份有效缓存并提示。`[]` 表示当前无项目；不要返回字符串 `"[]"`。

完整示例见 [examples/display.json](examples/display.json)。示例的所有数字都是虚构数据，`demo=true`。

向后兼容扩展示例及验收数据：[tests/fixtures/display-v1-extended.json](tests/fixtures/display-v1-extended.json)。

设备无 Wi-Fi IP 时，应用按同一退避节奏调用固件重连接口，使用已保存的热点配置，不改写 SSID / 密码。Wi-Fi 恢复获得 IP 后立即请求数据，不等待剩余退避时间。Wi-Fi 正常而 HTTP 接口失败时只重试 HTTP；401 / 403 仍显示鉴权失败并保留缓存。
