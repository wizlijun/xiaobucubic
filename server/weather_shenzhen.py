#!/usr/bin/env python3
"""查询中国深圳当前天气（Open-Meteo，免费、无需 API key）。

天气以预报为准: condition / rain_percent 取未来 12 小时逐小时预报中最显著的天气
和最高降水概率，low_c / high_c 取今日预报；temperature_c、湿度、气压等为当前值。
扩展字段 condition_now 为当前天气，forecast_hours 为预报时长，pressure_hpa 为海平面气压。
updated_at 取接口数据对应的时间（每 15 分钟一档），不是查询时间。

用法:
    ./weather_shenzhen.py          # 人类可读输出
    ./weather_shenzhen.py --json   # 显示服务所用的天气 JSON
    ./weather_shenzhen.py --push [URL] [--interval 300]   # 提交到显示服务
"""
import argparse
import json
import sys
import urllib.error
import urllib.request
from urllib.parse import urlencode

import display_push

API_URL = "https://api.open-meteo.com/v1/forecast"
CITY = "深圳"
LATITUDE, LONGITUDE = 22.5431, 114.0579
FORECAST_HOURS = 12

# WMO 天气代码 → 中文；终端按文字中的“晴 / 雨 / 云”选择背景。代码越大天气越显著。
CONDITIONS = {
    0: "晴", 1: "晴间多云", 2: "多云", 3: "阴",
    45: "雾", 48: "雾凇",
    51: "小毛毛雨", 53: "毛毛雨", 55: "大毛毛雨", 56: "冻毛毛雨", 57: "冻毛毛雨",
    61: "小雨", 63: "中雨", 65: "大雨", 66: "冻雨", 67: "冻雨",
    71: "小雪", 73: "中雪", 75: "大雪", 77: "雪粒",
    80: "阵雨", 81: "中阵雨", 82: "强阵雨", 85: "阵雪", 86: "强阵雪",
    95: "雷阵雨", 96: "雷阵雨伴冰雹", 99: "强雷阵雨伴冰雹",
}


def fetch_weather():
    query = urlencode({
        "latitude": LATITUDE,
        "longitude": LONGITUDE,
        "current": "temperature_2m,relative_humidity_2m,apparent_temperature,weather_code,wind_speed_10m,pressure_msl",
        "hourly": "weather_code,precipitation_probability",
        "daily": "temperature_2m_max,temperature_2m_min",
        "timezone": "Asia/Shanghai",
        "timeformat": "unixtime",
        "forecast_days": 2,
        "forecast_hours": FORECAST_HOURS,
    })
    req = urllib.request.Request(API_URL + "?" + query, headers={"User-Agent": "weather-shenzhen/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.load(resp)
    except urllib.error.HTTPError as exc:
        raise RuntimeError("天气接口请求失败: HTTP %d" % exc.code) from None
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise RuntimeError("天气接口网络错误: %s" % getattr(exc, "reason", exc)) from None
    except ValueError:
        raise RuntimeError("天气接口未返回有效 JSON。") from None
    if not isinstance(data, dict) or not isinstance(data.get("current"), dict):
        raise RuntimeError("天气接口返回格式不符合预期。")
    return data


def first(daily, key):
    values = daily.get(key) or []
    return values[0] if values else None


def condition(code):
    return None if code is None else CONDITIONS.get(code, "未知")


def peak(hourly, key):
    values = [v for v in hourly.get(key) or [] if v is not None]
    return max(values) if values else None


def to_display(data):
    current = data["current"]
    hourly = data.get("hourly") or {}
    daily = data.get("daily") or {}
    if current.get("time") is None:
        raise RuntimeError("天气接口未返回观测时间。")
    # 预报缺失时退回当前天气。
    forecast_code = peak(hourly, "weather_code")
    code_now = current.get("weather_code")
    return {
        "city": CITY,
        "condition": condition(code_now if forecast_code is None else forecast_code),
        "condition_now": condition(code_now),
        "forecast_hours": FORECAST_HOURS,
        "temperature_c": current.get("temperature_2m"),
        "feels_like_c": current.get("apparent_temperature"),
        "low_c": first(daily, "temperature_2m_min"),
        "high_c": first(daily, "temperature_2m_max"),
        "humidity_percent": current.get("relative_humidity_2m"),
        "rain_percent": peak(hourly, "precipitation_probability"),
        "wind_kmh": current.get("wind_speed_10m"),
        "pressure_hpa": current.get("pressure_msl"),
        "source": "Open-Meteo",
        "updated_at": int(current["time"]),
    }


def summary(weather):
    def num(value):
        return "--" if value is None else "%g" % value

    return "%s 未来%d小时%s，当前%s %s°C (%s~%s°C)" % (
        weather["city"], weather["forecast_hours"], weather["condition"] or "--",
        weather["condition_now"] or "--", num(weather["temperature_c"]),
        num(weather["low_c"]), num(weather["high_c"]))


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--json", action="store_true", help="输出显示服务所用的天气 JSON")
    display_push.add_arguments(parser)
    args = parser.parse_args()
    try:
        if args.push:
            display_push.run(args, lambda: to_display(fetch_weather()), path="/v1/weather", describe=summary)
            return
        weather = to_display(fetch_weather())
        if args.json:
            print(json.dumps(weather, indent=2, ensure_ascii=False))
        else:
            print(summary(weather))
            print("体感 %s°C  湿度 %s%%  气压 %s hPa  未来降水概率 %s%%  风速 %s km/h" % (
                weather["feels_like_c"], weather["humidity_percent"], weather["pressure_hpa"],
                weather["rain_percent"], weather["wind_kmh"]))
    except RuntimeError as exc:
        sys.exit(str(exc))
    except KeyboardInterrupt:
        sys.exit(130)


if __name__ == "__main__":
    main()
