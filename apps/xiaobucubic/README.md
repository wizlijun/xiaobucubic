# xiaobucubic

运行于 **ClocTeck HoloCubic Lua 固件**的小屏信息面板，针对 320×240 设计。安装应用不需要重新烧录固件。

**主页**按服务端 `subscriptions` 数组动态显示全部订阅、流量余额和重置时间，不写死提供商名称或数量。1–3 项使用宽卡片，4 项缩短行高同屏显示，5–6 项改为两列；超过 6 项自动分页，每 15 秒轮播，也可左 / 右翻页。天气融合进背景与顶部；有有效提醒时，在所有额度页之后插入**消息页**，多条消息依次展示。服务删除提醒后回到额度页。

余额来自窗口字段：只有百分比时显示剩余百分比；提供 `total_bytes` 和 `used_bytes` 时自动显示实际剩余 / 总流量（如 `750GiB/1000GiB`），同时保留剩余比例。任意提供商的双窗口都显示次窗口细条，周窗口说明如 `37% 周四21:00重置`；新增搬瓦工或其他项目不需要再次修改客户端。接口增删、重排项目时复用现有控件并重新计算位置。

主页省去“Token 额度 / 剩余比例 / 主窗口”等说明行，直接展示天气和额度卡片。有天气背景时，卡片底板和进度填充均为半透明，叠加后不超过 40.4% 不透明度，天气图案可透出。额度进度以卡片全高的半透明纵向渐变表示，上方稍亮、下方渐淡，宽度对应剩余额度，文字位于填充上层。剩余低于 20% 为警告黄，低于 5% 为警戒红（数字与填充同步变色），20% 及以上使用订阅配色；天气“已过期”提示独立显示在天气文字上方。Claude 的另一个额度窗口显示为卡片底部 4px 细条，右下角显示窗口标签与剩余百分比；按服务端顺序固定大面积显示 5 小时额度，细条显示 7 天额度，上键仅刷新，不再交换两者。Claude 下方说明固定显示窗口与重置时间，省略重复的“官方”字样，过长文本省略显示，不滚动。两个视图均不设标题栏和底部状态栏，右上角显示同步 / 在线 / 离线状态。模拟数据的“演示”标识紧邻右上角联网状态。额度卡片和消息正文使用释放出的底部空间。消息不显示标题；正文使用 22px 中文字体，每条最多 5 行，超出部分用省略号截断，每条备忘只显示一张便签，保留原始换行，英文按完整单词折行，超长网址等才拆分；通知按顺序使用 Post-it 风格的淡黄（`#FFF2A6`）、淡绿（`#DDEEB4`）、柔红（`#F7B6B2`）、浅蓝（`#B9DFF2`）四种全屏便签底色（无黑边），搭配深一档的同色标题栏、深色正文和留白；城市、湿度和气压在中间一列统一居中对齐，湿度（如 `51%`）放在城市下方；天气区下沿依次显示温度范围（`23–32°C`）、气压（`1011 hPa`）和天气（如“晴”），使用 16px 字号并省去数值的文字标签。

额度显示为 `floor(max(0, 100 - used_percent))%`，表示订阅剩余配额比例，不伪造 token 总数。无数据、过期、离线都有明确状态。没有硬编码账户或真实订阅数据。

| 操作 | 效果 |
|---|---|
| 左 / 右 | 在全部额度页及有效消息页之间切换；只有一页时保持当前页 |
| 上 | 主页刷新数据，主 / 次额度位置保持不变；消息页显示下一条 |
| 下 | 暂停 / 恢复轮播 |
| Home | 退出 |

## 安装

`package/` 的内容复制到 TF 卡 `/apps/xiaobucubic/`，然后在 Launcher 重新扫描应用。也可将 `dist/xiaobucubic-1.2.2.zip` 解压到 TF 卡根目录。升级时保留设备已有 `config.json` 与 `cache.json`，不要用包内空配置覆盖实际服务端地址和读取 token。

USB 读卡器可直接更新 TF 卡；设备的 ESP32 USB 烧录串口与 TF 卡文件是两个不同通道。当前项目提供的是 Lua 应用安装包，并非可写入 ESP32 Flash 的整机 ROM 镜像。

设备已联网时，使用 Python 3 的部署工具（无第三方依赖）：

```sh
python3 tools/deploy.py http://10.15.2.72 --launch
```

