import SwiftUI

struct ContentView: View {
    @StateObject private var dataManager = VLRDataManager()
    
    var body: some View {
        TabView {
            GamesListView()
                .environmentObject(dataManager)
                .tabItem {
                    Label("Games", systemImage: "calendar")
                }
        }
        // Colors the active tab icon purple
        .tint(Color(red: 0.4, green: 0.2, blue: 0.9))
    }
}
