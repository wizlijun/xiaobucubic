-- Inject two HTTP failures only in this QA VM, then use the real configured API.
-- Never disconnect Wi-Fi, change credentials, or write failed responses to cache.
local BASE='/sd/apps/xiaobucubic_retryqa/'
local codec=sjson or json
local attempts={}
local original_get=http.get
local function save(doc) file.putcontents(BASE..'result.json',codec.encode(doc)) end
http.get=function(url,options,callback)
  local attempt={at=tmr.time()};attempts[#attempts+1]=attempt
  local function complete(code,body,headers)
    attempt.code=code
    callback(code,body,headers)
    local s=XIAOBUCUBIC.state
    attempt.failures=s.failures;attempt.next_retry=s.next_retry;attempt.connection=s.connection
  end
  if #attempts<=2 then complete(-1,'');return end
  return original_get(url,options,complete)
end
save({done=false})
local ok,err=pcall(dofile,'/sd/apps/xiaobucubic/main.lua')
if not ok then save({done=true,error=tostring(err)});return end
local timer=tmr.create()
local ticks=0
timer:alarm(1000,tmr.ALARM_AUTO,function()
  ticks=ticks+1
  local s=XIAOBUCUBIC.state
  if #attempts>=3 and attempts[3].code then
    timer:unregister()
    save({done=true,attempts=attempts,connection=s.connection,failures=s.failures,next_retry=s.next_retry,
      error=s.connection~='已同步' and 'Real API recovery failed' or nil})
  elseif ticks>=40 then
    timer:unregister();save({done=true,error='Retry check timed out',attempts=attempts,connection=s.connection})
  end
end)
