import SwiftUI
import Combine

struct GamesListView: View {
    @State private var selectedDate: String = {
        let formatter = DateFormatter()
        formatter.dateFormat = "MMM d"
        return formatter.string(from: Date())
    }()

    @EnvironmentObject var dataManager: VLRDataManager

    // ⏱ 5-minute auto refresh
    @State private var refreshTimer = Timer.publish(every: 300, on: .main, in: .common).autoconnect()

    var body: some View {
        NavigationStack {
            ZStack {
                Color.black.ignoresSafeArea()

                VStack(spacing: 0) {
                    
                    DateScrollerView(selectedDate: $selectedDate)
                        .padding(.bottom, 10)
                    
                    headerView

                    ScrollView {
                        mainContent
                    }
                    .refreshable {
                        await dataManager.forceRefresh()
                    }
                }
            }
        }
        .onAppear {
            dataManager.fetchTimeline()
        }
        .onChange(of: selectedDate) { newDate in
            dataManager.filterMatches(for: newDate)
        }
        // ⏱ AUTO REFRESH
        .onReceive(refreshTimer) { _ in
            Task {
                await dataManager.forceRefresh()
            }
        }
        .task {
            // Instantly load what is currently in the database
            dataManager.fetchTimeline()
        }
    }
    
    // Header for the Timeline
    private var headerView: some View {
        HStack {
            Text("Timeline")
                .font(.system(size: 24, weight: .bold))
                .foregroundColor(.white)
            Spacer()
        }
        .padding(.horizontal)
        .padding(.bottom, 12)
    }

    // Main content area
    @ViewBuilder
    private var mainContent: some View {
        if dataManager.isLoading && dataManager.allMatches.isEmpty {
            ProgressView()
                .tint(Color(red: 0.4, green: 0.2, blue: 0.9))
                .padding(.top, 50)
                
        } else if dataManager.filteredMatches.isEmpty {
            Text("No games found in database.")
                .foregroundColor(.gray)
                .padding(.top, 50)
                
        } else {
            gamesColumns
        }
    }
    
    private var gamesColumns: some View {
        // 🔥 TWO COLUMN LAYOUT
        HStack(alignment: .top, spacing: 8) {
            
            // 🔴 LEFT — LIVE
            VStack(spacing: 8) {
                ForEach(dataManager.filteredMatches.filter { $0.is_live }) { match in
                    // 櫨 FIX: Pass the 'match' object into the GameDetailView
                    NavigationLink(destination: GameDetailView(match: match)) {
                        GameCardView(match: match)
                            .overlay(
                                RoundedRectangle(cornerRadius: 12)
                                    .stroke(Color.red, lineWidth: 2)
                            )
                    }
                    .buttonStyle(PlainButtonStyle())
                }
            }
            
            // ⚪ RIGHT — NON-LIVE
            VStack(spacing: 8) {
                ForEach(dataManager.filteredMatches.filter { !$0.is_live }) { match in
                    // 櫨 FIX: Pass the 'match' object into the GameDetailView
                    NavigationLink(destination: GameDetailView(match: match)) {
                        GameCardView(match: match)
                    }
                    .buttonStyle(PlainButtonStyle())
                }
            }
        }
        .padding(.horizontal)
    }
}
