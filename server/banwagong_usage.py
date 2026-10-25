#!/usr/bin/env python3
"""查询搬瓦工当前计费月流量，仅调用 KiwiVM getServiceInfo。

凭据从 BANWAGONG_VEID / BANWAGONG_API_KEY 环境变量读取，或写入同目录
banwagong.env（参见 banwagong.env.example）。环境变量优先。

用法:
    python3 banwagong_usage.py
    python3 banwagong_usage.py --json       # 输出显示服务数据，不输出原始响应
    python3 banwagong_usage.py --push [URL] [--interval 300]
"""
import argparse
import json
import os
import shlex
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from decimal import Decimal, InvalidOperation
from pathlib import Path

import display_push

API_URL = "https://api.64clouds.com/v1/getServiceInfo"
ENV_FILE = Path(__file__).with_name("banwagong.env")
MAX_BYTES = 2**53 - 1


def load_credentials():
    names = ("BANWAGONG_VEID", "BANWAGONG_API_KEY")
    values = {}
    if not all(name in os.environ for name in names):
        try:
            lines = ENV_FILE.read_text(encoding="utf-8").splitlines()
        except FileNotFoundError:
            lines = []
        except OSError:
            raise RuntimeError("无法读取 banwagong.env，请检查文件权限。") from None
        for line in lines:
            key, sep, value = line.strip().partition("=")
            if sep and key.strip() in names:
                try:
                    parts = shlex.split(value, comments=True)
                except ValueError:
                    raise RuntimeError("banwagong.env 格式错误，请参考示例文件。") from None
                if len(parts) > 1:
                    raise RuntimeError("banwagong.env 的值包含空格时需使用引号。")
                values[key.strip()] = parts[0] if parts else ""
    veid, api_key = (os.environ.get(name, values.get(name, "")).strip() for name in names)
    if not veid and not api_key:
        return None
    if not veid or not api_key:
        raise RuntimeError("请同时配置 BANWAGONG_VEID 和 BANWAGONG_API_KEY。")
    if not veid.isascii() or not veid.isdigit() or int(veid) <= 0:
        raise RuntimeError("BANWAGONG_VEID 必须是正整数 VPS ID。")
    return veid, api_key


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def fetch_usage(veid, api_key):
    body = urllib.parse.urlencode({"veid": veid, "api_key": api_key}).encode("utf-8")
    req = urllib.request.Request(API_URL, data=body, headers={
        "Content-Type": "application/x-www-form-urlencoded",
        "Accept": "application/json",
        "User-Agent": "banwagong-usage/1.0",
    }, method="POST")
    try:
        with urllib.request.build_opener(NoRedirect).open(req, timeout=20) as resp:
            data = json.load(resp)
    except urllib.error.HTTPError as exc:
        raise RuntimeError("KiwiVM 请求失败: HTTP %d。" % exc.code) from None
    except (urllib.error.URLError, TimeoutError, OSError):
        raise RuntimeError("无法连接 KiwiVM，请检查网络或稍后重试。") from None
    except ValueError:
        raise RuntimeError("KiwiVM 未返回有效 JSON。") from None
    # 不打印远端 message 或响应正文，避免错误响应回显凭据。
    if not isinstance(data, dict) or isinstance(data.get("error"), bool) or data.get("error") not in (0, "0"):
        raise RuntimeError("KiwiVM 查询失败，请检查凭据、API 权限或稍后重试。")
    return data


def number(data, key, default=None):
    value = data.get(key, default)
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        raise RuntimeError("KiwiVM 缺少或返回无效的 %s。" % key)
    try:
        result = Decimal(str(value))
    except InvalidOperation:
        raise RuntimeError("KiwiVM 返回无效的 %s。" % key) from None
    if not result.is_finite() or result < 0 or result > MAX_BYTES:
        raise RuntimeError("KiwiVM 返回无效的 %s。" % key)
    return result


def to_display(data):
    total = number(data, "plan_monthly_data")
    used = number(data, "data_counter")
    multiplier = number(data, "monthly_data_multiplier", 1)
    reset = number(data, "data_next_reset")
    if total <= 0 or multiplier <= 0 or total != int(total) or used != int(used):
        raise RuntimeError("KiwiVM 返回无效的流量额度、计数或倍率。")
    if reset <= 0 or reset > 1e11 or reset != int(reset):
        raise RuntimeError("KiwiVM data_next_reset 必须是 Unix 秒。")
    # KiwiVM 的额度与计数均应用倍率；用 Decimal 避免大字节数的浮点损失。
    total_bytes = int(total * multiplier)
    used_bytes = int(used * multiplier)
    if not 0 < total_bytes <= MAX_BYTES or used_bytes > MAX_BYTES:
        raise RuntimeError("KiwiVM 换算后的流量额度或用量超出支持范围。")
    item = {
        "id": "banwagong",
        "name": "搬瓦工",
        "source": "official",
        "updated_at": int(time.time()),
        "windows": [{
            "label": "月度",
            "used_percent": round(used_bytes / total_bytes * 100, 1),
            "reset_at": int(reset),
            "total_bytes": total_bytes,
            "used_bytes": used_bytes,
            "remaining_bytes": max(0, total_bytes - used_bytes),
        }],
    }
    if isinstance(data.get("plan"), str) and data["plan"].strip():
        item["plan"] = data["plan"].strip()[:80]
    return item


def collect():
    credentials = load_credentials()
    if credentials is None:
        raise RuntimeError("未配置搬瓦工凭据，请设置 BANWAGONG_VEID 和 BANWAGONG_API_KEY。")
    return to_display(fetch_usage(*credentials))


def summary(item):
    window = item["windows"][0]
    return "搬瓦工 本计费月剩余 %.2f / %.2f GiB，已用 %.1f%%，重置时间 %s" % (
        window["remaining_bytes"] / 1024**3, window["total_bytes"] / 1024**3,
        window["used_percent"], time.strftime("%Y-%m-%d %H:%M:%S %Z", time.localtime(window["reset_at"])))


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--json", action="store_true", help="输出显示服务所用的订阅 JSON")
    display_push.add_arguments(parser)
    args = parser.parse_args()
    if args.interval < 0 or (args.interval and args.interval < 60):
        parser.error("--interval 必须为 0（单次）或至少 60 秒")
    try:
        # 默认自动采集启用；尚未配置时跳过，不产生虚假的 0 用量。
        if args.push:
            if load_credentials() is None:
                print("搬瓦工未配置，跳过采集。")
                return
            display_push.run(args, collect, describe=summary)
            return
        item = collect()
        print(json.dumps(item, indent=2, ensure_ascii=False) if args.json else summary(item))
    except RuntimeError as exc:
        sys.exit(str(exc))
    except KeyboardInterrupt:
        sys.exit(130)


if __name__ == "__main__":
    main()
