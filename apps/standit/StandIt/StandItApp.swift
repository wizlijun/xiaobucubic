import SwiftUI
import WidgetKit

@main
struct StandItApp: App {
    @StateObject private var store = DisplayStore()
    @State private var config = ConfigStore.shared.load()
    @State private var editing = false

    var body: some Scene {
        WindowGroup {
            Group {
                if config == nil || editing {
                    SettingsView(initial: config, onSaved: {
                        config = ConfigStore.shared.load()
                        editing = false
                        store.reloadFromCache()
                        WidgetCenter.shared.reloadAllTimelines()
                    }, onClose: config == nil ? nil : {
                        config = ConfigStore.shared.load()
                        editing = false
                    })
                } else {
                    BoardView(store: store) { editing = true }
                }
            }
            .preferredColorScheme(.dark)
            .statusBarHidden()
            .persistentSystemOverlays(.hidden)
        }
    }
}
