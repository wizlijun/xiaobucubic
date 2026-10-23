#!/usr/bin/env python3
"""Temporary QA app: collect screenshots, remove QA app, then launch xiaobucubic."""
import argparse
import json
import time
import urllib.parse
from pathlib import Path
from deploy import ROOT, request


def run(base):
    qa="/sd/apps/xiaobucubic_qa/"
    out=ROOT/".runtime/device-qa"
    out.mkdir(parents=True,exist_ok=True)
    quote=lambda p: urllib.parse.quote(p,safe="")
    def upload(name, data): request(base,"/api/system/fs/upload?path="+quote(qa+name),"PUT",data)
    upload("app.info",b"name = xiaobucubic QA\nkind = app\nentry = main.lua\nversion = 1\n")
    upload("main.lua",(ROOT/"tests/device_probe.lua").read_bytes())
    try:
        request(base,"/devtools/api/apps/rescan","POST",b"")
        request(base,"/api/system/launch?id=xiaobucubic_qa","POST",b"")
        result=None
        for _ in range(40):
            time.sleep(1)
            try: result=json.loads(request(base,"/api/system/fs/file?path="+quote(qa+"result.json")))
            except Exception: continue
            if result.get("done"):break
        (out/"result.json").write_text(json.dumps(result,ensure_ascii=False,indent=2))
        if not result or not result.get("done") or result.get("error"):
            raise RuntimeError(f"Probe failed; see {out}/result.json")
        if result.get("font_errors"):raise RuntimeError("Font errors: "+str(result["font_errors"]))
        for row in result["pages"]:
            if not row.get("screenshot"): raise RuntimeError("Screenshot failed: "+str(row))
            name="page-"+str(row["page"])+".png"
            # Lua tostring on numeric division can produce a '.0' suffix.
            try: image=request(base,"/api/system/fs/file?path="+quote(qa+name))
            except Exception: image=request(base,"/api/system/fs/file?path="+quote(qa+"page-"+str(row["page"])+".0.png"))
            (out/name).write_bytes(image)
        assert result["pages"][2]["actual_view"]==1,"Empty messages did not return to home"
        home_text=list(result["pages"][0]["labels"].values())
        assert "38%" in home_text and "28°C" in home_text,"Remaining quota/weather missing"
        print("PASS: API, fonts, two views, empty-message home, secondary quota:",out)
    finally:
        request(base,"/api/system/launch?id=xiaobucubic","POST",b"")
        request(base,"/devtools/api/rmdir?path="+quote(qa.rstrip('/'))+"&recursive=1","DELETE")
        request(base,"/devtools/api/apps/rescan","POST",b"")


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("device")
    run(parser.parse_args().device)
