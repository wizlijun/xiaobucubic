import SwiftUI
import WidgetKit

@main
struct StandItWidgetBundle: WidgetBundle {
    var body: some Widget { PlaceholderWidget() }
}

struct PlaceholderWidget: Widget {
    var body: some WidgetConfiguration {
        StaticConfiguration(kind: "StandItBoard", provider: PlaceholderProvider()) { _ in Text("StandIt") }
            .supportedFamilies([.systemSmall])
    }
}

struct PlaceholderProvider: TimelineProvider {
    struct Entry: TimelineEntry { let date: Date }
    func placeholder(in context: Context) -> Entry { Entry(date: .now) }
    func getSnapshot(in context: Context, completion: @escaping (Entry) -> Void) { completion(Entry(date: .now)) }
    func getTimeline(in context: Context, completion: @escaping (Timeline<Entry>) -> Void) {
        completion(Timeline(entries: [Entry(date: .now)], policy: .never))
    }
}
