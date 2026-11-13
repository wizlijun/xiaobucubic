# ap24 · ESP32-S3 USB Wi-Fi 路由器

## 当前保留配置：Qualia 5800 + 720 方屏（2026-11-13）

用户实机确认 **方向正确、颜色正常、不闪，切页正常**，保留这一版。常规 `qualia-720` 已采用与已烧录的 `qualia-720-rotate` 相同的设置；后者保留作为兼容配置名。旧 480 屏仍使用各自独立配置。

| 设置 | 保留值 |
| --- | --- |
| 面板 | YX40006ACT / NV3052C，720×720，无触摸玻璃 |
| 像素时钟 | 35 MHz（名义刷新率约 57.02 Hz） |
| 水平：同步 / 后肩 / 前肩 | 2 / 44 / 46 |
| 垂直：同步 / 后肩 / 前肩 | 2 / 18 / 16 |
| PCLK 输出边沿 | `pclk_active_neg=true` |
| 屏幕扫描方向 | 保留 `MADCTR=0x03`，不再使用失败的扫描方向翻转方案 |
| 画面方向 | `APP_FRAME_ROTATE_180=y`，后台完整帧额外旋转 180° |
| 颜色与缓冲 | RGB565 双帧缓冲、PNG 静态误差扩散、渐变空间抖色；20 行 bounce、64 KB 缓存 |
| 背光 | 扩展器常亮，软件 PWM 关闭 |

```sh
./scripts/board.sh qualia-720 build
```

产物在 `build/qualia-720/`。已有构建目录中的 sdkconfig 优先于 defaults；升级旧缓存时在 menuconfig 中确认 `APP_FRAME_ROTATE_180=y`、`YX40006ACT_ROTATE_180=y` 和上述时序。硬件 `display.rotation_degrees=180` 与 `app.software_rotation_degrees=180` 分别报告扫描方向和额外绘制旋转，不要为了视觉方向再翻转扫描寄存器。

已烧录并经用户确认的镜像 SHA256：`cc6c85a6e5092fd7bd0647e96ee27249aa12174ffdb3062f82378e7def60cad7`。本地归档在 `backups/qualia-720-software-rotate-20261113/`；固件、ELF、运行状态及本机资料不入 Git。运行检查确认 4 套字体、HTTP 200、帧等待超时 0，绘制端旋转实测约 249 ms/次，仅在重绘时执行。当前通过观察不代表已确定此前间歇闪烁的根因或完成长期压力测试。

以下为接线依据及历史调试记录；当前使用以上配置。

## YX40006ACT / NV3052C 720×720 方屏

新增独立的 `qualia-720` 与 `qualia-720-color-test` 配置，适用于用户提供的 **YX40006ACT（排线 FPC-40006A-V01）、NV3052C、40pin 方屏 + Qualia 5800**。原 `qualia`、`qualia-color-test` 和默认 `waveshare` 继续使用 ST7701 480×480；控制板和面板在 menuconfig 中分别选择。

依据用户提供的 `YX40006ACT-RGB接口驱动资料`：

