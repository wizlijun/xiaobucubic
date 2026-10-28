#!/usr/bin/env python3
"""Validate private AP settings and generate a build-only C header."""
import json
import pathlib
import sys


def render(config):
    ssid = config.get("ssid", "ap24")
    password = config.get("password", "")
    channel = config.get("channel", 6)
    clients = config.get("max_clients", 4)
    if not isinstance(ssid, str) or not 1 <= len(ssid.encode("utf-8")) <= 32 or any(ord(c) < 32 or ord(c) == 127 for c in ssid):
        raise ValueError("SSID must be 1–32 UTF-8 bytes without control characters")
    if not isinstance(password, str) or not 8 <= len(password) <= 63 or any(not 32 <= ord(c) <= 126 for c in password):
        raise ValueError("Password must contain 8–63 printable ASCII characters")
    if type(channel) is not int or not 1 <= channel <= 11:
        raise ValueError("Channel must be an integer between 1 and 11")
    if type(clients) is not int or not 1 <= clients <= 4:
        raise ValueError("max_clients must be an integer between 1 and 4")
    return ("/* Generated from private local configuration. Do not commit. */\n#pragma once\n"
            f"#define ROUTER_SSID {json.dumps(ssid, ensure_ascii=False)}\n"
            f"#define ROUTER_PASSWORD {json.dumps(password)}\n"
            f"#define ROUTER_CHANNEL {channel}\n#define ROUTER_MAX_CLIENTS {clients}\n")


if __name__ == "__main__":
    try:
        source, target = map(pathlib.Path, sys.argv[1:])
        result = render(json.loads(source.read_text()))
        target.write_text(result)
        target.chmod(0o600)
    except (OSError, ValueError, TypeError) as exc:
        sys.exit(f"Router configuration: {exc}")
