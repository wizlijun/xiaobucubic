# HP 算法实现规格（Oura → PUT /v1/energy）

2026-11-25 · 依据：`docs/hp-algorithm-design.md`（算法设计）、`docs/hp-design-spec.md`（显示协议边界）、`server/` 现有代码、Oura API v2 官方 OpenAPI 1.43（当前线上版本）与 Oura 支持文档。

本文只写**已确定**的实现规则。原先待讨论的问题已在第 9 节定下。

---

## 0. 与原设计文档的差异（按官方文档修正）

| # | 原设计 | 官方事实 | 本规格的处理 |
|---|---|---|---|
| D1 | 心率每 5 分钟一个点，连续 10 分钟无样本按「未观测」处理 | 日间心率每 5 分钟测 1 分钟，**只在低运动、体温稳定时测**，最长可能 30 分钟没有读数（support: Heart Rate Graph）。运动时一般没有 `awake` 心率，除非开了 workout | 是否佩戴由 `class_5_min == '0'` 判断，是否在动由 MET 判断，心率只用来计算「静止时的压力或恢复」和「workout 的 TRIMP」。静止时心率可以沿用前值，最多 30 分钟 |
| D2 | 安静基线 HRq 取「清醒且静止时段心率中位数」 | `heartrate.source` 的取值为 `awake / workout / rest / sleep / live / session`，`awake` 只在低运动时测量 | HRq = 28 天内 `source == "awake"` 心率的中位数 |
| D3 | 小睡取「其他类型且不少于 15 分钟」 | `sleep.type` 的取值为 `deleted / sleep / long_sleep / late_nap / rest`：`sleep` 为 15 分钟至 3 小时，`long_sleep` 超过 3 小时，`rest` 是误判后被拒的记录 | 主睡眠只从 `long_sleep` 中选。HP 日内的其他睡眠段按小睡处理：`sleep`、`late_nap`，以及非主睡眠的 `long_sleep`，都要求 `total_sleep_duration >= 900`。`rest` 和 `deleted` 忽略 |
| D4 | 准备度只读 `daily_readiness` | `sleep` 记录里也内嵌了 `readiness.score` | 准备度先读 `daily_readiness.score`，为空时读主睡眠的 `readiness.score`，两者都为空才走备用锚点 |
| D5 | 夜间通过「过了习惯入睡时刻且没有新的清醒样本」判断入睡 | 心率在后台定期同步，入睡后会出现 `source == "sleep"` 的行；睡眠记录**只在打开 App 时才同步** | 入睡时刻优先取 `sleep` 心率；没有时再用习惯入睡时刻兜底（见 4.5） |
| D6 | 可选用 Oura webhook 实时触发 | webhook 没有 `heartrate` 类型，只发通知不带数据，并要求公网 HTTPS 回调；frp 出口是明文 HTTP | v1 不做 webhook，只做 10 分钟轮询 |
| D7 | 复用 `~/git/testouraring/getouraring.py` 与 `.oura_token.json` | 这台机器上没有该仓库、令牌和 `~/myhealthdata` | 在 `server/` 内新写 OAuth 与取数模块（只用标准库），见 Q1 |
| D8 | `stress_high` 单位按分钟 | schema 写的是秒，tag 文字写的是分钟，二者矛盾 | 只在校准报告中使用。按秒解析；若 28 天中位数小于 1440，判为分钟，并在报告中标注 |

## 1. 目标与非目标

- **目标**：一个常驻进程每 10 分钟从 Oura 拉一次数据，用「晨间定锚 + 日间负荷 + 睡眠回血」无状态重放出 HP，写入 `PUT /v1/energy`。显示服务和三端客户端零改动。
- **非目标**：Oura webhook；服务端 Collector 调度；历史曲线；自动拟合参数（v1 只出校准报告，参数人工调整）；任何非 Oura 数据源。
- **反目标**：不能把估算值伪装成实测。算不出来时必须写 `null`。也不能让 HP 进程影响 AI 订阅采集器的「终端活跃」判定（见 Q3）。

## 2. 模块与文件

全部放在 `server/`，只用 Python 标准库，与现有采集脚本一致。

