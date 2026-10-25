import SwiftUI

struct ContentView: View {
    @StateObject private var dataManager = VLRDataManager()
    
    var body: some View {
        GamesListView()
            .environmentObject(dataManager)
    }
}
