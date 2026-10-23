-- Verify real API polls, retained widgets and large multiline message layout.
-- Synthetic display-only messages are never sent to the backend or saved in cache.
local BASE='/sd/apps/xiaobucubic_liveqa/'
local codec=sjson or json
local labels,images,receipts,font_errors={}, {}, {}, {}
local cleans,label_writes=0,0
local original_label,original_clean,original_delete=lv_label_set_text,lv_obj_clean,lv_obj_del
lv_label_set_text=function(id,value)
  labels[tostring(id)]=tostring(value);label_writes=label_writes+1;return original_label(id,value)
end
lv_obj_clean=function(id) labels={};images={};cleans=cleans+1;return original_clean(id) end
lv_obj_del=function(id) labels[tostring(id)]=nil;return original_delete(id) end
local original_font=lv_font_load
lv_font_load=function(path)
  local f,e=original_font(path)
  if not f then font_errors[#font_errors+1]=path..': '..tostring(e) end
  return f,e
end
local original_image=lv_img_set_src
lv_img_set_src=function(id,path) images[#images+1]=path;return original_image(id,path) end
local original_get=http.get
http.get=function(url,options,callback)
  return original_get(url,options,function(code,body,headers)
    local before=cleans
    callback(code,body,headers)
    local s=XIAOBUCUBIC and XIAOBUCUBIC.state
    if code==200 and s and s.connection=='已同步' then
      receipts[#receipts+1]={received_at=tmr.time(),generated_at=s.snapshot.generated_at,
        cleans=cleans,incremental_cleans=cleans-before}
    end
  end)
end
local function save(doc) file.putcontents(BASE..'result.json',codec.encode(doc)) end
local function screenshot(name)
  local shot,e=lv_snapshot_take(lv_scr_act(),LV_IMG_CF_TRUE_COLOR)
  if not shot then return false,tostring(e) end
  local saved,se=lv_snapshot_save_to_png(shot,BASE..name);lv_snapshot_free(shot)
  return saved,se
end
save({done=false})
local ok,err=pcall(dofile,'/sd/apps/xiaobucubic/main.lua')
if not ok then save({done=true,error=tostring(err)});return end
local timer=tmr.create()
local ticks,result,phase=0,nil,0
timer:alarm(1000,tmr.ALARM_AUTO,function()
  ticks=ticks+1
  if #receipts<2 then
    if ticks>=85 then
      timer:unregister();save({done=true,error='Two successful polls not observed',receipts=receipts,
        connection=XIAOBUCUBIC.state.connection,font_errors=font_errors})
    end
    return
  end
  local s=XIAOBUCUBIC.state
  s.rotate_at=s.tick+10000
  if phase==0 then
    result={done=false,receipts=receipts,labels=labels,images=images,snapshot=s.snapshot,
      view=s.page,connection=s.connection,background=s.background,font_errors=font_errors,
      incremental_cleans=receipts[2].incremental_cleans}
    s.page=1;XIAOBUCUBIC.render();phase=1;return
  elseif phase==1 then
    result.screenshot,result.screenshot_error=screenshot('home.png')
    -- Shallow copy protects the actual response retained in the test result.
    local display={};for k,v in pairs(s.snapshot) do display[k]=v end
    display.messages={{id='qa-layout',title='消息换行与大字显示',sender='bot',priority='normal',
      text='第一行：记得带伞。\n第二行：下午三点开会。\n这是一段较长的提醒文字，用来检查自动换行和底部空间是否足够。'}}
    s.snapshot=display;s.page=2;XIAOBUCUBIC.render()
    local writes=label_writes;XIAOBUCUBIC.render()
    result.message_labels_unchanged=label_writes==writes
    phase=2;return
  end
  timer:unregister()
  result.message_screenshot,result.message_screenshot_error=screenshot('messages.png')
  result.done=true;save(result)
end)