| 文件 | 职责 | 是否有 IO |
|---|---|---|
| `oura_auth.py` | OAuth2 授权码 + PKCE 登录；令牌持久化与自动刷新 | 文件、网络 |
| `oura_client.py` | Oura v2 取数：分页、日期余量、429 处理 | 网络 |
| `hp_model.py` | 纯函数：基线、锚点、5 分钟网格、重放、夜间预估、trend、status、note | 无 |
| `hp_usage.py` | CLI 与常驻循环：取数 → 模型 → 生成 payload → 推送 | 有 |
| `oura.env.example` | `OURA_CLIENT_ID=`、`OURA_CLIENT_SECRET=`、`OURA_REDIRECT_URI=http://127.0.0.1:8765/callback` 模板 | — |
| `test_hp_model.py`、`test_oura_client.py`、`test_oura_auth.py`、`test_hp_usage.py` | 单元测试，`python3 -m unittest` | — |

本地文件（权限 0600，不进版本库）：

- `server/oura.env`：已被 `*.env` 规则忽略。
- `server/oura_token.json`、`server/hp_cache.json`：在 `.gitignore` 中新增这两项。

推送复用 `display_push.push(url, item, path="/v1/energy")` 和 `display_push.write_token()`。

## 3. Oura 接入

### 3.1 授权（`oura_auth.py`）

- `python3 oura_auth.py login`：
  1. 生成 `state` 和 PKCE `S256` challenge，打印授权 URL：`https://cloud.ouraring.com/oauth/authorize?response_type=code&client_id=…&redirect_uri=…&scope=personal daily heartrate workout&state=…&code_challenge=…&code_challenge_method=S256`。
  2. 在 `127.0.0.1:8765` 上临时监听 `/callback`，校验 `state`。
  3. 拿到 code 后 POST `https://api.ouraring.com/oauth/token`（form-urlencoded，带 `code_verifier`）。
  4. 收到令牌后写入 `oura_token.json`：`{access_token, refresh_token, expires_at, scope}`。其中 `expires_at = now + expires_in`。
- **刷新**：在 `expires_at - 300 <= now` 或请求返回 401 时触发。
  - refresh token **只能用一次**，所以「刷新 → 写新令牌」必须在 `fcntl` 文件锁内完成，用临时文件加 `os.replace` 原子落盘，**新令牌写入成功后才能使用**（做法与 `grok_auth.py` 一致）。
  - 刷新返回 `invalid_grant` 时抛 `AuthRequired`。
- **请求头**：所有请求都带 `User-Agent: xiaobucubic-hp/1`，否则可能被拒为 403；另带 `Authorization: Bearer …`。

### 3.2 取数（`oura_client.py`）

接口：`get(collection, **params) -> list[dict]`。

- 自动沿 `next_token` 翻页。
- 日期参数用 `urlencode` 编码，保证 `+` 变成 `%2B`。
- 日期区间是否包含端点，官方未说明：查询时前后各多取 1 天，再在本地按 `day` 或时间戳过滤。

每轮请求的数据，D 为本地今天（时区取系统时区，即 Asia/Shanghai）：

| 集合 | 参数 | 用途 |
|---|---|---|
| `sleep` | `start_date=D-30`、`end_date=D+1` | 锚点、小睡，以及睡眠类基线 |
| `daily_readiness` | `D-30`～`D+1` | 准备度，以及常态锚点 Ā |
| `daily_activity` | `D-1`～`D+1` | `met`、`class_5_min` |
| `workout` | `D-1`～`D+1` | 运动时段与强度 |
| `daily_stress` | 只在 `--report` 中请求，`D-30`～`D` | 校准对照 |
| `heartrate` | `start_datetime = D-1 00:00` 本地时间，`end_datetime = now` | 日间心率与入睡判定 |
| `personal_info` | 进程启动时取 1 次 | `age`、`biological_sex` |

- **心率基线**：每个本地日只算一次，取 `D-28 00:00` 到 `D 00:00` 的 `heartrate`，结果缓存到 `hp_cache.json`，内容为 `{day, hr_quiet, valid_days}`。
- **请求量**：每轮约 6 次请求，加上每天 1 次基线批量请求，远低于 5000 次 / 5 分钟的限额。
- **错误处理**：
  - 429：读 `Retry-After`，本轮放弃。
  - 网络错误或 5xx：本轮放弃，不推送。服务端会在 `stale_after_seconds` 后把卡片显示为灰色「已过期」，语义正好是「推送链路断了」。
  - `AuthRequired`：推送 `level_percent: null`、`status: "待授权"`。

## 4. 模型（`hp_model.py`）

### 4.1 输入与时间

