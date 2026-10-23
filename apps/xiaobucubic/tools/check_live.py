#!/usr/bin/env python3
"""Verify real API polling and capture the live device screen, without logging tokens."""
import argparse
import json
import time
import urllib.parse
from deploy import ROOT, request


def run(base):
    qa='/sd/apps/xiaobucubic_liveqa/'
    out=ROOT/'.runtime/live-check'
    out.mkdir(parents=True,exist_ok=True)
    quote=lambda s:urllib.parse.quote(s,safe='')
    def upload(name,data):request(base,'/api/system/fs/upload?path='+quote(qa+name),'PUT',data)
    upload('app.info',b'name = Xiaobu Live Check\nkind = app\nentry = main.lua\n')
    upload('main.lua',(ROOT/'tests/device_live_probe.lua').read_bytes())
    try:
        request(base,'/devtools/api/apps/rescan','POST',b'')
        request(base,'/api/system/launch?id=xiaobucubic_liveqa','POST',b'')
        result=None
        for _ in range(95):
            time.sleep(1)
            try:result=json.loads(request(base,'/api/system/fs/file?path='+quote(qa+'result.json')))
            except Exception:continue
            if result.get('done'):break
        (out/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
        assert result and result.get('done') and not result.get('error'),f'Live check failed: {out}/result.json'
        assert len(result['receipts'])>=2
        delta=result['receipts'][1]['received_at']-result['receipts'][0]['received_at']
        assert 55<=delta<=75,f'Unexpected poll interval: {delta}'
        assert result['connection']=='已同步' and not result['snapshot']['demo']
        assert result['background'] and result['images'],'Weather image not selected'
        assert result['screenshot'],result.get('screenshot_error')
        assert not result.get('font_errors'),result.get('font_errors')
        assert result.get('message_screenshot'),result.get('message_screenshot_error')
        assert result['incremental_cleans']==0,'Poll cleared the screen'
        assert result['message_labels_unchanged'],'Identical render rewrote labels'
        if not result['snapshot']['messages']:assert result['view']==1
        shot=request(base,'/api/system/fs/file?path='+quote(qa+'home.png'))
        (out/'home.png').write_bytes(shot)
        (out/'messages.png').write_bytes(request(base,'/api/system/fs/file?path='+quote(qa+'messages.png')))
        print('PASS: two live API responses, interval',delta,'seconds; background',result['background'])
        print('Display:',json.dumps(list(result['labels'].values()),ensure_ascii=False))
        print('Screenshot:',out/'home.png')
    finally:
        request(base,'/api/system/launch?id=xiaobucubic','POST',b'')
        request(base,'/devtools/api/rmdir?path='+quote(qa.rstrip('/'))+'&recursive=1','DELETE')
        request(base,'/devtools/api/apps/rescan','POST',b'')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('device')
    run(parser.parse_args().device)
