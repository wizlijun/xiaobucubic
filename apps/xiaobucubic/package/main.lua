-- xiaobucubic / ClocTeck Lua + LVGL. API contract: GET /v1/display.
local BASE="/sd/apps/xiaobucubic/"
local model=dofile(BASE.."display_model.lua")
local codec=sjson or json
local C={bg=0x070C12,panel=0x111C28,line=0x203142,text=0xF0F5FC,muted=0x8497AC,
  mint=0x6DE1C2,blue=0x83B6FF,amber=0xFFC078,yellow=0xFFD166,red=0xFF5F6D}
local cfg={api_url="",read_token="",refresh_seconds=60,rotate_seconds=15,auto_rotate=true}
local state={alive=true,busy=false,tick=0,page=1,window=1,message=1,message_part=1,last_fetch=-10000,request_id=0,
  last_received=nil,rotate_at=15,connection="等待配置",snapshot=nil,error=nil,failures=0}
local fonts={}
local ui={nodes={},props={}}

local function decode(raw)
  if type(raw)~="string" or #raw>24576 then return nil end
  local ok,value=pcall(codec.decode,raw)
  return ok and type(value)=="table" and value or nil
end
local function read_json(path)
  local ok,raw=pcall(file.getcontents,path)
  return ok and decode(raw) or nil
end
local loaded=read_json(BASE.."config.json") or {}
cfg.api_url=model.text(loaded.api_url,"",1024)
cfg.read_token=model.text(loaded.read_token,"",512)
cfg.refresh_seconds=model.number(loaded.refresh_seconds,15,3600) or 60
cfg.rotate_seconds=model.number(loaded.rotate_seconds,8,120) or 15
cfg.auto_rotate=loaded.auto_rotate~=false
state.rotate_at=cfg.rotate_seconds
local cached=read_json(BASE.."cache.json")
if cached then state.snapshot=model.normalize(cached);state.connection="离线缓存" end