工具只写入 `/sd/apps/xiaobucubic/`，逐文件校验，覆盖前备份到 `.runtime/backups/`。升级时保留设备已有配置；指定 `--config /path/to/config.json` 才覆盖配置。不要在应用正在运行时用读卡器更换文件。

### 通过 USB 更新数据（设备无需 Wi-Fi）

固件的 Type-C 提供 USB 串口，不是 USB 网卡。`tools/usb_bridge.py` 在电脑读取服务端接口，通过分块、逐块确认的串口协议将数据送入设备；只转发本应用的数据，不为其他设备应用提供通用网络。电脑需要保持开机、联网和 USB 连接；拔线或电脑休眠后显示缓存，重新连接后自动恢复。

先在设备上安装 1.2.0（包括 `usb_transport.lua`），将现有接口配置安全保存到电脑的私有配置文件，再运行：

```sh
uv run --with pyserial python tools/usb_bridge.py --config /private/path/config.json --once --usb-only
```

首次确认 USB 成功传输后，`--usb-only` 才会保存 `transport="usb"`、清空设备保存的 Wi-Fi SSID/密码并关闭 Wi-Fi。该操作会使设备的 Wi-Fi 管理网页断开。开机设置 `/sd/apps/settings.json` 必须使用 `autostart_wait_for_wifi=false`，才能在无 Wi-Fi 时自动进入应用。USB 模式不会发起 Wi-Fi 重连；数据不再更新时保留缓存，显示 `USB离线`。

macOS 登录后自动运行转发：

```sh
uv venv .runtime/usb-bridge/venv
uv pip install --python .runtime/usb-bridge/venv/bin/python pyserial
python3 tools/install_usb_bridge.py --python .runtime/usb-bridge/venv/bin/python --config /private/path/config.json
```

安装用户级 LaunchAgent `local.xiaobucubic.usb-bridge`，日志位于 `.runtime/usb-bridge/`，配置文件权限为 `0600`。默认选择唯一的 `/dev/cu.usbmodem*` 设备；多设备时单独运行桥接脚本并指定 `--port`。此处只读取配置中的 API 地址与只读 token，不写入服务端数据。切换为 USB 后不要运行下面用于 Wi-Fi 模式的自启动工具。

### USB 优先，Wi-Fi 备用（1.2.1）

先通过固件配网页将备用热点写入设备，再设置设备的 `config.json`：

```json
{
  "transport": "auto",
  "wifi_fallback_ssid": "ap24",
  "usb_timeout_seconds": 90
}
```

以上字段合并进已有配置，保留 API 地址与只读 token。Wi-Fi 密码只交给固件保存，不写入仓库。`wifi_fallback_ssid` 必须与固件保存的 SSID 完全一致，否则拒绝连接其他网络。

开机等待 USB 20 秒；正常情况下保持 USB 同步并关闭 Wi-Fi。超过 90 秒没有收到有效 USB 数据时启用备用 Wi-Fi；电脑端明确报告接口网络错误时立即尝试备用 Wi-Fi。收到有效 USB 数据后切回 USB、关闭 Wi-Fi，保留备用热点凭据；取消尚未完成的 HTTP 请求，防止迟到回调覆盖 USB 数据。右上角显示当前使用的 `USB` 或 `Wi-Fi ap24`（Wi-Fi 后跟当前热点名称）；长热点名称省略，避免挤入天气区域。

升级现有 USB-only 设备时，先暂停电脑转发服务并保持串口打开，再在设备上进入 Wi-Fi 配网页。写入备用热点后须先安装新程序、将 `transport` 改成 `auto`，再启动信息面板；旧版本 USB-only 启动逻辑会清空 Wi-Fi 配置。继续使用 `autostart_wait_for_wifi=false`，以便无 Wi-Fi 时仍能等待 USB。

已安装 1.2.1 后，可以直接通过 USB 写入备用热点，无需再进入配网页：

```sh
uv run --with pyserial python tools/usb_bridge.py --config /private/path/config.json --configure-wifi ap24 --once
```

密码由终端隐藏输入，也可通过 `--wifi-password-file /private/path/password` 从私有文件读取，不作为命令行参数传递。设备将热点写入固件的持久配置，把 `transport=auto` 与备用 SSID 写入应用配置，然后关闭 Wi-Fi 等待 USB；后续中断时自动启用该备用网络。配置回执不包含密码。

