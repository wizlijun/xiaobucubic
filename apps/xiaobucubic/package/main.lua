-- xiaobucubic / ClocTeck Lua + LVGL. API contract: GET /v1/display.
local BASE="/sd/apps/xiaobucubic/"
local model=dofile(BASE.."display_model.lua")
local codec=sjson or json
local C={bg=0x070C12,panel=0x111C28,line=0x203142,text=0xF0F5FC,muted=0x8497AC,
  mint=0x6DE1C2,blue=0x83B6FF,amber=0xFFC078,yellow=0xFFD166,red=0xFF5F6D}
local NOTE_COLORS={
  {paper=0xFFF2A6,header=0xE2CA65}, -- yellow
  {paper=0xDDEEB4,header=0xAEC87C}, -- green
  {paper=0xF7B6B2,header=0xDE8580}, -- coral red
  {paper=0xB9DFF2,header=0x83BBD7}, -- sky blue
}
local cfg={api_url="",read_token="",refresh_seconds=60,rotate_seconds=15,auto_rotate=true,utc_offset_minutes=480}
local state={alive=true,busy=false,tick=0,page=1,quota_page=1,window=1,message=1,last_fetch=-10000,request_id=0,
  last_received=nil,rotate_at=15,connection="等待配置",snapshot=nil,error=nil,failures=0}
local usb
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
cfg.utc_offset_minutes=model.number(loaded.utc_offset_minutes,-720,840) or 480
cfg.transport=loaded.transport=="auto" and "auto" or loaded.transport=="usb" and "usb" or "wifi"
cfg.wifi_fallback_ssid=model.text(loaded.wifi_fallback_ssid,"",64)
cfg.usb_timeout_seconds=model.number(loaded.usb_timeout_seconds,30,600) or math.max(90,cfg.refresh_seconds+30)
state.active_transport=cfg.transport=="wifi" and "wifi" or "usb"
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
  state.message_key=key
  state.active_count=#messages
  state.quota_page=math.min(state.quota_page,model.quota_pages(state.snapshot))
  if #messages==0 then state.page=1 end
  return messages
