# StandIt 设计文档（iOS 便签显示端 + StandBy 小组件）

日期：2026-11-18 · 状态：待确认

## 1. 意图

StandIt 是本项目显示系统的第三个显示端，与 HoloCubic Lua 应用（`apps/xiaobucubic/`）、wifirouter 原生便签应用（`server/wifirouter/README.md` “原生便签应用”一节）同类：读取同一个 `GET /v1/display`，把额度、天气和彩色便签（仿 Post-it 体验）显示在 iPhone 上。

核心场景：iPhone Duo 合上或展开立在桌上进入 StandBy 时，StandBy 里出现我们的内容；打开 App 时直接看到当前的可视化内容，不需要任何操作。

## 2. 目标 / 非目标 / 反目标

**目标**
- 打开 App 即全屏显示当前内容：额度页、天气、便签页自动轮播。
- 提供一个 StandBy 小组件，只占 StandBy 的一半，App 不运行时也能自行刷新。
- 屏幕自适应：iPhone Duo 内屏、外屏都不是方屏，竖屏、横屏（StandBy 只在横向触发）都要按实际宽高排版，不能按固定比例或方屏缩放。
- 极简：代码量小、无第三方依赖。

**非目标（本版不做）**
- 交互：除首次粘贴接入点与 token 外，不做翻页手势、暂停、点击跳转、编辑便签。
- 服务端改动：接口、鉴权方式保持现状。
- Live Activity、APNs 推送、Widget 推送刷新。
- App Store 上架（名称与商标问题届时再处理）。
- iPad / Mac / watchOS。

**反目标（出现即视为失败）**
- 小组件只能显示 App 上次打开时的旧数据。
- 断网或接口出错时把额度清零、显示伪造数据，或清空已有缓存。
- 内屏 / 横屏下内容被裁切、拉伸变形，或大片留白像是缩放后的方屏。
- token 以明文写入 UserDefaults、日志或 Git。

## 3. 约束

- 工具链：本机 Xcode 27.2，带 iPhone Duo 模拟器；部署目标 iOS 27.0。
- 语言与框架：Swift、SwiftUI、WidgetKit，仅用系统框架。
- 数据接口：`apps/xiaobucubic/API.md` 定义的 schema v1，字段含义、百分比换算、过期判断以该文档为准。示例：`apps/xiaobucubic/examples/display.json`、`apps/xiaobucubic/tests/fixtures/display-v1-extended.json`。
- 鉴权：服务端配置了只读 token 时需 `Authorization: Bearer <token>`；未配置则不带头。只用只读 token。
- 网络：当前经 frp 以明文 HTTP 暴露（`server/frpc.toml`，TCP 8007）。iOS ATS 默认拒绝 HTTP，本版在 App 与小组件的 Info.plist 中设置 `NSAllowsArbitraryLoads = YES`，并在 README 标注“改为 HTTPS 后移除”。
- StandBy 官方能力：第三方只能以 `systemSmall` 小组件出现在 StandBy，系统放大到半屏、两个并排；弱光下 `vibrant` 渲染并整体染红，背景可能被移除。iPhone Duo 内屏 StandBy 是否接受更大尺寸，官方未说明，需真机确认。
- 小组件刷新有系统配额，按 15 分钟一次请求时间线；时间线中预排的条目可在不发起请求的情况下切换显示。

## 4. 实现方式

| 方案 | 说明 | 取舍 | 结论 |
|---|---|---|---|
| A. App + Widget Extension 各自拉取 | 两端共用一个 Swift 模型文件，各自请求接口；配置存共享 Keychain，缓存存 App Group | App 不运行时 StandBy 仍能更新 | **选用** |
| B. 小组件只读 App 缓存 | 只有 App 请求接口 | StandBy 时 App 不运行，数据必然过时，触犯反目标 | 排除 |
| C. Live Activity | 全屏 StandBy 展示 | 需要 APNs 和服务端改动，单次最长约 8 小时，超出范围 | 排除 |

用户已确认方案 A。

## 5. 已确定的设计

### 5.1 工程结构

位于 `apps/standit/`：

