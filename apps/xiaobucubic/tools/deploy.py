#!/usr/bin/env python3
"""Install only xiaobucubic using ClocTeck DevTools and verify every uploaded byte."""
import argparse
import hashlib
import json
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from datetime import datetime

ROOT = Path(__file__).resolve().parents[1]


def request(base, route, method="GET", body=None):
    req = urllib.request.Request(base.rstrip("/") + route, data=body, method=method)
    with urllib.request.urlopen(req, timeout=30) as response:
        return response.read()


def install(base, config=None, launch=False):
    state = json.loads(request(base, "/api/system/state"))
    backup = ROOT/".runtime/backups"/datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    backup.mkdir(parents=True, mode=0o700)
    (backup/"state.json").write_text(json.dumps({"current_app": state.get("current_app")}, indent=2))
    files = sorted(f for f in (ROOT/"package").rglob("*") if f.is_file())
    prepared=[]
    # Back up every affected file before writing any file, including runtime config.
    for file in files:
        relative = file.relative_to(ROOT/"package")
        path = "/sd/apps/xiaobucubic/" + relative.as_posix()
        route = "/api/system/fs/file?path=" + urllib.parse.quote(path, safe="")
        old = None
        try: old = request(base, route)
        except urllib.error.HTTPError as error:
            if error.code != 404: raise
        if old is not None:
            target=backup/relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(old)
            target.chmod(0o600)
        data = config.read_bytes() if config and relative.as_posix()=="config.json" else file.read_bytes()
        # Updating the app without --config preserves its existing endpoint and token.
        if relative.as_posix()=="config.json" and not config and old is not None: data=old
        prepared.append((path,route,data,old))
    if (state.get("current_app") or {}).get("id")=="xiaobucubic":
        request(base,"/api/system/exit","POST",b"")
    try:
        for path,route,data,_ in prepared:
            request(base,"/api/system/fs/upload?path="+urllib.parse.quote(path,safe=""),"PUT",data)
            actual=request(base,route)
            if hashlib.sha256(actual).digest()!=hashlib.sha256(data).digest():
                raise RuntimeError("Upload verification failed: "+path)
            print("verified",path)
        result=json.loads(request(base,"/devtools/api/apps/rescan","POST",b""))
        if not result.get("ok"): raise RuntimeError("Application rescan failed")
    except Exception:
        # Restore existing files. Backups remain available if the network itself is down.
        for path,_,_,old in prepared:
            if old is not None:
                try: request(base,"/api/system/fs/upload?path="+urllib.parse.quote(path,safe=""),"PUT",old)
                except Exception: pass
        print("Installation failed; backups:",backup)
        raise
    if launch: request(base,"/api/system/launch?id=xiaobucubic","POST",b"")
    print("Installed xiaobucubic. Backup:",backup)


if __name__ == "__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("device",help="e.g. http://10.15.2.72")
    parser.add_argument("--config",type=Path,help="Local config.json with API URL and read token")
    parser.add_argument("--launch",action="store_true")
    args=parser.parse_args()
    install(args.device,args.config,args.launch)
