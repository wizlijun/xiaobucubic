# HP 指标与周限算法（现行实现）

2026-11-26 · 对应代码：`server/hp_model.py`（日 HP）、`server/hp_weekly.py`（周限）、`server/hp_usage.py`（采集与组装）、`server/display_server.py`（投影为卡片）。

本文只描述**当前代码实际怎么算**，参数值均取自代码默认值（`DEFAULT_PARAMS`，可用 `hp_usage.py --params FILE` 覆盖）。设计动机与取舍见 `docs/hp-algorithm-design.md` 和 `docs/superpowers/specs/2026-11-25-hp-weekly-limit-design.md`。

---

## 两条公式（一句话版本）

后面各节把这两条展开。为了贴近代码，每条里各保留一处递推：日 HP 每 5 分钟截断到 0–100，周限账本的结余不能为负。

### 公式一：日 HP

$$
HP(t)=
\begin{cases}
\operatorname{clamp}_{[0,100]}\!\left(HP_0-\displaystyle\int_{t_0}^{t}\big(b+L(u)-G(u)\big)\,du\right) & \text{醒着}\\[2ex]
HP_{\text{bed}}+\big(\bar A-HP_{\text{bed}}\big)^{+}\cdot\min\!\left(1,\ \dfrac{1-e^{-s/\tau}}{1-e^{-H/\tau}}\right) & \text{睡着}
\end{cases}
\qquad
HP_0=\operatorname{clamp}_{[20,100]}\big(40+1.5\,(r-50)\big)
$$

