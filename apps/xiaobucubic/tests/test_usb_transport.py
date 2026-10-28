"""Exercise the real Lua USB framing, including malformed and incomplete transfers."""
import json
import unittest
from pathlib import Path
from lupa import LuaRuntime

ROOT=Path(__file__).resolve().parents[1]

class UsbTest(unittest.TestCase):
    def setUp(self):
        self.lua=LuaRuntime(unpack_returned_tuples=True)
        def convert(value):
            if isinstance(value,dict):return self.lua.table_from({k:convert(v) for k,v in value.items()})
            if isinstance(value,list):return self.lua.table_from([convert(v) for v in value])
            return value
        self.lua.globals().decode=lambda raw:convert(json.loads(raw))
        self.lua.execute('''
        replies={};bodies={};clock=0;disabled=false;fallback=false
        sjson={decode=decode,encode=function(value) replies[#replies+1]=value;return '{}' end}
        uart={setup=function() end,on=function(_,_,fn) receive=fn end,write=function() end}
        tmr={time=function() return clock end}
        options={status=function() return {transport='usb'} end,
          usb_only=function() disabled=true end,upstream_unavailable=function() fallback=true end,
          configure_wifi=function(ssid,password) assert(ssid=="ap24");configured=true end,
          accept=function(body) bodies[#bodies+1]=body;return true end}
        ''')
        self.module=self.lua.execute((ROOT/'package/usb_transport.lua').read_text())
        self.module.start(self.lua.globals().options)
        self.g=self.lua.globals()

    def send(self,kind,**extra):
        self.g.receive('XBC1 '+json.dumps({'id':'test','type':kind,**extra},ensure_ascii=False)+'\n')
        return self.g.replies[len(self.g.replies)]

    def test_unicode_chunks_and_commit(self):
        body='{"text":"USB中文测试"}'
        self.send('begin',bytes=len(body.encode()))
        self.send('chunk',data=body[:10]);self.send('chunk',data=body[10:])
        self.assertEqual(self.send('commit').status,'ok')
        self.assertEqual(list(self.g.bodies.values()),[body])
        self.assertEqual(self.send('commit').status,'error')

    def test_wrong_length_and_timeout_never_apply(self):
        self.send('begin',bytes=3);self.send('chunk',data='ab')
        self.assertEqual(self.send('commit').status,'error')
        self.send('begin',bytes=3)
        self.assertEqual(self.send('chunk',data='abcd').status,'error')
        self.send('begin',bytes=3);self.g.clock=31
        self.assertEqual(self.send('chunk',data='abc').status,'error')
        self.assertEqual(len(self.g.bodies),0)

    def test_upstream_failure_notifies_fallback_without_applying_data(self):
        self.assertEqual(self.send('upstream_unavailable').status,'ok')
        self.assertTrue(self.g.fallback)
        self.assertEqual(len(self.g.bodies),0)

    def test_wifi_configuration_ack_does_not_echo_password(self):
        reply=self.send('wifi_config',ssid='ap24',password='test-only-secret')
        self.assertEqual(reply.status,'ok');self.assertTrue(self.g.configured)
        self.assertIsNone(reply.password)
        self.assertEqual(self.send('wifi_config',ssid='bad',password='test-only-secret').status,'error')

    def test_mode_switch_and_bad_input(self):
        self.g.receive('XBC1 {broken\n');self.g.receive('console noise\n')
        self.assertEqual(len(self.g.replies),0)
        self.assertEqual(self.send('usb_only').status,'ok');self.assertTrue(self.g.disabled)
        self.assertEqual(self.send('status').transport,'usb')

if __name__=='__main__':unittest.main()
