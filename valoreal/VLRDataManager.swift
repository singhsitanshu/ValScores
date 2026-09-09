import Foundation
import Combine

@MainActor
class VLRDataManager: ObservableObject {
    @Published var allMatches: [MatchInfo] = []
    @Published var filteredMatches: [MatchInfo] = []
    @Published var isLoading = false
    @Published private(set) var errorMessage: String?

    private let apiClient: APIClient
    private var timelineTask: Task<Void, Never>?

    init() {
        self.apiClient = .live
    }

    init(apiClient: APIClient) {
        self.apiClient = apiClient
    }

    // Filter + sort: live first, upcoming next, finished last.
    func filterMatches(for selectedDate: Date, calendar: Calendar = .autoupdatingCurrent) {
        let matchesForDate = allMatches.filter {
            MatchTimeContract.isMatch($0, on: selectedDate, calendar: calendar)
        }

        let liveMatches = matchesForDate.filter { $0.is_live }
        let upcomingMatches = matchesForDate.filter { !$0.is_live && !$0.is_finished }
        let finishedMatches = matchesForDate.filter { $0.is_finished && !$0.is_live }

        filteredMatches = liveMatches + upcomingMatches + finishedMatches
    }

    func fetchTimeline(for selectedDate: Date = Date()) {
        timelineTask?.cancel()
        isLoading = true
        errorMessage = nil

        timelineTask = Task { [weak self] in
            guard let self else { return }
            do {
                let range = try timelineRange(around: selectedDate)
                let matches = try await apiClient.timeline(from: range.start, to: range.end)
                try Task.checkCancellation()

                allMatches = matches
                filterMatches(for: selectedDate)
                isLoading = false
            } catch let error as APIClientError where error.isCancelled {
                return
            } catch is CancellationError {
                return
            } catch {
                errorMessage = error.localizedDescription
                isLoading = false
            }
        }
    }

    func forceRefresh(for selectedDate: Date? = nil) async {
        timelineTask?.cancel()
        let date = selectedDate ?? Date()
        isLoading = true
        errorMessage = nil

        do {
            let range = try timelineRange(around: date)
            try await apiClient.refresh()
            let matches = try await apiClient.timeline(from: range.start, to: range.end)
            try Task.checkCancellation()

            allMatches = matches
            filterMatches(for: date)
            isLoading = false
        } catch let error as APIClientError where error.isCancelled {
            isLoading = false
        } catch is CancellationError {
            isLoading = false
        } catch {
            errorMessage = error.localizedDescription
            isLoading = false
        }
    }

    func matchDetails(matchID: Int, gameID: String) async throws -> MatchStatsResponse {
        try await apiClient.matchDetails(matchID: matchID, gameID: gameID)
    }

    private func timelineRange(
        around selectedDate: Date,
        calendar: Calendar = .autoupdatingCurrent
    ) throws -> (start: Date, end: Date) {
        let selectedDay = calendar.startOfDay(for: selectedDate)
        guard
            let start = calendar.date(byAdding: .day, value: -3, to: selectedDay),
            let end = calendar.date(byAdding: .day, value: 7, to: start)
        else {
            throw APIClientError.invalidURL
        }
        return (start, end)
    }
}
