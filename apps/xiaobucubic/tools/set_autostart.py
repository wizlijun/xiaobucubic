#!/usr/bin/env python3
"""Configure ClocTeck Launcher to open xiaobucubic after Wi-Fi gets an IP."""
import argparse
import json
import urllib.parse
from datetime import datetime

from deploy import ROOT, request


def patch_launcher(data):
    newline = "\r\n" if b"\r\n" in data else "\n"
    source = data.decode("utf-8").replace("\r\n", "\n")
    setting = 'local AUTOSTART_APP_ID = tostring(SETTINGS.autostart_app_id or DEFAULT_AUTOSTART_APP_ID)'
    wait_setting = 'local AUTOSTART_WAIT_FOR_WIFI = setting_bool(SETTINGS.autostart_wait_for_wifi, false)'
    old = '  t:alarm(AUTOSTART_DELAY_MS, tmr.ALARM_SINGLE, function(self)\n'
    new = '''  t:alarm(AUTOSTART_DELAY_MS, tmr.ALARM_AUTO, function(self)
    -- Keep the boot decision while waiting, even if Wi-Fi takes over 5 seconds.
    if AUTOSTART_WAIT_FOR_WIFI then
      local ip = station_ip()
      if not ip or ip == "0.0.0.0" then return end
    end
'''
    if wait_setting in source and new in source:
        return data
    if wait_setting in source or source.count(setting) != 1 or source.count(old) != 1:
        raise RuntimeError("Unrecognized Launcher source; no device files changed")
    source = source.replace(setting, setting + "\n" + wait_setting).replace(old, new)
    return source.replace("\n", newline).encode("utf-8")


def configure(base):
    state = json.loads(request(base, "/api/system/state"))
    if not any(item.get("id") == "xiaobucubic" for item in state.get("apps", [])):
        raise RuntimeError("Install xiaobucubic before configuring autostart")
    paths = ["/sd/apps/launcher/main.lua", "/sd/apps/settings.json"]
    routes = ["/api/system/fs/file?path=" + urllib.parse.quote(p, safe="") for p in paths]
    before = [request(base, route) for route in routes]
    settings = json.loads(before[1])
    if not isinstance(settings, dict):
        raise RuntimeError("Invalid device settings; no files changed")
    settings.update(autostart_enabled=True, autostart_app_id="xiaobucubic",
                    autostart_wait_for_wifi=True)
    after = [patch_launcher(before[0]),
             (json.dumps(settings, ensure_ascii=False, indent=2) + "\n").encode()]
    backup = ROOT / ".runtime/backups" / ("autostart-" + datetime.now().strftime("%Y%m%d-%H%M%S-%f"))
    backup.mkdir(parents=True, mode=0o700)
    for name, data in zip(["launcher.lua", "settings.json"], before):
        target = backup / name
        target.write_bytes(data)
        target.chmod(0o600)
    uploads = ["/api/system/fs/upload?path=" + urllib.parse.quote(p, safe="") for p in paths]
    changed = []
    try:
        for i, data in enumerate(after):
            if before[i] == data:
                continue
            changed.append(i)
            request(base, uploads[i], "PUT", data)
            if request(base, routes[i]) != data:
                raise RuntimeError("Read-back verification failed: " + paths[i])
    except Exception:
        for i in reversed(changed):
            try:
                request(base, uploads[i], "PUT", before[i])
            except Exception as error:
                print("Restore failed:", paths[i], str(error))
        print("Original files:", backup)
        raise
    print("Verified: boot -> wait for Wi-Fi IP -> xiaobucubic")
    print("Applies on next reboot. Original files:", backup)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("device", help="e.g. http://10.15.2.72")
    configure(parser.parse_args().device)
