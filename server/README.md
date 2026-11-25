# 显示服务数据采集

`./start.sh` 启动服务及按需采集。搬瓦工通过 KiwiVM `getServiceInfo` 查询当前计费月的流量，订阅 ID 为 `banwagong`，默认排在 Claude、Codex、Grok、Gemini 后面。

## Gemini 订阅额度

`gemini_usage.py` 通过本机 `agy --print /usage --output-format json` 只读斜杠命令查询 Antigravity（Gemini Models）的 5 小时与 7 天额度，不发起模型推理也不消耗 token，订阅 ID 为 `gemini`。默认已加入服务端采集列表，也可单独执行：

```sh
python3 gemini_usage.py          # 人类可读输出
python3 gemini_usage.py --json   # agy /usage 原始 JSON
python3 gemini_usage.py --push   # 单次采集并提交到本机显示服务
```

## 个人能量（预留）

服务端提供 `PUT /v1/energy` 与 `DELETE /v1/energy`，并在 `GET /v1/display` 顶层返回 `energy`（未设置时为 `null`，客户端自动隐藏）。规划与字段说明见 [docs/energy-bar-plan.md](../docs/energy-bar-plan.md)，可用 `energy_usage.py` 手动推送或清空：

```sh
python3 energy_usage.py --level 78 --status 充沛 --note "睡眠 7.5h" --push
python3 energy_usage.py --clear --push
```

## HP（Oura）

`hp_usage.py` 读取 Oura 数据估算 HP，并推送到 `PUT /v1/energy`。

1. 在 [cloud.ouraring.com](https://cloud.ouraring.com) 创建应用，Redirect URI 填 `http://localhost:8765/callback`。
2. 复制 `oura.env.example` 为 `oura.env`，填入 client id 与 secret。
3. 授权：`python3 oura_auth.py login`，token 保存在 `oura_token.json`（已被 git 忽略）。
4. 启动：`python3 hp_usage.py --push --follow`，每 600 秒一轮，对齐到整 10 分钟；单轮出错只记日志。

其他用法：`python3 hp_usage.py`（打印摘要）、`--json`、`--explain`（当日每格明细）、`--params FILE`（覆盖模型参数）。

`energy_usage.py` 手动写入的值会在 `hp_usage.py` 的下一轮被覆盖。运行 HP 常驻进程时不要再手动写入。

## Grok 订阅额度

`grok_usage.py` 复用官方 Grok CLI `grok login` 保存的 `~/.grok/auth.json`，只读查询 SuperGrok 等个人订阅的周额度（Grok、Grok Bot、Cursor 共用同一个周额度池，`productUsage` 中列出 Grok Bot 等分项）。说明见 [COLLECTION_API.md](COLLECTION_API.md#grok-订阅额度)。

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

Lua 客户端 1.1.0 起保留全部订阅，始终单列动态排版：每页最多六项同屏、更多项自动分页。流量窗口自动显示实际剩余 / 总容量，无需按提供商 ID 适配。旧版 1.0.0 仍只显示前三项，需要升级设备上的应用文件。

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
