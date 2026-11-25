# 按服务端指令采集

`start.sh` 启动显示服务和各个 `--push --follow` 采集器。采集器先询问服务端，再决定是否请求上游；提交成功后使用响应中的调度指令安排下一次轮询。所有订阅和天气共用此协议。

默认有客户端读取时每 600 秒更新一个数据源；连续 180 秒没有合法的 `GET /v1/display` 后，停止发起上游查询。已经发出的查询允许完成。采集器仍每 15 秒询问服务端；终端重新访问且缓存到期后，通常在 15 秒内开始查询（失败退避或已有查询仍生效）。终端首先收到现有缓存，下一次读取获得新结果。

启动时不主动查询上游，并根据保存的 `updated_at` 避免重启后重复采集新鲜数据。消息接口、健康检查、上传及调度轮询都不延长终端活跃时间。查询失败后依次等待 600、1200、2400、3600 秒，之后最多每 3600 秒重试；无人读取期间仍暂停。失败不会更新缓存时间戳。

## 询问是否查询

仅写 token 可以调用：

```http
POST /v1/collectors/bandwagon/poll
Authorization: Bearer <write_token>
Content-Type: application/json

{}
```

支持 `claude`、`codex`、`grok`、`gemini`、`bandwagon`、`weather`（另保留 `banwagong` 兼容采集器）。此 POST 会在允许查询时原子分配 90 秒采集租约，避免多个采集器同时请求同一个数据源。

```json
{
  "collection": {
    "collector": "bandwagon",
    "query_now": false,
    "paused": true,
    "reason": "no_clients",
    "poll_after_seconds": 15,
    "next_query_after_seconds": null,
    "lease_id": null
  }
}
```

只有 `query_now: true` 且获得 `lease_id` 才开始查询。`poll_after_seconds` 表示再次询问服务端的等待时间；`next_query_after_seconds` 是当时的调度预估，暂停时为 `null`，不能跳过轮询直接据此查询。`reason` 包括 `no_clients`、`fresh`、`due`、`in_progress`、`retry_backoff`。

## 提交与失败

查询成功后使用现有 `PUT /v1/subscriptions/<id>` 或 `PUT /v1/weather`，增加 `X-Collection-Lease: <lease_id>` 请求头。响应保留原字段并附加 `collection`，采集器按其中的 `poll_after_seconds` 等待后再次询问。调度信息不会写入订阅缓存，也不会出现在终端显示数据里。过期或重复提交的租约返回 409，不覆盖缓存。

查询或提交失败时报告：

```http
POST /v1/collectors/bandwagon/failure
Authorization: Bearer <write_token>
Content-Type: application/json

{"lease_id":"<lease_id>"}
```

返回相同格式的 `collection` 指令。采集器异常退出后，未完成的租约到期也进入退避。服务端无法连接或指令无效时，采集器每 15 秒重试控制接口，不自行访问上游。

## 配置与检查

```sh
./start.sh --refresh-interval 600 --idle-after 180 --poll-interval 15 --max-interval 3600
python3 bandwagon_usage.py --push --follow
```

`--min-interval` 是 `--refresh-interval` 的别名。旧的采集器 `--interval N` 非零参数会启用服务端调度，N 不再控制上游查询间隔。单独 `--push` 仍可用于人工单次查询和提交；它不受持续采集的暂停规则限制。

显示服务 `--collectors ''` 只禁用本机内置采集器，调度接口仍可供独立采集器使用。不要同时启动旧版本固定周期的采集脚本。

`GET /healthz` 返回 `collection_paused`、刷新/轮询间隔、最近终端读取时间，以及各采集器最近轮询时间。成功的调度心跳不刷访问日志；实际提交和错误会记录日志。

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest -v test_collection_schedule test_bandwagon_usage
```

## Grok 订阅额度

`grok_usage.py` 是默认的 `grok` 采集器，适用于个人订阅（SuperGrok 等）。新版套餐中 Grok、Grok Bot、Cursor 共用一个周额度池，账单接口 `GET https://cli-chat-proxy.grok.com/v1/billing?format=credits` 返回 `config.creditUsagePercent`、`config.currentPeriod`（`type=USAGE_PERIOD_TYPE_WEEKLY`、`start`、`end`）以及按产品拆分的 `config.productUsage`（如 `GrokBot`）；套餐名称取自 `/v1/settings` 的 `subscription_tier_display`。这是官方 CLI 的客户端接口，字段可能变化。

为什么不用 API key：截至 2026-11，Cursor 个人 User API key 只能调用 Cloud Agents API（`/v1/me` 仅返回 key 与身份信息），Admin / Organization API key 只对 Teams / Enterprise 开放且以美元计费，xAI API key 属于独立计费的 Grok API；三者都不能读取个人订阅的周额度百分比。官方说明见 [Cursor APIs](https://cursor.com/docs/api)、[Models & Pricing](https://cursor.com/docs/models-and-pricing)。因此使用官方 CLI 自身的 OIDC 登录（官方颁发方 `auth.x.ai`、官方 client id），不解密其他应用的钥匙串，也不读取浏览器 Cookie。


Grok 采集器在服务端允许查询后才检查凭据。access token 距离过期不足 5 分钟时，使用保存的 refresh token 向官方 `https://auth.x.ai/oauth2/token` 自动续期；账单请求返回 401 时重新读取凭据，必要时续期并重试一次。403 作为权限问题处理，网络故障和服务端临时错误保留原凭据并交由调度器退避。

凭据路径依次取 `--auth-file`、`GROK_AUTH_PATH`、`GROK_HOME/auth.json`、`~/.grok/auth.json`。续期共用官方 CLI 的 `auth.json.lock`，原子保存更新后的 access token、轮换后的 refresh token 和到期时间，保留其他账号字段及 scope，文件权限为 0600。不会自动打开浏览器或发起模型请求。只有刷新凭据缺失、失效或被撤销，或续期后仍被拒绝时，才需要重新登录。

实现依据：[官方认证说明](https://github.com/xai-org/grok-build/blob/main/crates/codegen/xai-grok-pager/docs/user-guide/02-authentication.md)、[官方刷新协议](https://github.com/xai-org/grok-build/blob/main/crates/codegen/xai-grok-login/src/oidc/protocol.rs)、[官方文件锁](https://github.com/xai-org/grok-build/blob/main/crates/codegen/xai-grok-login/src/manager/lock.rs)。测试：`python3 -m unittest -v test_grok_auth`。

## Gemini 订阅额度

`gemini_usage.py` 是默认的 `gemini` 采集器，通过本机 Antigravity CLI 的只读斜杠命令 `agy --print /usage --output-format json` 读取 `Gemini Models` 模型组的 5 小时（`5h`）和 7 天（`weekly`）配额（`num_turns: 0`，不消耗 token）。`remaining_fraction` 换算为显示接口统一的 `used_percent = round((1 - remaining_fraction) * 100, 1)`，主窗口固定为 `5小时`、次窗口为 `7天`，与 `claude` / `codex` 一致。可执行路径支持 `--agy`、`AGY_BIN`、`PATH` 及 `~/.local/bin/agy` 自动查找。测试：`python3 -m unittest -v test_gemini_usage`。
