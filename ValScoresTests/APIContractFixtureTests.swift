import Foundation
import XCTest
@testable import ValScores

/// Decodes the backend's golden contract fixtures (tests/fixtures/api), which
/// tests/test_api_fixtures.py keeps identical to real API responses.
final class APIContractFixtureTests: ValScoresTestCase {
    private static let fixtureDirectory = URL(fileURLWithPath: #filePath)
        .deletingLastPathComponent()
        .deletingLastPathComponent()
        .appendingPathComponent("tests/fixtures/api", isDirectory: true)

    private func fixture(_ name: String) throws -> Data {
        try Data(contentsOf: Self.fixtureDirectory.appendingPathComponent(name))
    }

    private func decode<T: Decodable>(_ type: T.Type, from name: String) throws -> T {
        try MatchTimeContract.makeDecoder().decode(type, from: fixture(name))
    }

    func testEveryFixtureIsDecodedByThisSuite() throws {
        let names = try FileManager.default
            .contentsOfDirectory(atPath: Self.fixtureDirectory.path)
            .filter { $0.hasSuffix(".json") }
        XCTAssertEqual(
            Set(names),
            [
                "timeline.json",
                "match_stats_upcoming.json",
                "match_stats_live_all.json",
                "match_stats_live_map_incomplete.json",
                "match_stats_finished_all.json",
                "refresh_partial.json",
                "error_validation_error.json",
                "error_invalid_range.json",
                "error_match_not_found.json",
                "error_game_not_found.json",
                "error_refresh_in_progress.json",
            ]
        )
    }

    func testTimelineFixtureDecodesEveryStatus() throws {
        let matches = try decode([MatchInfo].self, from: "timeline.json")

        XCTAssertEqual(
            matches.map(\.status),
            [.finished, .upcoming, .live, .postponed, .cancelled]
        )
        XCTAssertEqual(matches.map(\.vlr_match_id), ["730003", "730001", "730002", "730004", "730005"])
        XCTAssertEqual(matches[0].startTime, isoDate("2026-09-07T07:00:00Z"))

        let finished = matches[0]
        XCTAssertEqual(finished.team1_score, 2)
        XCTAssertNil(finished.team1_round_score)

        let live = matches[2]
        XCTAssertTrue(live.is_live)
        XCTAssertEqual(live.team1_round_score, 7)

        for match in matches where match.status != .live && match.status != .finished {
            XCTAssertNil(match.team1_score, "\(match.status) must not carry a score")
            XCTAssertFalse(match.is_live)
            XCTAssertFalse(match.is_finished)
        }
        XCTAssertEqual(matches[4].team1, "KRÜ Esports")
    }

    func testMatchStatsFixturesDecodeAndPreserveMissingValues() throws {
        let upcoming = try decode(MatchStatsResponse.self, from: "match_stats_upcoming.json")
        XCTAssertEqual(upcoming.match_info.status, .upcoming)
        XCTAssertTrue(upcoming.match_info.maps.isEmpty)
        XCTAssertTrue(upcoming.team1_roster.isEmpty)

        let liveAll = try decode(MatchStatsResponse.self, from: "match_stats_live_all.json")
        XCTAssertEqual(liveAll.match_info.match_id, 2)
        XCTAssertEqual(liveAll.match_info.selected_game_id, MapStatInfo.allMapsGameID)
        XCTAssertTrue(liveAll.match_info.maps[0].isAllMaps)
        XCTAssertNil(liveAll.match_info.maps[0].map_number)
        XCTAssertNil(liveAll.team1_roster[0].adr, "an aggregate over an incomplete map is unknown")
        XCTAssertEqual(liveAll.team1_roster[0].kills, 26)

        let incomplete = try decode(MatchStatsResponse.self, from: "match_stats_live_map_incomplete.json")
        let boo = incomplete.team1_roster[0]
        XCTAssertEqual(boo.assists, 0, "a genuine zero stays zero")
        XCTAssertNil(boo.adr)
        XCTAssertNil(boo.kast)
        XCTAssertEqual(boo.plus_minus, 3)
        XCTAssertNil(incomplete.match_info.maps.last?.team1_round_score)

        let finished = try decode(MatchStatsResponse.self, from: "match_stats_finished_all.json")
        XCTAssertEqual(finished.team1_roster[0].kast, 81.0)
        XCTAssertEqual(finished.team2_roster[0].plus_minus, -2)
        XCTAssertNil(finished.team2_roster[0].role)
    }

    func testRefreshFixtureDecodes() throws {
        let refresh = try decode(RefreshResponse.self, from: "refresh_partial.json")
        XCTAssertEqual(refresh.status, "partial")
        XCTAssertEqual(refresh.failures.first?.vlr_match_id, "730002")
        XCTAssertEqual(refresh.warning_count, refresh.warnings.count)
        XCTAssertEqual(refresh.warnings.first?.stage, "detail_warning")
    }

    func testErrorFixturesDecodeToKnownCodes() throws {
        let expected: [String: APIErrorCode] = [
            "error_validation_error.json": .validationError,
            "error_invalid_range.json": .invalidRange,
            "error_match_not_found.json": .matchNotFound,
            "error_game_not_found.json": .gameNotFound,
            "error_refresh_in_progress.json": .refreshInProgress,
        ]
        for (name, code) in expected {
            let envelope = try decode(APIErrorEnvelope.self, from: name)
            XCTAssertEqual(envelope.error.errorCode, code, name)
            XCTAssertFalse(envelope.error.message.isEmpty, name)
        }
        XCTAssertEqual(APIErrorCode(rawValue: "something_new"), .unknown("something_new"))
    }

    func testClientSurfacesContractErrorCode() async throws {
        let body = String(decoding: try fixture("error_refresh_in_progress.json"), as: UTF8.self)
        let client = makeClient { request in
            self.response(request, status: 409, body: body)
        }

        do {
            try await client.refresh()
            XCTFail("Expected a conflict")
        } catch let error as APIClientError {
            XCTAssertEqual(error.serverCode, .refreshInProgress)
        }
    }

    func testUnavailableStatsRenderAsDashNotZero() {
        XCTAssertEqual(PlayerStatFormat.count(nil), PlayerStatFormat.unavailable)
        XCTAssertEqual(PlayerStatFormat.count(0), "0")
        XCTAssertEqual(PlayerStatFormat.signed(nil), PlayerStatFormat.unavailable)
        XCTAssertEqual(PlayerStatFormat.signed(7), "+7")
        XCTAssertEqual(PlayerStatFormat.signed(-2), "-2")
        XCTAssertEqual(PlayerStatFormat.ratio(nil), PlayerStatFormat.unavailable)
        XCTAssertEqual(PlayerStatFormat.ratio(1.5), "1.50")
        XCTAssertEqual(PlayerStatFormat.percent(nil), PlayerStatFormat.unavailable)
        XCTAssertEqual(PlayerStatFormat.percent(78), "78%")
        XCTAssertEqual(PlayerStatFormat.percent(72.5), "72.5%")
    }

    func testUnknownStatusesSortWithScheduledMatches() async throws {
        let manager = makeManager { request in
            self.response(
                request,
                body: """
                [\(self.matchJSON(id: 1, team1: "Cancelled", status: "cancelled", startTime: "2026-09-07T09:00:00Z")),
                \(self.matchJSON(id: 2, team1: "Final", status: "finished", startTime: "2026-09-07T10:00:00Z", isFinished: true)),
                \(self.matchJSON(id: 3, team1: "Mystery", status: "forfeited", startTime: "2026-09-07T11:00:00Z")),
                \(self.matchJSON(id: 4, team1: "Now", status: "live", startTime: "2026-09-07T12:00:00Z", isLive: true))]
                """
            )
        }
        let utc = calendar(timeZone: "UTC")
        manager.fetchTimeline(for: isoDate("2026-09-07T12:00:00Z"), calendar: utc)
        try await waitUntil { manager.timelineState.isLoadedForTests }

        XCTAssertEqual(manager.filteredMatches.map(\.team1), ["Now", "Mystery", "Final", "Cancelled"])
        XCTAssertEqual(manager.filteredMatches[1].status, .unknown("forfeited"))
    }
}
