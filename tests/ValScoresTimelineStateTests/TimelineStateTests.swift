import Foundation
#if canImport(FoundationNetworking)
import FoundationNetworking
#endif

final class TimelineMockURLProtocol: URLProtocol {
    static var handler: ((URLRequest) throws -> (HTTPURLResponse, Data))?

    override class func canInit(with request: URLRequest) -> Bool { true }

    override class func canonicalRequest(for request: URLRequest) -> URLRequest {
        request
    }

    override func startLoading() {
        guard let handler = Self.handler else {
            client?.urlProtocol(self, didFailWithError: URLError(.unknown))
            return
        }

        do {
            let (response, data) = try handler(request)
            client?.urlProtocol(self, didReceive: response, cacheStoragePolicy: .notAllowed)
            client?.urlProtocol(self, didLoad: data)
            client?.urlProtocolDidFinishLoading(self)
        } catch {
            client?.urlProtocol(self, didFailWithError: error)
        }
    }

    override func stopLoading() {}
}

@main
struct TimelineStateTests {
    @MainActor
    static func main() async throws {
        try await exactlyOneInitialRequestLoadsMatches()
        try await emptyAndFailureHaveDifferentStates()
        try await retryRecoversFromFailure()
        try await failedReloadKeepsStaleContent()
        try await olderResponseCannotReplaceNewerSelection()
        try await calendarDayChangeReloadsTheDateWindow()
        print("Ran 6 Swift timeline-state tests: OK")
    }

    @MainActor
    static func exactlyOneInitialRequestLoadsMatches() async throws {
        var requestCount = 0
        let manager = makeManager { request in
            requestCount += 1
            return response(request, status: 200, body: matchJSON(
                id: 1,
                team1: "Alpha",
                startTime: "2026-09-07T12:00:00Z"
            ))
        }

        manager.fetchTimeline(for: isoDate("2026-09-07T12:00:00Z"), calendar: utcCalendar)
        require(manager.timelineState == .initialLoading, "initial load has an explicit state")
        try await waitUntil { manager.timelineState.isLoaded }

        require(requestCount == 1, "one initial timeline request")
        require(manager.filteredMatches.map(\.id) == [1], "initial match is visible")
    }

    @MainActor
    static func emptyAndFailureHaveDifferentStates() async throws {
        let emptyManager = makeManager { request in
            response(request, status: 200, body: "[]")
        }
        emptyManager.fetchTimeline(for: isoDate("2026-09-07T12:00:00Z"), calendar: utcCalendar)
        try await waitUntil { emptyManager.timelineState.isEmpty }

        let failedManager = makeManager { request in
            response(
                request,
                status: 503,
                body: "{\"error\":{\"code\":\"unavailable\",\"message\":\"Try again later\"}}"
            )
        }
        failedManager.fetchTimeline(for: isoDate("2026-09-07T12:00:00Z"), calendar: utcCalendar)
        try await waitUntil { failedManager.timelineState.isFailed }

        guard case .failed(let message) = failedManager.timelineState else {
            fatalError("Test failed: expected failed state")
        }
        require(message == "Try again later", "server error is shown")
    }

    @MainActor
    static func retryRecoversFromFailure() async throws {
        var requestCount = 0
        let manager = makeManager { request in
            requestCount += 1
            if requestCount == 1 {
                return response(request, status: 500, body: "failure")
            }
            return response(request, status: 200, body: matchJSON(
                id: 2,
                team1: "Recovered",
                startTime: "2026-09-07T15:00:00Z"
            ))
        }

        manager.fetchTimeline(for: isoDate("2026-09-07T12:00:00Z"), calendar: utcCalendar)
        try await waitUntil { manager.timelineState.isFailed }
        manager.retryTimeline(calendar: utcCalendar)
        try await waitUntil { manager.timelineState.isLoaded }

        require(requestCount == 2, "retry performs one additional request")
        require(manager.filteredMatches.first?.team1 == "Recovered", "retry replaces failure")
    }

    @MainActor
    static func failedReloadKeepsStaleContent() async throws {
        var requestCount = 0
        let manager = makeManager { request in
            requestCount += 1
            if requestCount == 1 {
                return response(request, status: 200, body: matchJSON(
                    id: 3,
                    team1: "Cached",
                    startTime: "2026-09-07T18:00:00Z"
                ))
            }
            Thread.sleep(forTimeInterval: 0.05)
            return response(request, status: 503, body: "offline")
        }

        manager.fetchTimeline(for: isoDate("2026-09-07T12:00:00Z"), calendar: utcCalendar)
        try await waitUntil { manager.timelineState.isLoaded }
        manager.retryTimeline(calendar: utcCalendar)
        require(manager.timelineState.isRefreshing, "reload preserves content in a refreshing state")
        require(manager.filteredMatches.map(\.id) == [3], "refreshing keeps existing content visible")
        try await waitUntil { manager.timelineState.isStale }

        require(manager.filteredMatches.map(\.id) == [3], "stale matches remain visible")
    }

