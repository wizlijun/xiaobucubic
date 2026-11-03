-- Pure data validation shared by the device and the host tests.
local M = {}
local function text(v, fallback, max, multiline)
  if type(v) ~= "string" then return fallback or "" end
  if multiline then v=v:gsub("\r\n","\n"):gsub("\r","\n"):gsub("\t","    ") end
  -- Bound both bytes and UTF-8 characters; never cut inside a code point.
  local out, n = {}, 0
  for c in v:gmatch("[%z\1-\127\194-\244][\128-\191]*") do
    if n >= (max or 80) then break end
    if (c:byte() >= 32 and c:byte() ~= 127) or (multiline and c=="\n") then
      out[#out+1] = c; n = n+1
    end
  end
  return table.concat(out)
end
M.text = text
local function number(v, lo, hi)
  if type(v) ~= "number" or v ~= v or v == math.huge or v == -math.huge then return nil end
  if lo and v < lo or hi and v > hi then return nil end
  return v
end
M.number = number
local function epoch(v) return number(v, 1, 4102444800) end
local sources = { official=true, manual=true, estimated=true, unknown=true }
local function source(v) return sources[v] and v or "unknown" end

function M.normalize(doc)
  if type(doc) ~= "table" or doc.schema_version ~= 1 then return nil, "接口版本不支持" end
  if not epoch(doc.generated_at) then return nil, "缺少数据时间" end
  if type(doc.subscriptions) ~= "table" or type(doc.messages) ~= "table" then
    return nil, "数据格式错误"
  end
  local out = {schema_version=1, generated_at=doc.generated_at, demo=doc.demo==true,
    stale_after_seconds=number(doc.stale_after_seconds,30,86400) or 900,
    subscriptions={}, messages={}}
  local seen = {}
  for _, p in ipairs(doc.subscriptions) do
    if type(p)=="table" and type(p.id)=="string" and p.id~="" and not seen[p.id] then
      seen[p.id]=true
      local row={id=text(p.id,"",64),name=text(p.name,p.id,40),plan=text(p.plan,"",24),
        source=source(p.source),updated_at=epoch(p.updated_at),windows={},note=text(p.note,"",80)}
      for _, w in ipairs(type(p.windows)=="table" and p.windows or {}) do
        if type(w)=="table" and #row.windows<2 then
          local window={label=text(w.label,"用量",16),
            used_percent=number(w.used_percent,0,1000),reset_at=epoch(w.reset_at)}
          local total,used=number(w.total_bytes,1,9007199254740991),number(w.used_bytes,0,9007199254740991)
          if total and used and total%1==0 and used%1==0 then
            window.total_bytes=total;window.used_bytes=used
            window.remaining_bytes=math.max(0,total-used)
            window.used_percent=used/total*100
          end
          row.windows[#row.windows+1]=window
        end
      end
      out.subscriptions[#out.subscriptions+1]=row
    end
  end
  for _, r in ipairs(doc.messages) do
    if type(r)=="table" and #out.messages<12 and type(r.text)=="string" then
      local content=text(r.text,"",180,true)
      if content:match("%S") then
        out.messages[#out.messages+1]={title=text(r.title,"提醒",40),text=content,
          priority=r.priority=="high" and "high" or "normal",due_at=epoch(r.due_at),
          id=text(r.id,"",80),updated_at=epoch(r.updated_at),expires_at=epoch(r.expires_at),
          sender=r.sender=="bot" and "bot" or nil}
      end
    end
  end
  local w=doc.weather
  if type(w)=="table" then
    out.weather={city=text(w.city,"",30),condition=text(w.condition,"",30),
      condition_now=text(w.condition_now,"",30),forecast_hours=number(w.forecast_hours,0,240),
      is_day=type(w.is_day)=="boolean" and w.is_day or nil,
      temperature_c=number(w.temperature_c,-100,100),feels_like_c=number(w.feels_like_c,-100,100),
      low_c=number(w.low_c,-100,100),high_c=number(w.high_c,-100,100),
      humidity_percent=number(w.humidity_percent,0,100),rain_percent=number(w.rain_percent,0,100),
      pressure_hpa=number(w.pressure_hpa,0,2000),
      wind_kmh=number(w.wind_kmh,0,500),updated_at=epoch(w.updated_at),source=text(w.source,"",40)}
  end
  if out.weather and w.is_day==false then out.weather.is_day=false end
  return out
end

function M.weather_asset(weather)
  if not weather then return nil end
  local c=(weather.condition or ""):lower()
  if c:find("雨") or c:find("冰雹") or c:find("rain") or c:find("drizzle") or c:find("thunder") or c:find("hail") then return "rain" end
  if c:find("雪") or c:find("snow") or c:find("sleet") then return "snow" end
  if c:find("雾") or c:find("霧") or c:find("霾") or c:find("fog") or c:find("mist") or c:find("haze") then return "overcast" end
  if c:find("阴") or c:find("陰") or c:find("overcast") then return "overcast" end
  if c:find("云") or c:find("雲") or c:find("cloud") then return "partly_cloudy" end
  if c:find("晴") or c:find("clear") or c:find("sun") then
    return (weather.is_day==false or c:find("夜") or c:find("night")) and "clear_night" or "sunny"
  end
  return "overcast"
end

function M.is_stale(updated_at, now, ttl)
  return not updated_at or not now or now-updated_at>(ttl or 900) or updated_at-now>300
end

function M.window_state(provider, window, now, ttl)
  if not window or window.used_percent==nil then return "unknown" end
  if M.is_stale(provider.updated_at, now, ttl) then return "stale" end
  if window.reset_at and now>=window.reset_at then return "expired" end
  return "ok"
end

function M.active_messages(data, now)
  local active={}
  for _,r in ipairs(data and data.messages or {}) do
    -- An untrusted clock cannot prove that a cached, expiring message is still live.
    if not r.expires_at or (now and r.expires_at>now) then active[#active+1]=r end
  end
  return active
end

function M.quota_pages(data)
  return math.max(1,math.ceil(#(data and data.subscriptions or {})/6))
end

function M.pages(data, now)
  local pages={}
  for i=1,M.quota_pages(data) do pages[#pages+1]={kind="subscriptions",quota_page=i} end
  if #M.active_messages(data,now)>0 then pages[#pages+1]={kind="messages"} end
  return pages
end

function M.subscription_layout(data, page)
  local count=#(data and data.subscriptions or {})
  page=math.max(1,math.min(page or 1,M.quota_pages(data)))
  local first=(page-1)*6+1
  local visible=math.min(6,count-first+1)
  local columns=visible>4 and 2 or 1
  local rows=math.max(1,math.ceil(visible/columns))
  local height=math.min(52,math.floor((164-(rows-1)*3)/rows))
  local width=columns==2 and 146 or 296
  local cards={}
  for i=1,visible do
    cards[#cards+1]={index=first+i-1,x=12+((i-1)%columns)*(width+4),
      y=72+math.floor((i-1)/columns)*(height+3),width=width,height=height}
  end
  return cards,page
end

function M.select_window(provider, index)
  return provider.windows[index] or provider.windows[1]
end

function M.companion_window(provider, index)
  if #provider.windows<2 then return nil end
  -- Array order defines the windows; labels remain display-only.
  return provider.windows[index==2 and 1 or 2]
end

function M.has_secondary(data)
  for _,p in ipairs(data and data.subscriptions or {}) do
    if #p.windows>1 then return true end
  end
  return false
end

function M.remaining(window)
  if not window or window.used_percent==nil then return nil end
  return math.floor(math.max(0,100-window.used_percent))
end

function M.window_label(window)
  if not window then return "暂无用量" end
  return window.label=="7天" and "周限" or window.label
end

local function calendar_day(day)
  -- Gregorian civil date from Unix days; independent of firmware RTC/timezone APIs.
  local z=day+719468
  local era=math.floor(z/146097)
  local doe=z-era*146097
  local yoe=math.floor((doe-math.floor(doe/1460)+math.floor(doe/36524)-math.floor(doe/146096))/365)
  local year=yoe+era*400
  local doy=doe-(365*yoe+math.floor(yoe/4)-math.floor(yoe/100))
  local mp=math.floor((5*doy+2)/153)
  local date=doy-math.floor((153*mp+2)/5)+1
  local month=mp+(mp<10 and 3 or -9)
  if month<=2 then year=year+1 end
  return year,month,date
end

function M.reset_date(timestamp, now, offset_minutes)
  if not epoch(timestamp) then return "" end
  local offset=(number(offset_minutes,-720,840) or 480)*60
  local local_seconds=timestamp+offset
  local day=math.floor(local_seconds/86400)
  local hour=math.floor(local_seconds%86400/3600)
  local minute=math.floor(local_seconds%3600/60)
  local today=epoch(now) and math.floor((now+offset)/86400) or nil
  local date
  if today and day==today then
    date=""
  elseif today and day>=today-(today+3)%7 and day<today-(today+3)%7+7 then
    date="周"..({"一","二","三","四","五","六","日"})[(day+3)%7+1]
  else
    local year,month,d=calendar_day(day)
    local current_year=today and calendar_day(today)
    date=(current_year and current_year~=year and string.format("%d/",year) or "")..string.format("%02d/%02d ",month,d)
  end
  return date..string.format("%02d:%02d重置",hour,minute)
end

function M.format_bytes(bytes)
  if not number(bytes,0,9007199254740991) then return "--" end
  local units={"B","KiB","MiB","GiB","TiB","PiB"}
  local unit=1
  while bytes>=1024 and unit<#units do bytes=bytes/1024;unit=unit+1 end
  -- Round down so a small balance never appears larger than the actual value.
  local value=math.floor(bytes*10)/10
  return string.format(value%1==0 and "%.0f" or "%.1f",value)..units[unit]
end

function M.quota_level(remaining)
  if remaining==nil then return "unknown" end
  if remaining<5 then return "critical" end
  if remaining<20 then return "low" end
  return "normal"
end

-- Conservative advances for the bundled 22px Noto font. CJK stays full-width;
-- Latin words are measured as a unit before deciding where to wrap.
function M.message_char_width(char)
  if char==" " or char=="\t" then return 6 end
  if #char>1 then return 22 end
  if char:match("[ilI!.,:;'|`]") then return 7 end
  if char:match("[MW@%%]") then return 22 end
  if char:match("[A-Z]") then return 16 end
  if char:match("[mw]") then return 19 end
  return 13
end

function M.message_chunks(value, max_width, max_lines, measure)
  max_width=max_width or 264;max_lines=max_lines or 5
  measure=measure or M.message_char_width
  local parts,lines,current,width={}, {},{},0
  local word,space={},false
  local function line()
    lines[#lines+1]=table.concat(current);current={};width=0
    if #lines==max_lines then parts[#parts+1]=table.concat(lines,"\n");lines={} end
  end
  local function token(chars)
    local size=0
    for _,char in ipairs(chars) do size=size+measure(char) end
    local gap=space and #current>0 and measure(" ") or 0
    if #current>0 and width+gap+size>max_width then line();gap=0 end
    if gap>0 then current[#current+1]=" ";width=width+gap end
    space=false
    -- Only a token wider than a whole line may be split (e.g. a long URL).
    for _,char in ipairs(chars) do
      local advance=measure(char)
      if #current>0 and width+advance>max_width then line() end
      current[#current+1]=char;width=width+advance
    end
  end
  local function flush()
    if #word>0 then token(word);word={} end
  end
  for char in (value or ""):gmatch("[%z\1-\127\194-\244][\128-\191]*") do
    if char=="\n" then flush();line();space=false
    elseif char==" " or char=="\t" or char=="\r" then flush();space=true
    elseif #char==1 then word[#word+1]=char
    else flush();token({char}) end
  end
  flush()
  if #current>0 then line() end
  if #lines>0 then parts[#parts+1]=table.concat(lines,"\n") end
  if #parts==0 then parts[1]="" end
  return parts
end
function M.message_preview(value)
  local chunks=M.message_chunks(value)
  if #chunks==1 then return chunks[1] end
  local prefix,last=chunks[1]:match("^(.*\n)([^\n]*)$")
  prefix,last=prefix or "",last or chunks[1]
  local chars,width={},0
  for char in last:gmatch("[%z\1-\127\194-\244][\128-\191]*") do
    chars[#chars+1]=char;width=width+M.message_char_width(char)
  end
  local removed=false
  while width+M.message_char_width("…")>264 and #chars>0 do
    width=width-M.message_char_width(table.remove(chars));removed=true
  end
  last=table.concat(chars)
  -- If making room cut an English word, omit the rest of that word too.
  if removed then last=last:gsub("[%w_]+$","") end
  return prefix..last:gsub("%s+$","").."…"
end
return M
