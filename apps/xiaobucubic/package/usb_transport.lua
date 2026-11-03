-- Framed USB serial input: bounded chunks, acknowledged before the next frame.
local M={}
function M.start(options)
  local codec=sjson or json
  local buffer,id,size,started=nil,nil,0,0
  local function reply(request,status,extra)
    local response=extra or {};response.id=request.id;response.status=status
    uart.write(0,"XBC1 "..codec.encode(response).."\n")
  end
  local function receive(raw)
    if type(raw)~="string" or #raw>2048 or raw:sub(1,5)~="XBC1 " then return end
    local ok,frame=pcall(codec.decode,raw:sub(6))
    if not ok or type(frame)~="table" or type(frame.id)~="string" or #frame.id>64 then return end
    if frame.type=="status" then reply(frame,"ok",options.status());return end
    if frame.type=="wifi_config" and options.configure_wifi then
      local changed=pcall(options.configure_wifi,frame.ssid,frame.password)
      reply(frame,changed and "ok" or "error",changed and options.status() or {error="Wi-Fi configuration failed"})
      return
    end
    if frame.type=="upstream_unavailable" and options.upstream_unavailable then
      options.upstream_unavailable();reply(frame,"ok",options.status());return
    end
    if frame.type=="usb_only" then
      local changed,err=pcall(options.usb_only)
      reply(frame,changed and "ok" or "error",changed and options.status() or {error=tostring(err)})
      return
    end
    if frame.type=="begin" and type(frame.bytes)=="number" and frame.bytes>0 and frame.bytes<=24576 then
      buffer={};id=frame.id;size=frame.bytes;started=tmr.time and tmr.time() or 0
      reply(frame,"ok");return
    end
    if frame.id~=id or not buffer then reply(frame,"error",{error="No transfer"});return end
    if tmr.time and tmr.time()-started>30 then buffer=nil;reply(frame,"error",{error="Transfer expired"});return end
    if frame.type=="chunk" and type(frame.data)=="string" and #frame.data<=1024 then
      local length=0;for _,part in ipairs(buffer) do length=length+#part end
      if length+#frame.data>size then buffer=nil;reply(frame,"error",{error="Transfer too large"});return end
      buffer[#buffer+1]=frame.data;reply(frame,"ok");return
    end
    if frame.type=="commit" then
      local body=table.concat(buffer);buffer=nil
      if #body~=size then reply(frame,"error",{error="Transfer size mismatch"});return end
      local accepted,err=options.accept(body)
      reply(frame,accepted and "ok" or "error",accepted and options.status() or {error=err});return
    end
    reply(frame,"error",{error="Unsupported frame"})
  end
  uart.setup(0,115200,uart.DATABITS_8 or 8,uart.PARITY_NONE or 0,uart.STOPBITS_1 or 1,0)
  uart.on("data")
  uart.on("data","\n",receive)
  return {stop=function() uart.on("data") end}
end
return M