- 统一换算成 Unix 秒。Oura 的时间都是带时区偏移的 ISO 8601，`heartrate` 另有 `timestamp_unix`（毫秒），优先用它。
- **网格**：5 分钟一格，与本地时钟的 :00、:05 … 对齐。第 i 格覆盖 `[t_i, t_i + 300)`。
- `met` 按 `timestamp + k × interval` 展开到分钟，一格内取非 null 值的平均。
- `class_5_min` 的第 k 个字符对应 `timestamp + 300k`，`timestamp` 是该活动日的 04:00。

### 4.2 选定 HP 日与锚点

1. **主睡眠**：对每个 `day`，从 `type == "long_sleep"` 的记录中取 `total_sleep_duration` 最大的一条。
2. **当前锚点**：从 `{D, D-1}` 中取有主睡眠、且 `bedtime_end <= now` 的最大 `day`。
   - 选中 `D`：正常日。夜间判定见 4.5。
   - 选中 `D-1`：昨天的 HP 日还没结束，按 4.5 判定当前处于日间、夜间还是醒后待同步。
   - `D` 和 `D-1` 都没有主睡眠：输出 `null`，status 为「待同步」。
3. **锚点时刻**：`t0 = 主睡眠.bedtime_end`。
4. **锚点值**：按以下顺序取第一个可用的。
   1. 准备度 R：先取 `daily_readiness[day].score`，为空再取 `主睡眠.readiness.score`。`HP0 = clamp(40 + 1.5(R-50), 20, 100)`。
   2. 都没有：用设计文档的备用锚点公式 `clamp(100·d^0.8 + 8·z_HRV − 8·z_RHR, 20, 100)`。

### 4.3 个人基线

- **有效日**：`[day-28, day-1]` 中有主睡眠的日子。
- **RHR**：有效日主睡眠 `lowest_heart_rate` 的中位数。
- **HRq**：同一窗口内 `source == "awake"` 心率的中位数。有效日不足 14 天时，取 `1.25 × RHR`。
- **夜间 HRV**：`ln(average_hrv)` 的中位数与 MAD，忽略 null。z 分数 = (x − 中位数) / (1.4826 × MAD)，截断到 ±2.5；MAD 为 0 时 z 记 0。
- **作息与常态锚点**：
  - 习惯入睡时刻、习惯起床时刻：主睡眠 `bedtime_start` / `bedtime_end` 的本地时刻中位数，按跨午夜的环形时间处理。
  - 习惯睡眠时长 T̄：`total_sleep_duration` 的中位数。
  - 睡眠需求：`total_sleep_duration` 的 P75，限制在 420–540 分钟。
  - 常态锚点 Ā：有效日中**有准备度**的那些天，按 4.2 准备度公式算出锚点，取中位数。一个都没有时，Ā = 当日 HP0。
  - 有效日为 0 时的默认值：习惯入睡 23:30，习惯起床 07:30，T̄ = 7.5h，睡眠需求 480 分钟。
- **最大心率**：HRmax = `208 − 0.7 × age`。`age` 为 null 时取 `--age` 参数；两者都没有时 HRmax 记为不可用（影响见 4.4 第 3 步）。
- **TRIMP 权重**：`biological_sex` 转小写后等于 `"female"` 时用 0.86 / 1.67，否则用 0.64 / 1.92。
- **基线不足**：有效日少于 14 天时，note 进入「校准中」候选。基线全部缺失（0 个有效日）时，RHR 和 HRq 无法计算：运动只走 MET 公式，静止格按「未观测」推进。

### 4.4 每格分类与速率（单位：HP/小时，b 为基础消耗）

从 `t0` 到 `now` 的每一格，按以下顺序判定，命中即停：

1. **小睡**：格子与某段小睡重叠 → 速率为 0。小睡的范围见 D3，时段为 `[bedtime_start, bedtime_end)`，且 `bedtime_start ≥ t0`。在小睡结束的那一格做回血：`hp += max(0, A − hp) × (1 − e^(−T/4.2))`，其中 T 是该小睡 `total_sleep_duration` 的小时数，A 是当日锚点。
2. **超出数据边界**：格子晚于数据边界 → **未观测**，速率 −(b + exp_load)。数据边界 = max(最后一行心率的时间, 最后一个非 null MET 分钟)。
3. **运动**：格子与 `workout` 时段重叠，或格内有 `source == "workout"` 的心率，或格内 MET 均值 ≥ 2.0。按以下顺序取第一个可用的公式：
   1. 格内有心率且 HRmax 可用：TRIMP 公式（同设计文档）。
   2. 有 MET：−(b + 1.5 × max(0, MET − 1.5))。
   3. 只有 workout 强度：用 `intensity` 映射 MET，easy 为 3、moderate 为 5、hard 为 8，再代入上一条公式。