转发程序在设备切换到其他应用时保持串口打开等待，不通过反复关闭、重开串口去触发设备复位。


### 开机自动进入应用

设备已保存 Wi-Fi 配置后，运行：

```sh
python3 tools/set_autostart.py http://设备IP
```

该工具备份并更新 `/sd/apps/settings.json` 和 `/sd/apps/launcher/main.lua`，保留其他设置，逐文件回读校验。下次开机时，Launcher 等待 Wi-Fi 获得有效 IP，然后自动进入 `xiaobucubic`；连接较慢时继续等待，可在应用列表手动打开 Wi-Fi 配网。每次开机只自动进入一次，按 Home 退出后不会再次跳入。

配置使用 `autostart_enabled=true`、`autostart_app_id="xiaobucubic"` 和 `autostart_wait_for_wifi=true`。最后一项由工具对 Launcher 的小范围补丁提供；升级官方 Launcher 后需要重新运行此工具。遇到无法识别的 Launcher 源码时工具会停止，不写入设备。

所有额度均显示服务端提供的具体重置时间：当天仅显示时分，其余本周（周一至周日）显示 `周四21:00重置`，跨周显示 `11/02 21:00重置`，跨年补上年份。默认按 UTC+8（台北／北京时间）换算；配置可选 `utc_offset_minutes` 可调整固定时区偏移。缺少重置时间时不推测日期，过期状态仍优先显示。

## 接入自己的服务

修改设备上的 `/sd/apps/xiaobucubic/config.json`：

```json
{
  "api_url": "https://your-service.example/v1/display",
  "read_token": "your-device-read-only-token",
  "refresh_seconds": 60,
  "rotate_seconds": 15,
  "auto_rotate": true
}
```

退出并重新打开应用后生效。接口只需返回一个 JSON，见 [API.md](API.md)。局域网调试可用 HTTP；远程服务应使用设备固件能验证证书的 HTTPS。账户登录凭证不放在设备上。

`cache.json` 由应用生成，保存最后一次成功的数据，启动断网时也可显示。接口鉴权失败、未知版本和解析失败不会覆盖缓存。设备未校时且无服务时间时，缓存数据按过期处理，带 `expires_at` 的消息暂不显示。成功响应后使用服务时间和本地单调时钟过滤过期消息，离线或暂停轮播时仍生效。

应用启动立即连接；失败后等待 5 / 10 / 20 / 40 / 80 / 160 / 300 秒再试，持续失败时每 5 分钟一次。Wi-Fi 断线会按此节奏使用设备已保存的热点配置重连，获得 IP 后立即同步。成功后重置退避并恢复默认 60 秒刷新；接口失败不会中断已连接的 Wi-Fi，离线期间继续显示有效缓存。

刷新复用现有 LVGL 控件，仅更新变化的文字、进度条或样式；天气类型不变时不重载背景图。只有切换主页 / 消息页时重建视图。相同数据不会触发全屏清空重绘。

## 本地演示

```sh
python3 tools/mock_api.py --host 0.0.0.0 --port 8768
```

把 `api_url` 配成 `http://电脑局域网IP:8768/v1/display`，电脑与 Cubic 需要相互可达。模拟服务只返回示例，不访问任何订阅账户；所有页面标注“演示”。电脑休眠或服务退出后，设备显示离线缓存。可使用 `--token-file` 启用读取鉴权。

## 开发和验证

```sh
uv run --with lupa python tests/test_display.py
python3 -m unittest discover -s tests -p 'test_mock_api.py'
python3 tools/build.py
```

运行时采用设备内置 `http`、`sjson`、`file`、`tmr`、`key`、LVGL API，无额外模块。包内保留八种 PNG 素材，主页按接口天气选择晴 / 云 / 雨 / 雪 / 晴夜背景，图片缺失时使用纯色背景；每条消息只显示一张便签，正文过长时用省略号截断。中文字体为 Noto Sans CJK，来自 ClocTeck 示例应用，OFL 许可随包附带；参见 [THIRD_PARTY.md](THIRD_PARTY.md)。

参考：[ClocTeck 应用开发说明](https://github.com/clocteck/holocubic-apps)、[Lua API](https://github.com/clocteck/holocubic-apps/blob/main/README_LUA.md)、[LVGL API](https://github.com/clocteck/holocubic-apps/blob/main/README_LVGL.md)。