end
local function reset_date(t)
  return model.reset_date(t,now(),cfg.utc_offset_minutes)
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
  if state.active_transport=="usb" then badge=state.connection=="已同步" and "USB" or "USB离线"
  elseif state.connection=="已同步" then
    local ssid=cfg.wifi_fallback_ssid
    if wifi and wifi.sta and wifi.sta.getconfig then
      local ok,saved=pcall(wifi.sta.getconfig)
      if ok and type(saved)=="table" then ssid=model.text(saved.ssid,ssid,32) end
    end
    badge=ssid~="" and ("Wi-Fi "..ssid) or "Wi-Fi"
  end
  if state.error=="接口鉴权失败" then badge="鉴权失败"
  elseif state.error=="请求超时" then badge="超时" end
  local color=state.error and C.amber or state.connection=="已同步" and C.mint or C.muted
  if state.page==2 then color=state.error and 0x823B20 or 0x38432B end
  local show_ap=badge:sub(1,6)=="Wi-Fi "
  box("network.dot",root,show_ap and 220 or 245,10,4,4,color,2)
  label("network.text",root,show_ap and 228 or 253,5,show_ap and 80 or 55,17,badge,small,color,
    LV_TEXT_ALIGN_RIGHT,LV_LABEL_LONG_DOT or LV_LABEL_LONG_CLIP or LV_LABEL_LONG_WRAP)
  label("network.demo",root,253,23,55,14,state.snapshot and state.snapshot.demo and "演示" or "",small,state.page==2 and 0x823B20 or C.amber,LV_TEXT_ALIGN_RIGHT)
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
  -- Keep the server-defined primary/secondary roles stable across refreshes and keys.
  state.window=1
  local data=state.snapshot
  if not data or #data.subscriptions==0 then
    label("quota.empty.title",root,18,113,284,26,"等待额度数据",medium,C.text)
    label("quota.empty.body",root,18,149,284,60,cfg.api_url=="" and "设置 config.json 的 api_url，连接你的数据接口。" or "接口接通后，这里显示服务端提供的剩余额度。",medium,C.muted)
    return
  end
  local layout=model.subscription_layout(data,state.quota_page)
  if model.quota_pages(data)>1 then
    label("quota.pages",root,211,23,34,14,state.quota_page.."/"..model.quota_pages(data),small,C.muted,LV_TEXT_ALIGN_RIGHT)
  end
  local palette={C.amber,C.mint,C.blue}
  local clip=LV_LABEL_LONG_DOT or LV_LABEL_LONG_CLIP or LV_LABEL_LONG_WRAP
  for slot,card in ipairs(layout) do
    local p=data.subscriptions[card.index]
    local id="quota."..slot
    local width,height=card.width,card.height
    local grid=width<200
    -- Both layers must be translucent: an opaque panel would hide the weather
    -- even when the progress tint itself has a low opacity.
    local panel=box(id,root,card.x,card.y,width,height,C.panel,7,state.background and 52 or 255)
    local accent=palette[(card.index-1)%#palette+1]
    local w=model.select_window(p,state.window)
    local companion=model.companion_window(p,state.window)
    local status=model.window_state(p,w,now(),data.stale_after_seconds)
    local value=model.remaining(w)
    local valid=status=="ok"
    local level=model.quota_level(value)
    local tone=level=="critical" and C.red or level=="low" and C.yellow or valid and accent or C.muted
    -- Full-height progress tint sits behind the text; width is remaining quota.
    -- Every color (including warning/red) stays translucent and fades downwards.
    local fill=box(id..".progress",panel,0,0,value and math.max(1,width*math.min(value,100)/100) or 1,height,
      tone,7,value and value>0 and (valid and 64 or 35) or 0)
    style(fill,"bg_grad_color",mix_color(C.panel,tone,0.16))
    style(fill,"bg_grad_dir",LV_GRAD_DIR_VER)
    style(fill,"bg_main_stop",0);style(fill,"bg_grad_stop",255)
    local balance=w and w.remaining_bytes and (model.format_bytes(w.remaining_bytes).."/"..model.format_bytes(w.total_bytes))
    local top=(height<45 or grid) and 2 or 5
    local value_width=grid and 50 or balance and 176 or 82
    local value_x=width-12-value_width
    label(id..".name",panel,grid and 6 or 10,top,value_x-(grid and 10 or 16),20,p.name,medium,C.text,LV_TEXT_ALIGN_LEFT,clip)
    label(id..".value",panel,value_x,top,value_width,20,
      not grid and balance or value and num(value,"%") or "--",medium,tone,LV_TEXT_ALIGN_RIGHT,clip)
    local detail=model.window_label(w)
    -- With two windows, omit the redundant official-source label so the
    -- window and reset time fit without a moving marquee. Keep non-official sources.
    if balance then detail=detail.." · "..(value and num(value,"%") or "--")
    elseif (not companion and not grid and height>=45) or p.source~="official" then detail=detail.." · "..source_names[p.source] end
    if status=="stale" then detail=detail.." · 已过期"
    elseif status=="expired" then detail=detail.." · 待刷新"
    elseif w and w.reset_at then detail=detail.." "..reset_date(w.reset_at) end
    local detail_y=(height<45 or grid) and 21 or 28
    label(id..".detail",panel,grid and 6 or 10,detail_y,grid and width-12 or companion and 120 or width-20,
      (height<45 or grid) and 13 or 15,grid and balance or detail,small,C.muted,LV_TEXT_ALIGN_LEFT,clip)
    if grid and balance and not companion then
      label(id..".reset",panel,6,35,width-12,13,detail,small,C.muted,LV_TEXT_ALIGN_LEFT,clip)
    end
    if companion then
      local secondary_status=model.window_state(p,companion,now(),data.stale_after_seconds)
      local secondary_value=model.remaining(companion)
      local secondary_level=model.quota_level(secondary_value)
      local secondary_tone=secondary_level=="critical" and C.red or secondary_level=="low" and C.yellow or
        secondary_status=="ok" and accent or C.muted
      local summary=(companion.label=="7天" and "" or model.window_label(companion).." ")..
        (secondary_value and num(secondary_value,"%") or "--")
      if secondary_status=="stale" then summary=summary.." · 已过期"
      elseif secondary_status=="expired" then summary=summary.." · 待刷新"
      elseif companion.reset_at then
        local reset=reset_date(companion.reset_at)
        if reset~="" then summary=summary.." "..reset end
      end
      label(id..".secondary.label",panel,grid and 6 or width-164,grid and 35 or detail_y,
        grid and width-12 or 152,(height<45 or grid) and 13 or 15,summary,small,secondary_tone,LV_TEXT_ALIGN_RIGHT,
        grid and LV_LABEL_LONG_SCROLL or clip)
      -- A narrow inset rail blends into the bottom of the main quota fill.
      local rail_y,rail_height=height-3,2
      if not grid and height>=45 then rail_y=height-6;rail_height=4 end
      box(id..".secondary.track",panel,10,rail_y,width-22,rail_height,C.muted,2,24)
      local rail=box(id..".secondary.fill",panel,10,rail_y,
        secondary_value and math.max(1,(width-22)*math.min(secondary_value,100)/100) or 1,rail_height,
        secondary_tone,2,secondary_value and secondary_value>0 and (secondary_status=="ok" and 112 or 55) or 0)
      style(rail,"bg_grad_color",mix_color(C.panel,secondary_tone,0.35))
      style(rail,"bg_grad_dir",LV_GRAD_DIR_VER)
      style(rail,"bg_main_stop",0);style(rail,"bg_grad_stop",255)
    end
  end
end
local function draw_reminder(messages)
  local r=messages[state.message]
  if not r then return end
  -- Each reminder occupies one sheet, with colors cycling through the palette.
  local palette=NOTE_COLORS[(state.message-1)%#NOTE_COLORS+1]
  local paper=palette.paper
  local ink,muted=0x30382D,0x626B50
  local header=palette.header
  box("message.header",root,0,0,320,29,header,0)
  label("message.count",root,14,6,225,20,"便签 · "..state.message.." / "..#messages,small,ink)
  local sheet=box("message.paper",root,0,29,320,211,paper,0)
  local body=label("message.body",sheet,22,14,276,158,model.message_preview(r.text),message_font,ink,
    LV_TEXT_ALIGN_LEFT,LV_LABEL_LONG_CLIP)
  style(body,"text_line_space",4)
  local due=""
  if r.due_at and now() then
    local mins=math.ceil((r.due_at-now())/60)
    due=mins<=0 and "已到提醒时间" or mins<60 and (mins.."分钟后") or (math.ceil(mins/60).."小时后")
  end
  label("message.meta",sheet,22,184,226,17,(r.sender=="bot" and "Bot · " or "")..
    (r.priority=="high" and "重要" or "备忘")..(due~="" and " · "..due or ""),small,muted,
    LV_TEXT_ALIGN_LEFT,LV_LABEL_LONG_CLIP)

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
local function suspend_wifi()
  wifi.stop()
  -- Preserve the station credentials while disabling the radio across restarts.
  wifi.mode(wifi.NULLMODE,true)
end
local function activate_fallback()
  if cfg.transport~="auto" or state.active_transport=="wifi" then return end
  if state.fallback_retry and monotonic()<state.fallback_retry then return end
  state.fallback_retry=monotonic()+30
  local ok=pcall(function()
    local saved=wifi.sta.getconfig()
    assert(cfg.wifi_fallback_ssid~="" and saved and saved.ssid==cfg.wifi_fallback_ssid,"Wrong fallback network")
    wifi.mode(wifi.STATION,false);wifi.start();wifi.sta.connect()
  end)
  if not ok then state.error="备用Wi-Fi不可用";render();return end
  state.active_transport="wifi";state.wifi_connected=false
  state.last_fetch=-10000;state.next_retry=nil;state.failures=0;state.error=nil
  state.connection=state.snapshot and "离线缓存" or "未连接"
  render()
end
local function refresh(force)
  if state.active_transport=="usb" then return end
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
      state.last_source="wifi";state.last_received=state.tick;state.failures=0;state.next_retry=nil;state.error=nil;state.connection="已同步"
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
  if #messages==0 then state.message=1;return end
  state.message=state.message%#messages+1
  state.message_key=message_key(messages[state.message],state.message)
end
local function switch_page(delta)
  sync_messages()
  local pages=model.pages(state.snapshot,now())
  local current=state.page==2 and #pages or state.quota_page
  if state.page==2 then advance_message() end
  local target=pages[(current-1+delta)%#pages+1]
  state.page=target.kind=="messages" and 2 or 1
  state.quota_page=target.quota_page or state.quota_page
  state.rotate_at=state.tick+cfg.rotate_seconds
end
local function stop()
  if not state.alive then return end
  state.alive=false;state.request_id=state.request_id+1
  pcall(function() timer:unregister() end)
  pcall(function() key.off() end)
  if usb then pcall(usb.stop) end
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
    else refresh(true) end
  elseif code==key.DOWN then cfg.auto_rotate=not cfg.auto_rotate end
  render()
end)
render()
timer:alarm(1000,tmr.ALARM_AUTO,function()
  if app.exiting and app.exiting() then stop();return end
  state.tick=state.tick+1
  if cfg.transport=="auto" and state.active_transport=="usb" then
    local age=monotonic()-(state.usb_received or state.usb_started or 0)
    if age>=(state.usb_received and cfg.usb_timeout_seconds or 20) then activate_fallback() end
  end
  local connected
  if state.active_transport=="wifi" then connected=wifi_connected() end
  if cfg.transport=="usb" and state.usb_received and monotonic()-state.usb_received>cfg.refresh_seconds*2+20 and state.connection=="已同步" then
    state.connection="离线缓存";render()
  end
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
local function disable_wifi()
  -- Erase station credentials in persistent storage, then keep the radio off.
  wifi.stop()
  wifi.mode(wifi.STATION,true)
  wifi.sta.config({ssid="",pwd=""},true)
  wifi.mode(wifi.NULLMODE,true)
  wifi.stop()
end
if uart and uart.setup and uart.on and uart.write then
  local function usb_status()
    local saved=wifi and wifi.sta and wifi.sta.getconfig and wifi.sta.getconfig() or nil
    return {transport=cfg.transport,active_transport=state.active_transport,last_source=state.last_source,
      connection=state.connection,can_configure_wifi=true,can_fallback=cfg.transport=="auto",generated_at=state.snapshot and state.snapshot.generated_at,
      wifi_mode=wifi and wifi.getmode and wifi.getmode(),
      saved_ssid=saved and saved.ssid or nil,ip=wifi and wifi.sta and wifi.sta.getip and wifi.sta.getip() or nil}
  end
  local ok,result=pcall(function()
    return dofile(BASE.."usb_transport.lua").start({status=usb_status,
      accept=function(body)
        local data,err=model.normalize(decode(body))
        if not data then return false,err end
        -- Ignore an in-flight HTTP response once USB has supplied newer data.
        state.request_id=state.request_id+1;state.busy=false
        if cfg.transport=="auto" then
          if state.active_transport~="usb" then pcall(suspend_wifi) end
          state.active_transport="usb";state.fallback_retry=nil
        end
        state.last_source="usb"
        state.snapshot=data;state.server_epoch=data.generated_at;state.server_mono=monotonic()
        state.usb_received=monotonic();state.last_received=state.tick
        state.connection="已同步";state.error=nil;state.failures=0
        pcall(file.putcontents,BASE.."cache.json",codec.encode(data));render()
        return true
      end,
      configure_wifi=function(ssid,password)
        assert(type(ssid)=="string" and #ssid>0 and #ssid<=32 and not ssid:find("[%z\r\n]"),"Invalid SSID")
        assert(type(password)=="string" and #password>=8 and #password<=63 and not password:find("[%z\r\n]"),"Invalid password")
        wifi.stop();wifi.mode(wifi.STATION,false)
        wifi.sta.config({ssid=ssid,pwd=password},true)
        local saved=wifi.sta.getconfig();assert(saved and saved.ssid==ssid,"SSID not saved")
        loaded.transport="auto";loaded.wifi_fallback_ssid=ssid
        assert(file.putcontents(BASE.."config.json",codec.encode(loaded)),"Could not save configuration")
        cfg.transport="auto";cfg.wifi_fallback_ssid=ssid;state.active_transport="usb"
        state.request_id=state.request_id+1;state.busy=false;state.fallback_retry=nil
        state.usb_received=nil;state.usb_started=monotonic();state.connection="离线缓存"
        suspend_wifi();render()
      end,
      upstream_unavailable=function() activate_fallback() end,
      usb_only=function()
        loaded.transport="usb"
        assert(file.putcontents(BASE.."config.json",codec.encode(loaded)),"Could not save USB configuration")
        cfg.transport="usb";state.active_transport="usb";state.request_id=state.request_id+1;state.busy=false
        disable_wifi();render()
      end})
  end)
  if ok then usb=result else print("[xiaobucubic] USB unavailable") end
end
state.usb_started=monotonic()
if cfg.transport=="auto" then
  pcall(suspend_wifi);state.connection="离线缓存";render()
elseif cfg.transport=="usb" then
  local ok=pcall(disable_wifi)
  if not ok then pcall(wifi.stop);state.error="Wi-Fi配置清除失败" end
  state.connection="离线缓存";render()
end
refresh(true)
