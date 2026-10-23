"""Boundary and lifecycle tests using Lua, not a reimplementation of the model."""
import json
import unittest
from pathlib import Path
from lupa import LuaRuntime

ROOT = Path(__file__).resolve().parents[1]


def lua_value(lua, value):
    if isinstance(value, dict): return lua.table_from({k: lua_value(lua,v) for k,v in value.items()})
    if isinstance(value, list): return lua.table_from([lua_value(lua,v) for v in value])
    return value


class DisplayTest(unittest.TestCase):
    def setUp(self):
        self.lua=LuaRuntime(unpack_returned_tuples=True)
        self.model=self.lua.execute((ROOT/"package/display_model.lua").read_text())
        self.fixture=json.loads((ROOT/"examples/display.json").read_text())

    def normalize(self, doc):
        return self.model.normalize(lua_value(self.lua,doc))

    def test_missing_is_not_zero(self):
        data=self.normalize(self.fixture)
        self.assertEqual(data.subscriptions[1].windows[1].used_percent,62)
        self.assertEqual(len(data.subscriptions[3].windows),0)
        self.fixture["subscriptions"][0]["windows"][0]["used_percent"]=0
        self.assertEqual(self.normalize(self.fixture).subscriptions[1].windows[1].used_percent,0)

    def test_invalid_version_and_time_rejected(self):
        for update in ({"schema_version":2},{"generated_at":None},{"subscriptions":"bad"}):
            with self.subTest(update=update):
                data,error=self.normalize(self.fixture|update)
                self.assertIsNone(data)
                self.assertTrue(error)

    def test_range_nan_and_utf8(self):
        for value in (-1, float("nan"), float("inf"), "34", 1001):
            self.fixture["subscriptions"][0]["windows"][0]["used_percent"]=value
            self.assertIsNone(self.normalize(self.fixture).subscriptions[1].windows[1].used_percent)
        self.assertEqual(self.model.text("中文测试"*60,"",40),"中文测试"*10)

    def test_expired_snapshot_does_not_claim_quota_reset(self):
        data=self.normalize(self.fixture)
        p=data.subscriptions[1]
        now=self.fixture["generated_at"]
        self.assertEqual(self.model.window_state(p,p.windows[1],now,900),"ok")
        p.windows[1].reset_at=now-1
        self.assertEqual(self.model.window_state(p,p.windows[1],now,900),"expired")
        self.assertEqual(p.windows[1].used_percent,62)
        self.assertEqual(self.model.window_state(p,p.windows[1],now+1000,900),"stale")
        self.assertTrue(self.model.is_stale(now,None,900))

    def test_limits_and_pagination(self):
        self.fixture["subscriptions"]=[dict(self.fixture["subscriptions"][0],id=str(n)) for n in range(30)]
        self.fixture["messages"]=[{"text":"test"} for _ in range(30)]
        data=self.normalize(self.fixture)
        self.assertEqual(len(data.subscriptions),3)
        self.assertEqual(len(data.messages),12)
        self.assertEqual(len(self.model.pages(data)),2)

    def test_remaining_and_long_message(self):
        data=self.normalize(self.fixture)
        self.assertEqual(self.model.remaining(data.subscriptions[1].windows[1]),38)
        self.assertIsNone(self.model.remaining(None))
        data.subscriptions[1].windows[1].used_percent=125
        self.assertEqual(self.model.remaining(data.subscriptions[1].windows[1]),0)
        chunks=self.model.message_chunks("中文"*90)
        self.assertEqual(len(chunks),3)
        self.assertEqual("".join(chunks.values()).replace("\n",""),"中文"*90)

    def test_empty_message_content_does_not_enable_message_page(self):
        self.fixture["messages"]=[{"text":""},{"text":" \n\t "},{}]
        data=self.normalize(self.fixture)
        self.assertEqual(len(data.messages),0)
        self.assertEqual(len(self.model.pages(data)),1)

    def test_weather_background_selection(self):
        for condition,asset in [("晴","sunny"),("多云","partly_cloudy"),("阴","overcast"),
                                ("小雨","rain"),("雷阵雨","rain"),("雨夹雪","rain"),("雾","overcast"),("未知","overcast"),("晴间多云","partly_cloudy")]:
            self.assertEqual(self.model.weather_asset(lua_value(self.lua,{"condition":condition})),asset)
        self.fixture["weather"].update(condition="晴",is_day=False)
        self.assertEqual(self.model.weather_asset(self.normalize(self.fixture).weather),"clear_night")

    def boot(self, wifi=False):
        lua=self.lua
        lua.globals().PY_MODEL=self.model
        lua.globals().PY_DOC=lua_value(lua,self.fixture)
        lua.execute('''
        labels={}; requests={}; writes={}; timers={}; nodes={}; node_id=1; cleans=0; mutations={}; images=0; mono=0; styles={}; long_modes={}
        LV_PART_MAIN=0; LV_OBJ_FLAG_SCROLLABLE=1; LV_TEXT_ALIGN_LEFT=0; LV_TEXT_ALIGN_RIGHT=1; LV_TEXT_ALIGN_CENTER=2
        LV_LABEL_LONG_WRAP=0; LV_LABEL_LONG_SCROLL=1; LV_LABEL_LONG_DOT=2; LV_GRAD_DIR_VER=1
        LV_FONT_MONTSERRAT_12=12; LV_FONT_MONTSERRAT_16=16; LV_FONT_MONTSERRAT_20=20; LV_FONT_MONTSERRAT_28=28
        dofile=function() return PY_MODEL end
        file={stat=function() return {} end,
          getcontents=function(path) if path:find('config.json') then return 'config' end end,
          putcontents=function(path,body) writes[#writes+1]={path,body}; return true end}
        sjson={decode=function(body)
          if body=='config' then return {api_url='http://localhost/v1/display'} end
          if body=='valid' then return PY_DOC end
          error('Invalid JSON')
        end,encode=function(doc) return 'cache' end}
        http={get=function(url,opts,callback) requests[#requests+1]=callback end}
        time={get=function() return PY_DOC.generated_at end}
        tmr={ALARM_AUTO=1,create=function()
          local t={alarm=function(self,ms,mode,cb) self.callback=cb end,
                   unregister=function(self) self.stopped=true end}
          timers[#timers+1]=t;return t
        end}
        key={SHORT=1,LEFT=2,RIGHT=3,UP=4,DOWN=5,HOME=6,
             on=function(cb) key.callback=cb end,off=function() key.callback=nil end}
        app={exiting=function() return false end,exit=function() app.exited=true end}
        lv_scr_act=function() return 0 end
        lv_obj_get_width=function() return 320 end;lv_obj_get_height=function() return 240 end
        lv_font_load=function() return 12 end;lv_font_free=function() end
        local create=function(parent) node_id=node_id+1;nodes[node_id]=parent;return node_id end
        lv_obj_create=create;lv_label_create=create
        lv_img_create=create;lv_img_set_src=function(id,path) image_path=path;images=images+1 end
        lv_obj_clean=function() labels={};nodes={};cleans=cleans+1 end
        lv_obj_del=function(id) labels[id]=nil;nodes[id]=nil end
        lv_obj_set_pos=function() end;lv_obj_set_size=function() end
        lv_obj_clear_flag=function() end;lv_label_set_long_mode=function(id,mode) long_modes[id]=mode end
        lv_label_set_text=function(id,value) assert(type(value)=='string');labels[id]=value;mutations[#mutations+1]={id=id,text=value} end
        for _,s in ipairs({'bg_color','bg_opa','bg_grad_color','bg_grad_dir','bg_main_stop','bg_grad_stop','border_width','radius','pad_all','text_font','text_color','text_align','text_line_space'}) do
          local prop=s
          _G['lv_obj_set_style_'..prop]=function(id,value) styles[id]=styles[id] or {};styles[id][prop]=value end
        end
        ''')
        if wifi:
            lua.execute("""
            wifi_ip=nil;wifi_attempts={}
            wifi={sta={getip=function() return wifi_ip end,
                connect=function() wifi_attempts[#wifi_attempts+1]=XIAOBUCUBIC.state.tick end}}
            """)
        lua.execute((ROOT/"package/main.lua").read_text())
        return lua.globals()

    def test_http_auth_error_keeps_last_good_snapshot(self):
        g=self.boot()
        g.requests[1](200,"valid")
        self.assertEqual(len(g.writes),1)
        g.XIAOBUCUBIC.refresh(True)
        g.requests[2](401,"bad")
        self.assertEqual(g.XIAOBUCUBIC.state.error,"接口鉴权失败")
        self.assertEqual(g.XIAOBUCUBIC.state.snapshot.subscriptions[1].windows[1].used_percent,62)
        self.assertEqual(len(g.writes),1)

    def test_timeout_and_late_callback_ignored(self):
        g=self.boot()
        for _ in range(16): g.timers[1].callback()
        self.assertEqual(g.XIAOBUCUBIC.state.error,"请求超时")
        g.requests[1](200,"valid")
        self.assertIsNone(g.XIAOBUCUBIC.state.snapshot)
        self.assertEqual(len(g.writes),0)

    def test_invalid_response_and_exit_cleanup(self):
        g=self.boot()
        g.requests[1](200,"malformed")
        self.assertIsNone(g.XIAOBUCUBIC.state.snapshot)
        g.XIAOBUCUBIC.refresh(True)
        g.key.callback(g.key.HOME,g.key.SHORT)
        g.requests[2](200,"valid")
        self.assertTrue(g.timers[1].stopped)
        self.assertTrue(g.app.exited)
        self.assertFalse(g.XIAOBUCUBIC.state.alive)
        self.assertEqual(len(g.writes),0)

    def test_all_pages_render_and_navigation(self):
        g=self.boot()
        g.requests[1](200,"valid")
        self.assertIn("38%",list(g.labels.values()))
        self.assertIn("28°C",list(g.labels.values()))
        for i in range(1,3):
            g.XIAOBUCUBIC.state.page=i
            g.XIAOBUCUBIC.render()
            self.assertIn("演示",list(g.labels.values()))
            self.assertNotIn("xiaobucubic",list(g.labels.values()))
            self.assertIn("在线",list(g.labels.values()))
        g.key.callback(g.key.RIGHT,g.key.SHORT)
        self.assertEqual(g.XIAOBUCUBIC.state.page,1)

    def test_no_messages_stays_home_even_after_navigation_and_timer(self):
        self.fixture["messages"]=[]
        g=self.boot()
        g.requests[1](200,"valid")
        self.assertEqual(len(self.model.pages(g.XIAOBUCUBIC.state.snapshot)),1)
        g.key.callback(g.key.RIGHT,g.key.SHORT)
        for _ in range(35):g.timers[1].callback()
        self.assertEqual(g.XIAOBUCUBIC.state.page,1)

    def test_messages_cycle_inside_two_views_and_removal_returns_home(self):
        g=self.boot();g.requests[1](200,"valid")
        for _ in range(15):g.timers[1].callback()
        self.assertEqual(g.XIAOBUCUBIC.state.page,2)
        self.assertEqual(g.XIAOBUCUBIC.state.message,1)
        for _ in range(30):g.timers[1].callback()
        self.assertEqual(g.XIAOBUCUBIC.state.page,2)
        self.assertEqual(g.XIAOBUCUBIC.state.message,2)
        self.fixture["messages"]=[]
        g.PY_DOC=lua_value(self.lua,self.fixture)
        g.XIAOBUCUBIC.refresh(True);g.requests[2](200,"valid")
        self.assertEqual(g.XIAOBUCUBIC.state.page,1)

    def use_extended_fixture(self):
        self.fixture=json.loads((ROOT/"tests/fixtures/display-v1-extended.json").read_text())

    def test_extended_sample_unknown_fields_and_decimals(self):
        self.use_extended_fixture()
        self.fixture["unknown_root"]={"anything": True}
        self.fixture["subscriptions"][0]["new_field"]=[1,2]
        self.fixture["subscriptions"][0]["windows"][0]["new_field"]="ignored"
        self.fixture["messages"][0]["new_field"]={}
        self.fixture["weather"].update(new_field="ignored",pressure_hpa=1011.4)
        data=self.normalize(self.fixture)
        self.assertEqual(data.weather.temperature_c,28.5)
        self.assertEqual(data.weather.wind_kmh,10.5)
        self.assertEqual(data.weather.pressure_hpa,1011.4)
        self.assertEqual(data.messages[1].expires_at,1792664640)
        g=self.boot();g.requests[1](200,"valid")
        self.assertIn("60%",list(g.labels.values()))
        self.assertIn("75%",list(g.labels.values()))
        for value in ("23–32°C","51%","1011 hPa"):
            self.assertIn(value,list(g.labels.values()))
        self.assertEqual(g.XIAOBUCUBIC.state.background,"partly_cloudy")

    def test_fractional_remaining_floors_and_single_window_up(self):
        self.use_extended_fixture()
        self.fixture["subscriptions"][0]["windows"][0]["used_percent"]=33.5
        g=self.boot();g.requests[1](200,"valid")
        self.assertIn("66%",list(g.labels.values()))
        g.key.callback(g.key.UP,g.key.SHORT)
        self.assertIn("83%",list(g.labels.values()))
        self.assertIn("75%",list(g.labels.values()))
        self.fixture["subscriptions"]=self.fixture["subscriptions"][1:]
        self.fixture["subscriptions"][0]["windows"][0].update(used_percent=99.6,label="123分钟")
        g.PY_DOC=lua_value(self.lua,self.fixture);g.requests[2](200,"valid")
        for _ in range(3):g.key.callback(g.key.UP,g.key.SHORT)
        self.assertEqual(g.XIAOBUCUBIC.state.window,1)
        self.assertIn("0%",list(g.labels.values()))
        self.assertTrue(any("123分钟" in s for s in g.labels.values()))

    def test_offline_expiry_exact_boundary_even_when_rotation_paused(self):
        self.use_extended_fixture()
        g=self.boot()
        self.lua.execute("tmr.time=function() return mono end; time.get=function() return 2000000000 end")
        g.requests[1](200,"valid")
        g.key.callback(g.key.RIGHT,g.key.SHORT)
        g.key.callback(g.key.DOWN,g.key.SHORT)
        g.XIAOBUCUBIC.refresh(True);g.requests[2](503,"")
        self.assertEqual(g.XIAOBUCUBIC.state.page,2)
        g.mono=59;g.timers[1].callback()
        self.assertEqual(g.XIAOBUCUBIC.state.page,2)
        # Simulates elapsed real time while the event loop was asleep, and a wrong RTC.
        g.mono=60;g.timers[1].callback()
        self.assertEqual(g.XIAOBUCUBIC.state.page,1)
        self.assertEqual(g.XIAOBUCUBIC.state.active_count,0)
        self.assertEqual(len(g.writes),1)
        self.assertEqual(len(g.XIAOBUCUBIC.state.snapshot.messages),1) # cache untouched

    def test_unknown_clock_hides_expiring_cache_messages_only(self):
        self.use_extended_fixture()
        data=self.normalize(self.fixture)
        self.assertEqual(len(self.model.active_messages(data,None)),0)
        data.messages[1].expires_at=None
        self.assertEqual(len(self.model.active_messages(data,None)),1)

    def test_message_line_breaks_and_bounded_pages(self):
        self.fixture["messages"]=[{"title":"消息","text":"第一行\r\n第二行\n\n第四行"}]
        data=self.normalize(self.fixture)
        self.assertEqual(data.messages[1].text,"第一行\n第二行\n\n第四行")
        chunks=self.model.message_chunks(data.messages[1].text)
        self.assertEqual(chunks[1],data.messages[1].text)
        for value in ("中"*180,"a"*180,"第一行\n"*20):
            for chunk in self.model.message_chunks(value).values():
                self.assertLessEqual(len(chunk.split("\n")),7)
                self.assertTrue(all(len(line)<=12 for line in chunk.split("\n")))
        g=self.boot();g.requests[1](200,"valid");g.key.callback(g.key.RIGHT,g.key.SHORT)
        self.assertIn("第一行\n第二行\n\n第四行",list(g.labels.values()))

    def test_poll_only_updates_changed_quota_and_keeps_background(self):
        self.fixture["messages"]=[]
        g=self.boot();g.requests[1](200,"valid")
        cleans,nodes,images=g.cleans,g.node_id,g.images
        writes=len(g.mutations)
        g.XIAOBUCUBIC.refresh(True);g.requests[2](200,"valid")
        self.assertEqual(len(g.mutations),writes)
        self.fixture["subscriptions"][0]["windows"][0]["used_percent"]=33.5
        g.PY_DOC=lua_value(self.lua,self.fixture)
        g.XIAOBUCUBIC.refresh(True);g.requests[3](200,"valid")
        self.assertEqual([g.mutations[i].text for i in range(writes+1,len(g.mutations)+1)],["66%"])
        self.assertEqual((g.cleans,g.node_id,g.images),(cleans,nodes,images))
        self.fixture["weather"]["condition"]="雷阵雨"
        g.PY_DOC=lua_value(self.lua,self.fixture)
        g.XIAOBUCUBIC.refresh(True);g.requests[4](200,"valid")
        self.assertEqual(g.cleans,cleans)
        self.assertEqual(g.images,images+1)
        self.assertEqual(g.XIAOBUCUBIC.state.background,"rain")

    def test_quota_warning_boundaries_and_translucent_vertical_gradient(self):
        self.fixture["messages"]=[]
        g=self.boot();g.requests[1](200,"valid")
        for remaining,level,color in [(20,"normal",0xFFC078),(19,"low",0xFFD166),
                                      (5,"low",0xFFD166),(4,"critical",0xFF5F6D),(0,"critical",0xFF5F6D)]:
            self.assertEqual(self.model.quota_level(remaining),level)
            self.fixture["subscriptions"][0]["windows"][0]["used_percent"]=100-remaining
            g.PY_DOC=lua_value(self.lua,self.fixture)
            g.XIAOBUCUBIC.refresh(True);g.requests[len(g.requests)](200,"valid")
            label=next(i for i,text in g.labels.items() if text==str(remaining)+"%")
            self.assertEqual(g.styles[label].text_color,color)
            panel=g.nodes[label]
            self.assertEqual(g.styles[panel].bg_opa,52)
            fill=next(i for i,parent in g.nodes.items() if parent==panel and g.styles[i].bg_grad_dir==1)
            self.assertEqual(g.styles[fill].bg_color,color)
            self.assertEqual(g.styles[fill].bg_main_stop,0)
            self.assertEqual(g.styles[fill].bg_grad_stop,255)
            self.assertNotEqual(g.styles[fill].bg_grad_color,color)
            self.assertEqual(g.styles[fill].bg_opa,64 if remaining else 0)
            opacity=1-(1-g.styles[panel].bg_opa/255)*(1-g.styles[fill].bg_opa/255)
            self.assertLess(opacity,0.5) # Both card layers must let weather through.
        self.assertEqual(self.model.quota_level(None),"unknown")

    def test_claude_companion_window_and_incremental_updates(self):
        self.use_extended_fixture()
        g=self.boot();g.requests[1](200,"valid")
        self.assertIn("7天 83%",list(g.labels.values()))
        for text in ("5小时 · 1小时后重置","7天 83%"):
            label=next(i for i,v in g.labels.items() if v==text)
            self.assertEqual(g.long_modes[label],g.LV_LABEL_LONG_DOT)
        self.assertIsNone(self.model.companion_window(g.XIAOBUCUBIC.state.snapshot.subscriptions[2],1))
        cleans,nodes=g.cleans,g.node_id
        self.fixture["subscriptions"][0]["windows"][1]["used_percent"]=81
        g.PY_DOC=lua_value(self.lua,self.fixture)
        g.XIAOBUCUBIC.refresh(True);g.requests[2](200,"valid")
        label=next(i for i,v in g.labels.items() if v=="7天 19%")
        self.assertEqual(g.styles[label].text_color,0xFFD166)
        self.assertEqual((g.cleans,g.node_id),(cleans,nodes))
        g.key.callback(g.key.UP,g.key.SHORT)
        self.assertIn("19%",list(g.labels.values()))
        self.assertIn("5小时 60%",list(g.labels.values()))
        self.fixture["subscriptions"][0]["windows"]=self.fixture["subscriptions"][0]["windows"][:1]
        g.PY_DOC=lua_value(self.lua,self.fixture);g.requests[3](200,"valid")
        self.assertNotIn("5小时 60%",list(g.labels.values()))
        self.assertNotIn("7天 19%",list(g.labels.values()))
        self.assertIn("60%",list(g.labels.values()))

    def test_companion_unknown_zero_and_expired(self):
        self.use_extended_fixture()
        self.fixture["subscriptions"][0]["windows"][1].update(label="本期",used_percent=None)
        g=self.boot();g.requests[1](200,"valid")
        self.assertIn("本期 --",list(g.labels.values()))
        self.fixture["subscriptions"][0]["windows"][1].update(used_percent=100,reset_at=self.fixture["generated_at"]-1)
        g.PY_DOC=lua_value(self.lua,self.fixture)
        g.XIAOBUCUBIC.refresh(True);g.requests[2](200,"valid")
        label=next(i for i,v in g.labels.items() if v=="本期 0% · 待刷新")
        self.assertEqual(g.styles[label].text_color,0xFF5F6D)

    def test_message_update_keeps_selection_and_partial_render(self):
        self.fixture["messages"]=[{"id":"a","title":"A","text":"第一条"},
                                  {"id":"b","title":"B","text":"第二条","updated_at":1}]
        g=self.boot();g.requests[1](200,"valid")
        g.key.callback(g.key.RIGHT,g.key.SHORT);g.key.callback(g.key.UP,g.key.SHORT)
        cleans=g.cleans
        self.fixture["messages"][1].update(text="已更新\n请查看",updated_at=2)
        self.fixture["messages"].reverse()
        g.PY_DOC=lua_value(self.lua,self.fixture)
        g.XIAOBUCUBIC.refresh(True);g.requests[2](200,"valid")
        self.assertEqual(g.XIAOBUCUBIC.state.message_key,"b")
        self.assertIn("已更新\n请查看",list(g.labels.values()))
        self.assertEqual(g.cleans,cleans)

    def test_all_documented_weather_conditions(self):
        groups={"sunny":"晴", "partly_cloudy":"晴间多云 多云",
                "overcast":"阴 雾 雾凇 未知",
                "snow":"小雪 中雪 大雪 雪粒 阵雪 强阵雪",
                "rain":"小毛毛雨 毛毛雨 大毛毛雨 冻毛毛雨 小雨 中雨 大雨 冻雨 阵雨 中阵雨 强阵雨 雷阵雨 雷阵雨伴冰雹 强雷阵雨伴冰雹"}
        for expected,conditions in groups.items():
            for condition in conditions.split():
                with self.subTest(condition=condition):
                    self.assertEqual(self.model.weather_asset(lua_value(self.lua,{"condition":condition})),expected)

    def test_default_poll_and_retry_recovery(self):
        self.fixture["messages"]=[]
        g=self.boot();g.requests[1](200,"valid")
        for _ in range(59):g.timers[1].callback()
        self.assertEqual(len(g.requests),1)
        g.timers[1].callback();self.assertEqual(len(g.requests),2)
        g.requests[2](403,"bad")
        self.assertEqual(g.XIAOBUCUBIC.state.error,"接口鉴权失败")
        for _ in range(4):g.timers[1].callback()
        self.assertEqual(len(g.requests),2)
        g.timers[1].callback();self.assertEqual(len(g.requests),3)
        self.assertEqual(len(g.writes),1)
        g.requests[3](200,"valid")
        self.assertEqual(g.XIAOBUCUBIC.state.failures,0)
        self.assertIsNone(g.XIAOBUCUBIC.state.next_retry)
        for _ in range(59):g.timers[1].callback()
        self.assertEqual(len(g.requests),3)
        g.timers[1].callback();self.assertEqual(len(g.requests),4)
        g.requests[4](503,"")
        self.assertEqual(g.XIAOBUCUBIC.state.next_retry-g.XIAOBUCUBIC.state.tick,5)

    def test_retry_progresses_to_five_minutes_and_stays_capped(self):
        self.fixture["messages"]=[]
        g=self.boot()
        for delay in [5,10,20,40,80,160,300,300,300]:
            count=len(g.requests)
            g.requests[count](503,"")
            for _ in range(delay-1):g.timers[1].callback()
            self.assertEqual(len(g.requests),count)
            g.timers[1].callback()
            self.assertEqual(len(g.requests),count+1)
        self.assertEqual(len(g.writes),0)

    def test_timeout_waits_before_retry_and_never_overlaps(self):
        g=self.boot()
        for _ in range(15):g.timers[1].callback()
        self.assertEqual(len(g.requests),1)
        g.timers[1].callback() # application timeout at 16 seconds
        self.assertEqual(g.XIAOBUCUBIC.state.next_retry,21)
        for _ in range(4):g.timers[1].callback()
        self.assertEqual(len(g.requests),1)
        g.timers[1].callback();self.assertEqual(len(g.requests),2)
        g.requests[1](200,"valid") # delayed first response must remain ignored
        self.assertTrue(g.XIAOBUCUBIC.state.busy)
        self.assertIsNone(g.XIAOBUCUBIC.state.snapshot)
        g.requests[2](200,"valid")
        self.assertEqual(len(g.writes),1)

    def test_wifi_reconnect_backoff_and_prompt_recovery(self):
        self.fixture["messages"]=[]
        g=self.boot(wifi=True)
        self.assertEqual(len(g.wifi_attempts),1)
        self.assertEqual(len(g.requests),0)
        for delay in [5,10,20,40,80,160,300]:
            count=len(g.wifi_attempts)
            for _ in range(delay-1):g.timers[1].callback()
            self.assertEqual(len(g.wifi_attempts),count)
            g.timers[1].callback();self.assertEqual(len(g.wifi_attempts),count+1)
        self.assertEqual(len(g.requests),0)
        g.wifi_ip="10.15.2.72"
        g.timers[1].callback() # don't wait another 300 seconds after getting an IP
        self.assertEqual(len(g.requests),1)
        g.requests[1](200,"valid")
        count=len(g.wifi_attempts)
        for _ in range(59):g.timers[1].callback()
        self.assertEqual(len(g.requests),1)
        self.assertEqual(len(g.wifi_attempts),count)
        g.wifi_ip=None;g.timers[1].callback()
        self.assertEqual(len(g.wifi_attempts),count+1)
        self.assertEqual(g.XIAOBUCUBIC.state.next_retry-g.XIAOBUCUBIC.state.tick,5)
        self.assertEqual(len(g.writes),1)
        g.key.callback(g.key.HOME,g.key.SHORT)
        g.XIAOBUCUBIC.refresh(True)
        self.assertEqual(len(g.wifi_attempts),count+1)

    def test_http_backoff_does_not_reconnect_healthy_wifi(self):
        g=self.boot(wifi=True)
        g.wifi_ip="10.15.2.72";g.timers[1].callback()
        count=len(g.wifi_attempts)
        g.requests[1](503,"")
        for _ in range(5):g.timers[1].callback()
        self.assertEqual(len(g.requests),2)
        self.assertEqual(len(g.wifi_attempts),count)

    def test_retry_uses_elapsed_time_and_handles_network_api_exception(self):
        g=self.boot()
        self.lua.execute("tmr.time=function() return mono end")
        g.requests[1](503,"")
        g.mono=4;g.timers[1].callback()
        self.assertEqual(len(g.requests),1)
        g.mono=100;g.timers[1].callback()
        self.assertEqual(len(g.requests),2)
        g.requests[2](503,"")
        self.lua.execute("http.get=function() error('network unavailable') end")
        g.mono=110;g.timers[1].callback()
        self.assertEqual(g.XIAOBUCUBIC.state.error,"网络接口不可用")
        self.assertEqual(g.XIAOBUCUBIC.state.next_retry,130)


if __name__ == "__main__": unittest.main()
