#!/usr/bin/env python3
"""提交或清除个人能量数据（PUT / DELETE /v1/energy），用于手动更新或后续接入数据源。

用法:
    ./energy_usage.py --level 78 --status 充沛 --note "睡眠 7.5h" --push
    ./energy_usage.py --level 65 --trend draining --source estimated --json
    ./energy_usage.py --clear --push
"""
import argparse
import json
import math
import sys
import time

import display_push

SOURCES = ("official", "manual", "estimated", "unknown")
TRENDS = ("charging", "draining", "steady")


def build_payload(level=None, name="HP", status=None, trend=None, note=None,
                  source="manual", stale_after=None, updated_at=None):
    if level is not None:
        if isinstance(level, bool) or not isinstance(level, (int, float)) or not math.isfinite(level):
            raise RuntimeError("level 必须是有效数字。")
        if not 0 <= level <= 100:
            raise RuntimeError("level 必须在 0–100 之间。")
        level = int(level) if float(level).is_integer() else round(float(level), 1)
    if source not in SOURCES:
        raise RuntimeError("source 必须是 %s 之一。" % " / ".join(SOURCES))
    if trend is not None and trend not in TRENDS:
        raise RuntimeError("trend 必须是 %s 之一。" % " / ".join(TRENDS))
    if stale_after is not None and (isinstance(stale_after, bool) or not isinstance(stale_after, int) or not 60 <= stale_after <= 7 * 86400):
        raise RuntimeError("stale_after 必须是 60–604800 的整数秒。")
    item = {
        "name": (name or "HP").strip()[:40] or "HP",
        "level_percent": level,
        "source": source,
        "updated_at": int(updated_at) if updated_at is not None else int(time.time()),
    }
    if status and status.strip():
        item["status"] = status.strip()[:16]
    if trend:
        item["trend"] = trend
    if note and note.strip():
        item["note"] = note.strip()[:80]
    if stale_after is not None:
        item["stale_after_seconds"] = stale_after
    return item


def summary(item):
    pct = "--" if item.get("level_percent") is None else "%g%%" % item["level_percent"]
    parts = [p for p in (item.get("status"), item.get("trend"), item.get("note")) if p]
    suffix = "（%s）" % " · ".join(parts) if parts else ""
    return "%s %s%s" % (item.get("name") or "HP", pct, suffix)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--level", type=float, default=None, help="当前能量百分比 0–100（省略表示未知 --）")
    parser.add_argument("--name", default="HP", help="卡片标题 (默认 HP)")
    parser.add_argument("--status", default=None, help="简短状态，如 充沛 / 正常 / 偏低")
    parser.add_argument("--trend", choices=TRENDS, default=None, help="趋势: charging / draining / steady")
    parser.add_argument("--note", default=None, help="补充说明，如 睡眠 7.5h · HRV 62")
    parser.add_argument("--source", choices=SOURCES, default="manual", help="来源 (默认 manual)")
    parser.add_argument("--stale-after", type=int, default=None, help="独立有效期秒数 (60–604800)")
    parser.add_argument("--clear", action="store_true", help="清空能量数据（界面隐藏）")
    parser.add_argument("--json", action="store_true", help="输出将提交的 JSON")
    display_push.add_arguments(parser, "energy")
    args = parser.parse_args()
    try:
        if args.clear:
            if args.push:
                display_push.request_json(args.push, "/v1/energy", None, method="DELETE")
                print("%s 已清空能量数据" % time.strftime("%H:%M:%S"), flush=True)
            else:
                print(json.dumps({"energy": None}, ensure_ascii=False, indent=2) if args.json else "能量: null（使用 --push 提交清除）")
            return
        item = build_payload(
            level=args.level, name=args.name, status=args.status, trend=args.trend,
            note=args.note, source=args.source, stale_after=args.stale_after,
        )
        if args.push:
            display_push.push(args.push, item, path="/v1/energy")
            print("%s 已提交 %s" % (time.strftime("%H:%M:%S"), summary(item)), flush=True)
        elif args.json:
            print(json.dumps(item, ensure_ascii=False, indent=2))
        else:
            print(summary(item))
    except (RuntimeError, OSError) as exc:
        sys.exit(str(exc))
    except KeyboardInterrupt:
        sys.exit(130)


if __name__ == "__main__":
    main()
