# 显示端修改建议

我的智能显示屏后端服务（`GET /v1/display`，`schema_version` 仍为 `1`）做了一些向后兼容的扩展。请根据下面的变更检查并修改显示端代码。原有字段的含义、类型和显示逻辑都没有变，不要改动已有的鉴权、轮询、退避、缓存和 401 / 403 处理逻辑。

## 一、必须确认的兼容性（不满足会导致解析失败）

1. JSON 解析必须忽略不认识的字段。根对象、订阅项、窗口、消息、天气对象都新增了字段（见第二节），不能因为多出字段就判定为"错误 JSON"或"未知版本"。
2. 数字字段可能是小数，不一定是整数：
   - `windows[].used_percent`，例如 `33.5`
   - weather 的 `temperature_c` / `feels_like_c` / `low_c` / `high_c` / `wind_kmh`，例如 `28.5`、`10.5`

   按浮点数解析，显示时再取整（剩余百分比建议 `floor(max(0, 100 - used_percent))`，避免把 99.6% 的已用显示成剩余 1%）。
3. 订阅的 `windows` 可能只有 1 个窗口（目前 Codex 和 Grok 都只有"7天"）。这种情况下上键不应切换到不存在的次窗口，也不要显示空窗口。
4. 窗口标签目前可能是："5小时"、"7天"、"本期"，以后也可能出现"N天" / "N小时" / "N分钟"。标签只用于显示，不要写死判断。
5. 响应正文仍保证不超过 24 KB。

## 二、新增字段

所有时间仍以 Unix 秒字段为准。新增的 `*_utc` 字段只用于调试，客户端不需要解析。

**根对象**

| 字段 | 说明 |
|---|---|
| `generated_at_utc` | `"2026-10-22T10:23:00Z"`，`generated_at` 的 UTC 文本 |

**订阅项 `subscriptions[]`**

| 字段 | 说明 |
|---|---|
| `updated_at_utc` | `updated_at` 的 UTC 文本 |
| `order` | 可选整数，服务端已按它排好序，客户端按数组顺序显示即可 |
| `windows[].reset_at_utc` | `reset_at` 的 UTC 文本 |

**消息 `messages[]`**

| 字段 | 说明 |
|---|---|
| `id` | 稳定标识，同一 id 再次出现表示同一条消息被更新了 |
| `updated_at` | 服务端收到或更新这条消息的时间（Unix 秒） |
| `expires_at` | 可选，过期时间（Unix 秒） |
| `sender` | 可选，`"bot"` 表示由机器人推送；没有这个字段表示是我手动添加的 |
| `due_at_utc` / `expires_at_utc` / `updated_at_utc` | 对应时间的 UTC 文本 |

**天气 `weather`**

| 字段 | 说明 |
|---|---|
| `condition` | **含义变更**：现在是"未来 `forecast_hours` 小时内最显著的天气"（预报），不再是当前实况 |
| `condition_now` | 当前实况天气 |
| `forecast_hours` | `condition` 依据的预报时长，目前是 12 |
| `rain_percent` | **含义变更**：未来 12 小时内的最高降水概率 |
| `low_c` / `high_c` | 今日预报的最低 / 最高温（不变） |
| `temperature_c` | 当前温度（不变） |
| `humidity_percent` | 当前相对湿度 %（原有字段，含义不变，之前终端未显示） |
| `pressure_hpa` | **新增**：当前海平面气压，单位 hPa，如 `1011.3`；缺失时为 `null` |
| `updated_at_utc` | `updated_at` 的 UTC 文本 |

## 三、建议修改

1. **本地也按 `expires_at` 过滤消息（重要）。**
   服务端只在生成响应时剔除过期消息。但网络失败时客户端会一直显示上一份缓存，缓存里的消息可能早已过期。
   建议：每次轮播消息前，跳过 `expires_at` 存在且 `<=` 当前时间的消息；过滤后一条都不剩时，按原规则关闭消息页、回到主页。
   设备时间不可靠时，可以用 `(expires_at - generated_at)` 加上收到响应时的本地单调时钟来判断。

