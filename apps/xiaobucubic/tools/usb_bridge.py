#!/usr/bin/env python3
"""Fetch display data over USB; notify compatible devices when Wi-Fi fallback is needed."""
import argparse
import glob
import getpass
import json
import time
import urllib.request
import urllib.error
from pathlib import Path
import serial

PREFIX=b'XBC1 '


def exchange(port, frame, timeout=8):
    port.write(PREFIX+json.dumps(frame,ensure_ascii=False,separators=(',',':')).encode()+b'\n')
    port.flush()
    deadline=time.monotonic()+timeout
    while time.monotonic()<deadline:
        line=port.readline()
        start=line.find(PREFIX)
        if start<0: continue
        try: reply=json.loads(line[start+len(PREFIX):])
        except (ValueError,UnicodeError):continue
        if reply.get('id')!=frame['id']:continue
        if reply.get('status')!='ok':raise RuntimeError(reply.get('error','Device rejected frame'))
        return reply
    raise TimeoutError('No USB acknowledgement')


def send_display(port, data):
    if not isinstance(data,dict) or data.get('schema_version')!=1:
        raise ValueError('Unsupported display response')
    body=json.dumps(data,ensure_ascii=False,separators=(',',':'))
    size=len(body.encode())
    if not 0<size<=24576:raise ValueError('Display response exceeds 24 KiB')
    request_id=str(time.time_ns())
    exchange(port,{'id':request_id,'type':'begin','bytes':size})
    for pos in range(0,len(body),128):
        exchange(port,{'id':request_id,'type':'chunk','data':body[pos:pos+128]})
    return exchange(port,{'id':request_id,'type':'commit'})


def fetch(config):
    headers={'Accept':'application/json'}
    if config.get('read_token'):headers['Authorization']='Bearer '+config['read_token']
    request=urllib.request.Request(config['api_url'],headers=headers)
    with urllib.request.urlopen(request,timeout=20) as response:
        raw=response.read(24577)
    if len(raw)>24576:raise ValueError('Display response exceeds 24 KiB')
    return json.loads(raw)


def open_port(path):
    # Set control lines before opening; keep the handle open between updates.
    port=serial.Serial(port=None,baudrate=115200,timeout=0.3,write_timeout=5)
    port.dtr=False;port.rts=False;port.port=path;port.open()
    return port


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config',required=True,type=Path)
    parser.add_argument('--port',help='Defaults to the single attached cu.usbmodem device')
    parser.add_argument('--once',action='store_true')
    parser.add_argument('--usb-only',action='store_true',help='Persist USB mode and erase device Wi-Fi credentials after delivery succeeds')
    parser.add_argument('--status',action='store_true')
    parser.add_argument('--configure-wifi',metavar='SSID',help='Save a fallback network over USB on a compatible device')
    parser.add_argument('--wifi-password-file',type=Path,help='Private UTF-8 password file; otherwise prompt without echo')
    args=parser.parse_args()
    if args.configure_wifi and args.usb_only:parser.error("Choose Wi-Fi fallback or USB-only mode")
    while True:
        try:
            config=json.loads(args.config.read_text())
            ports=[args.port] if args.port else glob.glob('/dev/cu.usbmodem*')
            if len(ports)!=1:raise RuntimeError('Expected one USB device; specify --port')
            with open_port(ports[0]) as port:
                # Some USB serial drivers reset the board on first open. Wait for
                # Launcher to start the app, then reuse this port for every poll.
                ready=None
                while ready is None:
                    try:
                        ready=exchange(port,{'id':str(time.time_ns()),'type':'status'},8)
                        break
                    except TimeoutError:
                        if args.once or args.status or args.configure_wifi:raise
                        print("Waiting for display app on the existing USB connection",flush=True)
                        time.sleep(5)
                if args.configure_wifi:
                    if not ready.get('can_configure_wifi'):raise RuntimeError('Device app does not support USB configuration yet')
                    password=args.wifi_password_file.read_text().rstrip('\r\n') if args.wifi_password_file else getpass.getpass('Wi-Fi password: ')
                    ready=exchange(port,{'id':str(time.time_ns()),'type':'wifi_config','ssid':args.configure_wifi,'password':password})
                    password=None
                    print('Fallback Wi-Fi saved:',ready.get('saved_ssid'),flush=True)
                    args.configure_wifi=None
                if args.status:
                    print(json.dumps(ready,ensure_ascii=False),flush=True);return
                print("USB connected:",json.dumps(ready,ensure_ascii=False),flush=True)
                while True:
                    config=json.loads(args.config.read_text())
                    try:
                        reply=send_display(port,fetch(config))
                        print('USB synchronized:',reply.get('generated_at'),flush=True)
                    except (urllib.error.URLError,ValueError,TimeoutError) as error:
                        print('API retry:',type(error).__name__,flush=True)
                        if ready.get('can_fallback'):
                            exchange(port,{'id':str(time.time_ns()),'type':'upstream_unavailable'})
                        if args.once:raise
                        time.sleep(10);continue
                    if args.usb_only:
                        print(json.dumps(exchange(port,{'id':str(time.time_ns()),'type':'usb_only'}),ensure_ascii=False),flush=True)
                        args.usb_only=False
                    if args.once:return
                    time.sleep(max(15,min(3600,int(config.get('refresh_seconds',60)))))
        except Exception as error:
            # Avoid logging request URLs, headers, payloads or credentials.
            print('USB bridge retry:',type(error).__name__,flush=True)
            if args.once or args.status:raise SystemExit(1)
            time.sleep(10)


if __name__=='__main__':main()
