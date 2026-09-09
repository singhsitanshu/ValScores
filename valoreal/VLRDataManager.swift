import Foundation
import Combine

enum TimelineLoadState: Equatable {
    case idle
    case initialLoading
    case loaded(lastUpdated: Date)
    case empty(lastUpdated: Date)
    case failed(message: String)
    case refreshing(lastUpdated: Date)
    case stale(lastUpdated: Date, message: String)
}

@MainActor
class VLRDataManager: ObservableObject {
    @Published private(set) var allMatches: [MatchInfo] = []
    @Published private(set) var filteredMatches: [MatchInfo] = []
    @Published private(set) var timelineState: TimelineLoadState = .idle

    private let apiClient: APIClient
    private var selectedDate = Date()
    private var loadedRange: Range<Date>?
    private var timelineTask: Task<Void, Never>?
    private var requestGeneration = 0

    init() {
        self.apiClient = .live
    }

    init(apiClient: APIClient) {
        self.apiClient = apiClient
    }

    func selectDate(_ date: Date, calendar: Calendar = .autoupdatingCurrent) {
        selectedDate = date
        filterMatches(for: date, calendar: calendar)

        let selectedDay = calendar.startOfDay(for: date)
        if loadedRange?.contains(selectedDay) == true {
            updateLoadedStateForSelection()
        } else {
            fetchTimeline(for: date, calendar: calendar)
        }
    }

    func fetchTimeline(
        for date: Date = Date(),
        calendar: Calendar = .autoupdatingCurrent
    ) {
        selectedDate = date
        startTimelineRequest(around: date, calendar: calendar)
    }

    func retryTimeline(calendar: Calendar = .autoupdatingCurrent) {
        startTimelineRequest(around: selectedDate, calendar: calendar)
    }

    func handleCalendarDayChange(
        to date: Date,
        calendar: Calendar = .autoupdatingCurrent
    ) {
        selectedDate = date
        startTimelineRequest(around: date, calendar: calendar)
    }

    func forceRefresh(for date: Date? = nil) async {
        timelineTask?.cancel()
        selectedDate = date ?? selectedDate
        requestGeneration += 1
        let generation = requestGeneration

        let range: Range<Date>
        do {
            range = try timelineRange(around: selectedDate)
        } catch {
            finishFailure(error, generation: generation)
            return
        }

        beginRequestState()
        do {
            try await apiClient.refresh()
            let matches = try await apiClient.timeline(
                from: range.lowerBound,
                to: range.upperBound
            )
            try Task.checkCancellation()
            guard generation == requestGeneration else { return }
            finishSuccess(matches: matches, range: range)
        } catch let error as APIClientError where error.isCancelled {
            finishCancellation(generation: generation)
        } catch is CancellationError {
            finishCancellation(generation: generation)
        } catch {
            finishFailure(error, generation: generation)
        }
    }

    func matchDetails(matchID: Int, gameID: String) async throws -> MatchStatsResponse {
        try await apiClient.matchDetails(matchID: matchID, gameID: gameID)
    }

    private func startTimelineRequest(
        around date: Date,
        calendar: Calendar
    ) {
        timelineTask?.cancel()
        requestGeneration += 1
        let generation = requestGeneration

        let range: Range<Date>
        do {
            range = try timelineRange(around: date, calendar: calendar)
        } catch {
            finishFailure(error, generation: generation)
            return
        }

        beginRequestState()
        timelineTask = Task { [weak self] in
            guard let self else { return }
            do {
                let matches = try await apiClient.timeline(
                    from: range.lowerBound,
                    to: range.upperBound
                )
                try Task.checkCancellation()
                guard generation == requestGeneration else { return }
                finishSuccess(matches: matches, range: range)
            } catch let error as APIClientError where error.isCancelled {
                finishCancellation(generation: generation)
            } catch is CancellationError {
                finishCancellation(generation: generation)
            } catch {
                finishFailure(error, generation: generation)
            }
        }
    }

    private func beginRequestState() {
        if let lastUpdated = lastUpdatedDate {
            timelineState = .refreshing(lastUpdated: lastUpdated)
        } else {
            timelineState = .initialLoading
        }
    }

    private func finishSuccess(matches: [MatchInfo], range: Range<Date>) {
        allMatches = matches
        loadedRange = range
        filterMatches(for: selectedDate)

        let updatedAt = Date()
        timelineState = filteredMatches.isEmpty
            ? .empty(lastUpdated: updatedAt)
            : .loaded(lastUpdated: updatedAt)
    }

    private func finishFailure(_ error: Error, generation: Int) {
        guard generation == requestGeneration else { return }
        if let lastUpdated = lastUpdatedDate {
            timelineState = .stale(
                lastUpdated: lastUpdated,
                message: error.localizedDescription
            )
        } else {
            timelineState = .failed(message: error.localizedDescription)
        }
    }

    private func finishCancellation(generation: Int) {
        guard generation == requestGeneration else { return }
        updateLoadedStateForSelection()
    }

    private func filterMatches(
        for date: Date,
        calendar: Calendar = .autoupdatingCurrent
    ) {
        let matchesForDate = allMatches.filter {
            MatchTimeContract.isMatch($0, on: date, calendar: calendar)
        }

        let liveMatches = matchesForDate.filter { $0.is_live }
        let upcomingMatches = matchesForDate.filter { !$0.is_live && !$0.is_finished }
        let finishedMatches = matchesForDate.filter { $0.is_finished && !$0.is_live }

        filteredMatches = liveMatches + upcomingMatches + finishedMatches
    }

    private func updateLoadedStateForSelection() {
        switch timelineState {
        case .refreshing, .stale:
            return
        default:
            break
        }

        guard let lastUpdated = lastUpdatedDate else { return }
        timelineState = filteredMatches.isEmpty
            ? .empty(lastUpdated: lastUpdated)
            : .loaded(lastUpdated: lastUpdated)
    }

    private var lastUpdatedDate: Date? {
        switch timelineState {
        case .loaded(let date), .empty(let date), .refreshing(let date), .stale(let date, _):
            return date
        case .idle, .initialLoading, .failed:
            return nil
        }
    }

    private func timelineRange(
        around date: Date,
        calendar: Calendar = .autoupdatingCurrent
    ) throws -> Range<Date> {
        let selectedDay = calendar.startOfDay(for: date)
        guard
            let start = calendar.date(byAdding: .day, value: -3, to: selectedDay),
            let end = calendar.date(byAdding: .day, value: 7, to: start)
        else {
            throw APIClientError.invalidURL
        }
        return start..<end
    }
}
