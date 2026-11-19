# Stand It

一个极简的 iOS 原生便签看板：打开就显示 `/v1/display` 的内容，包括额度卡片、天气和彩色便签；另附两个 StandBy 小组件（余量、便签），各占待机界面的一半。

- 唯一的交互是粘贴接入点和 token。接口文档见 [`apps/xiaobucubic/API.md`](../xiaobucubic/API.md)。
- 布局按实际宽高自适应：Duo 内屏横竖、外屏、半折叠（上下或左右分屏）、普通 iPhone 都适用。截图生成方法见下文。
- 前台每 60 秒刷新一次；失败后按 5、10、20…300 秒退避，期间继续显示上一次成功的数据，并在状态行标出“数据时间”。

## 构建与安装

需要 Xcode 26+ 和 [XcodeGen](https://github.com/yonaskolb/XcodeGen)。

```bash
cd apps/standit
cp Local.xcconfig.example Local.xcconfig   # 填团队 ID 与 Bundle 前缀，此文件不进 Git
xcodegen
tools/test.sh                              # 单元测试（模拟器 iPhone 17 Pro Max）
xcodebuild -scheme StandIt -destination 'id=<设备 UDID>' -allowProvisioningUpdates \
  -derivedDataPath build build
xcrun devicectl device install app --device <设备 UDID> build/Build/Products/Debug-iphoneos/StandIt.app
```

**App Group。** App 与小组件默认通过 App Group 共用缓存。如果 Xcode 没有登录账号，只有团队通配开发描述文件，就无法开通 App Group。此时在 `Local.xcconfig` 里加上下面两行：

```
STANDIT_APP_GROUP =
STANDIT_ENTITLEMENTS_VARIANT = -NoAppGroup
```

这样小组件仍通过共享钥匙串读取接入点，只是自己联网、自己缓存。

## 使用

1. 打开 Stand It，在“接入点 URL”中粘贴服务地址：`http://host:8007` 或完整的 `…/v1/display` 都可以。在“Token”中粘贴只读 token；服务端不鉴权时留空。可以用“粘贴”按钮，它会填入当前选中的输入框。
2. 点“保存”。App 会立即试连一次：成功就进入看板；鉴权失败时停在设置页提示；其他错误会保存配置并给出原因。
3. 之后要修改，点看板右上角的齿轮。

接入点和 token 只存在本机钥匙串（`AfterFirstUnlockThisDeviceOnly`），不写入 UserDefaults、日志或仓库。

看板每 15 秒切一页：额度页（天气 + 额度卡片，放不下时分多页）与每张便签轮流显示。App 在前台时屏幕常亮。

## StandBy 小组件（占一半）

Stand It 提供两个小组件，可以分别放进 StandBy 的小组件栈：

- **Stand It 余量**：剩余最少的几个额度（小号 3 个、大号 5 个、竖长特大号 8 个）。
- **Stand It 便签**：有效便签每分钟换一张；没有便签时显示“暂无便签”。

1. 主屏长按空白处 → 编辑 → 添加小组件 → Stand It。这一步可选，但能确认小组件已出现。
2. 手机横放充电、锁屏，进入 StandBy。
3. 长按左侧或右侧的小组件栈 → 解锁 → 点“+” → 先后加入“Stand It 余量”和“Stand It 便签” → 完成。

两个小组件放进同一个栈后，上下滑动就能切换；也可以一侧放余量、另一侧放便签。每 15 分钟联网刷新一次；App 刷新成功后也会通知两个小组件立即更新。夜间 StandBy 是单色显示，告警用 ⚠︎ 和粗体表示。

## 截图

没有 Duo 模拟器，所以用 SwiftUI `ImageRenderer` 在单元测试里按各尺寸渲染主界面：

```bash
TEST_RUNNER_STANDIT_SNAPSHOT_DIR=/tmp/standit-shots tools/test.sh
```

## 已知限制

- 服务端目前经 frp 以明文 HTTP 暴露，所以 Info.plist 开了 `NSAllowsArbitraryLoads`。服务改成 HTTPS 后应删除这一项。
- 半折叠分屏依赖 iOS 27.1 的 `UIView.reservedRegions(kind: .division)`。目前没有变化通知，所以在布局时和每 15 秒查询一次；折叠或展开后，最多 15 秒才会切换布局。
- 小组件的刷新频率受系统预算限制，15 分钟只是请求值。
- 时间统一按 UTC+8 显示，与设备固件一致。
