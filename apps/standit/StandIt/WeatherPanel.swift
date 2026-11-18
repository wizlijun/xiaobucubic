import SwiftUI

struct WeatherPanel: View {
    let weather: Weather?

    var body: some View {
        GeometryReader { geo in
            let s = min(geo.size.width, geo.size.height * 1.3)
            ZStack(alignment: .bottomLeading) {
                if let asset = DisplayModel.weatherAsset(weather) {
                    Image("weather_\(asset)").resizable().scaledToFill()
                        .frame(width: geo.size.width, height: geo.size.height).clipped()
                    LinearGradient(colors: [.black.opacity(0.05), .black.opacity(0.65)], startPoint: .top, endPoint: .bottom)
                } else {
                    Palette.panel
                }
                if let w = weather {
                    VStack(alignment: .leading, spacing: s * 0.015) {
                        Text([w.city, w.condition].filter { !$0.isEmpty }.joined(separator: " · "))
                            .font(.system(size: s * 0.075, weight: .semibold, design: .rounded))
                        Text(w.temperatureC.map { "\(Int($0.rounded()))°" } ?? "--°")
                            .font(.system(size: s * 0.26, weight: .bold, design: .rounded)).monospacedDigit()
                        let extras = [range(w), w.humidityPercent.map { "湿度 \(Int($0.rounded()))%" },
                                      w.pressureHpa.map { "\(Int($0.rounded()))hPa" }].compactMap { $0 }
                        if !extras.isEmpty {
                            Text(extras.joined(separator: "  ")).font(.system(size: s * 0.06, design: .rounded))
                                .lineLimit(2).minimumScaleFactor(0.6)
                        }
                    }
                    .foregroundStyle(.white).shadow(color: .black.opacity(0.4), radius: 4)
                    .lineLimit(1).minimumScaleFactor(0.5)
                    .padding(s * 0.07)
                } else {
                    Text("暂无天气").font(.system(size: s * 0.08, design: .rounded)).foregroundStyle(Palette.muted)
                        .frame(maxWidth: .infinity, maxHeight: .infinity)
                }
            }
            .frame(width: geo.size.width, height: geo.size.height)
            .clipShape(RoundedRectangle(cornerRadius: min(24, s * 0.06)))
        }
    }

    private func range(_ w: Weather) -> String? {
        guard let lo = w.lowC, let hi = w.highC else { return nil }
        return "\(Int(lo.rounded()))° / \(Int(hi.rounded()))°"
    }
}
