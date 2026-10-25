# 显示服务数据采集

`./start.sh` 启动服务及定时采集。搬瓦工通过 KiwiVM `getServiceInfo` 查询当前计费月的流量，订阅 ID 为 `banwagong`，默认排在 Claude、Codex、Grok 后面。

## 搬瓦工配置

在 KiwiVM 面板的 API 页面获取该 VPS 的 VEID 和 API Key，在 `server` 目录执行：

```sh
cp banwagong.env.example banwagong.env
chmod 600 banwagong.env
```

编辑 `banwagong.env` 填写两个值（该文件已被 Git 忽略）：

```dotenv
BANWAGONG_VEID=你的VPS编号
BANWAGONG_API_KEY=你的API密钥
```

也支持同名环境变量，优先于文件。凭据不放在命令行参数中；采集器通过 HTTPS POST 请求体提交凭据，不跟随重定向。文件只解析赋值，不执行 shell 命令。

```sh
python3 banwagong_usage.py              # 本计费月剩余 GiB、已用百分比和重置时间
python3 banwagong_usage.py --json       # 显示接口使用的订阅对象
python3 banwagong_usage.py --push       # 单次采集并提交到本机显示服务
python3 banwagong_usage.py --push --interval 300
```

默认服务采集列表已包含 `banwagong`；升级代码后需重启服务。如果自行使用 `--collectors` 指定列表，请添加 `banwagong`。两个凭据都没有配置时自动采集会跳过；只填一个、接口报错或返回无效流量时采集失败，保留上次成功数据和时间戳，不写入虚假零值。独立执行查询但没有凭据时返回错误。

## 返回数据

沿用 `GET /v1/display` 的 `subscriptions`，`schema_version` 保持 `1`。示例数据为虚构：

```json
{
  "id": "banwagong",
  "name": "搬瓦工",
  "source": "official",
  "updated_at": 1792886400,
  "windows": [{
    "label": "月度",
    "used_percent": 25.0,
    "reset_at": 1794009600,
    "total_bytes": 1073741824000,
    "used_bytes": 268435456000,
    "remaining_bytes": 805306368000
  }]
}
```

- `月度` 表示主机当前计费月，不是假定每月 1 日重置。`reset_at` 直接使用 API 的 `data_next_reset`（Unix 秒）。
- `total_bytes = plan_monthly_data × monthly_data_multiplier`，`used_bytes = data_counter × monthly_data_multiplier`；倍率缺省为 1，结果向下取整到字节。
- `remaining_bytes = max(0, total_bytes - used_bytes)`；超额时保留大于 100 的 `used_percent`。GiB 数为字节数除以 `1024³`。
- 窗口新增的三个字节字段是可选扩展。写入流量窗口必须同时提供 `total_bytes`、`used_bytes`；服务端计算剩余量和百分比，若提交了不一致的 `remaining_bytes` 则拒绝。原有仅百分比的窗口不受影响。
- 采集时间不会随读取刷新；服务端沿用现有 `*_utc` 调试字段。

当前 Lua 设备端只显示订阅数组前三项，且不展示字节数字。第四项可由接口读取；在设备上同时展示四项需另外调整客户端布局。

## 验证

在仓库根目录运行（无需真实凭据）：

```sh
python3 -m unittest discover -s server/tests -v
```

测试覆盖倍率、超额、缺失与无效数据、凭据读取、请求方式、失败不写入，以及本机 HTTP 提交、读取和重启后的状态恢复。
