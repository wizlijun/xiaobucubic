# xiaobucubic

运行于 **ClocTeck HoloCubic Lua 固件**的小屏信息面板，针对 320×240 设计。安装应用不需要重新烧录固件。

只有两个视图：**主页**显示 Claude、Codex、Grok 的剩余额度、重置倒计时，并将天气融合进背景与顶部；**消息页**显示提醒文字。有消息时每 15 秒在两个视图间轮播，多条消息依次展示；没有消息时一直停留在主页。服务返回空提醒数组后立即回到主页。

主页省去“Token 额度 / 剩余比例 / 主窗口”等说明行，直接展示天气和额度卡片。有天气背景时，卡片底板和进度填充均为半透明，叠加后不超过 40.4% 不透明度，天气图案可透出。额度进度以卡片全高的半透明纵向渐变表示，上方稍亮、下方渐淡，宽度对应剩余额度，文字位于填充上层。剩余低于 20% 为警告黄，低于 5% 为警戒红（数字与填充同步变色），20% 及以上使用订阅配色；天气“已过期”提示独立显示在天气文字上方。Claude 的另一个额度窗口显示为卡片底部 4px 细条，右下角显示窗口标签与剩余百分比；默认大面积显示 5 小时额度，细条显示 7 天额度，上键交换两者。Claude 下方说明固定显示窗口与重置时间，省略重复的“官方”字样，过长文本省略显示，不滚动。两个视图均不设标题栏和底部状态栏，右上角显示同步 / 在线 / 离线状态。模拟数据的“演示”标识紧邻右上角联网状态。额度卡片和消息正文使用释放出的底部空间。消息不显示标题；正文使用 22px 中文字体，每段最多 7 行，保留原始换行，自动折行和分段；城市、湿度和气压在中间一列统一居中对齐，湿度（如 `51%`）放在城市下方；天气区下沿依次显示温度范围（`23–32°C`）、气压（`1011 hPa`）和天气（如“晴”），使用 16px 字号并省去数值的文字标签。

额度显示为 `floor(max(0, 100 - used_percent))%`，表示订阅剩余配额比例，不伪造 token 总数。无数据、过期、离线都有明确状态。没有硬编码账户或真实订阅数据。

| 操作 | 效果 |
|---|---|
| 左 / 右 | 有消息时切换主页 / 消息页；无消息时留在主页 |
| 上 | 主页切换可用的主 / 次额度窗口并刷新（单窗口订阅保持不变）；消息页显示下一条 / 下一段 |
| 下 | 暂停 / 恢复轮播 |
| Home | 退出 |

## 安装

`package/` 的内容复制到 TF 卡 `/apps/xiaobucubic/`，然后在 Launcher 重新扫描应用。也可将 `dist/xiaobucubic-1.0.0.zip` 解压到 TF 卡根目录。

设备已联网时，使用 Python 3 的部署工具（无第三方依赖）：

```sh
python3 tools/deploy.py http://10.15.2.72 --launch
```

工具只写入 `/sd/apps/xiaobucubic/`，逐文件校验，覆盖前备份到 `.runtime/backups/`。升级时保留设备已有配置；指定 `--config /path/to/config.json` 才覆盖配置。不要在应用正在运行时用读卡器更换文件。

### 开机自动进入应用

设备已保存 Wi-Fi 配置后，运行：

```sh
python3 tools/set_autostart.py http://设备IP
```

该工具备份并更新 `/sd/apps/settings.json` 和 `/sd/apps/launcher/main.lua`，保留其他设置，逐文件回读校验。下次开机时，Launcher 等待 Wi-Fi 获得有效 IP，然后自动进入 `xiaobucubic`；连接较慢时继续等待，可在应用列表手动打开 Wi-Fi 配网。每次开机只自动进入一次，按 Home 退出后不会再次跳入。

配置使用 `autostart_enabled=true`、`autostart_app_id="xiaobucubic"` 和 `autostart_wait_for_wifi=true`。最后一项由工具对 Launcher 的小范围补丁提供；升级官方 Launcher 后需要重新运行此工具。遇到无法识别的 Launcher 源码时工具会停止，不写入设备。

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

运行时采用设备内置 `http`、`sjson`、`file`、`tmr`、`key`、LVGL API，无额外模块。包内保留八种 PNG 素材，主页按接口天气选择晴 / 云 / 雨 / 雪 / 晴夜背景，图片缺失时使用纯色背景；消息正文过长时分段显示，仍只有一个消息视图。中文字体为 Noto Sans CJK，来自 ClocTeck 示例应用，OFL 许可随包附带；参见 [THIRD_PARTY.md](THIRD_PARTY.md)。

参考：[ClocTeck 应用开发说明](https://github.com/clocteck/holocubic-apps)、[Lua API](https://github.com/clocteck/holocubic-apps/blob/main/README_LUA.md)、[LVGL API](https://github.com/clocteck/holocubic-apps/blob/main/README_LVGL.md)。
