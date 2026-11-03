# ap24 · ESP32-S3 USB Wi-Fi 路由器

让 Mac 保持连接原来的 Wi-Fi，通过 USB 把网络分享给 ESP32-S3，再由 S3 提供 **ap24** 2.4 GHz 热点。

```text
互联网 ← 当前 Wi-Fi ← Mac 互联网共享 ← USB CDC NCM ← ESP32-S3 ← ap24 ← 小屏/其他设备
```

## 硬件与功能

- 微雪 ESP32-S3-LCD-Driver-Board，8 MB Flash、8 MB Octal PSRAM；PSRAM 以 80 MHz 运行，用于 LCD 帧缓冲，CPU 240 MHz。
- 40 针接口连接微雪 4 英寸 ST7701 480×480 方屏，上电短暂显示便签黄 `#FFF59D`，随后自动运行原生 C 信息面板，显示额度、天气和消息便签。
- 使用 S3 **原生 USB** 接口（GPIO19/20），不是只接 USB-UART 芯片的串口接口。
- WPA2-PSK，默认信道 6，最多 4 个客户端。SSID、密码和信道来自本地配置。
- USB CDC NCM 网卡 + CDC ACM 调试串口；面向当前 Mac，无需 RNDIS 驱动。
- USB 侧 DHCP 客户端；热点侧 `10.42.32.1/24`、DHCP、IPv4 NAPT。
- 热点 DNS 地址固定为 `10.42.32.1`，普通 UDP DNS 请求转发至 USB DHCP 下发的 DNS。
- 状态页 `http://10.42.32.1/`；只读 JSON 接口 `/api/status`。也可从 Mac 访问 USB 租约地址上的同一接口。
- USB 断开或租约丢失时关闭 NAT；恢复租约后自动开启。热点可用于本地访问。检测到上下游网段重叠时禁用转发并在状态页提示。

这是一台依赖 Mac 供电和网络共享的 IPv4 小型路由器。Mac 睡眠、断网或关闭共享后，热点不能访问互联网。USB Full-Speed 的总线速率上限是 12 Mbps，实际路由吞吐更低，适合小屏和轻量设备，未针对视频或大量并发优化。DNS 代理目前仅支持 UDP，不代理 TCP DNS；设备可自行指定外部 DNS，相关 TCP/UDP 流量照常经过 NAT。

## 配置与构建

固定使用 ESP-IDF **v5.5.2**、`espressif/esp_tinyusb` **2.2.1**、TinyUSB **0.19.0~3**、`espressif/esp_lcd_st7701` **2.0.3** 、`espressif/esp_lcd_panel_io_additions` **1.0.1~1** 和 LVGL **8.3.11**。工具链、构建产物和本地密码均被 Git 忽略。安装脚本只安装本项目使用的 Xtensa 工具链，不安装未使用的 ULP/RISC-V 编译器和 OpenOCD；CMake 仍会校验实际编译器版本。

```sh
cd wifirouter
./scripts/setup.sh
cp config.example.json config.local.json  # 已有本地配置时不要覆盖
cp app.example.json app.local.json       # 已有本地配置时不要覆盖
chmod 600 config.local.json app.local.json
# 编辑 config.local.json，设置至少 8 个字符的密码
# 编辑 app.local.json，设置显示 API 地址和只读 token
./scripts/idf.sh set-target esp32s3
./scripts/idf.sh build
uv run --with lupa python -m unittest discover -s tests -v
```

当前工作目录已有用户指定的本地密码。`config.local.json` 不纳入 Git；示例文件中没有真实密码。修改配置后重新构建、烧录即可生效。密码会存在固件二进制中，不要公开分发包含真实密码的构建产物。

从旧版纯路由固件升级时，已有 `sdkconfig` 的值会覆盖 defaults；先备份该文件，再执行 `./scripts/idf.sh set-target esp32s3` 重新生成配置，或在 menuconfig 中启用与 `sdkconfig.defaults` 相同的 PSRAM / CPU / LCD 选项。本机当前配置已更新。

## 4 英寸显示屏