```
apps/standit/
  StandIt.xcodeproj
  Shared/            # App 与 Widget 共用：模型、解析、网络、配置、配色、视图组件
  StandIt/           # App target：入口、设置页、轮播主界面
  StandItWidget/     # Widget Extension：一个小组件
  Tests/             # 单元测试：解析、换算、过期、格式化
  README.md
```

- App 名称（显示名）：StandIt；Bundle ID 前缀与签名团队由构建者在本机填写（不入 Git 的 `Local.xcconfig`）。
- App 与 Widget 共享 App Group（缓存）与 Keychain Access Group（接入点 + token）。

### 5.2 配置（唯一的交互）

- 首次启动或未配置时显示设置页：两个输入框“接入点 URL”、“Token（可留空）”，一个“粘贴”按钮（从剪贴板填入当前聚焦的框），一个“保存”。
- 接入点填服务根地址或完整 `/v1/display` 地址均可；以 `/v1/display` 结尾时原样使用，否则拼接。
- 保存后立即请求一次：成功进入主界面并刷新所有小组件；401 / 403 提示鉴权失败；其他错误提示原因但仍保存。
- 已配置后，主界面右上角一个低调的齿轮按钮可重新进入设置页；除此之外主界面不响应交互。
- 接入点与 token 都存 Keychain（共享 Access Group），不写 UserDefaults、不打日志。

### 5.3 数据与刷新

- 解析规则完全跟随 `API.md`：未知字段忽略；`schema_version != 1`、非 200、坏 JSON 不覆盖缓存；同 ID 订阅只保留首项；`used_percent` 转剩余 `floor(max(0, 100 - used))`，未知显示 `--`；流量窗口按字节显示“剩余 / 总量”，单位 B…PiB 自动选择；`updated_at` 超过 `stale_after_seconds` 标记“过期”；`expires_at` 已到的便签不显示；`demo == true` 显示“演示”标识。
- 时间直接用 iOS 系统时钟（联网自动校时，可信；这与嵌入式设备不同，构建时决定）。时区固定 UTC+8（与现有显示端一致）。
- App：前台时每 60 秒请求；失败退避 5 / 10 / 20 / 40 / 80 / 160 / 300 秒，之后每 300 秒；10 秒超时。进入后台停止轮询。每次成功后写共享缓存并调用 `WidgetCenter.shared.reloadAllTimelines()`。
- Widget：时间线 Provider 每次请求接口，成功写共享缓存；失败用共享缓存。下一次刷新策略 `.after(now + 15 分钟)`。
- 缓存：最后一份成功响应的原始 JSON + 接收时间，存 App Group 容器文件。

### 5.4 App 主界面

全屏深色背景（沿用 `server/wifirouter/main/app_ui.c` 配色：底色 `#070C12`、面板 `#111C28`、文字 `#F0F5FC`、次要 `#8497AC`、卡片循环色 薄荷 `#6DE1C2` / 蓝 `#83B6FF` / 琥珀 `#FFC078`，警告黄 `#FFD166`，警戒红 `#FF5F6D`）。

页面按顺序每 15 秒自动切换，无有效便签时只轮播额度页：

1. **额度页**（可多页）：每页若干额度卡片 + 天气区。卡片显示名称、主窗口剩余百分比（大字）、窗口标签与重置时间、次窗口细条与百分比、来源标记、过期状态；剩余 <20% 黄、<5% 红。天气区显示城市、预报天气、当前温度、最低 / 最高温、湿度、气压，背景用 `apps/xiaobucubic/package/assets/weather/` 中对应天气图（规则见 `API.md`），等比填充裁切。
2. **便签页**：每条便签一页，纸色依次黄 `#FFF2A6` / 绿 `#DDEEB4` / 珊瑚 `#F7B6B2` / 天蓝 `#B9DFF2`，深色文字 `#30382D`，保留换行，重要标记、Bot、到期倒计时放在底部一行；字号自动缩小以放下全文，最小字号仍放不下时末尾省略号。字体使用系统圆体（`.rounded`），不内置第三方字体。

**屏幕自适应（重点）**