4. **未佩戴**：`class_5_min` 对应字符为 `'0'` → 未观测。
5. **静止且有心率**：用格内 `source ∈ {awake, rest, live, session}` 的心率均值。格内没有时，沿用 30 分钟内（最多 6 格）最后一个这类心率，对应官方「最长 30 分钟没有读数」的说法。之后按设计文档的规则计算：
   - e = (HR − HRq) / HRq。
   - e ≤ −0.05：静息恢复，速率 −b + 2.0。
   - 否则：压力消耗，速率 −(b + min(8, 20 × max(0, e − 0.08)))。
6. **其余情况**：静止但心率不可用 → 未观测。

- 每一格：`hp = clamp(hp + rate × 5/60, 0, 100)`。只重放已经结束的格子（`t_i + 300 ≤ now`），所以数值最多滞后 5 分钟。
- 默认参数：b = 2.0、exp_load = 0.8。运行中的进程只用参数里的值。`--report` 会打印建议的 exp_load，但不会自动生效，需要人工写进 `--params`，这与「v1 不自动拟合」一致。
- 每一格都记录 `kind`（`nap / unobserved / exercise / offwrist / rest / stress / still`）与 `rate`，供 note、trend 和 `--explain` 使用。

### 4.5 夜间模式

当前锚点日之后还没有新的主睡眠时，按本节把当前 HP 日分成三种状态：**日间**、**夜间**、**醒后待同步**。

本节中「清醒心率」指 `source ∈ {awake, workout, live, rest, session}` 的心率行，「睡眠心率」指 `source == "sleep"` 的行。

**入睡时刻 t_bed**：只在 t0 之后、且晚于锚点当天（t0 所在本地日期）18:00 的时段里找，按以下顺序取第一个成立的。

1. 存在至少 2 行睡眠心率，且相邻两行间隔不超过 30 分钟。t_bed 取这段睡眠心率的第一行；如果有多段，取最早的一段**非小憩**段。
   - 一段睡眠心率算**小憩**（比如傍晚在沙发上打盹），当且仅当同时满足：其后存在已确认的醒来（用下面 t_wake 的同一判定：某行清醒心率 a，`(a, a + 30 分钟]` 内没有睡眠心率，且 `now ≥ a + 30 分钟`），并且这段从第一行到最后一行的跨度小于 3 小时。
   - 小憩段跳过，继续在更晚的段里找 t_bed。小憩段内的格子不需要特殊处理。
   - 第 2 条的习惯入睡时刻兜底，只在没有任何非小憩段时才用。
2. `now ≥ 习惯入睡时刻 + 30 分钟`，且最后一行清醒心率早于 `now − 30 分钟`。t_bed = 最后一行清醒心率的时间 + 5 分钟。这条用于睡眠心率还没同步上来的情况。

两条都不成立时，处于**日间**状态，按 4.4 推进。

**醒来时刻 t_wake**：在 t_bed 之后，取第一行满足以下两条的清醒心率 a，t_wake = a 的时间。

- `(a, a + 30 分钟]` 内没有睡眠心率；
- `now ≥ a + 30 分钟`。

起夜这类短暂醒来，30 分钟内又会出现睡眠心率，所以不算醒来。如果睡眠心率还没同步，第二天会被重放自动纠正。

**三种状态的输出**：

| 状态 | 条件 | HP | trend | note |
|---|---|---|---|---|
| 夜间 | 有 t_bed，没有 t_wake | `sleep_estimate(HP_bed, (now − t_bed)/3600, Ā, T̄)` | `charging` | 睡眠预估 |
| 醒后待同步 | 有 t_wake，且 `now < t_wake + 2h` | 冻结为 `sleep_estimate(HP_bed, (t_wake − t_bed)/3600, Ā, T̄)` | `steady` | 睡眠预估 |
| 醒后超时 | 有 t_wake，且 `now ≥ t_wake + 2h` | `null` | 省略 | 无，status 为「待同步」（Q2） |

- HP_bed 为从 t0 重放到 t_bed 的结果。t_bed 之后的格子不进入日间重放，所以睡眠心率不会被当成「未观测」。
- 一直睡、没有醒来的情况，夜间状态会持续下去，优先于 Q2 的 null 规则。此时 sleep_estimate 最多回到 Ā。
- **退出**：新一天的主睡眠同步后，4.2 切到新锚点，三种状态一并结束。
- **兜底**：日间状态下，如果 `now ≥ 习惯起床时刻 + 2h`，且 t0 已经超过 20 小时，说明整夜既没有睡眠心率也没有新的主睡眠，直接输出 null「待同步」。

