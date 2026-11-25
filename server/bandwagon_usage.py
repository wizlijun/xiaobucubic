#!/usr/bin/env python3
"""查询 BandwagonHost（搬瓦工）本期流量，接入显示服务的定时采集。

在环境变量或同目录 display.env 中配置 BANDWAGON_VEID / BANDWAGON_API_KEY。
仅调用 getServiceInfo；凭据不通过命令行参数传递，不输出原始响应。

用法:
    python3 bandwagon_usage.py
    python3 bandwagon_usage.py --json
    python3 bandwagon_usage.py --push [URL] [--follow]
"""
import argparse
import json
import math
import os
import sys
import time
import urllib.error
import urllib.request
from urllib.parse import urlencode

import display_push

API_URL = "https://api.64clouds.com/v1/getServiceInfo"


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def load_credentials():
    names = ("BANDWAGON_VEID", "BANDWAGON_API_KEY")
    values = {}
    try:
        with open(display_push.ENV_FILE, encoding="utf-8") as stream:
            for line in stream:
                key, separator, value = line.strip().partition("=")
                if separator and key.strip() in names:
                    values[key.strip()] = value.strip().strip("'\"")
    except FileNotFoundError:
        pass
    except OSError:
        raise RuntimeError("无法读取 display.env 中的 Bandwagon 凭据。") from None
    for name in names:
        if os.environ.get(name, "").strip():
            values[name] = os.environ[name].strip()
    missing = [name for name in names if not values.get(name)]
    if missing:
        raise RuntimeError("请在环境变量或 display.env 配置 " + " / ".join(missing))
    if not values[names[0]].isascii() or not values[names[0]].isdigit():
        raise RuntimeError("BANDWAGON_VEID 必须是数字 VPS ID。")
    return values[names[0]], values[names[1]]


def fetch_usage(veid, api_key):
    query = urlencode({"veid": veid, "api_key": api_key})
    request = urllib.request.Request(API_URL + "?" + query, headers={
        "Accept": "application/json", "User-Agent": "bandwagon-usage/1.0",
    })
    try:
        with urllib.request.build_opener(NoRedirect).open(request, timeout=20) as response:
            data = json.load(response)
    except urllib.error.HTTPError as exc:
        raise RuntimeError("Bandwagon 查询失败: HTTP %d" % exc.code) from None
    except (urllib.error.URLError, TimeoutError, OSError):
        # 异常可能包含带 API key 的 URL，不输出异常原文。
        raise RuntimeError("Bandwagon 查询网络错误，请检查网络后重试。") from None
    except ValueError:
        raise RuntimeError("Bandwagon 接口未返回有效 JSON。") from None
    if not isinstance(data, dict) or isinstance(data.get("error"), bool) or data.get("error") not in (0, "0"):
        raise RuntimeError("Bandwagon 接口返回错误，请检查 VEID、API Key 和 API 访问权限。")
    return data


def number(data, key, positive=False):
    value = data.get(key)
    if value is None or isinstance(value, bool):
        raise RuntimeError("Bandwagon 接口缺少有效的 %s。" % key)
    try:
        value = float(value)
    except (TypeError, ValueError, OverflowError):
        raise RuntimeError("Bandwagon 接口的 %s 不是有效数字。" % key) from None
    if not math.isfinite(value) or value < 0 or (positive and value == 0):
        raise RuntimeError("Bandwagon 接口的 %s 超出有效范围。" % key)
    return value


def to_display(data):
    used = number(data, "data_counter")
    total = number(data, "plan_monthly_data", positive=True)
    used_percent = used / total * 100
    if not math.isfinite(used_percent):
        raise RuntimeError("Bandwagon 流量比例超出有效范围。")
    reset = data.get("data_next_reset")
    if reset is not None:
        reset = number(data, "data_next_reset", positive=True)
        if reset >= 1e11:
            raise RuntimeError("Bandwagon 重置时间必须为 Unix 秒。")
        reset = int(reset)
    return {
        "id": "bandwagon",
        "name": "Bandwagon",
        "source": "official",
        "updated_at": int(time.time()),
        "windows": [{"label": "本期流量", "used_percent": used_percent, "reset_at": reset}],
    }


def collect():
    return to_display(fetch_usage(*load_credentials()))


def summary(item):
    window = item["windows"][0]
    remaining = max(0, 100 - window["used_percent"])
    return "Bandwagon 本期流量剩余 %.1f%%（重置时间: %s）" % (
        remaining, time.strftime("%Y-%m-%d %H:%M", time.localtime(window["reset_at"]))
        if window["reset_at"] else "未知")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--json", action="store_true", help="输出显示服务订阅 JSON")
    display_push.add_arguments(parser, "bandwagon")
    args = parser.parse_args()
    try:
        if args.push:
            display_push.run(args, collect, describe=summary)
        else:
            item = collect()
            print(json.dumps(item, ensure_ascii=False, indent=2) if args.json else summary(item))
    except (RuntimeError, OSError) as exc:
        sys.exit(str(exc))
    except KeyboardInterrupt:
        sys.exit(130)


if __name__ == "__main__":
    main()