- `YX40006ACT specs.pdf` 第 4、6、8、13 页：720×720、3SPI+18RGB、40pin 定义、背光和复位要求。已对照 [Qualia 官方原理图](https://github.com/adafruit/Adafruit-Qualia-S3-RGB666-PCB/blob/main/Adafruit%20Qualia%20S3%20RGB666.sch)核对电源、控制、RGB 和触摸引脚。第 7、8 脚在此屏为 NC；Qualia 上对应 IM 配置，无需改接。LCD RESET 与 TP_RESET 在 Qualia 上共用扩展器 P2。
- 厂家于 2026-11-13 确认 `LCD/时序参考timing.png`：**720×720、35 MHz，水平同步脉宽/后肩/前肩 2/44/46，垂直 2/18/16**。720 正常版、静态测试版与 menuconfig 默认均启用 `CONFIG_YX40006ACT_REFERENCE_TIMING=y`，理论约 57.0 Hz。`40006A timing.txt` 的 6/25/25、2/17/20 仅保留用于显式历史对照。截图没有注明 PCLK 采样边沿、同步极性或面板模拟参数，不能视作这些设置也已获厂家确认。当前下降沿输出配置保持不变。
- `LCD/NV3052C-Datasheet-V0.1.pdf`：第 5.2.11、5.2.21、5.2.24、5.2.41 节，标准唤醒、扫描方向、RGB 格式与页选择。
- `CTP/D-FT6336U-DataSheet-V1.1.pdf` 和 `CTP/寄存器地址.pdf`：触摸复位拉低至少 5 ms，复位后等待至少 300 ms；当前 Qualia 共用复位拉低 20 ms，触摸探测前另等待 300 ms。FT6336U 使用 `0x38`、8 位寄存器地址，读取 `0x02` 起的触摸状态和 12 位坐标。保留旧屏 GT911 的 16 位寄存器路径。
- `CTP/All_Drv_MTK_V4.1_20151124_Beta` 解压源码：`focaltech_core.c` 使用 `(0x70 >> 1)`，确认 ESP-IDF 应传入 7 位地址 `0x38`；`focaltech_core.h` 定义芯片 ID 寄存器 `0xA3`，`focaltech_flash.c` 的 FT6336GU 条目为 `0x64`、最多两点。厂家坐标和事件解码与本实现一致。该包面向 MTK/Android，不能直接作为 ESP-IDF 驱动编译；其中升级协议及固件数组不用于本次适配。当前应用只处理单指点击/滑动，多指帧取消当前手势；720 坐标范围和 180° 方向仍需实机核对。

**初始化限制：资料包没有这块面板完整的 Gamma/GIP/电压寄存器表，也未明确承诺出厂配置足以直接点屏。** 本版是待实机验证的出厂配置唤醒路径：硬件复位 → 选择 page 0 → SLPOUT → 等待 120 ms → 设置 18 位 RGB 接口和 180° 扫描 → DISPON。没有写入其他型号的模拟/Gamma/GIP 参数，没有进行 OTP 烧写。若出厂参数不足以点屏，仍需厂家补充该面板初始化表。状态中的 `initialized` 只代表主机端初始化调用成功，不能证明面板已正确点亮；`requires_factory_panel_settings=true` 明确报告这项依赖。

Qualia 仍输出 RGB565 双帧缓冲，经板上红/蓝最低位复制形成屏幕的 18 根 RGB 数据线，因此 NV3052C `COLMOD=0x60`；帧缓冲色深仍是 16 位。原始扫描方向使用 NV3052C `0x36` 的 SS/GS 位；当前保留这些位，并在绘制端额外旋转 180°，触摸坐标随额外旋转变换（当前屏无触摸）。背光保留板上原来的限流设定；资料中的 40 mA 是屏幕背光典型值，软件没有增加电流。

布局、整帧提交、天气背景和触摸区域按物理尺寸缩放。720 双帧缓冲合计 **2,073,600 字节**，保留 20 行 bounce buffer 和 64 KB 数据缓存。字体复用原来四套 7,215 字字库，以逐字双线性插值放大到 27/36/48 像素；只有一个 4,608 字节的临时字形缓冲，不额外常驻完整大字号字库。它是原字形的栅格放大，并非重新生成的高分辨率字体。字库素材、Flash 分区和缓存地址保持兼容，无需扩容或清空缓存。

构建（在 `wifirouter` 目录）：

```sh
./scripts/board.sh qualia-720 build
./scripts/board.sh qualia-720-color-test build
```

产物分别位于 `build/qualia-720/` 和 `build/qualia-720-color-test/`。静态测试图保留 USB 路由，在两个帧缓冲中写入相同的色条、灰阶和边缘刻度，不启动 LVGL 与应用同步，便于先检查面板扫描和颜色。正常版才检测触摸和加载应用。

2026-11-12 实机进展：16 MHz 静态诊断版已烧录并通过 Flash 哈希校验，状态确认 YX40006ACT、720×720、厂家文本时序及 8 MB PSRAM；用户确认显示色条和灰阶，但有闪烁。原固件的引导、分区、应用已读取备份至 `backups/qualia-before-720-20261112/boot-partitions-app.bin`，分区表与新版本一致。16 MHz 诊断固件另存于 `backups/qualia-720-color-16mhz-20261112/`。将 `qualia-720-color-test` 改为 35 MHz、保持其余参数不变后，实机状态确认频率生效，用户确认静态图闪烁消失。正常应用 `qualia-720` 随之改为 35 MHz。35 MHz 诊断版已写入应用分区并通过 Flash 哈希校验（921,024 字节），固件与日志保存在 `backups/qualia-720-color-35mhz-20261112/`；静态图状态和用户观察均已确认。35 MHz 完整应用也已烧录并通过 Flash 哈希校验（1,478,992 字节），备份和日志位于 `backups/qualia-720-app-35mhz-20261112/`；该完整应用实机出现黄色启动画面后循环重启，串口尚未进入触摸检测与首帧绘制。修改字库读取为固定 32 KB 窗口缓存，避免加载时同时持有整份字体源文件和解析结果；补充逐字体 PSRAM 日志及状态中的 `reset_reason`。此修改用于降低内存峰值并定位故障，32 KB 字库缓存版本已烧录并通过哈希校验（1,479,984 字节），实机约 38 秒完成四套字库加载，持续运行超过 6 分钟未重启，HTTP 200 同步与帧切换正常；23 项状态检查通过（curl 获取实机 JSON 后由检查脚本离线验证，Python 直接联网在本机报 No route to host）。证据支持字库加载内存峰值与启动失败相关，但未取得原崩溃堆栈。用户确认本屏不带触摸，因此不要求 `--require-touch`。用户仍观察到完整应用静止时闪烁，尽管 35 MHz 静态色条无闪烁；曾将正常应用时钟调至 30 MHz 进行单变量对照，默认配置保留 35 MHz，30 MHz 对照版已烧录并通过 Flash 哈希校验（1,479,984 字节），实机频率已确认，用户反馈无改善或更严重，并明确为静止画面也整屏亮度忽明忽暗；产物和日志位于 `backups/qualia-720-font-stream-30mhz-20261112/`。原固件和运行记录位于 `backups/qualia-720-font-stream-20261112/`。下载模式需 BOOT0 配合 RESET；本次烧录后的自动 watchdog 复位未恢复 USB，单按 RESET 后正常启动。

在已有相同分区/字库的 Qualia 上，选定镜像后可仅更新应用：

```sh
./scripts/board.sh qualia-720-color-test -p /dev/cu.usbmodem实际端口 app-flash
# 静态图确认后切换完整应用：
./scripts/board.sh qualia-720 -p /dev/cu.usbmodem实际端口 app-flash
python3 scripts/check_router.py http://192.168.2.3 --expect-board qualia_5800 --expect-panel yx40006act --require-display --require-app --require-buffered-display --require-stable-rgb
```

新设备完整烧录使用 `flash`，包含字库素材；不要将 `app-flash` 用于缺少现有素材/分区的新设备。静态诊断模式只使用 `--require-display`，不能要求应用/触摸已运行。状态检查通过也不能替代肉眼确认色彩、画面方向、闪烁和触摸区域。

验证记录：`qualia-720`、`qualia-720-color-test`、`qualia`、`waveshare` 均编译通过，生成配置已确认分别选择正确面板；主机测试共 13 项通过，1 项原 Lua 对照因可选 `lupa` 未安装跳过。新增检查覆盖 FT6336U 事件/坐标边界、1/2/4/8bpp 字形插值及缓冲边界、480/720 状态检查和错误面板/时序拒绝。字体与触摸 C 测试启用 ASan/UBSan。已完成多次应用烧录与哈希校验；启动重启问题经字库缓存修改后未再复现，但完整应用整屏亮度闪动尚未解决。

## 开发板选择（2026-11-09）

微雪版本保留为默认板型；新增 Adafruit **Qualia ESP32-S3 for TTL RGB-666 Displays，产品 5800**。两款板共用原生应用、USB NCM 路由和帧缓冲逻辑，分别选择 RGB 接线及 LCD 控制接口。当前屏幕配置仍是原来的 **4 英寸 ST7701 / 480×480**，不是任意 RGB666 屏的通用初始化。用户已确认 Qualia 继续使用原来的微雪 4 英寸 ST7701 / 480×480 屏幕；已对照双方原理图核对 40pin 的电源、RGB、控制及触摸针脚。两种板型均编译通过，7 项主机测试通过。Qualia 原厂完整 16 MB Flash 已备份至 `backups/qualia-original-20261109/flash-16mb.bin`，旁边保存 SHA256 清单。首版已完整烧录并通过全部镜像哈希校验；USB / DHCP / NAT、HTTP 200 同步、字库及双帧缓冲共 20 项状态检查通过，但用户观察到横条，显示兼容验证尚未完成。仅将 Qualia 像素时钟降至 4 MHz 的诊断版已单独烧录应用，哈希校验通过；重启后 20 项状态检查通过，像素时钟 4 MHz、帧等待超时 0、HTTP 200、四套字库均已确认。用户反馈 4 MHz 后仍有条纹闪烁、画面观感变差，降频方案无效。当前源码和待烧录版本已恢复 8 MHz，并仅为 Qualia 将 SLPOUT 移到寄存器配置之后、DISPON 之前（仍等待 120 ms），其余屏幕参数不变；该版本已烧录并通过哈希校验，运行状态确认 8 MHz 及 `configure_then_sleep_out` 生效，但用户反馈条纹和闪烁基本无变化，故尚未定位根因。微雪保持原始初始化顺序和 8 MHz。

在 `wifirouter` 目录中构建：

```sh
./scripts/board.sh waveshare build
./scripts/board.sh qualia build
```

产物和各自的 `sdkconfig` 分别位于 `build/waveshare/`、`build/qualia/`；原有 `build/` 产物和根目录 `sdkconfig` 不覆盖。原来的 `./scripts/idf.sh build` 默认仍选择微雪。升级前源文件、配置及已有镜像保存在本机 `backups/before-qualia-20261109-174527/`，内有 SHA256 清单。

| 配置 | 微雪 LCD Driver Board | Qualia 5800 |
| --- | --- | --- |
| Flash / Octal PSRAM | 8 MB / 8 MB | 16 MB / 8 MB |
| RGB HSYNC / VSYNC / DE / PCLK | 38 / 39 / 40 / 41 | 41 / 42 / 2 / 1 |
| RGB D0–D7 | 5 / 45 / 48 / 47 / 21 / 14 / 13 / 12 | 40 / 39 / 38 / 0 / 45 / 48 / 47 / 21 |
| RGB D8–D15 | 11 / 10 / 9 / 46 / 3 / 8 / 18 / 17 | 14 / 13 / 12 / 11 / 10 / 9 / 46 / 3 |
| LCD SPI CS / SCK / MOSI | GPIO 42 / 2 / 1 | PCA9554A P1 / P0 / P7 |
| I²C SDA / SCL | 15 / 7 | 8 / 18 |
| LCD reset / backlight | 软件复位 / 无直接控制 | PCA9554A P2 / P4 |

Qualia 使用默认地址 `0x3f`，扩展芯片与 GT911 共享 I²C 总线；IRQ 与 UP/DN 按钮脚保持输入，当前未映射板载按钮操作。初始化期间关闭背光，硬件复位和面板配置完成后开启；I²C 写失败会传播为显示初始化错误，路由继续运行。两板当前源码均使用 8 MHz；Qualia 的 4 MHz 实机对照未解决条纹。两板均使用 20 行 bounce buffer、64 字节 cache line、双帧缓冲和 180° 旋转。16 MB Flash 沿用现有分区布局，缓存地址仍为 `0x710000`，额外容量暂不分配。

接线依据：[Adafruit 引脚说明](https://learn.adafruit.com/adafruit-qualia-esp32-s3-for-rgb666-displays/pinouts)、[CircuitPython 板级引脚](https://github.com/adafruit/circuitpython/blob/main/ports/espressif/boards/adafruit_qualia_s3_rgb666/pins.c)、[I²C 引脚](https://github.com/adafruit/circuitpython/blob/main/ports/espressif/boards/adafruit_qualia_s3_rgb666/mpconfigboard.h)与[官方 Arduino 示例](https://learn.adafruit.com/adafruit-qualia-esp32-s3-for-rgb666-displays/arduino-rainbow-demo)。RGB666 指连接器及面板布线，ESP32 按原厂示例输出 RGB565。不同 40pin 屏的电源针脚不一定相同，应确认屏幕型号及排线定义后烧录。

确认屏幕匹配并备份新板原固件后，完整烧录所选板型（包含字库素材）：

```sh
./scripts/board.sh qualia -p /dev/cu.usbmodem实际端口 flash
# 换回微雪时：
./scripts/board.sh waveshare -p /dev/cu.usbmodem实际端口 flash
python3 scripts/check_router.py http://192.168.2.3 --expect-board qualia_5800 --require-display --require-app --require-buffered-display --require-stable-rgb
```

Qualia 本次 USB 租约为 `192.168.2.3`，Mac 仍使用 `en10` 共享网络。首次按 Boot0 进入下载后，RTS 复位可能仍停留在 ROM；可松开全部按键后按 RESET，或用 esptool `--before no_reset --after watchdog_reset chip_id` 启动应用。

`display.board` 报告 `qualia_5800` 或 `waveshare_lcd`；新版本 `display.init_sequence` 区分 `configure_then_sleep_out`（Qualia）和 `waveshare_original`。Qualia 调整依据为 [Adafruit TL040WVS03 初始化示例](https://learn.adafruit.com/adafruit-qualia-esp32-s3-for-rgb666-displays/qualia-s3-rgb-666-with-tl040wvs03-4-480x480-square-display)的唤醒顺序；仍使用本机原屏幕的所有寄存器值，不替换其他面板的电压参数。编译和状态接口不能证明实际屏幕颜色、触摸及长期刷新正常，需实机观察。下文的屏幕接线和历史实机记录对应微雪旧板。

让 Mac 保持连接原来的 Wi-Fi，通过 USB 把网络分享给 ESP32-S3，再由 S3 提供 **ap24** 2.4 GHz 热点。

```text
互联网 ← 当前 Wi-Fi ← Mac 互联网共享 ← USB CDC NCM ← ESP32-S3 ← ap24 ← 小屏/其他设备
```

## Qualia 色彩诊断

`./scripts/board.sh qualia-color-test build` 生成独立诊断镜像 `build/qualia-color-test/ap24_router.bin`，不覆盖正常 Qualia 或微雪构建。诊断保留 USB 路由、相同的面板初始化和 8 MHz RGB 扫描；在两个帧缓冲中直接写入相同的 RGB565 原色条、灰阶、白边和单像素刻度后不再改写，完全不启动 LVGL 应用、字体读取或显示 API 同步。`display.test_pattern=static_rgb565_bars_gray_grid` 标识诊断模式。

色条诊断版已单独烧录应用（926,288 字节），Flash 哈希校验通过；运行状态确认 `static_rgb565_bars_gray_grid`、RGB565、480×480、8 MHz、PSRAM 8 MB 以及 USB / NAT 正常。诊断模式下 `app.state=starting` 是未启动业务应用的预期状态，额度不会刷新。用户确认静态图案没有条纹或闪烁，说明相同 RGB565 和面板时序在静态负载下可以正常显示；后续排查转向应用绘制、帧切换和内存带宽，尚不能据此排除负载相关的硬件因素。观察静态色条可区分像素颜色/数据线问题与应用绘制负载问题，但不能只凭状态接口判断肉眼条纹。恢复正常界面只需重新烧录 `build/qualia/ap24_router.bin`，无需重刷素材。480×480 和 RGB565 始终不变；RGB666 连接器并不代表 ESP32 实际输出 18 位独立数据，Qualia 官方也使用 16 根数据线。

正常 Qualia 版本准备进行单变量对照：仅将数据缓存容量从 32 KB 增至 64 KB，恢复完整应用，保留 8 MHz / 20 行 bounce / RGB565 / 480×480 和原来的双帧同步。每次 RGB 预取覆盖 19,200 字节，字体与 LVGL 也会使用数据缓存；扩大容量是针对缓存竞争的验证，并非已确认根因。状态新增 `display.data_cache_bytes`；64 字节的缓存行大小与 64 KB 缓存容量是不同参数。微雪与静态色条配置保持原样，之前的正常 Qualia 固件及配置备份到 `backups/qualia-before-cache64-20261109/`。已有 `build/qualia/sdkconfig` 需同时启用 `CONFIG_ESP32S3_DATA_CACHE_64KB`（defaults 不覆盖已有配置）。参见 [Espressif 的 PSRAM/LVGL 缓存配置建议](https://docs.espressif.com/projects/esp-iot-solution/en/latest/display/tools/esp_lvgl_adapter.html#psram-optimization-when-available)。正常 Qualia 验证版已编译通过（1,481,408 字节），7 项主机测试通过，微雪版本也重新编译通过。此版已单独烧录应用并通过 Flash 哈希校验；启动后 21 项状态检查通过，确认数据缓存 65,536 字节、四套字库加载、HTTP 200 同步、帧等待超时 0，USB / NAT 正常。初次抽样最大 VSYNC 间隔为 34.183 ms。用户随后确认有改善，但反馈渐变有明显色阶、颜色种类偏少；尚未确认条纹和闪烁完全消失。

### Qualia 渐变过渡优化

用户已将颜色问题明确为渐变色阶，而不是红蓝颠倒或整体偏色。Qualia 当前输出 RGB565，共 65,536 个可编码颜色；[Adafruit 官方彩虹示例](https://learn.adafruit.com/adafruit-qualia-esp32-s3-for-rgb666-displays/arduino-rainbow-demo)也采用 RGB565。原有 LVGL 渐变不抖色，深色、小色差渐变容易出现条带。

仅正常 Qualia 配置启用 `CONFIG_LV_DITHER_GRADIENT`，在订阅卡片的纵向渐变上使用固定 8×8 空间抖色；保留 64 KB 数据缓存、480×480、16 位双缓冲以及相同扫描时序，不使用时间抖色。`app.gradient_dither=ordered_rgb565_adjacent_levels` 标识优化已启用。微雪与静态色条配置保持不变。空间混色可以改善过渡的视觉效果，但不会增加硬件色深，近看也可能看见细小纹理。

本项目锁定的 LVGL 8.3.11 有序抖色给 8 位通道加入 -32～31 的扰动，对 RGB565 暗色偏大。项目通过仅 Qualia 生效的链接包装替换纵向抖色函数，在高精度渐变值两侧的相邻 5/6 位色阶间分配固定图案，不修改托管依赖源码。若升级 LVGL，需重新核对该函数接口及渐变绘制调用方式。8 项主机测试通过，包含实际 C 代码的相邻色阶约束、所有 256 通道值的平均误差、黑白端点、重复帧确定性和短行越界检查（ASan/UBSan）。软件暗阶预览已检查，条带减轻；Qualia / 微雪均编译通过。此前改善条纹的固件及配置已保存至 `backups/qualia-cache64-before-dither-20261109/`。优化版应用 1,482,448 字节已烧录并通过 Flash 哈希校验。启动后确认抖色标识与 64 KB 缓存生效，21 项状态检查通过；18 秒抽样跨越一次切页，提交帧由 4 增至 5，等待超时保持 0，最大 VSYNC 间隔 34.185 ms；所抽样便签页刷新 92.82 ms，启动以来最大刷新 573.728 ms。实际渐变观感与闪烁是否改善仍待用户反馈。

### 与旧微雪显示效果的对照（待定位）

用户进一步明确：同一块屏幕在旧微雪设备上清晰，换 Qualia 后颜色层次不足。因此不能将新出现的差异简单归因于 RGB565；暂不把增加渲染位深或更多抖色作为已证实的修复。当前硬件仍运行已烧录的有序抖色版本，尚未加入 RGB888 渲染。

核对[微雪驱动板原理图](https://files.waveshare.com/wiki/ESP32-S3-LCD-Driver-Board/ESP32-S3-LCD-Driver-Board-Sch.pdf)和 [Qualia 原理图](https://github.com/adafruit/Adafruit-Qualia-S3-RGB666-PCB)：两者 40pin 的 R0/R1、B0/B1 均连到同一个红/蓝最低位输出，因此这项位复制方式一致。当前 GPIO 映射与各自接线吻合；像素尺寸、RGB565 格式、8 MHz 时钟、扫描边沿/前后肩及面板 Gamma 寄存器值沿用旧版。Qualia 独有的初始化唤醒顺序和背光电路仍属于对照项。

[屏幕手册](https://files.waveshare.com/wiki/ESP32-S3-LCD-Driver-Board/4inch-Touch-LCD-Module-User-Manual.pdf)同时标注 16.7M 显示色数与 18 位 RGB 输入，未说明二者如何对应，不能据此称当前链路具备 24 位独立输出。该手册背光典型电流 40 mA；[Qualia 默认背光电流为 25 mA](https://learn.adafruit.com/adafruit-qualia-esp32-s3-for-rgb666-displays/backlight-settings)，这可能影响亮度/暗部观感，但不是已确认的色阶根因。当前软件已将背光使能置高，增加电流涉及硬件设定，不作未经屏幕电流上限核实的调整。尚需实际屏幕近照或同一页面的旧/新板对照，区分色阶、低位数据异常及亮度差异。

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

像素时钟 8 MHz（约 29.3 帧/秒），HSYNC 脉宽/后肩/前肩为 8/10/50，VSYNC 为 3/8/8。RGB565 双帧共占 921,600 字节 PSRAM，两块内部 DMA 缓冲各容纳 20 行（共 38,400 字节）；LCD 中断分配到 core 1，Wi-Fi 使用 core 0。数据缓存行使用 64 字节，LCD / DMA 回调在 IRAM 执行，回调信号量使用静态内部 RAM；关闭每帧强制 DMA 重启，由驱动在发现中转缓冲 EOF 不足时于 VSYNC 恢复。RGB 硬件持续扫描输出；LVGL 在后台帧缓冲画完整页，再在帧边界切换，避免 40 行分块更新逐渐出现在屏幕上。通过 ST7701 硬件同时反转 X/Y 扫描方向，将画面旋转 180°；触摸坐标同步映射为 `(479-x, 479-y)`，无需软件旋转像素。两个缓冲直接交替用作 LVGL 画布和 LCD 帧，无需整屏复制；等待 RGB bounce-buffer 的 frame-complete 回调后才重用旧前台缓冲。仅变化的控件触发重绘，启用 2 张 PNG 解码缓存和 4 KB 渐变缓存。天气 PNG 沿用原应用素材，中文字体按 480×480 屏幕重新生成。原厂配置没有独立背光和复位 GPIO，使用软件复位；GPIO45 是 RGB 数据线，不可当作背光控制。USB 使用的 GPIO19/20 不变。

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

## 顶部绕到底部的偶发错位（2026-11-04）

左侧杂色修复后，用户另报偶发整幅画面纵向循环错位，并确认切页不会恢复、需要重启。抽样时 VSYNC 与完整帧计数均为 2,112、等待超时为 0；这只能证明扫描继续运行，不能判断行起点是否正确。

检查本项目锁定的 ESP-IDF 5.5.2 驱动发现：`lcd_rgb_panel_eof_handler` 用 `bb_eof_count % 2` 选择待填充缓冲；开启 `CONFIG_LCD_RGB_RESTART_IN_VSYNC` 时，每帧复位 DMA，却绕过了条件恢复路径里的 `bb_eof_count = 0`。若 EOF 中断出现丢失 / 延迟并破坏缓冲相位，强制重启可能延续错误相位。这与按一小块行数循环错位的表现一致，但尚未实机捕获触发瞬间。

验证版关闭 `CONFIG_LCD_RGB_RESTART_IN_VSYNC`，使用驱动默认的 EOF 不足检测及 VSYNC 恢复；继续使用 8 MHz、20 行缓冲、64 字节缓存行和 IRAM-safe 回调。状态接口增加 `restart_policy`，检查脚本要求为 `on_underflow`。当前仅修改重同步策略，未修改画面布局或字库。ESP-IDF v5.5.2 编译通过，固件 1,479,776 字节；生成的 sdkconfig 确认已禁用每帧重启。等待烧录和多次切页 / 同步后的复现观察。

已有 `sdkconfig` 会覆盖默认值，升级时请在 menuconfig 关闭 “Always restart RGB LCD transmission in VSYNC”，或重新生成 sdkconfig。仅需更新应用，不需重烧字库或更改分区。

## 实现参考

显示功能实机验证（2026-11-03）：ESP-IDF v5.5.2 编译通过，应用 900,416 字节；配置校验测试 3 项通过，烧录后 Flash 哈希校验通过。正常拔插 USB 后新固件启动，用户确认整屏变黄。`--require-display` 实机检查 7 项通过：DHCP、USB、NAT、无网段重叠、ST7701 初始化、480×480 便签黄配置和 8 MB PSRAM；内部空闲堆约 176 KB。烧录前客户端租约检查通过；烧录后检查时没有热点客户端连接，因此未重新验证客户端外网访问。

- [ESP USB Device 官方说明](https://docs.espressif.com/projects/esp-usb/en/latest/esp32s3/usb_device.html)
- [ESP-IDF v5.5.2 USB 网络示例](https://github.com/espressif/esp-idf/tree/v5.5.2/examples/peripherals/usb/device/tusb_ncm)
- [Apple：共享 Mac 的互联网连接](https://support.apple.com/guide/mac-help/share-internet-connection-mac-network-users-mchlp1540/mac)
- [微雪 LCD Driver Board 官方资料](https://www.waveshare.com/wiki/ESP32-S3-LCD-Driver-Board)
- [Espressif ST7701 驱动](https://components.espressif.com/components/espressif/esp_lcd_st7701/versions/2.0.3/readme)

### 720 屏参考时序对照（进行中）

`CONFIG_YX40006ACT_REFERENCE_TIMING=y` 使用资料图片的 H=2/44/46、V=2/18/16；最初默认关闭时使用型号文本的 H=6/25/25、V=2/17/20；厂家于 2026-11-13 确认图片参数后，默认改为开启。当前正常版选择参考时序并恢复 35 MHz（理论约 57.0 Hz），已烧录并通过 Flash 哈希校验（1,480,048 字节），状态已确认参考时序生效，但用户反馈无改善或更严重。连续约 71 秒采样中 uptime 从 233 增至 304 秒，无自行重启，HTTP 同步与帧切换正常；画面静止时仍有整屏亮度闪动。该完整应用参考时序实验不能标记显示兼容完成；后续又进行了下述静态中灰测试。产物和日志保存在 `backups/qualia-720-reference-20261112/`。状态新增 `display.timing_source`；检查参考配置使用 `--expect-timing reference --expect-pclk 35000000`。本屏无触摸，不加 `--require-touch`。未修改背光电流、Gamma、GIP 或 VCOM 参数；临时分块绘制方案未纳入固件。


### 静态中灰与 PNG 色阶（2026-11-12）

启用 `CONFIG_DISPLAY_TEST_MIDGRAY=y` 后，两个帧缓冲固定为 RGB565 `0x8410`，不启动 LVGL、字体和应用同步。35 MHz / 图片参考时序诊断版已烧录并校验；运行状态确认 `static_rgb565_midgray_8410`，采样 uptime 为 447 秒，用户确认均匀灰色也明显闪烁。备份位于 `backups/qualia-720-midgray-20261112/`。这说明闪烁不依赖应用绘制或渐变抖色，但尚不能区分面板初始化、扫描或供电问题。现有资料没有该面板专用的完整初始化表，需要厂家提供匹配 FPC-40006A-V01 / YX40006A 的 Gamma、VCOM、GIP、电压设置与时序/极性；没有尝试其他型号的模拟参数。

720 正常版新增 `CONFIG_APP_PNG_RGB565_DITHER`（默认开启），在 LVGL PNG 解码后、RGB565 打包前，对原始 RGBA8 做静态蛇形误差扩散，保留 alpha。每通道限制在相邻两个 RGB565 码值之间；透明像素不向邻居扩散误差。工作区只有两行，分配失败时保留原始解码结果供 LVGL 常规打包。该功能通过链接包装接入，不修改托管依赖；已有渐变空间抖色保持开启。它改善 PNG 颜色量化，不能让 Qualia 的 16 位输出变成 24 位，也不作为闪烁修复。

正常版编译通过，应用 1,480,448 字节；链接映射确认 PNG 包装与量化函数已纳入镜像。主机测试 14 项中 13 项通过、1 项可选 Lua 对照跳过；新增 ASan/UBSan 测试覆盖所有 256 级输入、相邻码值、透明度、重复结果、短行边界及非法尺寸。标准 RGB565 数值模型的测试图平均通道误差由 2.0788 降至 0.0720，这不是面板实测色差。镜像与配置位于 `backups/qualia-720-image-quantize-20261112/`，已只更新应用分区并通过 Flash 哈希校验；实机状态确认四套字库、HTTP 200 同步与 PNG 量化标识生效，帧等待超时为 0。但用户反馈仍闪烁、颜色过渡无明显改善，因此不能标记色阶问题已解决。

换板对照尚未实施：用户提出用微雪板对照，随后要求暂停，先核查 Qualia 的 RGB666 能力。官方产品 5800 说明明确写出 16 个 TFT 数据 GPIO 用于 RGB565；RGB666 指兼容的 40pin 面板接口。本地 ESP-IDF 的 ESP32-S3 `SOC_LCDCAM_RGB_DATA_WIDTH=16`，RGB 驱动拒绝超过该宽度的总线。当前 NV3052C 已设置 `COLMOD=0x60`（18 位物理输入），不能仅把主机 `data_width` 改为 18 来获得独立 RGB666。未为此更改或烧录显示格式。


### Qualia 背光亮度对照（准备完成，未烧录）

用户要求测试亮度，但尚未确认 PWM 焊桥是否接通，且没有焊接过。依据 [Qualia 官方引脚说明](https://learn.adafruit.com/adafruit-qualia-esp32-s3-for-rgb666-displays/pinouts)和原理图，SJ7 将 A1/GPIO16 连接到 TPS61169 CTRL；该节点还连接 PCA9554A P4。硬件支持 PWM 不等于当前程序正在 PWM 调光：设备上已烧录的程序只把 P4 持续置高。

新增 `CONFIG_QUALIA_BACKLIGHT_PWM`（默认关闭）及 `CONFIG_QUALIA_BACKLIGHT_PERCENT`。启用时先释放 P4 为输入，再初始化 GPIO16 LEDC，避免共网输出冲突；20 kHz、10 位占空比，100% 使用持续高电平，关闭为持续低电平。[TI TPS61169 手册](https://www.ti.com/lit/ds/symlink/tps61169.pdf)规定 PWM 输入 5–100 kHz，并通过占空比调节内部电流参考，不应把芯片的 1.2 MHz 开关频率等同于背光明暗闪动。

独立 `qualia-720-pwm-test` 配置使用 35 MHz 图片参考时序、静态中灰、50% PWM 占空比；构建命令为 `./scripts/board.sh qualia-720-pwm-test build`。此模式需要物理 SJ7 已接通、A1 没有其他外设；状态报告请求占空比，不声称测得实际亮度或焊桥状态。PWM 测试版和默认关闭 PWM 的正常版均编译通过。测试镜像备份到 `backups/qualia-720-pwm50-unflashed-20261112/`，尚未烧录、未验证实际亮度或闪烁变化。当前设备仍运行原 PNG 色阶实验版。


### RGB666 接线感知的颜色量化（2026-11-12，待上屏验证）

用户移动排线后反馈似乎不再闪烁。保持当前接线并观察，接触问题仍只是线索，尚未确定根因；本次颜色修改不调整扫描时序、背光、VCOM 或 Gamma。

依据 [Qualia 原理图](https://github.com/adafruit/Adafruit-Qualia-S3-RGB666-PCB/blob/main/Adafruit%20Qualia%20S3%20RGB666.sch)，J1 的 R0/R1（28/29）共接 IO11，B0/B1（16/17）共接 IO40。红蓝通道的五位码 q 实际形成六位码 `2*q + (q&1)`，级差交替为 3 和 1；不是等间隔的 `q*63/31`。新增 `qualia_color.h` 统一描述这个可输出码值集合。720 屏的渐变有序抖色、PNG 静态误差扩散均选择实际相邻码值，并按接口码值反馈误差；绿通道仍为独立六位。旧 ST7701 480 屏保留原有渐变量化算法。

不增加整帧副本或时域抖色。RGB565 双缓冲、NV3052C `COLMOD=0x60`、35 MHz 图片参考时序和关闭 PWM 的配置保持不变。状态分别报告 `rgb_independent_data_bits=16`、`rgb_connector_data_bits=18`，以及 `rgb565_to_rgb666_rb_lsb_duplicated` 接线方式，避免把兼容 RGB666 宣称为完整独立 18 位输出。应用标识为 `static_qualia_rgb666_mapped_diffusion` 和 `ordered_qualia_rgb666_mapped_levels`。

主机测试共 15 项，14 通过、1 项可选 Lua 对照跳过；包含旧算法回归以及按独立接线模型检查 256 级输入、平均码值误差、相邻码值、黑白端点、透明度、重复确定性和 ASan/UBSan 边界检查。按六位接口码归一化的 PNG 测试平均误差 0.0752，直接截断为 2.1386（0–255 数值尺度）；这不是光学色差或 Gamma 测量，不能直接推断肉眼改善。720 正常版与旧 480 Qualia 均编译通过。产物保存于 `backups/qualia-720-rgb666-mapped-20261112/`，2026-11-13 已仅更新应用分区，1,480,976 字节写入并通过 Flash 哈希校验；等待 RESET 后启动和上屏确认。


2026-11-13 实机否定结果：RGB666 接线量化实验烧录并通过哈希校验后，用户反馈“有明显错误，还闪烁”。不能认定数值误差改善带来实际显示改善，也未定位错误类别。已归档实验源码、固件及状态，撤回运行路径中的接线量化，恢复此前 RGB565 图片/渐变算法；准确的 16 位独立数据、18 根接口线状态说明保留。准备直接恢复 `backups/qualia-720-image-quantize-20261112/ap24_router.bin`（SHA256 `8ee2669ceb52aa655947aee0d108f5c1b0b283c96f81d01a400e89d917ebeefc`），该镜像是用户移动排线后曾暂时不闪的上一版，不能称为已确认长期稳定。

回退执行结果：2026-11-13 已将上述上一版镜像（1,480,448 字节）写回应用分区并通过 Flash 哈希校验。源代码也已恢复原颜色算法，正常版编译通过，14 项主机测试中 13 项通过、1 项跳过。运行中的实验版最后采样 uptime=143 秒、四套字库加载、HTTP 200、帧等待超时 0；这些状态不能排除视觉错误。用户确认回退后新增显示错误消失，但仍有闪烁。颜色映射实验已撤回，闪烁问题仍未解决；先固定原固件继续检查排线和连接。


### 厂家确认时序（2026-11-13）

将厂家截图中的 35 MHz / H=2/44/46 / V=2/18/16 固定为 720 配置默认值，检查脚本默认也改为 `reference`。从设备 HTTP 状态逐项核对：当前已运行相同的分辨率、时钟与六项时序参数，因此无需为了这组参数重复烧录。此确认排除了继续在两份时序资料之间猜测的必要，但不代表闪烁已修复；采样边沿和专用初始化仍未由截图确认。


### 恢复原 480 屏对照（2026-11-13）

用户换回原 ST7701 480×480 屏，开发板仍为 Qualia。检查发现换屏后的设备仍运行 NV3052C 720×720 / 35 MHz 配置，不能用该状态判断旧屏兼容性。重新构建 `qualia` 正常版，确认 ST7701、480×480、8 MHz、64 KB 数据缓存、20 行 bounce、PWM 关闭；只写入应用分区，1,484,752 字节并通过 Flash 哈希校验。备份和日志位于 `backups/qualia-480-return-20261113/`，重启后实机状态确认 Qualia / ST7701 / 480×480 / 8 MHz，用户确认显示正常、不闪烁。

8 MHz 是此前旧屏传输稳定性排查保留的像素时钟，不是面板性能上限。H=8/10/50、V=3/8/8 时，一帧 548×499=273,452 个周期，理论刷新率约 29.26 Hz；720 屏厂家参数一帧 812×756=613,872 周期，35 MHz 对应约 57.02 Hz。两次换屏对照的分辨率、面板、初始化及刷新率均不同，不能单凭结果确认唯一故障原因。


### 480 屏约 60 Hz 对照（2026-11-13）

新增 `CONFIG_ST7701_PCLK_HZ`，默认保留已验证的 8 MHz；独立 `qualia-480-60hz` 配置选择 16,407,120 Hz，在原 H=8/10/50、V=3/8/8 时序下理论为 60 Hz。双缓冲、20 行 bounce、64 KB 缓存、初始化、颜色处理、采样边沿及背光保持原 480 配置。状态新增 `configured_refresh_hz`（名义值，不是电气实测）。检查高刷新率版本时加 `--expect-pclk 16407120`。

构建命令：`./scripts/board.sh qualia-480-60hz build`。新增配置项后旧构建目录需要执行一次 `./scripts/board.sh qualia reconfigure build` 更新 sdkconfig；正常 8 MHz 版本与新版本均编译通过，状态检查测试通过。480 屏手册 RGB 时序表规定 DOTCLK 周期至少 33 ns，16.407 MHz 约 60.95 ns；满足该项规格不等于完整系统已经通过稳定性验证。参考：https://files.waveshare.com/wiki/ESP32-S3-LCD-Driver-Board/4inch-Touch-LCD-Module-User-Manual.pdf （印刷页 11）。

高刷新率产物备份于 `backups/qualia-480-60hz-20261113/`；原先用户确认不闪、功能正常且颗粒感消失的版本为 `backups/qualia-480-return-20261113/` 的 8 MHz 固件。该观察发生在 60 Hz 烧录之前，不能归因于刷新率提升。

60 Hz 实验版已仅更新应用分区，1,484,784 字节并通过 Flash 哈希校验，重启后确认 16,407,120 Hz / 名义 60 Hz，22 项运行状态检查通过（curl 实机 JSON 离线校验）；100 秒扫描采样平均 59.240 次/秒，帧等待超时 0。用户确认显示正常、不闪不花，当前保留此版；尚未进行长期压力测试。


### 720 屏片内灰色对照（2026-11-13）

用户断电换回 NV3052C 720 屏。独立 `qualia-720-sram-test` 配置保留厂家 35 MHz / H=2/44/46 / V=2/18/16、原采样边沿与标准初始化、背光常亮。新增 `CONFIG_DISPLAY_TEST_SRAM_ONLY`，依赖静态中灰诊断配置。设置 RGB `no_fb=true`、`num_fbs=0`，不获取或分配整屏帧缓冲；使用两块内部 DMA 缓冲，每块 720×20×2=28,800 字节，合计 57,600 字节。IRAM `on_bounce_empty` 回调以 32 位常量写入 RGB565 `0x8410`，不读取 PSRAM 像素。其他系统功能仍可使用 PSRAM，不能称为整个系统禁用了 PSRAM。

参考 [ESP-IDF 5.5.2 Bounce Buffer Only](https://docs.espressif.com/projects/esp-idf/en/v5.5.2/esp32s3/api-reference/peripherals/lcd/rgb_lcd.html#bounce-buffer-only)。启动前注册填充、VSYNC 与完整帧回调；状态报告 `pixel_source=internal_sram_generated_gray`、`frame_buffers=0`、填充次数、扫描次数和最大填充耗时。没有 LVGL、字体加载或应用同步；USB 路由仍工作。对照目标是此前同 35 MHz 时序的 PSRAM 静态中灰，不与完整应用的绘制负载混为一谈。

诊断版构建通过（922,640 字节）；正常 480/60 Hz 分支也重新编译通过。主机全套 15 项测试中 14 项通过、1 项可选 Lua 跳过，32 位填充优化后相关 5 项测试再次通过。新增 ASan/UBSan 测试覆盖 0/1/奇数/整块像素及前后边界；ELF 符号确认三个回调和 atomic helper 在 `.iram0.text`，计数器在 `.dram0.data`。产物与配置位于 `backups/qualia-720-sram-test-20261113/`。硬件实际结果待观察。

片内灰色实机结果：烧录并校验通过，用户确认一直闪烁。状态证实无整屏帧缓冲、片内像素源，35 MHz 时序保持不变。67 秒采样扫描回调平均 57.507/秒，完整帧回调平均 57.507/秒，最大填充耗时 359.30 µs（20 行名义有效传输时间约 411.43 µs、含行消隐约 464 µs）。该耗时不包含回调开始之前的中断等待，不能证明完全没有欠载。PSRAM 图像读取竞争作为主因的可能性降低，初始化/信号/供电仍待区分。


### PCLK 边沿单变量对照（2026-11-13）

重新检查用户指定的 `CTP/All_Drv_MTK_V4.1_20151124_Beta/...` 源码目录：readme 明确为 MTK xx82 平台，v4.1 新增 FT6336G/U；`focaltech_core.c` 为触摸驱动，附带触摸升级固件与手势库。没有发现 NV3052C/YX40006 LCD 初始化、PCLK/HSYNC/VSYNC 或 VCOM/Gamma 配置，不能将触摸升级字节作为 LCD 寄存器表。

用户授权继续试验后，新增独立 `qualia-720-sram-edge-test` 配置，保持 35 MHz、厂家 H/V 时序、内部 SRAM 灰色、标准唤醒、常亮背光，仅关闭 `CONFIG_YX40006ACT_PCLK_ACTIVE_NEG`。生成的两份 sdkconfig 全文比较确认只有这一项不同。该项是主机输出边沿对照，不代表已经确认面板采样极性；当前无法据此推断 VCOM 值。

测试镜像构建通过，备份位于 `backups/qualia-720-sram-edge-test-20261113/`。此前原边沿片内灰屏已确认仍闪烁，保留其固件作对照；反向边沿应用已烧录（922,640 字节）并通过 Flash 哈希校验，等待 RESET 后的运行检查和肉眼观察。


### 反向 PCLK 边沿完整应用验证（2026-11-13）

反向边沿片内灰屏已烧录并校验通过，运行状态确认 `pclk_active_neg=false`、35 MHz、内部灰色像素源。用户先报告不闪，随后修正为“闪烁减轻，仔细观察不出来”；应记录为改善迹象，尚不能确认闪烁完全消除。47 秒采样 VSYNC 与完整帧回调均约 56.72 次/秒。

新增 `qualia-720-edge-test` 完整应用配置，恢复双 PSRAM 帧缓冲、字体和同步。生成的 sdkconfig 与正常 `qualia-720` 全文比较只有 `CONFIG_YX40006ACT_PCLK_ACTIVE_NEG` 一项不同。构建通过，固件 1,480,800 字节，产物在 `backups/qualia-720-edge-app-20261113/`。原默认边沿保留作对照，未因灰屏观察提前宣告该设置为最终修复。

反向边沿完整应用已写入应用分区并通过 Flash 哈希校验，等待重启后的运行状态和视觉观察。


反向边沿完整应用的否定结果：用户先反馈“仍有轻微闪烁，但明显改善”，随后明确黑/灰文字变成其他颜色或整体偏色。实机状态 uptime=139 秒、四套字体加载、HTTP 200、帧等待超时 0、颜色算法与原版一致，`pclk_active_neg=false` 已生效。该试验因偏色未通过，不能用灰屏闪烁减轻判定为有效修复；像素采样异常成为合理解释，但未取得电气波形证据。保留实验产物与日志，常规默认边沿仍为 `true`；准备回退至 `qualia-720-image-quantize-20261112` 的原边沿镜像。

2026-11-13 已撤销反向 PCLK 边沿实验，恢复此前原边沿 720 完整应用（1,480,448 字节），Flash 哈希校验通过。日志保存于 `backups/qualia-720-edge-app-20261113/rollback-flash.log`；等待 RESET 后确认偏色恢复。闪烁仍未解决。

回退后状态已确认 `pclk_active_neg=true`、35 MHz、完整应用运行；偏色是否消除仍待用户肉眼确认。


### 24 MHz 片内灰屏对照（2026-11-13）

反向边沿出现偏色后，恢复原边沿 `pclk_active_neg=true`。用户要求继续尝试，新增 `qualia-720-sram-24mhz-test`：与此前已闪烁的 35 MHz 片内灰屏相比，生成的 sdkconfig 全文只改变像素时钟为 24 MHz。保持 H=2/44/46、V=2/18/16、标准唤醒、背光常亮和 SRAM 生成 `0x8410`。

这是诊断实验，不替代厂家确认的 35 MHz 默认。理论刷新率降为 39.096 Hz，每 20 行含消隐扫描时间约 676.67 µs（原来 464 µs），同时改变了输出数据速率和帧频。可以观察增加传输/填充余量是否改善，但即便仍闪烁，也不能单独排除高速信号因素，因为低刷新率是伴随变量。此前 30 MHz 实验使用完整应用，不能视为同一片内像素路径的重复测试。

构建通过，固件与配置保存于 `backups/qualia-720-sram-24mhz-test-20261113/`，应用已写入（922,640 字节）并通过 Flash 哈希校验，等待 RESET 后的运行状态及实际闪烁观察。

24 MHz 片内灰屏结果：状态确认频率、原边沿与内部像素源均生效，用户反馈没有改善或更严重；uptime=47 秒，VSYNC/完整帧计数均为 1814，最大填充约 360.10 µs。停止降频方向的重复实验，当前保留固定灰屏以便进行独立供电对照。


### 24 MHz 灰屏稳定后的完整应用对照（2026-11-13）

后续用户反馈灰屏逐渐不闪，并确认期间未重启、换供电或动排线；继续观察后确认一直不闪，断电重启对照后仍反馈稳定。此后续结果修正上面的初次负向观察，但没有测量温度、电源波形或精确观察时长，不能确定最初变化的原因。

新增独立 `qualia-720-24mhz-test` 完整应用配置，基于正常 `qualia-720` 仅将像素时钟改为 24 MHz，保持原 PCLK 边沿、厂家 H/V 消隐参数、原颜色算法及常亮背光。恢复双 PSRAM 帧缓冲、字体与应用同步，以验证真实界面负载；默认 35 MHz 配置保留。构建命令：`./scripts/board.sh qualia-720-24mhz-test build`。灰屏固件仍保留作对照；完整应用尚未烧录或通过视觉验证。

24 MHz 完整应用构建通过；生成的 sdkconfig 全文比较确认相对正常 35 MHz 完整应用只改变 PCLK 频率。固件 1480800 字节，备份于 `backups/qualia-720-24mhz-app-20261113/`，SHA256 `581a53005d94787b185d5570253967d3bdc396d1c85cd80e94def973a2926b9e`。待进入下载模式后仅更新应用分区。

2026-11-13T14:41:43+09:00 24 MHz 原边沿完整应用已仅写入 0x10000 应用分区，1,480,800 字节，esptool 返回成功且 Hash of data verified。保持 bootloader，等待用户 RESET 后检查运行和视觉结果；尚未认定完整应用稳定。


24 MHz 完整应用视觉验证：用户确认不闪、颜色看着还行；状态确认字体加载、同步正常、帧等待超时 0。用户随后要求相对当前画面旋转 180 度。新增独立于时序的 `CONFIG_YX40006ACT_ROTATE_180`，原配置默认开启，24 MHz 应用配置关闭，将 NV3052C MADCTR 的 SS/GS 从 0x03 改为 0x00；RGB/BGR 位不变。状态中的角度相对面板原生扫描方向，因此此次为 0 度，实际画面相对上一版翻转 180 度。480 屏仍保持原来的 180 度。旋转前稳定固件保存在 `backups/qualia-720-24mhz-app-20261113/`。

旋转版 720 完整应用与原 480/60 Hz 配置均编译通过。生成配置比较确认稳定版只新增旋转选项；720 旋转产物保存在 `backups/qualia-720-24mhz-rotate-20261113/`，待烧录及方向验证。

2026-11-13T14:47:22+09:00 旋转版已仅写入 0x10000 应用分区（1,480,800 字节），Flash 哈希校验通过，保持 bootloader。待 RESET 后验证实际方向、颜色与闪烁。

2026-11-13T14:50:00+09:00 用户否定硬件扫描旋转版：“方向不对，又开始闪了”。状态确认 24 MHz、原 PCLK 边沿、rotation_degrees=0、应用正常且 frame_wait_timeouts=0，不能据这些计数判定视觉稳定。准备恢复用户明确确认不闪且颜色尚可的 qualia-720-24mhz-app-20261113 镜像（SHA256 581a53005d94787b185d5570253967d3bdc396d1c85cd80e94def973a2926b9e）。撤销 24 MHz 配置的扫描方向变更，后续方向需求应另行验证绘制端旋转。

2026-11-13T14:51:55+09:00 已恢复旋转前的 24 MHz 完整应用（qualia-720-24mhz-app-20261113，1,480,800 字节），仅更新 0x10000 应用分区，Flash 哈希校验通过。保持 bootloader，等待 RESET 后确认是否重新稳定；旋转需求尚未完成。

2026-11-13T14:52:58+09:00 用户确认回退后仍闪。实时采样 uptime=35 秒，应用已运行、4 套字库、HTTP 200、帧等待超时 0；display 配置逐项与此前用户确认不闪的状态比较，除可变空闲内存外完全相同（24 MHz、原边沿、MADCTR 原方向、原 H/V 时序）。之前“不闪”的结果尚不能视为可重复的稳定修复；不能仅归因于扫描方向修改。当前启动时间较短，先保持固件和供电连接不动，观察启动数分钟后是否仍闪，再决定下一项对照。

2026-11-13T14:56:19+09:00 用户澄清：没有拔 Type-C，只按 RESET，仍然闪。尚未确认按 RESET 前是否已经不闪，不能据此认定 RESET 重新触发闪烁。状态：24 MHz、原方向、原边沿，uptime=70 秒、应用正常、帧等待超时 0。源码核对：MCU 启动时会通过 PCA9554A 将屏幕 RESET 拉低 20 ms、释放后等待 120 ms，再执行显示唤醒；因此按 MCU RESET 后也会重新初始化面板，不是仅重启 UI。暂不改固件。

2026-11-13T15:04:14+09:00 按用户要求恢复 35 MHz 完整应用：qualia-720-image-quantize-20261112/ap24_router.bin，SHA256 8ee2669ceb52aa655947aee0d108f5c1b0b283c96f81d01a400e89d917ebeefc。原 PCLK 边沿、厂家 H=2/44/46 V=2/18/16，原 RGB565 颜色处理。仅写入 0x10000 应用分区，1,480,448 字节，Flash 哈希校验通过，保持 bootloader 等待用户 RESET。24 MHz 实验不作为已解决闪烁的配置；旋转需求尚未完成。

2026-11-13T15:06:48+09:00 恢复 35 MHz 完整应用后用户反馈“又不闪了”。实机状态：PCLK=35000000，原边沿=True，uptime=8 秒，frame_wait_timeouts=None。此为当前视觉观察，不是长期稳定或根因确认；35 MHz 也可暂时不闪，不能把此前改善单独归因于降频至 24 MHz。保持当前固件及连接继续使用观察，暂不改变旋转或参数。

2026-11-13T15:36:12+09:00 引导对照第 3 步结果：要求固定板端 Type-C 和排线，在供电端断电约 60 秒后插回同一端口，用户反馈“完整界面一直不闪，切页正常”。此前仅 RESET 对照也不闪。两次均未复现故障，不支持把 RESET 或供电拔插认定为必然触发因素；根因仍未确定，不宣称长期修复。保留当前 35 MHz 原边沿完整应用进行正常使用观察，暂不继续改时序或旋转。uptime=596 秒，PCLK=35000000，app=running，fonts=4，frame_wait_timeouts=0。


### 35 MHz 完整应用绘制端旋转（2026-11-13）

用户确认恢复 35 MHz 后完整界面不闪、切页正常；固定固件的 RESET 对照及供电端断电再上电对照均未复现闪烁。用户再次要求相对当前画面旋转 180 度，采用绘制端旋转，不再次翻转 NV3052C 扫描寄存器。此前短暂不闪不等于确定根因或长期修复。

新增独立 `qualia-720-rotate` 配置和 `CONFIG_APP_FRAME_ROTATE_180`（默认关闭，仅 720 完整应用可选）。保持 35 MHz、原 PCLK 边沿、H=2/44/46、V=2/18/16、MADCTR=0x03、COLMOD=0x60、常亮背光及原颜色处理。配置与旧备份相比只增加显式原扫描方向、关闭 PWM 的标识以及开启绘制端旋转。

`full_refresh` 模式下，在 flush 提交前将已完成的后台 RGB565 帧原地翻转，再沿用原双缓冲提交和完成回调等待；没有新增整屏缓冲，没有处理正在扫描的前台帧。每次重绘增加约 1 MB 读取和 1 MB 写入，实际性能与闪烁仍需硬件验证。像素字节及颜色位完整保留。触摸坐标在原变换后应用相同的额外 180 度变换（当前屏无触摸）。状态保留硬件 `display.rotation_degrees=180`，新增 `app.software_rotation_degrees=180` 和 `rotation_ms` 表示额外的画面旋转与耗时。

[LVGL 8.3 官方说明](https://lvgl.io/docs/open/8.3/porting/display)要求 full_refresh 模式自行在 flush 中旋转像素，不能直接开启内建 sw_rotate。已核对本地 LVGL 实现与双缓冲提交顺序。

720 旋转版及 480/60 Hz 回归构建通过；6 项相关主机测试通过，新增 ASan/UBSan 检查涵盖非正方形、单像素、奇数长度、480/720 全帧映射、RGB565 原色字节、两次旋转还原以及边界。镜像 1,481,072 字节，SHA256 `cc6c85a6e5092fd7bd0647e96ee27249aa12174ffdb3062f82378e7def60cad7`，保存于 `backups/qualia-720-software-rotate-20261113/`；尚未烧录。此前原方向镜像保留在 `backups/qualia-720-image-quantize-20261112/`。

2026-11-13T16:00:44+09:00 绘制端旋转 180 度版本已写入 0x10000 应用分区（1,481,072 字节），Flash 哈希校验通过。35 MHz、原 PCLK 边沿和原屏幕扫描方向保持不变。当前保持 bootloader，等待用户 RESET；上屏方向、颜色、闪烁及 rotation_ms 待验证。

最终保留与提交验证：用户确认绘制端旋转版“方向正确，颜色正常，不闪”。常规 `qualia-720` 已采用相同设置，重新构建通过，生成 sdkconfig 与已验证旋转镜像完全一致。主机测试 16 项：15 通过、1 项可选 Lua 对照跳过；从设备 curl 获取真实 JSON 后离线执行 23 项状态检查，全部通过，并单独核对软件旋转 180 度、原 PCLK 边沿和硬件扫描方向。相关日志保存于本机最终镜像备份目录。
