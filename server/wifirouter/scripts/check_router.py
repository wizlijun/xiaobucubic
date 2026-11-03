#!/usr/bin/env python3
"""Read-only hardware smoke check; does not claim to test Internet reachability."""
import argparse
import ipaddress
import json
import urllib.request

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("url", help="Router URL, e.g. http://192.168.2.2")
parser.add_argument("--require-client", action="store_true")
parser.add_argument("--require-display", action="store_true", help="Check LCD initialization, not physical screen output")
parser.add_argument("--require-app", action="store_true", help="Check native app and real HTTP sync")
parser.add_argument("--require-buffered-display", action="store_true", help="Check whole-frame swapping and driver acknowledgments")
parser.add_argument("--require-stable-rgb", action="store_true", help="Check conservative RGB timing, IRAM callbacks and scan activity")
args = parser.parse_args()
opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
with opener.open(args.url.rstrip("/") + "/api/status", timeout=5) as response:
    status = json.load(response)
checks = {
    "DHCP server running": status.get("dhcp_running") is True,
    "USB attached": status.get("usb_attached") is True,
    "IPv4 NAT enabled": status.get("nat_ready") is True,
    "No subnet overlap": status.get("subnet_conflict") is False,
}
if args.require_client:
    network = ipaddress.ip_network(status["ap_ip"] + "/24", strict=False)
    checks["Client has a DHCP address"] = any(
        ipaddress.ip_address(address) in network for address in status.get("client_ips", [])
    )
if args.require_display:
    display = status.get("display", {})
    checks["ST7701 initialized"] = display.get("state") == "initialized" and display.get("error") == "ESP_OK"
    checks["480x480 configured"] = display.get("width") == 480 and display.get("height") == 480
    checks["8 MB PSRAM available"] = display.get("psram_bytes") == 8 * 1024 * 1024
if args.require_app:
    app = status.get("app", {})
    checks["Native app running"] = app.get("state") == "running" and app.get("implementation") == "native_c"
    checks["Chinese fonts loaded"] = app.get("fonts_loaded") == 4
    checks["Adaptive WenKai typography active"] = app.get("typography") == "480px_adaptive_18_24_32" and app.get("message_font_family") == "LXGW WenKai"
    checks["Display API synchronized"] = app.get("http_status") == 200 and app.get("connection") == "已同步" and app.get("has_snapshot") is True
    checks["Persistent cache available"] = app.get("cache_available") is True
if args.require_buffered_display:
    app = status.get("app", {})
    checks["Two LCD framebuffers"] = status.get("display", {}).get("frame_buffers") == 2
    checks["Whole-frame presentation active"] = app.get("refresh_mode") == "whole_frame_double_buffer" and app.get("presented_frames", 0) > 0
    checks["Frame boundary acknowledgments healthy"] = app.get("frame_wait_timeouts") == 0
if args.require_stable_rgb:
    display, app = status.get("display", {}), status.get("app", {})
    checks["RGB bandwidth margin configured"] = display.get("pixel_clock_hz") == 8000000 and display.get("bounce_lines") == 20
    checks["RGB cache and ISR configured"] = display.get("cache_line_bytes") == 64 and display.get("isr_iram_safe") is True
    checks["RGB scanning and completing frames"] = app.get("rgb_vsyncs", 0) > 0 and app.get("rgb_frame_completions", 0) > 0
for name, passed in checks.items():
    print(f"{'PASS' if passed else 'FAIL'}: {name}")
print(json.dumps(status, ensure_ascii=False, indent=2))
raise SystemExit(0 if all(checks.values()) else 1)
