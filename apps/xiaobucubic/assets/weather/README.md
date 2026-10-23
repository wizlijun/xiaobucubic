# 天气背景素材

为 xiaobucubic 的 320×240 横屏制作，2026-10-22 使用内置 image_gen 生成。统一为深色天空与低亮度氛围，左侧及下方留出文字区域，无文字、无界面元素。

| 天气 | 设备用图 |
|---|---|
| 晴天 | [sunny.png](../../package/assets/weather/sunny.png) |
| 多云 | [partly_cloudy.png](../../package/assets/weather/partly_cloudy.png) |
| 阴天 | [overcast.png](../../package/assets/weather/overcast.png) |
| 雨天 | [rain.png](../../package/assets/weather/rain.png) |
| 雷雨 | [thunderstorm.png](../../package/assets/weather/thunderstorm.png) |
| 雪天 | [snow.png](../../package/assets/weather/snow.png) |
| 雾天 | [fog.png](../../package/assets/weather/fog.png) |
| 晴夜 | [clear_night.png](../../package/assets/weather/clear_night.png) |

- `originals/`：生成原图，1448×1086，保留未修改版本。
- `../../package/assets/weather/`：等比例缩小的设备版本，320×240 PNG。
- [prompts.json](prompts.json)：完整的共用提示词和八种天气提示词。
- [manifest.json](../../package/assets/weather/manifest.json)：文件名与天气类别对应关系。

图片已接入应用主页，按 API 的 `weather.condition` 自动选择。晴天可额外传 `is_day: false` 选择晴夜背景；缺失图片时回退到代码绘制背景。