驱动只针对微雪 **ESP32-S3-LCD-Driver-Board + 4 英寸 ST7701 480×480 方屏**，使用原厂 40 针 RGB 接口。使用 GT911 触摸映射原版方向键操作（SDA15 / SCL7，自动探测地址 0x5D / 0x14）。初始化命令提取自[微雪官方示例包](https://files.waveshare.com/wiki/ESP32-S3-LCD-Driver-Board/ESP32-S3-LCD-Driver-Board/Demo/ESP32-S3-LCD-Driver-Board_demo.zip)中的 `Arduino/Demo/LVGL_Porting_4inch/ESP_Panel_Board_Custom.h`，保留原始寄存器参数；不要换用 2.1 / 2.8 英寸圆屏初始化表。

| 信号 | ESP32-S3 GPIO |
| --- | --- |
| 3-wire SPI CS / SCK / SDA | 42 / 2 / 1 |
| RGB HSYNC / VSYNC / DE / PCLK | 38 / 39 / 40 / 41 |
| RGB D0–D7 | 5 / 45 / 48 / 47 / 21 / 14 / 13 / 12 |
| RGB D8–D15 | 11 / 10 / 9 / 46 / 3 / 8 / 18 / 17 |

像素时钟 8 MHz（约 29.3 帧/秒），HSYNC 脉宽/后肩/前肩为 8/10/50，VSYNC 为 3/8/8。RGB565 双帧共占 921,600 字节 PSRAM，两块内部 DMA 缓冲各容纳 20 行（共 38,400 字节）；LCD 中断分配到 core 1，Wi-Fi 使用 core 0。数据缓存行使用 64 字节，LCD / DMA 回调在 IRAM 执行，回调信号量使用静态内部 RAM；保留 VSYNC 重同步。RGB 硬件持续扫描输出；LVGL 在后台帧缓冲画完整页，再在帧边界切换，避免 40 行分块更新逐渐出现在屏幕上。通过 ST7701 硬件同时反转 X/Y 扫描方向，将画面旋转 180°；触摸坐标同步映射为 `(479-x, 479-y)`，无需软件旋转像素。两个缓冲直接交替用作 LVGL 画布和 LCD 帧，无需整屏复制；等待 RGB bounce-buffer 的 frame-complete 回调后才重用旧前台缓冲。仅变化的控件触发重绘，启用 2 张 PNG 解码缓存和 4 KB 渐变缓存。天气 PNG 沿用原应用素材，中文字体按 480×480 屏幕重新生成。原厂配置没有独立背光和复位 GPIO，使用软件复位；GPIO45 是 RGB 数据线，不可当作背光控制。USB 使用的 GPIO19/20 不变。

`main/display.c` 中 `NOTE_YELLOW_RGB565` 为 `0xFFB3`，对应启动画面 `#FFF59D` 的 RGB565 量化值。`/api/status` 的 `display` 对象报告初始化状态、错误、尺寸、启动颜色和 PSRAM 容量。`initialized` 仅说明驱动初始化成功，接口不能读取屏幕实际亮度或验证颜色，仍需目视确认。屏幕驱动初始化失败会记录错误并保留路由服务；此固件要求板上 PSRAM 能正常启动。

```sh
python3 scripts/check_router.py http://192.168.2.2 --require-display --require-app --require-buffered-display --require-stable-rgb
# 另有设备连接热点时可追加 --require-client
```

本机 `backups/ap24-before-display-20261103/` 保存了添加屏幕前可用的路由固件、引导程序、分区表与配置，未纳入 Git。

## 原生便签应用

`main/app_model.c`、`app_ui.c`、`app_runtime.c` 将 `../../apps/xiaobucubic/package/display_model.lua` 和 `main.lua` 的行为移植为 C，不包含 Lua 引擎或脚本解释执行。当前对齐上游 `ce2c175` 中应用 **1.2.2**（通过本地合并提交 `1a0e7aa` 拉取）。Lua 仅用于 Mac 上的模型对照测试。原应用文件不修改；构建时复制原天气素材及本项目 `assets/fonts` 的屏幕字库，校验 SHA256 并打包到 SPIFFS，保留两款字体的 OFL 许可。此板继续使用已有的 USB NCM 网卡获取 HTTP 数据，保留 ap24 热点；不运行原 HoloCubic 专用的 UART 桥接或关闭 Wi-Fi 射频的逻辑。

- 开机直接运行；没有 Launcher。主页按服务端顺序显示全部订阅和流量余额，每页最多 6 张卡片；超过 6 项自动增加额度页，5–6 项使用两列布局。有有效消息时额度页与便签页轮播，默认每 15 秒切页，无有效消息时只轮播额度页。
- 保留最新版剩余额度计算、20% / 5% 告警阈值、所有订阅的双窗口细条、半透明渐变、天气过期状态、演示标记和局部刷新。主次窗口保持服务端顺序；流量显示剩余量 / 总量，支持 B 至 PiB。重置时间使用简短日期，默认 UTC+8，可在 app.local.json 设置 utc_offset_minutes（-720..840）。
- 每条备忘只占一张便签，依次使用黄 / 绿 / 珊瑚红 / 天蓝纸色和深色文字。正文最多 180 字，按实际字形宽度和 414×316 像素正文区域换行，优先 32px，放不下时改用 24px；两种字号均为 LXGW WenKai。中文句末标点随前一字换行，仍超出一页的内容加省略号；保留原始换行、同 ID 消息位置、重要标记、Bot 和提醒倒计时。每秒过滤过期消息，断网和暂停轮播期间同样有效。
- 布局按 320×240 坐标缩放至 480×480；辅助文字为 18px Noto Sans CJK，标题 / 额度名称为 24px Noto Sans CJK，备忘正文为 24/32px LXGW WenKai，温度为 48px Montserrat。四套中文字库均覆盖原有 7,215 字符。启动时一次读取字库到临时 PSRAM，再在内存解析，避免 SPIFFS 上大量小读操作。天气图等比放大、左右居中裁切，铺满方屏。
- 后台读取 `/v1/display`，默认 60 秒同步；失败后等待 5 / 10 / 20 / 40 / 80 / 160 / 300 秒，后续每 300 秒重试；10 秒网络超时、15 秒应用兜底，过时响应不会覆盖新状态。USB 网络恢复后立即重试，保留 ap24 路由功能。
- 以服务端时间加单调时钟计算过期和倒计时；断网显示有效缓存。缓存单独存放在 NVS，重启保留；冷启动未获得可信时间时隐藏带过期时间的消息。401 / 403、错误 JSON 和不支持的协议版本不覆盖缓存。
- 只使用现有服务的读取 token，不访问订阅账户。`app.local.json` 和构建镜像包含本地读取配置，不纳入 Git，也不经状态页返回。

触摸操作对应原版按键：

| 触摸操作 | 原版按键 / 效果 |
| --- | --- |
| 左右滑动，或点屏幕左 / 右边缘 | 左 / 右：切换额度分页和便签页 |
| 上滑，或点中间区域 | 上：主页刷新（主次窗口不交换）；便签页下一条 |
| 下滑，或点底部 50px 区域 | 下：暂停 / 恢复轮播 |
| 长按至少 3 秒后松开 | Home：退出显示应用，路由继续工作；重启设备再次进入 |

触摸未检测到时仍正常同步、显示和自动轮播。`/api/status` 的 `app` 对象提供当前页、同步状态、HTTP 状态码、重试倒计时、字库加载数、缓存与触摸状态，以及实际渲染耗时、帧切换等待时间和完成帧数，不返回凭据或消息正文。

Flash 分区为 2 MB 应用、5 MB 只读素材区和 128 KB 独立缓存区，保留原有路由 NVS / PHY 分区；缓存仍在 `0x710000`。安装大字号 / 文楷版必须使用完整 `idf.py flash`，同时更新分区表、程序和字体素材；不可仅烧应用，也不要擦除整个 Flash。后续不涉及分区或素材的修改才可单独 `app-flash`。`backups/ap24-yellow-20261103/` 保存了此次移植前的可用黄色屏幕固件。

## 字体来源与重新生成

正文使用 [LXGW WenKai Regular v1.530](https://github.com/lxgw/LxgwWenKai/releases/tag/v1.530)，标题和辅助文字沿用 Noto Sans CJK。两者均使用 SIL OFL 1.1，许可随字库放在 `assets/fonts`。生成后的 LVGL 二进制字库纳入项目，普通构建不需要下载字体或安装 Node 工具。`manifest.json` 记录源字体和生成物 SHA256。

需重新生成时，将原 Noto 字体、该版本文楷 TTF 和许可 `OFL-LXGWWenKai.txt` 放到 `.tools/fontgen/`，运行：

```sh
npm install --prefix .tools/fontgen --no-audit --no-fund lv_font_conv@1.5.3
python3 scripts/generate_fonts.py .tools/fontgen/NotoSansCJKsc-Regular.otf .tools/fontgen/LXGWWenKai-Regular.ttf
./scripts/idf.sh build
```

生成器从原 `ui16.bin` 提取字符集合，校验新字库字符覆盖一致；采用 2bpp 抗锯齿。文楷版编译通过；使用同一份 C UI 和 LVGL 在主机渲染短便签、180 字长便签及 4 / 6 卡片页面，核对 32/24px 自动切换、中文标点换行及标签高度，预览在 `build/ui-preview/`。程序 1,478,576 字节，2 MB 应用分区仍有约 29% 余量；5 MB SPIFFS 镜像生成通过。程序、分区表及 5 MB 素材镜像已完整烧录，全部通过 Flash 哈希校验。2026-11-04 实机确认四套字体加载、HTTP 200 数据同步、USB / DHCP / NAT 正常，空闲堆约 2.2 MB，帧等待超时为 0；用户报告左侧固定竖条 / 杂色，各页面都有。180° 硬件旋转和双缓冲整屏切换继续保留。

## 烧录

先用 `ls /dev/cu.usbmodem*` 确认端口。初次连接的 USB Serial/JTAG 端口可以直接烧录：

```sh
./scripts/idf.sh -p /dev/cu.usbmodem11201 flash
```

固件启动后，USB 会重新枚举为网卡和 CDC 串口，串口名称可能改变。查看日志：

```sh
./scripts/idf.sh -p /dev/cu.usbmodem新端口 monitor
```

若后续无法自动进入下载模式：按住 **BOOT**，按一下 **RESET/EN**，再松开 BOOT，然后使用重新出现的 ROM 串口烧录。手动进入下载模式后，如果烧录完成仍显示原来的 ROM 串口，请松开 BOOT 后按一下 RESET，或正常插拔 USB，启动新固件。不要烧写 eFuse；此项目不需要任何不可逆的硬件配置。

## Mac 端启用共享

1. 保持 Mac 已连接能上网的 Wi-Fi，并用数据线连接 S3。
2. 打开 **系统设置 → 通用 → 共享 → 互联网共享** 的配置。
3. “共享以下来源的连接”选择 **Wi-Fi**。
4. 共享目标选择新出现的 **ap24 USB Router / USB Ethernet / USB net** 网卡（具体名称取决于 macOS）。不要选择上游 Wi-Fi 自身。
5. 开启互联网共享；macOS 可能显示正常的系统授权提示。
6. 在小屏/手机上连接 **ap24**，输入本地配置里的密码。
7. 访问 `http://10.42.32.1/`，确认 `dhcp_running=true`、`client_ips` 有设备地址、`usb_attached=true`、`nat_ready=true`、`subnet_conflict=false`，再访问外网验证。

`nat_ready=true` 表示已取得 USB 地址并开启转发，不等同于外网已经可达。状态页不回显密码。没有共享时热点仍可连接，但 USB DHCP 地址为空，不能上网。

可在 Mac 上执行硬件检查（USB 地址以实际 DHCP 租约为准）：

```sh
python3 scripts/check_router.py http://192.168.2.2 --require-client
```

这会检查实际运行固件的 DHCP 服务、USB 链路、NAT、网段冲突和客户端租约；外网访问仍需在连接热点的设备上测试。`clients` 是 Wi-Fi 关联数，`client_ips` 才是已分配的 IP。`dns_queries` / `dns_failures` 可用于区分 DNS 请求是否到达及是否成功。

Mac 可用下面命令查看新网卡和路由，避免误选其他 USB 设备：

```sh
networksetup -listallhardwareports
ifconfig
```

## 原固件恢复

本机 `backups/esp32s3-original-20261028.bin` 是烧录前读取的完整 8 MB Flash；同目录 `SHA256SUMS` 保存校验值，整个目录不纳入 Git。恢复前先进入 ROM 下载模式，确认端口后执行：

```sh
export IDF_TOOLS_PATH="$PWD/.tools/espressif"
export IDF_SKIP_TOOLS_CHECK=1
. .tools/esp-idf/export.sh
unset IDF_SKIP_TOOLS_CHECK
python -m esptool --chip esp32s3 --port /dev/cu.usbmodem实际端口 \
  write_flash 0x0 backups/esp32s3-original-20261028.bin
```

备份可能包含旧固件的配置，保留在本机即可。

## 本机验证记录（2026-10-28）

- ESP-IDF v5.5.2 实际构建通过，应用固件 850,336 字节；烧录后 Flash 哈希校验通过。
- 配置校验测试 3 项通过；硬件检查中的 DHCP、USB、NAT、网段和客户端租约 5 项通过。
- Mac 识别为 `ap24 USB Router`（本次为 `en10`），互联网共享来源为 Wi-Fi。
- USB 上游租约 `192.168.2.2`，网关 `192.168.2.1`；两台热点客户端获得 `10.42.32.2`、`10.42.32.3`。
- 状态页可访问，DNS 查询成功；用户确认热点客户端可以正常访问互联网。
- Mac 上原有 Clash 设置保持原样。接口编号和租约地址可能随重连变化。

## 原生便签移植验证（2026-11-03）

- 原生 C 固件构建通过，无编译警告；固件与 SPIFFS 中没有 Lua 引擎或脚本。
- 6 项主机测试通过，包括对最新 `display_model.lua` 的 118 组差分对照：百分比边界、过期、天气、中文 / 英文换行、单张便签截断、动态额度分页、流量余额、时区与日期。Git 合并后的服务端上游 19 项和本地 34 项测试通过。
- 13 个原始字库 / 天气素材 / 许可文件逐一 SHA256 校验通过，读取配置只存在 Git 忽略的本地文件和构建目录。
- 使用既有只读配置验证真实 `/v1/display` 返回 HTTP 200、schema v1。
- 首版原生应用、分区表与 4 MB 字库素材已烧录并通过 Flash 哈希校验。首版实机成功加载 3 套中文字库、同步 3 条消息（HTTP 200），用户确认界面正常；GT911 未检测到，自动轮播可用。最新版彩色便签已烧录并通过哈希校验，用户确认便签有颜色；设备状态确认 4 个订阅、3 条消息和绿色纸面，USB / DHCP / NAT 均正常。后续整屏切换优化版（1,419,152 字节）已单独烧录应用并通过 Flash 哈希校验；正常重启后实机检查通过：双缓冲整屏切换工作、帧等待超时为 0，HTTP / DHCP / USB / NAT 正常；一次便签刷新实测绘制及提交共 80.3 ms，其中帧切换等待 8.0 ms，启动以来最大刷新耗时 696.8 ms。后续 180° 硬件旋转版（1,419,504 字节）已烧录并通过 Flash 哈希校验，后续运行状态确认 180° 配置已生效。

## 左侧花屏排查（2026-11-04）

修复前字体加载和同步正常，15 秒串口采样未出现报错，固定边缘杂色跨页面存在。调整 RGB 带宽和中断配置后用户确认恢复，支持传输时序 / 供数余量不足这一判断；由于多项配置一起改变，尚未通过逐项对照确定唯一触发因素，也不能断言字体扩容本身是直接原因。

按照 [Espressif RGB 漂移排查建议](https://docs.espressif.com/projects/esp-faq/en/latest/software-framework/peripherals/lcd.html#why-do-i-get-drift-overall-drift-of-the-display-when-esp32-s3-is-driving-an-rgb-lcd-screen)，验证版将像素时钟从 12 MHz 降至 8 MHz，中转缓冲从每块 10 行增至 20 行，缓存行从 32 字节改为 64 字节，并启用 IRAM-safe LCD 中断及内部静态信号量。双整屏缓冲、180° 旋转、文楷与字号逻辑不变。每块缓冲的传输时间从约 0.46 ms 延长至 1.37 ms，增加中断处理余量；不改变便签轮播或服务端同步周期。

固件已编译通过，1,479,648 字节的应用已通过 `app-flash` 写入并完成 Flash 哈希校验；字库、分区和缓存保留。正常重启后用户确认左侧花屏消失；18 项状态检查通过。运行 32 秒时四套字库加载正常、HTTP 200、空闲堆 2,197,772 字节、内部空闲堆 110,483 字节、帧等待超时为 0，8 MHz / 20 行 / 64 字节 / IRAM-safe 配置均已生效。以上为启动后抽样，尚不代表长期压力测试。状态接口新增 RGB 配置、VSYNC / 完整帧计数和最大 VSYNC 间隔；这些数据辅助排查，不等同于“无花屏”的证据。若仍有固定边缘异常，继续核对面板时序及硬件连接。

## 实现参考

显示功能实机验证（2026-11-03）：ESP-IDF v5.5.2 编译通过，应用 900,416 字节；配置校验测试 3 项通过，烧录后 Flash 哈希校验通过。正常拔插 USB 后新固件启动，用户确认整屏变黄。`--require-display` 实机检查 7 项通过：DHCP、USB、NAT、无网段重叠、ST7701 初始化、480×480 便签黄配置和 8 MB PSRAM；内部空闲堆约 176 KB。烧录前客户端租约检查通过；烧录后检查时没有热点客户端连接，因此未重新验证客户端外网访问。

- [ESP USB Device 官方说明](https://docs.espressif.com/projects/esp-usb/en/latest/esp32s3/usb_device.html)
- [ESP-IDF v5.5.2 USB 网络示例](https://github.com/espressif/esp-idf/tree/v5.5.2/examples/peripherals/usb/device/tusb_ncm)
- [Apple：共享 Mac 的互联网连接](https://support.apple.com/guide/mac-help/share-internet-connection-mac-network-users-mchlp1540/mac)
- [微雪 LCD Driver Board 官方资料](https://www.waveshare.com/wiki/ESP32-S3-LCD-Driver-Board)
- [Espressif ST7701 驱动](https://components.espressif.com/components/espressif/esp_lcd_st7701/versions/2.0.3/readme)