### 4.6 trend

- 正常日：取最近 3 格（含未观测格）rate 的均值。≥ +2.5 为 `charging`，≤ −2.5 为 `draining`，其余为 `steady`。
- 夜间和醒后待同步：见 4.5 的表。
- 输出 null 时省略 trend。

### 4.7 status 与 note

- **status**：按设计文档的分数段表取词，用的是**四舍五入后**的整数 level。null 时为「待同步」，未授权时为「待授权」。
- **note**：按以下顺序取第一个命中的。
  1. 「睡眠预估」：处于夜间或醒后待同步。这两种状态下不再判断下面各条，「未同步」也不显示，因为睡眠预估不依赖实时数据。
  2. 「{h}h未同步」：只在日间判断。h = floor((now − 最后一行清醒心率) / 3600)，在 3 ≤ h < 8 时命中。
  3. 「准备度{R}」：`now − t0 < 3600`，且锚点来自准备度。
  4. 「运动中」：最近 3 格 `exercise` 的平均消耗（不含 b）≥ 6。
  5. 「生理压力高」：最近 3 格都是 `stress`，且平均压力消耗 ≥ 3。
  6. 「小憩回血」或「静息恢复」：最近 3 格内刚结束一次小睡，或最近一格是 `rest`。
  7. 「建议休息」：level < 20。
  8. 「校准中」：有效日少于 14 天。
- **长度检查**：拼装结果「{status} · {note}」不超过 16 个字符。最长的组合是 2 + 3 + 5 = 10，测试中逐条断言。

### 4.8 输出为 null 的情形

| 情形 | 判定 |
|---|---|
| 没有锚点 | 见 4.2 第 2 步 |
| 日间长时间无数据 | 日间状态，且 `now − 最后一行清醒心率 ≥ 8h` |
| 醒后超时 | 见 4.5 |
| 整夜无数据 | 见 4.5 的兜底规则 |

null 时的 payload：`{"name": "HP", "level_percent": null, "status": "待同步", "source": "estimated", "updated_at": now, "stale_after_seconds": 1800}`。

## 5. 输出（payload）

```json
{"name":"HP","level_percent":55,"status":"尚可","trend":"draining","note":"生理压力高",
 "source":"estimated","updated_at":<now>,"stale_after_seconds":1800}
```

- `level_percent`：取 `round()` 后的整数。
- `source`：固定为 `estimated`。v1 没有手动输入，见 Q3。
- payload 由 `energy_usage.build_payload()` 生成，复用它的字段校验。

## 6. CLI 与运行（`hp_usage.py`）

| 命令 | 行为 |
|---|---|
| `hp_usage.py` | 计算一次，打印摘要（复用 `energy_usage.summary`） |
| `hp_usage.py --json` | 打印 payload |
| `hp_usage.py --explain` | 打印当日每格的时间、kind、心率、MET、rate 和 HP，供调试 |
| `hp_usage.py --push` | 计算一次并推送 |
| `hp_usage.py --push --follow` | 常驻运行，每 600 秒一轮，对齐到整 10 分钟。不走 `/v1/collectors` 调度，因为 energy 不在 `COLLECTORS` 中，PUT 时 `_save_collection` 会直接保存 |
| `hp_usage.py --report --days 28` | 校准报告。每天一行：锚点、来源、睡前 HP、模型压力分钟与 `stress_high`、模型恢复分钟与 `recovery_high`、触 0 和触 100 的时间占比。末行汇总中位数，并打印建议的 exp_load（只打印，不写入任何文件） |
| `--params FILE` | 用 JSON 覆盖第 7 节中的任意参数 |
| `--now ISO` | 只用于调试与测试，指定计算时刻 |

`--follow` 模式下单轮出错只记日志，下一轮照常执行，不会退出进程。

## 7. 参数（默认值，均可由 `--params` 覆盖）

`basal=2.0, k_act=0.15, k_met=1.5, k_stress=20, theta_stress=0.08, stress_cap=8, theta_rest=-0.05, rest_gain=2.0, tau_sleep=4.2, exp_load=0.8, trend_band=2.5, kappa=1.0`

其中 κ 同时乘 b、运动消耗和压力消耗，`rest_gain` 不乘。v1 的 κ 固定为 1.0，由人工根据 `--report` 的结果调整。

