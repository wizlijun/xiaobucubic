#!/usr/bin/env python3
"""Verify 5s/10s HTTP retries and recovery on hardware without disconnecting Wi-Fi."""
import argparse
import json
import time
import urllib.parse
from deploy import ROOT, request


def run(base):
    qa='/sd/apps/xiaobucubic_retryqa/'
    out=ROOT/'.runtime/retry-check'
    out.mkdir(parents=True,exist_ok=True)
    quote=lambda s: urllib.parse.quote(s,safe='')
    def upload(name,data):
        request(base,'/api/system/fs/upload?path='+quote(qa+name),'PUT',data)
    try:
        upload('app.info',b'name = Xiaobu Retry Check\nkind = app\nentry = main.lua\n')
        upload('main.lua',(ROOT/'tests/device_retry_probe.lua').read_bytes())
        request(base,'/devtools/api/apps/rescan','POST',b'')
        request(base,'/api/system/launch?id=xiaobucubic_retryqa','POST',b'')
        result=None
        for _ in range(48):
            time.sleep(1)
            try:
                result=json.loads(request(base,'/api/system/fs/file?path='+quote(qa+'result.json')))
            except Exception:
                continue
            if result.get('done'):break
        (out/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
        assert result and result.get('done') and not result.get('error'),f'Retry check failed: {out}/result.json'
        attempts=result['attempts']
        intervals=[attempts[i+1]['at']-attempts[i]['at'] for i in range(2)]
        assert 5<=intervals[0]<=6 and 10<=intervals[1]<=11,intervals
        assert [r['code'] for r in attempts[:2]]==[-1,-1]
        assert attempts[2]['code']==200 and result['connection']=='已同步'
        assert result['failures']==0 and result.get('next_retry') is None
        print('PASS: injected failures retried after',intervals,'seconds; real API recovered, retry counter reset')
        print('Evidence:',out/'result.json')
    finally:
        request(base,'/api/system/launch?id=xiaobucubic','POST',b'')
        request(base,'/devtools/api/rmdir?path='+quote(qa.rstrip('/'))+'&recursive=1','DELETE')
        request(base,'/devtools/api/apps/rescan','POST',b'')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('device')
    run(parser.parse_args().device)
