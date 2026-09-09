import SwiftUI
import Combine

struct GamesListView: View {
    @State private var selectedDate = Date()

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
                        await dataManager.forceRefresh(for: selectedDate)
                    }
                }
            }
        }
        .onChange(of: selectedDate) { _, newDate in
            dataManager.filterMatches(for: newDate)
        }
        // ⏱ AUTO REFRESH
        .onReceive(refreshTimer) { _ in
            Task {
                await dataManager.forceRefresh(for: selectedDate)
            }
        }
        .task {
            // Instantly load what is currently in the database
            dataManager.fetchTimeline(for: selectedDate)
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

    @ViewBuilder
    private var mainContent: some View {
        if dataManager.isLoading && dataManager.allMatches.isEmpty {
            ProgressView()
                .tint(Color(red: 0.4, green: 0.2, blue: 0.9))
                .padding(.top, 50)
        } else if let errorMessage = dataManager.errorMessage,
                  dataManager.allMatches.isEmpty {
            Text(errorMessage)
                .foregroundColor(.gray)
                .multilineTextAlignment(.center)
                .padding(.horizontal)
                .padding(.top, 50)
        } else if dataManager.filteredMatches.isEmpty {
            Text("No games found in database.")
                .foregroundColor(.gray)
                .padding(.top, 50)
                
        } else {
            gamesList
        }
    }
    
    private var gamesList: some View {
        LazyVStack(spacing: 8) {
            ForEach(dataManager.filteredMatches) { match in
                NavigationLink(destination: GameDetailView(match: match)) {
                    GameCardView(match: match)
                }
                .buttonStyle(PlainButtonStyle())
            }
        }
        .padding(.horizontal)
        .padding(.bottom, 16)
    }
}
