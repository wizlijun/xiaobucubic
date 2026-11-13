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
parser.add_argument("--expect-board", choices=("waveshare_lcd", "qualia_5800"), help="Verify the running firmware's board profile")
parser.add_argument("--expect-panel", choices=("waveshare_st7701", "yx40006act"), help="Verify the LCD panel independently of the controller board")
parser.add_argument("--require-touch", action="store_true", help="Check touch-controller detection, not physical coordinates")
parser.add_argument("--expect-pclk", type=int, help="Expected RGB clock in Hz for an explicit timing experiment")
parser.add_argument("--expect-timing", choices=("text", "reference"), default="reference", help="YX40006ACT timing set (default: supplier-confirmed reference image)")
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
if args.expect_board:
    checks["Expected board profile"] = status.get("display", {}).get("board") == args.expect_board
display = status.get("display", {})
is_720 = display.get("panel_id") == "yx40006act"
expected_size = 720 if is_720 else 480
if args.expect_panel:
    checks["Expected panel profile"] = display.get("panel_id") == args.expect_panel
if args.require_touch:
    app = status.get("app", {})
    checks["Touch controller detected"] = app.get("touch_available") is True
    checks["Expected touch controller"] = app.get("touch_controller") == ("FT6336U" if is_720 else "GT911")
if args.require_client:
    network = ipaddress.ip_network(status["ap_ip"] + "/24", strict=False)
    checks["Client has a DHCP address"] = any(
        ipaddress.ip_address(address) in network for address in status.get("client_ips", [])
    )
if args.require_display:
    display = status.get("display", {})
    checks["LCD driver initialized (physical output unverified)"] = display.get("state") == "initialized" and display.get("error") == "ESP_OK"
    checks[f"{expected_size}x{expected_size} configured"] = display.get("width") == expected_size and display.get("height") == expected_size
    checks["8 MB PSRAM available"] = display.get("psram_bytes") == 8 * 1024 * 1024
if args.require_app:
    app = status.get("app", {})
    checks["Native app running"] = app.get("state") == "running" and app.get("implementation") == "native_c"
    checks["Chinese fonts loaded"] = app.get("fonts_loaded") == 4
    typography = "720px_scaled_27_36_48" if is_720 else "480px_adaptive_18_24_32"
    checks["Adaptive WenKai typography active"] = app.get("typography") == typography and app.get("message_font_family") == "LXGW WenKai"
    checks["Display API synchronized"] = app.get("http_status") == 200 and app.get("connection") == "已同步" and app.get("has_snapshot") is True
    checks["Persistent cache available"] = app.get("cache_available") is True
if args.require_buffered_display:
    app = status.get("app", {})
    checks["Two LCD framebuffers"] = status.get("display", {}).get("frame_buffers") == 2
    checks["Whole-frame presentation active"] = app.get("refresh_mode") == "whole_frame_double_buffer" and app.get("presented_frames", 0) > 0
    checks["Frame boundary acknowledgments healthy"] = app.get("frame_wait_timeouts") == 0
if args.require_stable_rgb:
    display, app = status.get("display", {}), status.get("app", {})
    expected_clock = args.expect_pclk if args.expect_pclk is not None else (35000000 if is_720 else 8000000)
    checks["Expected RGB clock and bounce buffers configured"] = display.get("pixel_clock_hz") == expected_clock and display.get("bounce_lines") == 20
    if is_720:
        timing = ("hsync_pulse_width", "hsync_back_porch", "hsync_front_porch", "vsync_pulse_width", "vsync_back_porch", "vsync_front_porch")
        expected_timing = (2, 44, 46, 2, 18, 16) if args.expect_timing == "reference" else (6, 25, 25, 2, 17, 20)
        checks["YX40006ACT supplier timing configured"] = tuple(display.get(key) for key in timing) == expected_timing
    checks["RGB cache and ISR configured"] = display.get("cache_line_bytes") == 64 and display.get("isr_iram_safe") is True
    if display.get("board") == "qualia_5800":
        checks["Qualia 64 KB data cache configured"] = display.get("data_cache_bytes") == 65536
    checks["RGB restarts only for recovery"] = display.get("restart_policy") == "on_underflow"
    checks["RGB scanning and completing frames"] = app.get("rgb_vsyncs", 0) > 0 and app.get("rgb_frame_completions", 0) > 0
for name, passed in checks.items():
    print(f"{'PASS' if passed else 'FAIL'}: {name}")
print(json.dumps(status, ensure_ascii=False, indent=2))
raise SystemExit(0 if all(checks.values()) else 1)
