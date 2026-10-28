# ap24 · ESP32-S3 USB Wi-Fi 路由器

让 Mac 保持连接原来的 Wi-Fi，通过 USB 把网络分享给 ESP32-S3，再由 S3 提供 **ap24** 2.4 GHz 热点。

```text
互联网 ← 当前 Wi-Fi ← Mac 互联网共享 ← USB CDC NCM ← ESP32-S3 ← ap24 ← 小屏/其他设备
```

## 硬件与功能

- ESP32-S3，8 MB Flash；当前板的 8 MB PSRAM 不启用，固件不依赖 PSRAM。
- 使用 S3 **原生 USB** 接口（GPIO19/20），不是只接 USB-UART 芯片的串口接口。
- WPA2-PSK，默认信道 6，最多 4 个客户端。SSID、密码和信道来自本地配置。
- USB CDC NCM 网卡 + CDC ACM 调试串口；面向当前 Mac，无需 RNDIS 驱动。
- USB 侧 DHCP 客户端；热点侧 `10.42.32.1/24`、DHCP、IPv4 NAPT。
- 热点 DNS 地址固定为 `10.42.32.1`，普通 UDP DNS 请求转发至 USB DHCP 下发的 DNS。
- 状态页 `http://10.42.32.1/`；只读 JSON 接口 `/api/status`。也可从 Mac 访问 USB 租约地址上的同一接口。
- USB 断开或租约丢失时关闭 NAT；恢复租约后自动开启。热点可用于本地访问。检测到上下游网段重叠时禁用转发并在状态页提示。

这是一台依赖 Mac 供电和网络共享的 IPv4 小型路由器。Mac 睡眠、断网或关闭共享后，热点不能访问互联网。USB Full-Speed 的总线速率上限是 12 Mbps，实际路由吞吐更低，适合小屏和轻量设备，未针对视频或大量并发优化。DNS 代理目前仅支持 UDP，不代理 TCP DNS；设备可自行指定外部 DNS，相关 TCP/UDP 流量照常经过 NAT。

## 配置与构建

固定使用 ESP-IDF **v5.5.2**、`espressif/esp_tinyusb` **2.2.1** 和 TinyUSB **0.19.0~3**。工具链、构建产物和本地密码均被 Git 忽略。安装脚本只安装本项目使用的 Xtensa 工具链，不安装未使用的 ULP/RISC-V 编译器和 OpenOCD；CMake 仍会校验实际编译器版本。

```sh
cd wifirouter
./scripts/setup.sh
cp config.example.json config.local.json  # 已有本地配置时不要覆盖
chmod 600 config.local.json
# 编辑 config.local.json，设置至少 8 个字符的密码
./scripts/idf.sh set-target esp32s3
./scripts/idf.sh build
python3 -m unittest discover -s tests -v
```

当前工作目录已有用户指定的本地密码。`config.local.json` 不纳入 Git；示例文件中没有真实密码。修改配置后重新构建、烧录即可生效。密码会存在固件二进制中，不要公开分发包含真实密码的构建产物。

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

## 实现参考

- [ESP USB Device 官方说明](https://docs.espressif.com/projects/esp-usb/en/latest/esp32s3/usb_device.html)
- [ESP-IDF v5.5.2 USB 网络示例](https://github.com/espressif/esp-idf/tree/v5.5.2/examples/peripherals/usb/device/tusb_ncm)
- [Apple：共享 Mac 的互联网连接](https://support.apple.com/guide/mac-help/share-internet-connection-mac-network-users-mchlp1540/mac)
