import Foundation
import XCTest
@testable import ValScores

final class MatchDetailAndNavigationTests: ValScoresTestCase {
    func testRapidMapChangesKeepOnlyNewestResponse() async {
        let state = MatchDetailState()
        let map1 = Task {
            await state.load(gameID: "map-1") {
                try? await Task.sleep(nanoseconds: 200_000_000)
                return self.details(gameID: "map-1", player: "Late Map 1")
            }
        }
        await Task.yield()
        state.invalidatePendingRequest()

        let map2 = Task {
            await state.load(gameID: "map-2") {
                try? await Task.sleep(nanoseconds: 100_000_000)
                return self.details(gameID: "map-2", player: "Late Map 2")
            }
        }
        await Task.yield()
        state.invalidatePendingRequest()

        let map3 = Task {
            await state.load(gameID: "map-3") {
                self.details(gameID: "map-3", player: "Current Map 3")
            }
        }

        await map3.value
        await map2.value
        await map1.value

        XCTAssertEqual(state.phase, .loaded)
        XCTAssertEqual(state.response?.match_info.selected_game_id, "map-3")
        XCTAssertEqual(state.response?.team1_roster.first?.name, "Current Map 3")
    }

    func testDetailEmptyFailureAndCancellationFinishLoading() async {
        let emptyState = MatchDetailState()
        await emptyState.load(gameID: "map-1") {
            self.details(gameID: "map-1", player: nil)
        }
        XCTAssertEqual(emptyState.phase, .empty)

        let failedState = MatchDetailState()
        await failedState.load(gameID: "map-1") {
            throw XCTestFailure.offline
        }
        XCTAssertEqual(failedState.phase, .failed(message: "Backend unavailable"))

        let cancelledState = MatchDetailState()
        await cancelledState.load(gameID: "map-1") {
            throw CancellationError()
        }
        XCTAssertFalse(cancelledState.phase.isLoading)
        XCTAssertNotNil(cancelledState.phase.errorMessage)
    }

    func testNavigationRouteCarriesSelectedMatchIdentity() throws {
        let data = Data("[\(matchJSON(id: 73, team1: "Selected", startTime: "2026-09-07T12:00:00Z"))]".utf8)
        let match = try MatchTimeContract.makeDecoder().decode([MatchInfo].self, from: data)[0]
        let route = MatchDetailRoute(match: match)

        XCTAssertEqual(route.match.id, 73)
        XCTAssertEqual(route.match.team1, "Selected")
        XCTAssertEqual(route, MatchDetailRoute(match: match))
    }

    private func details(gameID: String, player: String?) -> MatchStatsResponse {
        let roster = player.map {
            [
                PlayerStatInfo(
                    name: $0,
                    team: "Alpha Five",
                    team_abbreviation: "AF",
                    acs: 245,
                    kd: 1.5,
                    adr: 160,
                    kills: 21,
                    deaths: 14,
                    assists: 7,
                    plus_minus: "+7",
                    kast: "78%",
                    first_kills: 4,
                    first_deaths: 1
                )
            ]
        } ?? []

        return MatchStatsResponse(
            match_info: MatchStatsInfo(
                team1: "Alpha Five",
                team2: "Bravo Crew",
                map_vetoes: [],
                selected_game_id: gameID,
                maps: []
            ),
            team1_roster: roster,
            team2_roster: []
        )
    }
}
