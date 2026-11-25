# HP 周限 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 HP 卡片上加一个每周六 12:00 重置的「周限」额度。睡眠、熬夜、运动、久坐、高压、透支、恢复这几项按普通成年人的标准折算成负债小时，额度紧张时卡片变成警告色。

**Architecture:** 新增纯函数模块 `hp_weekly.py`，从 Oura 数据和 HP 重放得到的 Step 里算出周账本。`hp_usage` 负责取数，缓存已结束日子的重放结果，再把 `weekly` 写进 energy 条目。`display_server` 校验 `weekly`，并把它投影成卡片的第二个额度。客户端不改。

**Tech Stack:** Python 3.9 stdlib，unittest（在 `server/` 下运行 `python3 -m unittest discover -p 'test_*.py'`）。

**Spec:** `docs/superpowers/specs/2026-11-25-hp-weekly-limit-design.md`

## Global Constraints

- 所有数值标准照抄 spec 的计分表：BUDGET 7h；睡眠 7h，还款最多算到 9h；熬夜从 00:00 起每小时 0.25h；运动 150 分钟（高强度 ×2），每差 60 分钟记 1h，最多 2.5h；步数 5000，不足一天记 0.25h；高强度超过 300 分钟的部分 1:1；高压超过 60 分钟的部分 0.5；HP<20% 的时间 0.5；恢复不足 1h；休息还款 0.25。
- 周期从本地时区的周六 12:00 开始，时区和 HP 一致（`local_tz()`）。
- 不提交密钥文件；不使用 `git add -A`；`display_server.py` 里混有用户自己没提交的改动，这部分只改、不提交。
- 说明行不超过 16 个字。

## Review Focus

- 周六 12:00 前后：上午属于上一周；周六的日汇总整天算新的一周。
- 周一早上还没有运动数据：按已过时间折算应完成量，不能一下子扣满 2.5h。
- 补拉过去某天的心率失败：那天的透支和休息按 0 计，不写缓存，日 HP 照常提交。
- 跨周时缓存要清空，不能把上一周的透支带进新的一周。
- `weekly` 字段非法时 `clean_energy` 返回 400；缺少 `weekly` 时卡片和现在一样，只有一个额度。

## Ruling

- 周限额度的标签用「7天」，不用 spec 里写的「周」：设备 `display_model.lua:171` 会把「7天」显示成「周限」，iPhone 会隐藏「7天」标签。这样和其他卡片的周限保持一致，客户端零改动。

---

### Task 1: `hp_weekly.py` 计分

**Files:** Create `server/hp_weekly.py`, `server/test_hp_weekly.py`

**Interfaces（Produces）:**
- `week_bounds(now, tz) -> (start_ts, reset_ts)`
- `compute(now, tz, sleeps, activities, stress_rows, steps, profile) -> dict | None`，返回
  `{"remaining_percent", "debt_hours", "reset_at", "top", "items": {key: h}, "days": [ledger rows]}`
  - `steps`：本周的 Step 列表，可以跨多天，函数内部按 `start >= start_ts` 过滤。
  - items 的键：`sleep late exercise_low sedentary exercise_high stress drain recovery`。
- `line(weekly) -> str | None`：剩余 ≥20% 时返回 None，否则返回 `本周欠Xh · 建议`。

Tests (TZ=+08:00, now 2026-11-25 22:00 周三, week start 11-21 12:00)：周界（周六 11:59 / 12:00 / 周日）；睡眠不足与还款上限；还款不能预存（先多睡后少睡，以及先少睡后多睡）；熬夜 02:30 记 0.625h、23:30 不记；运动按已过时间折算、上限 2.5h；高强度当量 ×2；步数当天不结算；高强度超 300 分钟；高压按秒和按分钟两种单位；透支和休息只统计 `start >= start_ts` 的格子；恢复不足由 HRV 或 RHR 的 z 值触发；top 与 line 的建议映射；剩余比例 clamp 在 0–100。

### Task 2: 取数范围、过去各天的重放与缓存、写入 energy 条目

**Files:** Modify `server/oura_client.py`（fetch_all：activity、workout、daily_stress 起始日改为 d−7）、`server/hp_model.py`（抽出 `day_steps(day, data, hr_quiet, p, tz, age)`，`day_summary` 改为调用它）、`server/hp_usage.py`（`weekly_for(...)`：缓存文件 `hp_weekly_cache.json` 按 week_start 存放已结束日子的 Step 摘要；覆盖说明行；`build_item` 加 `weekly`；`--explain` 打印账本；`--report` 输出按周回算）。Tests: `test_oura_client.py`、`test_hp_usage.py`。

### Task 3: display_server 校验与第二额度

**Files:** Modify `server/display_server.py`（`clean_energy` 校验 `weekly`；`energy_to_subscription` 追加 `{"label":"7天","used_percent":100−remaining,"reset_at":reset_at}`）。Tests: `test_hp_weekly.py` 的 DisplayServer 部分。

### Task 4: 上线

重启 HP 采集器，手动推送一轮，核对卡片数据；用 `--report` 回算并汇报。
