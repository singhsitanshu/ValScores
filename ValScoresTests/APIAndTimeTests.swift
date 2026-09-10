import Foundation
import XCTest
@testable import ValScores

final class APIAndTimeTests: ValScoresTestCase {
    func testTimelineJSONDecodingUsesCanonicalDate() async throws {
        let client = makeClient { request in
            self.response(
                request,
                body: "[\(self.matchJSON(id: 1, team1: "Alpha", startTime: "2026-09-07T00:30:00Z"))]"
            )
        }

        let matches = try await client.timeline(
            from: isoDate("2026-09-06T00:00:00Z"),
            to: isoDate("2026-09-08T00:00:00Z")
        )

        XCTAssertEqual(matches.count, 1)
        XCTAssertEqual(matches[0].startTime, isoDate("2026-09-07T00:30:00Z"))
        XCTAssertNil(matches[0].team1_score)
    }

    func testDetailJSONDecodingPreservesTeamAssociation() async throws {
        let client = makeClient { request in
            self.response(request, body: self.detailJSON())
        }

        let details = try await client.matchDetails(matchID: 42, gameID: "map-1")

        XCTAssertEqual(details.match_info.selected_game_id, "map-1")
        XCTAssertEqual(details.team1_roster.map(\.team), ["Alpha Five"])
        XCTAssertEqual(details.team2_roster.map(\.team), ["Bravo Crew"])
        XCTAssertEqual(details.team1_roster.first?.team_abbreviation, "AF")
        XCTAssertEqual(details.team2_roster.first?.team_abbreviation, "BC")
    }

    func testServerErrorIsNotReportedAsDecodingFailure() async {
        let client = makeClient { request in
            self.response(
                request,
                status: 500,
                body: "{\"error\":{\"code\":\"database_down\",\"message\":\"Database unavailable\"}}"
            )
        }

        do {
            _ = try await client.matchDetails(matchID: 1)
            XCTFail("Expected server error")
        } catch APIClientError.server(let status, let code, let message) {
            XCTAssertEqual(status, 500)
            XCTAssertEqual(code, "database_down")
            XCTAssertEqual(message, "Database unavailable")
        } catch {
            XCTFail("Unexpected error: \(error)")
        }
    }

    func testMalformedSuccessPayloadProducesDecodingError() async {
        let client = makeClient { request in
            self.response(request, body: "not-json")
        }

        do {
            _ = try await client.timeline(from: Date(), to: Date().addingTimeInterval(60))
            XCTFail("Expected decoding error")
        } catch APIClientError.decoding {
            // Expected.
        } catch {
            XCTFail("Unexpected error: \(error)")
        }
    }

    func testCancellationHasDedicatedError() async {
        let client = makeClient { _ in
            throw URLError(.cancelled)
        }

        do {
            _ = try await client.matchDetails(matchID: 1)
            XCTFail("Expected cancellation")
        } catch APIClientError.cancelled {
            // Expected.
        } catch {
            XCTFail("Unexpected error: \(error)")
        }
    }

    func testUTCGroupingCrossesMidnightAndIgnoresLocale() throws {
        let data = Data("[\(matchJSON(id: 1, team1: "Alpha", startTime: "2026-09-07T00:30:00Z"))]".utf8)
        let match = try MatchTimeContract.makeDecoder().decode([MatchInfo].self, from: data)[0]
        let selectedDate = isoDate("2026-09-06T18:00:00Z")
        let english = calendar(timeZone: "America/Chicago", locale: "en_US")
        let french = calendar(timeZone: "America/Chicago", locale: "fr_FR")

        XCTAssertTrue(MatchTimeContract.isMatch(match, on: selectedDate, calendar: english))
        XCTAssertTrue(MatchTimeContract.isMatch(match, on: selectedDate, calendar: french))
        XCTAssertFalse(
            MatchTimeContract.isMatch(
                match,
                on: isoDate("2026-09-07T18:00:00Z"),
                calendar: french
            )
        )
    }
}
