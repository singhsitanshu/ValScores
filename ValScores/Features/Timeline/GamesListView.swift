import SwiftUI
import Combine

struct MatchDetailRoute: Hashable {
    let match: MatchInfo

    static func == (lhs: Self, rhs: Self) -> Bool {
        lhs.match.id == rhs.match.id
    }

    func hash(into hasher: inout Hasher) {
        hasher.combine(match.id)
    }
}

struct GamesListView: View {
    @State private var selectedDate = Date()
    @State private var dateWindowReference = Date()
    @State private var suppressNextDateSelection = false
    @State private var refreshTimer = Timer.publish(
        every: 300,
        on: .main,
        in: .common
    ).autoconnect()

    @EnvironmentObject private var dataManager: VLRDataManager

    var body: some View {
        NavigationStack {
            ZStack {
                Color.black.ignoresSafeArea()

                VStack(spacing: 0) {
                    DateScrollerView(
                        selectedDate: $selectedDate,
                        referenceDate: dateWindowReference
                    )
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
            .navigationDestination(for: MatchDetailRoute.self) { route in
                GameDetailView(match: route.match)
            }
        }
        .onChange(of: selectedDate) { _, newDate in
            if suppressNextDateSelection {
                suppressNextDateSelection = false
                return
            }
            dataManager.selectDate(newDate)
        }
        .onReceive(refreshTimer) { _ in
            Task {
                await dataManager.forceRefresh(for: selectedDate)
            }
        }
        .onReceive(NotificationCenter.default.publisher(for: .NSCalendarDayChanged)) { _ in
            handleCalendarDayChange()
        }
        .task {
            dataManager.fetchTimeline(for: selectedDate)
        }
    }

    private var headerView: some View {
        HStack(alignment: .firstTextBaseline) {
            Text("Timeline")
                .font(.system(size: 24, weight: .bold))
                .foregroundColor(.white)

            Spacer()

            if let lastUpdated {
                Text("Updated \(lastUpdated.formatted(date: .omitted, time: .shortened))")
                    .font(.caption)
                    .foregroundColor(.white.opacity(0.5))
            }
        }
        .padding(.horizontal)
        .padding(.bottom, 12)
    }

    @ViewBuilder
    private var mainContent: some View {
        switch dataManager.timelineState {
        case .idle, .initialLoading:
            loadingView(label: "Loading matches…")

        case .loaded:
            gamesList

        case .empty:
            emptyView

        case .failed(let message):
            failureView(message: message, staleDate: nil)

        case .refreshing:
            VStack(spacing: 14) {
                loadingView(label: "Refreshing…", compact: true)
                if dataManager.filteredMatches.isEmpty {
                    Text("Checking for matches on this date…")
                        .font(.subheadline)
                        .foregroundColor(.gray)
                } else {
                    gamesList
                }
            }

        case .stale(let updatedAt, let message):
            VStack(spacing: 14) {
                failureView(message: message, staleDate: updatedAt)
                if dataManager.filteredMatches.isEmpty {
                    Text("No cached matches are available for this date.")
                        .font(.subheadline)
                        .foregroundColor(.gray)
                } else {
                    gamesList
                }
            }
        }
    }

    private func loadingView(label: String, compact: Bool = false) -> some View {
        VStack(spacing: 10) {
            ProgressView()
                .tint(Color(red: 0.4, green: 0.2, blue: 0.9))
            Text(label)
                .font(.subheadline)
                .foregroundColor(.gray)
        }
        .padding(.top, compact ? 8 : 50)
    }

    private var emptyView: some View {
        VStack(spacing: 8) {
            Text("No matches scheduled")
                .font(.headline)
                .foregroundColor(.white.opacity(0.8))
            Text(selectedDate.formatted(.dateTime.month(.wide).day()))
                .font(.subheadline)
                .foregroundColor(.gray)
        }
        .padding(.top, 50)
    }

    private func failureView(message: String, staleDate: Date?) -> some View {
        VStack(spacing: 10) {
            Text(staleDate == nil ? "Couldn’t load matches" : "Showing saved matches")
                .font(.headline)
                .foregroundColor(.white.opacity(0.85))

            Text(message)
                .font(.subheadline)
                .foregroundColor(.gray)
                .multilineTextAlignment(.center)

            if let staleDate {
                Text("Last updated \(staleDate.formatted(date: .abbreviated, time: .shortened))")
                    .font(.caption)
                    .foregroundColor(.orange.opacity(0.8))
            }

            Button("Retry") {
                dataManager.retryTimeline()
            }
            .buttonStyle(.borderedProminent)
            .tint(Color(red: 0.4, green: 0.2, blue: 0.9))
        }
        .padding(.horizontal)
        .padding(.top, 36)
    }

    private var gamesList: some View {
        LazyVStack(spacing: 8) {
            ForEach(dataManager.filteredMatches) { match in
                NavigationLink(value: MatchDetailRoute(match: match)) {
                    GameCardView(match: match)
                }
                .buttonStyle(.plain)
            }
        }
        .padding(.horizontal)
        .padding(.bottom, 16)
    }

    private var lastUpdated: Date? {
        switch dataManager.timelineState {
        case .loaded(let date), .empty(let date), .refreshing(let date), .stale(let date, _):
            return date
        case .idle, .initialLoading, .failed:
            return nil
        }
    }

    private func handleCalendarDayChange(calendar: Calendar = .autoupdatingCurrent) {
        let now = Date()
        let wasFollowingToday = calendar.isDate(
            selectedDate,
            inSameDayAs: dateWindowReference
        )
        dateWindowReference = now

        if wasFollowingToday {
            suppressNextDateSelection = true
            selectedDate = now
        }
        dataManager.handleCalendarDayChange(to: selectedDate, calendar: calendar)
    }
}
