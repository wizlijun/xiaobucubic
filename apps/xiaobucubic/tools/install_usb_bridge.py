#!/usr/bin/env python3
"""Install the USB display bridge as a macOS login agent using an existing Python environment."""
import argparse
import os
from pathlib import Path
import plistlib
import subprocess

LABEL='local.xiaobucubic.usb-bridge'
ROOT=Path(__file__).resolve().parents[1]


def install(python,config):
    config=config.resolve();python=python.absolute()
    if not config.is_file() or not python.is_file():raise RuntimeError('Python or configuration missing')
    config.chmod(0o600)
    runtime=ROOT/'.runtime/usb-bridge';runtime.mkdir(parents=True,mode=0o700,exist_ok=True)
    agents=Path.home()/'Library/LaunchAgents';agents.mkdir(parents=True,exist_ok=True)
    target=agents/(LABEL+'.plist')
    if target.exists():(runtime/'launchagent-before.plist').write_bytes(target.read_bytes())
    doc={'Label':LABEL,'ProgramArguments':[str(python),str(ROOT/'tools/usb_bridge.py'),'--config',str(config)],
         'WorkingDirectory':str(ROOT),'RunAtLoad':True,'KeepAlive':True,'ThrottleInterval':10,
         'StandardOutPath':str(runtime/'bridge.log'),'StandardErrorPath':str(runtime/'bridge-error.log'),
         'EnvironmentVariables':{'PYTHONUNBUFFERED':'1'}}
    domain='gui/'+str(os.getuid())
    subprocess.run(['launchctl','bootout',domain+'/'+LABEL],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    target.write_bytes(plistlib.dumps(doc));target.chmod(0o600)
    subprocess.run(['launchctl','bootstrap',domain,str(target)],check=True)
    print('Installed:',LABEL)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--python',required=True,type=Path)
    parser.add_argument('--config',required=True,type=Path)
    args=parser.parse_args();install(args.python,args.config)