local root=lv_scr_act()
local W,H=lv_obj_get_width(root),lv_obj_get_height(root)
if not W or W<100 then W=320 end
if not H or H<100 then H=240 end
local sx,sy=W/320,H/240
local function px(v) return math.floor(v*sx+0.5) end
local function py(v) return math.floor(v*sy+0.5) end
local function load_font(name,fallback)
  local ok,f=pcall(lv_font_load,BASE.."font/"..name)
  if ok and f then fonts[#fonts+1]=f; return f end
  print("[xiaobucubic] font unavailable: "..name)
  return fallback
end
local small=load_font("ui12.bin",LV_FONT_MONTSERRAT_12)
local medium=load_font("ui16.bin",LV_FONT_MONTSERRAT_16)
local message_font=load_font("ui22.bin",medium)
local large=LV_FONT_MONTSERRAT_28
-- Retain LVGL objects and compare properties before touching the display.
-- Only navigation rebuilds a view; HTTP callbacks never clear the current view.
local function property(obj,key,value,apply)
  local values=ui.props[obj]
  if not values then values={};ui.props[obj]=values end
  if values[key]~=value then apply();values[key]=value end
end
local function style(obj,key,value)
  property(obj,"style:"..key,value,function() _G["lv_obj_set_style_"..key](obj,value,LV_PART_MAIN) end)
end
local function node(id,kind,parent)
  local n=ui.nodes[id]
  if not n then
    local create=kind=="label" and lv_label_create or kind=="image" and lv_img_create or lv_obj_create
    n={obj=create(parent),parent=parent};ui.nodes[id]=n
    lv_obj_clear_flag(n.obj,LV_OBJ_FLAG_SCROLLABLE)
  end
  n.seen=true
  return n.obj
end
local function geometry(o,x,y,w,h)
  property(o,"pos",x..","..y,function() lv_obj_set_pos(o,px(x),py(y)) end)
  if w and h then property(o,"size",w..","..h,function() lv_obj_set_size(o,px(w),py(h)) end) end
end
local function box(id,parent,x,y,w,h,color,radius,opacity)
  local o=node(id,"box",parent)
  geometry(o,x,y,w,h)
  style(o,"bg_color",color);style(o,"bg_opa",opacity or 255);style(o,"border_width",0)
  style(o,"radius",radius or 0);style(o,"pad_all",0)
  return o
end
local function label(id,parent,x,y,w,h,value,font,color,align,long_mode)
  local o=node(id,"label",parent)
  geometry(o,x,y,w,h)
  style(o,"text_font",font or small);style(o,"text_color",color or C.text)
  style(o,"text_align",align or LV_TEXT_ALIGN_LEFT)
  long_mode=long_mode or LV_LABEL_LONG_WRAP
  property(o,"long",long_mode,function() lv_label_set_long_mode(o,long_mode) end)
  value=tostring(value or "")
  property(o,"text",value,function() lv_label_set_text(o,value) end)
  return o
end
local function finish_frame()
  local removed={}
  for _,n in pairs(ui.nodes) do if not n.seen then removed[n.obj]=true end end
  for id,n in pairs(ui.nodes) do
    if not n.seen then
      if not removed[n.parent] then lv_obj_del(n.obj) end
      ui.props[n.obj]=nil;ui.nodes[id]=nil
    end
  end
end
local function monotonic()
  if tmr.time then
    local ok,t=pcall(tmr.time)
    if ok and type(t)=="number" then return t end
  end
  return state.tick
end
local function now()
  -- Server time + monotonic elapsed survives a bad RTC and failed subsequent polls.
  if state.server_epoch then return state.server_epoch+math.max(0,monotonic()-state.server_mono) end
  if time and time.get then
    local ok,t=pcall(time.get)
    if ok and type(t)=="number" and t>1700000000 and
      (not state.snapshot or t>=state.snapshot.generated_at) then return t end
  end
end
local function active_messages() return model.active_messages(state.snapshot,now()) end
local function message_key(r,index) return r.id and r.id~="" and r.id or "index:"..index end
local function sync_messages()
  local messages=active_messages()
  local selected
  for i,r in ipairs(messages) do
    if message_key(r,i)==state.message_key then selected=i;break end
  end
  state.message=selected or math.min(state.message,math.max(1,#messages))
  local r=messages[state.message]
  local key=r and message_key(r,state.message)
  if key~=state.message_key then state.message_part=1 end
  state.message_key=key
  state.active_count=#messages
  if #messages==0 then state.page=1 end
  return messages
end
local function countdown(t)
  local n=now()
  if not t or not n then return "" end
  local s=math.max(0,t-n)
  if s==0 then return "待刷新" end
  if s>=86400 then return math.ceil(s/86400).."天后重置" end
  if s>=3600 then return math.floor(s/3600).."小时后重置" end
  return math.max(1,math.ceil(s/60)).."分钟后重置"
end
local function num(v,suffix)
  if type(v)~="number" then return "--" end
  return string.format("%.0f",v)..(suffix or "")
end
local source_names={official="官方",manual="手动",estimated="估算",unknown="待接入"}
local function mix_color(a,b,weight)
  local color=0
  for _,place in ipairs({65536,256,1}) do
    local x,y=math.floor(a/place)%256,math.floor(b/place)%256
    color=color+math.floor(x+(y-x)*weight+0.5)*place
  end
  return color
end
local function network_indicator()
  local badge=state.busy and "同步中" or state.connection=="已同步" and "在线" or
    state.connection=="离线缓存" and "离线" or state.connection=="待配置" and "待配置" or "未连接"
  if state.error=="接口鉴权失败" then badge="鉴权失败"
  elseif state.error=="请求超时" then badge="超时" end
  local color=state.error and C.amber or state.connection=="已同步" and C.mint or C.muted
  box("network.dot",root,245,10,4,4,color,2)
  label("network.text",root,253,5,55,17,badge,small,color,LV_TEXT_ALIGN_RIGHT)
  label("network.demo",root,253,23,55,14,state.snapshot and state.snapshot.demo and "演示" or "",small,C.amber,LV_TEXT_ALIGN_RIGHT)
end
local function weather_background()
  local asset=model.weather_asset(state.snapshot and state.snapshot.weather)
  -- Keep the background layer below the data even when weather first arrives later.
  local layer=box("background",root,0,0,320,240,C.bg,0)
  if asset and file.stat and file.stat(BASE.."assets/weather/"..asset..".png") then
    local img=node("background.image","image",layer)
    local src="S:/apps/xiaobucubic/assets/weather/"..asset..".png"
    property(img,"src",src,function() lv_img_set_src(img,src) end)
    geometry(img,0,0)
    if W~=320 or H~=240 then
      local zoom=math.floor(math.min(sx,sy)*256)
      property(img,"zoom",zoom,function() lv_img_set_zoom(img,zoom) end)
    end
    box("background.shade",layer,0,0,320,240,C.bg,0,40)
    state.background=asset
  else state.background=nil end
end
local function weather_inline()
  local w=state.snapshot and state.snapshot.weather
  local valid=w and w.temperature_c~=nil
  local stale=not valid or model.is_stale(w.updated_at,now(),state.snapshot.stale_after_seconds)
  label("weather.temperature",root,12,12,100,35,valid and num(w.temperature_c,"°C") or "--°C",large,stale and C.muted or C.text)
  label("weather.city",root,119,10,89,20,valid and model.text(w.city,"",7) or "天气待同步",
    medium,stale and C.muted or C.mint,LV_TEXT_ALIGN_CENTER,LV_LABEL_LONG_SCROLL)
  -- Humidity sits below the city; range, pressure and forecast form the bottom row.
  label("weather.humidity",root,119,30,89,20,valid and
    (num(w.humidity_percent).."%") or "",medium,C.muted,LV_TEXT_ALIGN_CENTER)
  label("weather.range",root,12,51,105,20,valid and
    (num(w.low_c).."–"..num(w.high_c).."°C") or "",medium,C.muted)
  label("weather.pressure",root,119,51,89,20,valid and
    (num(w.pressure_hpa).." hPa") or "",medium,C.muted,LV_TEXT_ALIGN_CENTER)
  label("weather.status",root,210,37,98,14,valid and stale and "已过期" or "",
    small,C.amber,LV_TEXT_ALIGN_RIGHT)
  label("weather.condition",root,210,51,98,20,valid and w.condition or "",
    medium,C.muted,LV_TEXT_ALIGN_RIGHT,LV_LABEL_LONG_SCROLL)
end
local function draw_subscriptions()
  weather_background();weather_inline()
  if not model.has_secondary(state.snapshot) then state.window=1 end
  local data=state.snapshot
  if not data or #data.subscriptions==0 then
    label("quota.empty.title",root,18,113,284,26,"等待额度数据",medium,C.text)
    label("quota.empty.body",root,18,149,284,60,cfg.api_url=="" and "设置 config.json 的 api_url，连接你的数据接口。" or "接口接通后，这里显示 Claude、Codex 和 Grok 的剩余额度。",medium,C.muted)
    return
  end
  for i,p in ipairs(data.subscriptions) do
    local id="quota."..i
    -- Both layers must be translucent: an opaque panel would hide the weather
    -- even when the progress tint itself has a low opacity.
    local panel=box(id,root,12,72+(i-1)*55,296,52,C.panel,7,state.background and 52 or 255)
    local accent=p.id=="claude" and C.amber or p.id=="codex" and C.mint or C.blue
    local w=model.select_window(p,state.window)
    local companion=model.companion_window(p,state.window)
    local status=model.window_state(p,w,now(),data.stale_after_seconds)
    local value=model.remaining(w)
    local valid=status=="ok"
    local level=model.quota_level(value)
    local tone=level=="critical" and C.red or level=="low" and C.yellow or valid and accent or C.muted
    -- Full-height progress tint sits behind the text; width is remaining quota.
    -- Every color (including warning/red) stays translucent and fades downwards.
    local fill=box(id..".progress",panel,0,0,value and math.max(1,296*math.min(value,100)/100) or 1,52,
      tone,7,value and value>0 and (valid and 64 or 35) or 0)
    style(fill,"bg_grad_color",mix_color(C.panel,tone,0.16))
    style(fill,"bg_grad_dir",LV_GRAD_DIR_VER)
    style(fill,"bg_main_stop",0);style(fill,"bg_grad_stop",255)
    label(id..".name",panel,10,5,155,20,p.name,medium,C.text)
    label(id..".value",panel,202,5,82,20,value and num(value,"%") or "--",medium,
      tone,LV_TEXT_ALIGN_RIGHT)
    local detail=w and w.label or "暂无用量"
    -- With two windows, omit the redundant official-source label so the
    -- window and reset time fit without a moving marquee. Keep non-official sources.
    if not companion or p.source~="official" then detail=detail.." · "..source_names[p.source] end
    if status=="stale" then detail=detail.." · 已过期"
    elseif status=="expired" then detail=detail.." · 待刷新"
    elseif w and w.reset_at then detail=detail.." · "..countdown(w.reset_at) end
    label(id..".detail",panel,10,28,companion and 160 or 278,15,detail,small,C.muted,
      LV_TEXT_ALIGN_LEFT,companion and (LV_LABEL_LONG_DOT or LV_LABEL_LONG_CLIP or LV_LABEL_LONG_WRAP) or LV_LABEL_LONG_WRAP)
    if companion then
      local secondary_status=model.window_state(p,companion,now(),data.stale_after_seconds)
      local secondary_value=model.remaining(companion)
      local secondary_level=model.quota_level(secondary_value)
      local secondary_tone=secondary_level=="critical" and C.red or secondary_level=="low" and C.yellow or
        secondary_status=="ok" and accent or C.muted
      local summary=companion.label.." "..(secondary_value and num(secondary_value,"%") or "--")
      if secondary_status=="stale" then summary=summary.." · 已过期"
      elseif secondary_status=="expired" then summary=summary.." · 待刷新" end
      label(id..".secondary.label",panel,178,28,106,15,summary,small,secondary_tone,
        LV_TEXT_ALIGN_RIGHT,LV_LABEL_LONG_DOT or LV_LABEL_LONG_CLIP or LV_LABEL_LONG_WRAP)
      -- A narrow inset rail blends into the bottom of the main quota fill.
      box(id..".secondary.track",panel,10,46,274,4,C.muted,2,24)
      local rail=box(id..".secondary.fill",panel,10,46,
        secondary_value and math.max(1,274*math.min(secondary_value,100)/100) or 1,4,
        secondary_tone,2,secondary_value and secondary_value>0 and (secondary_status=="ok" and 112 or 55) or 0)
      style(rail,"bg_grad_color",mix_color(C.panel,secondary_tone,0.35))
      style(rail,"bg_grad_dir",LV_GRAD_DIR_VER)
      style(rail,"bg_main_stop",0);style(rail,"bg_grad_stop",255)
    end
  end
end
local function draw_reminder(messages)
  local r=messages[state.message]
  label("message.count",root,12,7,225,20,"消息 · "..state.message.." / "..#messages,small,C.muted)
  if not r then return end
  local accent=r.priority=="high" and C.amber or C.mint
  box("message.accent",root,12,34,3,198,accent,1)
  -- Title-free reminders leave room for seven lines of large body text.
  local chunks=model.message_chunks(r.text)
  state.message_part=math.min(state.message_part,#chunks)
  local body=label("message.body",root,25,44,278,194,chunks[state.message_part],message_font,C.text)
  style(body,"text_line_space",2)
  local due=""
  if r.due_at and now() then
    local mins=math.ceil((r.due_at-now())/60)
    due=mins<=0 and "已到提醒时间" or mins<60 and (mins.."分钟后") or (math.ceil(mins/60).."小时后")
  end
  label("message.meta",root,25,26,283,17,(r.sender=="bot" and "Bot · " or "")..
    (r.priority=="high" and "重要" or "备忘")..(due~="" and " · "..due or "")..
    (#chunks>1 and (" · "..state.message_part.."/"..#chunks) or ""),small,accent)
end
local function render()
  if not state.alive then return end
  local messages=sync_messages()
  if ui.page~=state.page then
    lv_obj_clean(root);ui={nodes={},props={},page=state.page}
    style(root,"bg_color",C.bg);style(root,"bg_opa",255);style(root,"pad_all",0)
    lv_obj_clear_flag(root,LV_OBJ_FLAG_SCROLLABLE)
  end
  for _,n in pairs(ui.nodes) do n.seen=false end
  if state.page==1 then draw_subscriptions() else draw_reminder(messages) end
  network_indicator();finish_frame()
end
local function fail(message)
  state.busy=false;state.failures=state.failures+1;state.error=message
  -- Wait after a failed attempt (including its timeout), never overlap requests.
  local delay=math.min(300,5*2^math.min(6,state.failures-1))
  state.next_retry=monotonic()+delay
  state.connection=state.snapshot and "离线缓存" or "未连接"
  render()
end
local function wifi_connected()
  if not wifi or not wifi.sta or not wifi.sta.getip or not wifi.sta.connect then return nil end
  local ok,ip=pcall(wifi.sta.getip)
  if not ok then return nil end -- Firmware without a usable Wi-Fi API still retries HTTP.
  return type(ip)=="string" and ip~="" and ip~="0.0.0.0"
end
local function refresh(force)
  if not state.alive or state.busy then return end
  if cfg.api_url=="" then
    if state.connection~="待配置" then state.connection="待配置";render() end
    return
  end
  if not force then
    if state.next_retry then
      if monotonic()<state.next_retry then return end
    elseif state.tick-state.last_fetch<cfg.refresh_seconds then return end
  end
  if not cfg.api_url:match("^https?://") then fail("接口地址无效");return end
  local connected=wifi_connected()
  if connected~=nil then state.wifi_connected=connected end
  if connected==false then
    -- Reuse the firmware's saved SSID/password, including hidden networks.
    -- Do not disconnect an existing association or rewrite Wi-Fi configuration.
    pcall(wifi.sta.connect)
    fail("Wi-Fi 未连接")
    return
  end
  state.busy=true;state.last_fetch=state.tick;state.request_id=state.request_id+1
  local request_id=state.request_id
  local headers={Accept="application/json"}
  if cfg.read_token~="" then headers.Authorization="Bearer "..cfg.read_token end
  local ok=pcall(function()
    http.get(cfg.api_url,{headers=headers,timeout=10000,bufsz=24576,max_redirects=0},function(code,body)
      if not state.alive or request_id~=state.request_id then return end
      state.busy=false
      if code~=200 then
        fail((code==401 or code==403) and "接口鉴权失败" or "连接失败，请稍后重试")
        return
      end
      local doc=decode(body)
      local data,err=model.normalize(doc)
      if not data then fail(err or "接口数据无效");return end
      state.snapshot=data;state.server_epoch=data.generated_at;state.server_tick=state.tick;state.server_mono=monotonic()
      state.last_received=state.tick;state.failures=0;state.next_retry=nil;state.error=nil;state.connection="已同步"
      -- One compact cache per successful poll; keep the last valid response on failure.
      pcall(file.putcontents,BASE.."cache.json",codec.encode(data))
      render()
    end)
  end)
  if not ok then fail("网络接口不可用") end
end
local timer=tmr.create()
local function advance_message()
  local messages=sync_messages()
  if #messages==0 then state.message=1;state.message_part=1;return end
  local current=messages[math.min(state.message,#messages)]
  local chunks=model.message_chunks(current.text)
  if state.message_part<#chunks then state.message_part=state.message_part+1
  else state.message=state.message%#messages+1;state.message_part=1 end
  state.message_key=message_key(messages[state.message],state.message)
end
local function switch_page(delta)
  sync_messages()
  local n=#model.pages(state.snapshot,now())
  if state.page==2 then advance_message() end
  state.page=(state.page-1+delta)%n+1
  state.rotate_at=state.tick+cfg.rotate_seconds
end
local function stop()
  if not state.alive then return end
  state.alive=false;state.request_id=state.request_id+1
  pcall(function() timer:unregister() end)
  pcall(function() key.off() end)
  lv_obj_clean(root)
  for _,f in ipairs(fonts) do pcall(lv_font_free,f) end
end
-- Exposed for device smoke testing and screenshots; no HTTP control endpoint.
XIAOBUCUBIC={state=state,render=render,stop=stop,refresh=refresh}
key.on(function(code,event)
  if event~=key.SHORT then return end
  if code==key.HOME then stop();app.exit();return end
  if code==key.LEFT or code==key.RIGHT then
    switch_page(code==key.RIGHT and 1 or -1)
  elseif code==key.UP then
    if state.page==2 then advance_message();state.rotate_at=state.tick+cfg.rotate_seconds
    else state.window=model.has_secondary(state.snapshot) and (state.window==1 and 2 or 1) or 1;refresh(true) end
  elseif code==key.DOWN then cfg.auto_rotate=not cfg.auto_rotate end
  render()
end)
render()
timer:alarm(1000,tmr.ALARM_AUTO,function()
  if app.exiting and app.exiting() then stop();return end
  state.tick=state.tick+1
  local connected=wifi_connected()
  if connected~=nil then
    if state.wifi_connected~=nil and connected~=state.wifi_connected and not state.busy then
      -- Detect recovery promptly even during a five-minute retry wait.
      state.failures=0;state.next_retry=nil;state.last_fetch=-10000
    end
    state.wifi_connected=connected
  end
  if state.busy and state.tick-state.last_fetch>15 then
    state.request_id=state.request_id+1;fail("请求超时")
  end
  if #active_messages()~=(state.active_count or 0) then render() end
  if cfg.auto_rotate and state.tick>=state.rotate_at then
    switch_page(1);render()
  elseif state.tick%30==0 then render() end
  refresh(false)
end)
refresh(true)
