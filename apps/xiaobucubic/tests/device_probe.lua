local BASE='/sd/apps/xiaobucubic_qa/'
local codec=sjson or json
local labels,errors={},{}
local original_label=lv_label_set_text
lv_label_set_text=function(id,value) labels[tostring(id)]=tostring(value);return original_label(id,value) end
local original_clean,original_delete=lv_obj_clean,lv_obj_del
lv_obj_clean=function(id) labels={};return original_clean(id) end
lv_obj_del=function(id) labels[tostring(id)]=nil;return original_delete(id) end
local original_font=lv_font_load
lv_font_load=function(path)
  local f,e=original_font(path)
  if not f then errors[#errors+1]=path..': '..tostring(e) end
  return f,e
end
local function save(doc) file.putcontents(BASE..'result.json',codec.encode(doc)) end
local ok,err=pcall(dofile,'/sd/apps/xiaobucubic/main.lua')
if not ok then save({done=true,error=tostring(err)});return end
local timer=tmr.create()
local ticks,step=0,0
local original_messages
local result={done=false,pages={},font_errors=errors}
save(result)
timer:alarm(1000,tmr.ALARM_AUTO,function()
  ticks=ticks+1
  if not XIAOBUCUBIC.state.snapshot then
    if ticks>20 then timer:unregister();save({done=true,error='No API snapshot',state=XIAOBUCUBIC.state}) end
    return
  end
  if ticks<3 then return end
  if not original_messages then original_messages=XIAOBUCUBIC.state.snapshot.messages end
  step=step+1
  -- Let LVGL finish layout for one tick before taking the image.
  if step%2==1 then
    local page=math.floor(step/2)+1
    if page>4 then
      timer:unregister();result.done=true;save(result);return
    end
    if page==1 then
      XIAOBUCUBIC.state.page=1
    elseif page==2 then
      XIAOBUCUBIC.state.page=2
    elseif page==3 then
      XIAOBUCUBIC.state.snapshot.messages={}
      XIAOBUCUBIC.state.page=2 -- must normalize to home when messages disappear
    else
      XIAOBUCUBIC.state.snapshot.messages=original_messages
      XIAOBUCUBIC.state.page=1;XIAOBUCUBIC.state.window=2
    end
    XIAOBUCUBIC.render()
  else
    local index=step/2
    local texts={};for k,v in pairs(labels) do texts[k]=v end
    local record={page=index,labels=texts,actual_view=XIAOBUCUBIC.state.page}
    local shot,e=lv_snapshot_take(lv_scr_act(),LV_IMG_CF_TRUE_COLOR)
    if shot then
      local saved,se=lv_snapshot_save_to_png(shot,BASE..'page-'..index..'.png')
      lv_snapshot_free(shot);record.screenshot=saved;record.error=se
    else record.error=tostring(e) end
    result.pages[#result.pages+1]=record
    save(result)
  end
end)