## 8. 测试（全部离线，使用合成 fixture）

- **模型**：
  - 复现设计文档示例日的锚点与网格，07:00–23:00 各节点 HP 与设计表格的误差不超过 ±1。若 D1 改动导致偏差，以新规则重新生成期望值，并在测试中注明。
  - 每一种 kind 的分类判定，以及分类优先级。
  - 小睡回血：从 40 起、锚点 88，睡 30 分钟后为 45。
  - 夜间两种入睡判定。
  - 起夜：03:00 有一行清醒心率，30 分钟内又有睡眠心率，仍处于夜间。
  - 07:00 醒来、App 还没同步：先是醒后待同步，数值冻结；09:00 之后变成 null；补到主睡眠后切到新锚点。
  - 睡过习惯起床时刻 + 2h：仍处于夜间。
  - 4.2 选日的三个分支。
  - 每一条 null 规则。
  - note 优先级，以及所有 status × note 组合的长度不超过 16。
- **取数**：mock `urlopen`，覆盖分页、`%2B` 编码、日期余量过滤、429。
- **授权**：刷新后先落盘再使用；并发刷新时只刷新一次；`invalid_grant` 时抛 `AuthRequired`。
- **端到端**：起一个本地 `display_server`（参照 `test_energy.py`），`--push` 之后 `GET /v1/display` 的 `subscriptions[0]` 符合预期。

接入真实账号后另做一次**数据核实**，不进入单测。结果写进本文件附录：

1. 7 天内相邻心率行的时间间隔分布，用来确认 3h 和 8h 阈值是否合适。
2. `daily_activity.met` 在白天是否随同步更新。
3. `stress_high` 的单位。

## 9. 已定决策（2026-11-25 确认）

- **Q1 Oura 授权与运行机器**：原来的 `getouraring.py`、令牌和 `~/myhealthdata` 都不在这台 Mac 上。**决定**：HP 进程跑在这台 Mac（显示服务所在机器），重新走 OAuth。用户需要在 cloud.ouraring.com 的 OAuth 应用里登记回调地址 `http://127.0.0.1:8765/callback`，并把 client id 和 secret 填进 `server/oura.env`。拿到凭据之前，实现和全部离线测试照常进行，只有第 8 节的「数据核实」要等授权。
- **Q2 早晨还没打开 Oura App 时显示什么**：睡眠和准备度只在打开 App 时同步，后台只同步心率和活动。**决定**：与原设计一致，习惯起床时刻 + 2h 之后仍没有当天主睡眠，就显示 null「待同步」，不先用常态锚点推进。用心率判断出醒来时刻后，规则改为「醒来 2h 后变 null」，醒来后的 2 小时内显示冻结的睡眠预估（见 4.5）。
- **Q3 手动打卡的入口**：服务端 energy 只有一个槽位，手机端的 `PUT` 会在 10 分钟内被 HP 进程覆盖。HP 进程也不能靠 `GET /v1/display` 回读打卡，因为写 token 读 display 会调用 `scheduler.on_request()`，让 AI 采集器一直认为有终端在看。**决定**：**不做打卡**，完全无感。
  - HP 全部来自 Oura 数据，用户不需要任何输入。HP 也从不主动提醒，没有通知、消息或推送，只在已有卡片上更新数字和文案。
  - 没有 `--checkin`，不存打卡记录，`source` 永远是 `estimated`，服务端不改。
  - `energy_usage.py` 仍能手动写入，用于调试，但写入的值下一轮会被 HP 进程覆盖。这一点要写进 README。

## 10. 方案比较

算法结构沿用 `docs/hp-algorithm-design.md` 的方案比较，选定 C「晨间定锚 + 日间负荷模型」。另外两个方案的问题：A 直接用准备度当 HP，一天只变一次，进度条失去意义；B 纯心率积分，误差会逐日累积。

工程上考虑过三种接入方式：

| 方式 | 取舍 | 结论 |
|---|---|---|
| 独立常驻进程，10 分钟一轮推送 | 与令牌放在同一台机器；不受「无终端时暂停」影响；进程就是唯一的写入方 | **选定** |
| 接入服务端 Collector 调度 | 没有终端在看时会暂停，恢复后第一屏显示的是旧值；还要改 `COLLECTORS` 与调度逻辑 | 不选。因为每轮都从头重放、不存状态，以后要改只需换一个触发方式 |
| Oura webhook 触发 | 没有 `heartrate` 类型，需要公网 HTTPS 回调 | v1 不做 |
