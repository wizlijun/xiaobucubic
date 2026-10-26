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

Lua 客户端 1.1.0 起保留全部订阅，并根据数量动态排版：四项同屏、五到六项双列、更多项自动分页。流量窗口自动显示实际剩余 / 总容量，无需按提供商 ID 适配。旧版 1.0.0 仍只显示前三项，需要升级设备上的应用文件。

## 验证

在仓库根目录运行（无需真实凭据）：

```sh
python3 -m unittest discover -s server/tests -v
```

测试覆盖倍率、超额、缺失与无效数据、凭据读取、请求方式、失败不写入，以及本机 HTTP 提交、读取和重启后的状态恢复。

## 提醒安全创建

`GET /v1/messages` 在原有 `now/messages` 之外返回 `capabilities: {"safe_create": true}`。消息 token 仍只能看到 Bot 消息，不暴露人工消息内容；客户端不能用这个列表长度判断全屏剩余容量。

支持该能力的服务允许 Bot 在 `POST /v1/messages` 请求体加入布尔值 `safe_create: true`。对新 ID，容量检查与写入处于同一个存储锁内：已满时返回 HTTP 409，完整保留已有消息；已有 Bot ID 在满容量时仍可原位更新。标记不存入消息，不改变原有权限校验；未带该标记的旧调用保留已有满容量淘汰逻辑。

新同步脚本应先确认 GET 的能力标记严格等于 `true`，仅新建时带上 `safe_create: true`。旧服务可能忽略未知请求字段，所以未宣告能力时只能更新或删除已知消息，新建应保持待同步。源码更新还需要部署并重启服务后才具备该能力；本次测试只启动本机临时 HTTP 服务，没有部署或访问正式服务。