- 一切尺寸从 `GeometryReader` 的实际宽高推导，不写死比例，不按方屏缩放；屏幕取自 window scene，不使用 `UIScreen.main`。
- 额度卡片网格按可用区域计算行列：横向（宽 > 高）时天气区放左侧或右侧一栏，卡片在另一侧排网格；竖向时天气区在顶部，卡片在下方。每页卡片数 = 在最小可读卡片尺寸下能放下的最大数量，放不下的进入下一页。
- 字号随卡片尺寸缩放（以卡片短边为基准），保证远距离可读。
- 覆盖以下尺寸并在模拟器截图核对：Duo 外屏竖 / 横、Duo 内屏竖 / 横、Duo 半折叠（铰链区域）、普通 iPhone 竖 / 横。
- 半折叠时用 `reservedRegions(kind: .division)` 取得折痕区域，内容不跨越折痕：横向帐篷 / 桌面姿态时上半区放额度大字，下半区放天气与次要信息。
- 遵守安全区与前置摄像头遮挡区（`reservedRegions(kind: .occlusion)`）。
- App 运行时保持屏幕常亮（`isIdleTimerDisabled = true`），便于作为桌面显示。

### 5.5 小组件

StandBy 中 StandIt 只占**一半**（用户要求），另一半留给系统时钟等其他组件。因此只做**一个** `StaticConfiguration` 小组件，只支持 `systemSmall`（系统在 StandBy 中把它放大到半屏）：

- 时间线每分钟一个条目，依次轮换：额度卡 → 每条有效便签 → 额度卡 → …；无有效便签时只显示额度卡。过期便签跳过，最多预排 15 分钟，15 分钟后刷新。
- 额度卡：剩余最少的 2–3 个订阅，名称 + 剩余百分比大字 + 细条。
- 便签卡：一张便签，纸色 + 正文。
- 天气不进小组件（我方决定：系统天气组件可放在另一半；半屏空间优先给额度和便签）。
- 该组件同时在主屏小号位置可用，不另做中号 / 大号。

- 背景用 `containerBackground(for: .widget)`，系统移除背景时内容仍可读。
- 读取 `widgetRenderingMode`：`fullColor` 正常配色；`vibrant`（StandBy 夜间整体染红）时不依赖颜色区分状态，改用粗细、图标（⚠︎）和文字表达告警。
- 便签卡在 `fullColor` 下用纸色背景；`vibrant` 下只保留正文。
- 无配置时显示“打开 StandIt 设置接入点”；鉴权失败显示“鉴权失败”；仅有缓存时角标显示数据时间。
- 点击小组件打开 App（系统默认行为，不做深链）。

## 6. 验证

- 单元测试：用 `apps/xiaobucubic/examples/display.json` 与 `tests/fixtures/display-v1-extended.json` 验证解析、剩余百分比边界（0、33.5、99.6、null、>100）、流量单位、过期判断、便签过期过滤、重复 ID。
- 预览：Xcode Previews 覆盖 §5.4 列出的全部尺寸，以及小组件 `systemSmall` 的两种渲染模式。
- 模拟器：iPhone Duo 模拟器截图核对内外屏和横竖屏无裁切、无变形。
- 真机（如有 iPhone Duo）：确认 StandBy 外屏、内屏都能把组件放在其中一半，并按时轮换。

## 7. 构建时补充的决定

- 签名：使用本机 Xcode 中的付费团队，自动签名；团队 ID 只写在 `Local.xcconfig`。免费团队描述文件 7 天过期，不适合常年摆放。
- 数据新鲜度：小组件按 15 分钟申请刷新，实际以系统配额为准；数据超过 `stale_after_seconds` 时在卡片角落显示数据时间，不算违反“旧数据”反目标。
- 半折叠：存在折痕区域时，以折痕为界分成两区：第一区（上 / 左）放当前页（额度卡或便签），第二区放天气与状态；页面照常每 15 秒轮播。左右折（书本姿态）同理。
- 小组件额度卡：按每个订阅各窗口中最低的剩余百分比升序，取前 3 个；未知（`--`）排最后。大字显示主窗口剩余，细条显示次窗口（没有则显示主窗口）。

## 8. 留给构建者的决定

- 卡片最小可读尺寸、字号曲线、间距等具体数值。
- 共享模型代码的文件拆分方式。
- 设置页的具体样式。
- 测试框架（XCTest 或 Swift Testing）。