2. **天气背景映射要覆盖所有可能的天气文字。** `condition` 的取值范围是：

   > 晴、晴间多云、多云、阴、雾、雾凇、小毛毛雨、毛毛雨、大毛毛雨、冻毛毛雨、小雨、中雨、大雨、冻雨、小雪、中雪、大雪、雪粒、阵雨、中阵雨、强阵雨、阵雪、强阵雪、雷阵雨、雷阵雨伴冰雹、强雷阵雨伴冰雹、未知

   建议按以下优先级判断：

   | 条件 | 背景 |
   |---|---|
   | 包含"雨"或"冰雹" | 雨 |
   | 包含"雪" | 雨（没有雪背景时）或雪 |
   | 包含"云"、"阴"、"雾" | 云 |
   | 以"晴"开头且不含"云" | 晴 |
   | 其他（含"未知"） | 云 |

   "晴间多云"按上面的规则会归为云。如果你希望它显示晴，就把"以'晴'开头"这条判断放到"云"之前。

3. **在主页显示湿度和气压：** 在天气区域的温度下方加一行，如"湿度 51%  气压 1011hPa"。气压四舍五入到整数，湿度取整。某项为 `null` 时显示 `--`；两项都为 `null` 时整行不显示。屏幕太窄时，优先保留湿度。

4. **天气文案（可选）：** 主页空间允许的话，显示为"现在{condition_now}，预计{condition}"。两者相同或 `condition_now` 缺失时，只显示 `condition`。空间不够就保持只显示 `condition`，它本身已经是预报。

5. **机器人消息标识（可选）：** `sender == "bot"` 的消息，在标题旁显示一个小标记（如"🤖"或"Bot"），方便区分自动推送和我手动添加的提醒。没有 `sender` 字段时不显示。

6. **消息更新检测（可选）：** 用 `id` + `updated_at` 判断消息是否变化。轮播中的某条消息内容被更新时，可以只刷新这一条，不必重置整个轮播。

7. **轮询节奏：** 保持默认 60 秒即可。服务端会根据轮询频率自动调整后台采集间隔，客户端不需要改动。
   可选优化：设备长时间离线或休眠后，第一次请求拿到的订阅数据可能已过期（`updated_at` 早于 `generated_at - stale_after_seconds`）。服务端收到这次请求后会立即重新采集，所以这时可以在 15–20 秒后额外请求一次，不要等满 60 秒；这次额外请求不计入失败退避。

## 四、验收用的真实响应示例

```json
{"schema_version":1,"generated_at":1792664580,"generated_at_utc":"2026-10-22T10:23:00Z","stale_after_seconds":900,
 "subscriptions":[
  {"id":"claude","name":"Claude","source":"official","updated_at":1792664565,"updated_at_utc":"2026-10-22T10:22:45Z",
   "windows":[{"label":"5小时","used_percent":40,"reset_at":1792669799,"reset_at_utc":"2026-10-22T11:49:59Z"},
              {"label":"7天","used_percent":17,"reset_at":1792670399,"reset_at_utc":"2026-10-22T11:59:59Z"}],"plan":"Max"},
  {"id":"codex","name":"Codex","source":"official","updated_at":1792664568,"updated_at_utc":"2026-10-22T10:22:48Z",
   "windows":[{"label":"7天","used_percent":25,"reset_at":1793199840,"reset_at_utc":"2026-10-28T15:04:00Z"}],"plan":"Pro"}],
 "messages":[
  {"id":"sample","title":"示例","text":"示例消息","priority":"normal","updated_at":1792664580,"updated_at_utc":"2026-10-22T10:23:00Z",
   "due_at":1792670000,"due_at_utc":"2026-10-22T11:53:20Z","expires_at":1792664640,"expires_at_utc":"2026-10-22T10:24:00Z","sender":"bot"}],
 "weather":{"city":"深圳","condition":"晴间多云","temperature_c":28.5,"feels_like_c":29.5,"low_c":23.2,"high_c":32,
  "humidity_percent":51,"rain_percent":0,"wind_kmh":10.5,"pressure_hpa":1011.3,"source":"Open-Meteo","updated_at":1792664100,
  "updated_at_utc":"2026-10-22T10:15:00Z","condition_now":"晴","forecast_hours":12}}
```

请用以下用例验证：

- [ ] 上面的响应能正常解析并显示。
- [ ] Codex 只有 1 个窗口时，按上键不出错。
- [ ] `used_percent` 为 `33.5` 时，显示剩余 66%。
- [ ] 断网后，示例消息在 `expires_at`（UTC 10:24:00）之后从轮播中消失；它是唯一一条消息，所以消失后消息页关闭。
- [ ] 主页显示"湿度 51%  气压 1011hPa"；`pressure_hpa` 为 `null` 时显示 `--`。
- [ ] `condition` 为"雷阵雨"显示雨背景，"阴"显示云背景，"晴"显示晴背景。
