import Foundation
import XCTest
@testable import ValScores

final class TimelineStateXCTests: ValScoresTestCase {
    func testStatusSortingIsLiveUpcomingFinished() async throws {
        let manager = makeManager { request in
            let matches = [
                self.matchJSON(
                    id: 3,
                    team1: "Finished",
                    status: "finished",
                    startTime: "2026-09-07T10:00:00Z",
                    isFinished: true
                ),
                self.matchJSON(
                    id: 2,
                    team1: "Upcoming",
                    startTime: "2026-09-07T11:00:00Z"
                ),
                self.matchJSON(
                    id: 1,
                    team1: "Live",
                    status: "live",
                    startTime: "2026-09-07T12:00:00Z",
                    isLive: true
                ),
            ].joined(separator: ",")
            return self.response(request, body: "[\(matches)]")
        }
        let utc = calendar(timeZone: "UTC")

        manager.fetchTimeline(for: isoDate("2026-09-07T12:00:00Z"), calendar: utc)
        try await waitUntil { manager.timelineState.isLoadedForTests }

        XCTAssertEqual(manager.filteredMatches.map(\.id), [1, 2, 3])
    }

    func testEmptyTimelineHasDedicatedState() async throws {
        let manager = makeManager { request in
            self.response(request, body: "[]")
        }

        manager.fetchTimeline(
            for: isoDate("2026-09-07T12:00:00Z"),
            calendar: calendar(timeZone: "UTC")
        )
        try await waitUntil { manager.timelineState.isEmptyForTests }

        XCTAssertTrue(manager.filteredMatches.isEmpty)
    }

    func testRapidDateChangesRejectEveryStaleResponse() async throws {
        let manager = makeManager { request in
            let start = self.queryItems(request)["start"] ?? ""
            if start.hasPrefix("2026-09") {
                Thread.sleep(forTimeInterval: 0.20)
                return self.response(
                    request,
                    body: "[\(self.matchJSON(id: 1, team1: "September", startTime: "2026-09-07T12:00:00Z"))]"
                )
            }
            if start.hasPrefix("2026-10") {
                Thread.sleep(forTimeInterval: 0.10)
                return self.response(
                    request,
                    body: "[\(self.matchJSON(id: 2, team1: "October", startTime: "2026-10-07T12:00:00Z"))]"
                )
            }
            return self.response(
                request,
                body: "[\(self.matchJSON(id: 3, team1: "November", startTime: "2026-11-07T12:00:00Z"))]"
            )
        }
        let utc = calendar(timeZone: "UTC")

        manager.fetchTimeline(for: isoDate("2026-09-07T12:00:00Z"), calendar: utc)
        manager.selectDate(isoDate("2026-10-07T12:00:00Z"), calendar: utc)
        manager.selectDate(isoDate("2026-11-07T12:00:00Z"), calendar: utc)
        try await waitUntil { manager.filteredMatches.first?.id == 3 }
        try await Task.sleep(nanoseconds: 300_000_000)

        XCTAssertEqual(manager.allMatches.map(\.id), [3])
        XCTAssertEqual(manager.filteredMatches.map(\.id), [3])
    }

    func testTimelineServerFailureIsNotEmptyState() async throws {
        let manager = makeManager { request in
            self.response(
                request,
                status: 503,
                body: "{\"error\":{\"code\":\"unavailable\",\"message\":\"Try later\"}}"
            )
        }

        manager.fetchTimeline(
            for: isoDate("2026-09-07T12:00:00Z"),
            calendar: calendar(timeZone: "UTC")
        )
        try await waitUntil { manager.timelineState.isFailedForTests }

        guard case .failed(let message) = manager.timelineState else {
            return XCTFail("Expected failed state")
        }
        XCTAssertEqual(message, "Try later")
    }
}