| 符号 | 含义 | 值 |
|---|---|---|
| $t_0$ | 主睡眠醒来时刻 | |
| $r$ | Oura 准备度（缺失时改用睡眠、HRV、静息心率估算，见第 2 节） | |
| $b$ | 清醒基础消耗 | 2 %/h |
| $L(u)$ | 当下负荷：<br>运动 $9\,x\,a\,e^{b'x}$，$x=\frac{HR-RHR}{HR_{max}-RHR}$<br>压力 $\min\big(8,\ 20\,(e-0.08)^{+}\big)$，$e=\frac{HR-HR_{quiet}}{HR_{quiet}}$<br>无数据或未佩戴 0.8 | %/h |
| $G(u)$ | 静息（$e\le-0.05$）时为 2，正好抵消 $b$；其它时候为 0 | %/h |
| $HP_{\text{bed}}$ | 入睡时的 HP | |
| $\bar A$ | 近 28 天 $HP_0$ 的中位数 | |
| $s$ | 已睡小时数 | |
| $H$ | 习惯睡眠时长 | |
| $\tau$ | 回血时间常数 | 4.2 h |

小睡用同一个指数式一次性回血，目标值换成当天的 $HP_0$。积分在代码里按 5 分钟一格离散，每格都截断到 0–100。

### 公式二：周限

$$
W=100\cdot\operatorname{clamp}_{[0,1]}\!\left(1-\frac{B_N+E}{7}\right),
\qquad
B_d=\big(B_{d-1}+D_d-C_d\big)^{+},\quad B_0=0
$$

$$
\begin{aligned}
D_d&=(7-h_d)^{+}+0.25\,\ell_d+\frac{0.5\,(m_d-60)^{+}}{60}+0.25\,\mathbf{1}[\text{steps}_d<5000]+\mathbf{1}[\text{恢复不良}_d]+0.5\,T_d(HP<20)\\
C_d&=\big(\min(h_d,9)-7\big)^{+}+0.25\,T_d(\text{rest})\\
E&=\min\!\left(2.5,\ \frac{(150\,p-M)^{+}}{60}\right)+\frac{(Q-300)^{+}}{60}
\end{aligned}
$$

| 符号 | 含义 |
|---|---|
| $W$ | 周剩余 %，从周六 12:00 起算；＜20 黄色，＜5 红色 |
| $B_d$ | 第 $d$ 天结束时的负债结余（小时），$N$ 为本周最后一天 |
| $D_d$ / $C_d$ | 当天负债 / 还款（小时） |
| $h_d$ | 当夜睡眠小时数（主睡眠 + 同日小睡） |
| $\ell_d$ | 入睡晚于 00:00 的小时数 |
| $m_d$ | Oura 高压力分钟数 |
| 恢复不良 | $z_{HRV}\le-1$，或 $z_{RHR}\ge1$ 且静息心率比基线高 ≥3 bpm |
| $T_d(\cdot)$ | 当天处于该状态的小时数，来自公式一的 5 分钟格 |
| $M$ | 中强度当量分钟 = 中强度分钟 + 2 × 高强度分钟 |
| $Q$ | 本周高强度分钟 |
| $p$ | 周进度 = 本周已过时间 ÷ 7 天，取 0–1 |

$(x)^{+}=\max(0,x)$，$\mathbf{1}[\cdot]$ 在条件成立时为 1、否则为 0。两条公式通过 $T_d(HP<20)$ 和 $T_d(\text{rest})$ 相连：白天透支和静息的时长直接计入周负债和还款。

---

## 0. 总览

```mermaid
flowchart TD
    O["Oura API<br/>sleep · daily_readiness · heartrate<br/>daily_activity · workout · daily_stress"] --> P["① 个人基线 Profile<br/>（前 28 天）"]
    O --> A["② 起点 HP₀<br/>（今早醒来时刻）"]
    P --> A
    A --> S{"③ 昼夜状态<br/>night_state"}
    S -- "白天 day" --> R["④ 5 分钟逐格重放<br/>HP 随每格速率变化"]
    S -- "夜里 night / 刚醒 woke" --> N["⑤ 睡眠回血预估"]
    S -- "醒来超 2h 未同步<br/>woke_timeout" --> X["不显示数值（待同步）"]
    R --> L["⑥ 等级 · 状态 · 趋势 · 说明行"]
    N --> L
    R --> W["⑦ 周限账本<br/>（本周六 12:00 起）"]
    O --> W
    W --> C["⑧ 卡片<br/>第 1 条：HP　第 2 条：周限（7天）"]
    L --> C
```

---

## 1. 个人基线 Profile

取锚点日**之前 28 天**里有主睡眠（`long_sleep`，每天取时长最长的一段）的日子，`valid_days` = 天数。

```mermaid
flowchart LR
    subgraph P28["近 28 天主睡眠"]
      RHR["静息心率 RHR<br/>= median(lowest_heart_rate)<br/>MAD_RHR = median(abs(x − RHR))"]
      HRV["ln HRV 基线<br/>= median(ln average_hrv)<br/>MAD_HRV 同理"]
      BED["习惯入睡 / 醒来时刻<br/>= 环形中位数（跨午夜）"]
      HAB["习惯睡眠 H = median(总睡眠)<br/>睡眠需要 need = clamp(Q3(总睡眠), 420, 540) 分钟"]
      AM["锚点中位数 Ā<br/>= median(每天的 HP₀)"]
    end
    Q["安静心率 hr_quiet<br/>valid_days ≥ 14：前 28 天清醒心率中位数<br/>否则：1.25 × RHR"]
    M["HRmax = 208 − 0.7 × 年龄<br/>TRIMP 系数 男 a=0.64 b=1.92<br/>女 a=0.86 b=1.67"]
```

**稳健 z 分数**（基线缺失或 MAD = 0 时取 0）：

```mermaid
flowchart LR
    Z["z(x) = clamp( (x − 中位数) ÷ (1.4826 × MAD), −2.5, +2.5 )"]
```

`z_HRV` 用 `ln(average_hrv)`，`z_RHR` 用 `lowest_heart_rate`。

---

## 2. 起点 HP₀（锚点）

锚点日：今天的主睡眠已结束就用今天，否则用昨天；都没有则不显示。`t₀` = 主睡眠醒来时刻（`bedtime_end`）。

```mermaid
flowchart TD
    Start["锚点日主睡眠"] --> Q{"有 Oura 准备度 r？"}
    Q -- 有 --> R["HP₀ = clamp( 40 + 1.5 × (r − 50), 20, 100 )<br/>r=50→40　r=70→70　r=90→100"]
    Q -- 没有 --> D["d = clamp( 总睡眠 ÷ need, 0.4, 1.0 )"]
    D --> F["HP₀ = clamp( 100 × d^0.8 + 8 × z_HRV − 8 × z_RHR, 20, 100 )"]
```

---

## 3. 白天：5 分钟逐格重放

从 `t₀` 到现在，按 5 分钟一格依次累加。速率 `rate` 的单位是 **%/h**：

```mermaid
flowchart LR
    U["HP(下一格) = clamp( HP(本格) + rate × 5/60, 0, 100 )"]
```

基础消耗 `basal = 2 %/h`（× κ，κ = 1）。每格按下图**从上到下**判定类型：

```mermaid
flowchart TD
    C["一个 5 分钟格"] --> NAP{"在小睡里？<br/>（≥15 分钟的 sleep / late_nap / 非主睡眠 long_sleep）"}
    NAP -- 是 --> NAPR["nap：rate = 0<br/>小睡最后一格一次性回血：<br/>HP += max(0, HP₀ − HP) × (1 − e^(−小睡小时 ÷ 4.2))"]
    NAP -- 否 --> HZ{"晚于最后一条已同步数据？"}
    HZ -- 是 --> UNO["unobserved：rate = −(2 + 0.8) = −2.8"]
    HZ -- 否 --> MV{"在运动？<br/>workout 时段 / workout 心率 / MET ≥ 2"}
    MV -- 是 --> EX["exercise：rate = −(2 + load)<br/>load 见下方「运动负荷」"]
    MV -- 否 --> OFF{"活动类别 = 0（未佩戴）？"}
    OFF -- 是 --> OFFR["offwrist：rate = −2.8"]
    OFF -- 否 --> HR{"有静止心率？<br/>（本格没有就沿用 30 分钟内最近一格）"}
    HR -- 无 --> UNO2["unobserved：rate = −2.8"]
    HR -- 有 --> E["相对偏离 e = (HR − hr_quiet) ÷ hr_quiet"]
    E --> REST{"e ≤ −0.05？"}
    REST -- 是 --> RESTR["rest：rate = −2 + 2 = 0（不掉血）"]
    REST -- 否 --> ST["load = min( 8, 20 × max(0, e − 0.08) )<br/>load ＞ 0 → stress，否则 still<br/>rate = −(2 + load)"]
```

**运动负荷 load**（按可用数据择一）：

```mermaid
flowchart TD
    L{"有心率且有 RHR、HRmax？"} -- 是 --> T["TRIMP：x = clamp( (HR − RHR) ÷ (HRmax − RHR), 0, 1 )<br/>load = 0.15 × 60 × x × a × e^(b·x)"]
    L -- 否 --> M{"有 MET？"}
    M -- 是 --> MM["load = 1.5 × max(0, MET − 1.5)"]
    M -- 否 --> W{"有 workout 强度？"}
    W -- 是 --> WW["easy=3 · moderate=5 · hard=8 当作 MET<br/>load = 1.5 × max(0, MET − 1.5)"]
    W -- 否 --> NO["不算运动，回到静止判定"]
```

速率参考：静止 −2 %/h；心率高出安静心率 18% 时 stress 约 −4 %/h，封顶 −10 %/h；男性心率储备 50% 时 TRIMP 约 −9.5 %/h。

---

## 4. 夜间：入睡判定与睡眠回血预估

只看锚点日 18:00 之后的心率。

```mermaid
stateDiagram-v2
    [*] --> day
    day --> night: 出现睡眠段（≥2 条睡眠心率，间隔 ≤30 分钟）<br/>短于 3h 且之后确认醒来的「傍晚打盹」跳过<br/>或：过了习惯入睡 +30 分钟、清醒心率已断 30 分钟
    night --> woke: 入睡后出现清醒心率，<br/>且 30 分钟内再无睡眠心率
    woke --> woke_timeout: 醒来超过 2h<br/>（新一天主睡眠还没同步）
    woke_timeout --> [*]: 显示「待同步」
```

入睡前的 HP 记为 `HP_bed`（重放到入睡时刻）。睡眠中按指数回血，回到 Ā：

```mermaid
flowchart LR
    F["f = (1 − e^(−已睡小时 ÷ 4.2)) ÷ (1 − e^(−H ÷ 4.2))"] --> S["HP = HP_bed + max(0, Ā − HP_bed) × min(1, f)"]
```

- `H` 是习惯睡眠时长；睡满 H 就恢复到 Ā。
- `Ā` 是锚点中位数，没有时用 HP₀。
- `night` 状态的「已睡小时」算到现在，`woke` 状态算到醒来时刻。
- 说明行固定为「睡眠预估」。

---

## 5. 输出：等级、状态、趋势、说明行

```mermaid
flowchart TD
    H["HP 浮点值"] --> LV["level = ⌊HP + 0.5⌋"]
    LV --> B{"状态词"}
    B --> B1["≥85 充沛"]
    B --> B2["≥65 良好"]
    B --> B3["≥45 尚可"]
    B --> B4["≥20 偏低"]
    B --> B5["≥5 告急"]
    B --> B6["＜5 见底"]
    T["最近 3 格 rate 平均"] --> T1{"≥ +2.5 → 回血 charging<br/>≤ −2.5 → 消耗 draining<br/>其它 → 平稳 steady"}
```

**不显示数值（待同步）** 的情况：

- 白天最后一次同步距今 ≥ 8h；
- 已过习惯醒来时刻 2h，且锚点醒来已超过 20h（新一天的睡眠还没同步）；
- 醒来超过 2h（`woke_timeout`）。

**说明 note**：按优先级取第一条命中的。

```mermaid
flowchart TD
    N1{"3–8h 未同步"} -->|命中| A1["Xh未同步"]
    N1 -->|否| N2{"醒来 1h 内且有准备度"}
    N2 -->|命中| A2["准备度 r"]
    N2 -->|否| N3{"最近 3 格平均运动负荷 ≥ 6"}
    N3 -->|命中| A3["运动中"]
    N3 -->|否| N4{"最近 3 格都是 stress<br/>且平均负荷 ≥ 3"}
    N4 -->|命中| A4["生理压力高"]
    N4 -->|否| N5{"刚结束小睡"}
    N5 -->|命中| A5["小憩回血"]
    N5 -->|否| N6{"本格 rest"}
    N6 -->|命中| A6["静息恢复"]
    N6 -->|否| N7{"level ＜ 20"}
    N7 -->|命中| A7["建议休息"]
    N7 -->|否| N8{"valid_days ＜ 14"}
    N8 -->|命中| A8["校准中"]
```

**卡片说明行 line**（白天，≤16 字，用「 · 」连接，超长从末尾丢弃）：

```mermaid
flowchart TD
    S["note / 当前速率 / 距习惯入睡小时数"] --> K1{"未同步？"}
    K1 -- 是 --> L1["Xh未同步"]
    K1 -- 否 --> K2{"准备度？"}
    K2 -- 是 --> L2["准备度r · 睡X.Xh"]
    K2 -- 否 --> K3{"运动中？"}
    K3 -- 是 --> L3["心率N · 运动中"]
    K3 -- 否 --> K4{"生理压力高？"}
    K4 -- 是 --> L4["心率N · 压力X分 · 深呼吸"]
    K4 -- 否 --> K5{"回血中？（小憩 / 静息 / 速率 ≥ +2.5）"}
    K5 -- 是 --> L5["+X%/h · 回血中"]
    K5 -- 否 --> K6{"level ＜ 20？"}
    K6 -- 是 --> L6["−X%/h · 该休息了"]
    K6 -- 否 --> K7{"已过习惯入睡（4h 内）？"}
    K7 -- 是 --> L7["−X%/h · 该睡了"]
    K7 -- 否 --> K8{"速率 ＜ 0？"}
    K8 -- "是，且睡前会跌到 20" --> L8["约Xh后到20% · 建议"]
    K8 -- "是，睡前跌不到 20" --> L9["睡前约Y% · 建议<br/>Y = level + 速率 × 距入睡小时"]
    K8 -- 否 --> L10["+X%/h · 建议"]
```

建议词：

| 条件 | 建议 |
|---|---|
| level ≥ 65 | 适合专注 |
| 45 ≤ level ＜ 65 | 适合轻任务 |
| level ＜ 45，距入睡 ≤ 2h | 宜早睡 |
| level ＜ 45，18 点前 | 宜小憩 |
| level ＜ 45，其它时间 | 宜放松 |

---

## 6. 周限

### 6.1 周期与总式

- 一周从**周六 12:00（系统时区）**开始，到下周六 12:00 重置。
- 预算 7 小时：把一周的透支折算成「负债小时」D。

```mermaid
flowchart LR
    D["本周负债 D（小时）"] --> R["周剩余 = clamp( 100 × (1 − D ÷ 7), 0, 100 ) %"]
    R --> C1["≥ 20%：正常色"]
    R --> C2["＜ 20%：黄色<br/>卡片说明行改为「本周欠X.Xh · 建议」"]
    R --> C3["＜ 5%：红色"]
```

### 6.2 逐日账本

每天的负债减去当天的还款，结余**不能为负**。所以多睡只能还旧债，不能预存。

```mermaid
flowchart LR
    B0["结余₀ = 0"] --> B1["结余(第 d 天) = max( 0, 结余(d−1) + Σ负债(d) − 还款(d) )"]
    B1 --> DD["D = 结余(最后一天) + 运动不足 + 高强度过量"]
```

```mermaid
flowchart TD
    subgraph DEBT["每天负债"]
      S["睡眠不足 sleep<br/>当夜总睡眠 h（主睡眠 + 同日小睡）<br/>h ＜ 7 → 7 − h"]
      LT["晚睡 late<br/>入睡钟点在 00:00–12:00（戒指记录的时区）<br/>→ 0.25 × 入睡小时数"]
      RC["恢复不良 recovery<br/>z_HRV ≤ −1 或 (z_RHR ≥ 1 且 RHR 比基线高 ≥ 3 bpm)<br/>→ 每夜 1h"]
      SD["久坐 sedentary<br/>已结束的日子步数 ＜ 5000 → 0.25h"]
      SS["高压力 stress<br/>Oura stress_high 分钟数 m<br/>m ＞ 60 → 0.5 × (m − 60) ÷ 60"]
      DR["透支 drain<br/>HP ＜ 20 的非小睡格<br/>每格 0.5 × 5/60 h（每小时 0.5h）"]
    end
    subgraph CREDIT["每天还款"]
      SC["多睡 h ＞ 7 → min(h, 9) − 7"]
      RS["静息 rest 格 每格 0.25 × 5/60 h（每小时 0.25h）"]
    end
```

各项归属：

- 睡眠、晚睡、恢复不良：记在醒来那天；只算醒来时刻落在本周内的夜晚。
- 日汇总（步数、压力）：按 Oura 的 `day` 字段，周六整天都算新的一周。
- 5 分钟格：按格的开始时刻归日。

### 6.3 全周项：运动

按 WHO 成人标准：每周 150 分钟中等强度当量；高强度 1 分钟折算 2 分钟。

```mermaid
flowchart TD
    M["中等强度当量 M = Σ( 中强度分钟 + 2 × 高强度分钟 )"] --> E["应达 E = 150 × min(1, 本周已过时间 ÷ 7 天)"]
    E --> LOW["运动不足 = min( 2.5, max(0, E − M) ÷ 60 ) 小时"]
    HI["本周高强度分钟 Hm"] --> HIGH["高强度过量 = max(0, Hm − 300) ÷ 60 小时"]
```

周初应达量很小，周中、周末逐步提高，所以不会一开周就背满 2.5h。

### 6.4 标准值一览

| 项 | 标准（普通成年人） | 折算 |
|---|---|---|
| 睡眠 | 每夜 7h | 少 1h 欠 1h；多睡最多按 9h 计 |
| 晚睡 | 00:00 前入睡 | 00:00 后每小时 0.25h |
| 运动不足 | 每周 150 分钟中等强度当量 | 缺 60 分钟欠 1h，封顶 2.5h |
| 高强度过量 | 每周 ≤ 300 分钟 | 超 60 分钟欠 1h |
| 久坐 | 每天 ≥ 5000 步 | 不足一天欠 0.25h |
| 高压力 | 每天 ≤ 60 分钟 | 超出每小时欠 0.5h |
| 透支 | HP ≥ 20% | HP 低于 20 的每小时欠 0.5h |
| 恢复不良 | HRV、静息心率在个人基线内 | 每夜欠 1h |
| 静息还款 | — | 每小时静息还 0.25h |

### 6.5 压力单位判定

Oura 文档写 `stress_high` 以秒计，实测数值都是 900 的倍数。

- **只有**全部行都 ≤ 1440 **且**至少有一个值不是 300 的倍数时，才当作分钟；其它情况一律按秒。
- 判定用本次拉取的全部行，不只看本周。
- 拿不准时按秒处理，算出的负债只会偏少，不会把平静的一周算成几十小时。

### 6.6 说明行与建议

- 负债最大的一项记为 `top`，对应的建议：

  | top | 建议 |
  |---|---|
  | sleep | 该补觉 |
  | late | 今晚早睡 |
  | exercise_low | 去动一动 |
  | sedentary | 多走走 |
  | exercise_high | 停练休息 |
  | stress | 放松一下 |
  | drain | 强制休息 |
  | recovery | 强制休息 |

- 周剩余 ＜ 20% 时，白天的卡片说明行改为「本周欠X.Xh · 建议」。
- 以下紧急说明优先，不会被周限覆盖：Xh未同步、准备度、运动中、生理压力高。

### 6.7 数据来源与缓存

- 睡眠、`daily_activity`、`workout` 和 `daily_stress` 每次都拉近 7 天。
- 本周已结束的日子：用当天的心率重放一遍 5 分钟格，结果缓存进 `server/hp_weekly_cache.json`，每天只算一次。
  - 补拉心率失败的那天不缓存，本轮按 0 计，下一轮重试。
- 今天的格直接用日 HP 本轮的重放结果。
- 周限计算出错只写日志，不影响日 HP 显示。

---

## 7. 卡片投影

`display_server.energy_to_subscription` 把能量项转成一张通用卡片，旧设备不用升级也能显示：

```mermaid
flowchart LR
    E["energy 项"] --> W1["窗口 1：HP<br/>used = 100 − level<br/>标签 = 状态词（· note，≤16 字）"]
    E --> W2["窗口 2：label = 7天<br/>used = 100 − 周剩余<br/>reset_at = 下个周六 12:00"]
    W2 --> DEV["设备显示「周限」<br/>iPhone 隐藏标签"]
    W1 --> TONE["颜色（各端一致）<br/>剩余 ＜ 20 黄 · ＜ 5 红"]
    W2 --> TONE
```

---

## 8. 参数表（`DEFAULT_PARAMS`）

| 参数 | 值 | 含义 |
|---|---|---|
| basal | 2.0 %/h | 清醒基础消耗 |
| k_act | 0.15 | TRIMP 负荷系数 |
| k_met | 1.5 | MET 负荷系数 |
| k_stress | 20.0 | 心率偏离 → 压力负荷 |
| theta_stress | 0.08 | 高出安静心率 8% 才算压力 |
| stress_cap | 8.0 %/h | 压力负荷上限 |
| theta_rest | −0.05 | 低于安静心率 5% 算静息 |
| rest_gain | 2.0 %/h | 静息抵消基础消耗 |
| tau_sleep | 4.2 h | 睡眠 / 小睡回血时间常数 |
| exp_load | 0.8 %/h | 未观测 / 未佩戴时的预期负荷 |
| trend_band | 2.5 %/h | 趋势判定阈值 |
| kappa | 1.0 | 全局负荷倍率 |

周限常量在 `hp_weekly.py` 顶部：BUDGET_H=7、SLEEP_NEED_H=7、SLEEP_CREDIT_MAX_H=9、LATE_WEIGHT=0.25、EXERCISE_MIN=150、EXERCISE_CAP_H=2.5、HIGH_MAX_MIN=300、STEPS_MIN=5000、SEDENTARY_H=0.25、STRESS_ALLOW_MIN=60、STRESS_WEIGHT=0.5、DRAIN_LEVEL=20、DRAIN_WEIGHT=0.5、RECOVERY_H=1、REST_CREDIT=0.25、RHR_MIN_DELTA=3、LOW_PERCENT=20。

---

## 9. 已知局限

- 日 HP 的说明行「压力X分」直接把 `stress_high` 当秒换算。`hp_usage.py` 的回测报告仍用旧规则判断单位（中位数 ＜ 1440 就当分钟），比周限的判定脆弱。
- 周的边界用系统时区；晚睡判定用戒指记录自带的时区。两者不同时（比如人在日本、戒指记录 +08:00），周六 12:00 指的是系统时区的 12:00。
- 静息（rest）的速率是 0，所以白天静坐只能停止掉血，不会回血；回血主要靠睡眠和小睡。