    @MainActor
    static func olderResponseCannotReplaceNewerSelection() async throws {
        let firstDate = isoDate("2026-09-07T12:00:00Z")
        let secondDate = isoDate("2026-10-07T12:00:00Z")
        let manager = makeManager { request in
            let start = queryItems(request)["start"] ?? ""
            if start.hasPrefix("2026-09") {
                Thread.sleep(forTimeInterval: 0.2)
                return response(request, status: 200, body: matchJSON(
                    id: 4,
                    team1: "Old",
                    startTime: "2026-09-07T12:00:00Z"
                ))
            }
            return response(request, status: 200, body: matchJSON(
                id: 5,
                team1: "Newest",
                startTime: "2026-10-07T12:00:00Z"
            ))
        }

        manager.fetchTimeline(for: firstDate, calendar: utcCalendar)
        manager.selectDate(secondDate, calendar: utcCalendar)
        try await waitUntil { manager.filteredMatches.first?.id == 5 }
        try await Task.sleep(nanoseconds: 300_000_000)

        require(manager.allMatches.map(\.id) == [5], "older response cannot replace new data")
        require(manager.filteredMatches.map(\.id) == [5], "newer selected date remains visible")
    }

    @MainActor
    static func calendarDayChangeReloadsTheDateWindow() async throws {
        var starts: [String] = []
        let manager = makeManager { request in
            starts.append(queryItems(request)["start"] ?? "")
            return response(request, status: 200, body: "[]")
        }

        manager.fetchTimeline(for: isoDate("2026-09-07T12:00:00Z"), calendar: utcCalendar)
        try await waitUntil { starts.count == 1 && manager.timelineState.isEmpty }
        manager.handleCalendarDayChange(
            to: isoDate("2026-09-08T12:00:00Z"),
            calendar: utcCalendar
        )
        try await waitUntil { starts.count == 2 && manager.timelineState.isEmpty }

        require(starts[0] != starts[1], "midnight reload advances the requested date window")
    }

    @MainActor
    static func waitUntil(
        timeoutNanoseconds: UInt64 = 2_000_000_000,
        condition: @escaping @MainActor () -> Bool
    ) async throws {
        let deadline = DispatchTime.now().uptimeNanoseconds + timeoutNanoseconds
        while !condition() {
            if DispatchTime.now().uptimeNanoseconds >= deadline {
                fatalError("Test failed: timed out waiting for state")
            }
            try await Task.sleep(nanoseconds: 10_000_000)
        }
    }

    @MainActor
    static func makeManager(
        handler: @escaping (URLRequest) throws -> (HTTPURLResponse, Data)
    ) -> VLRDataManager {
        TimelineMockURLProtocol.handler = handler
        let configuration = URLSessionConfiguration.ephemeral
        configuration.protocolClasses = [TimelineMockURLProtocol.self]
        let client = APIClient(
            baseURLString: "http://127.0.0.1:8000",
            session: URLSession(configuration: configuration)
        )
        return VLRDataManager(apiClient: client)
    }

    static func response(
        _ request: URLRequest,
        status: Int,
        body: String
    ) -> (HTTPURLResponse, Data) {
        let response = HTTPURLResponse(
            url: request.url!,
            statusCode: status,
            httpVersion: nil,
            headerFields: ["Content-Type": "application/json"]
        )!
        return (response, Data(body.utf8))
    }

    static func matchJSON(id: Int, team1: String, startTime: String) -> String {
        """
        [{"id":\(id),"team1":"\(team1)","team2":"Opponent","team1_score":null,
        "team2_score":null,"status":"upcoming","start_time":"\(startTime)",
        "is_live":false,"is_finished":false,"team1_round_score":null,
        "team2_round_score":null}]
        """
    }

    static func queryItems(_ request: URLRequest) -> [String: String] {
        let items = URLComponents(url: request.url!, resolvingAgainstBaseURL: false)?.queryItems ?? []
        return Dictionary(uniqueKeysWithValues: items.map { ($0.name, $0.value ?? "") })
    }

    static func isoDate(_ value: String) -> Date {
        ISO8601DateFormatter().date(from: value)!
    }

    static var utcCalendar: Calendar {
        var calendar = Calendar(identifier: .gregorian)
        calendar.timeZone = TimeZone(secondsFromGMT: 0)!
        return calendar
    }

    static func require(_ condition: @autoclosure () -> Bool, _ message: String) {
        guard condition() else { fatalError("Test failed: \(message)") }
    }
}

private extension TimelineLoadState {
    var isLoaded: Bool {
        if case .loaded = self { return true }
        return false
    }

    var isEmpty: Bool {
        if case .empty = self { return true }
        return false
    }

    var isFailed: Bool {
        if case .failed = self { return true }
        return false
    }

    var isStale: Bool {
        if case .stale = self { return true }
        return false
    }

    var isRefreshing: Bool {
        if case .refreshing = self { return true }
        return false
    }
}
