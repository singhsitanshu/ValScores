import Foundation

@main
struct MatchDetailStateTests {
    @MainActor
    static func main() async throws {
        try await loadingTransitionsToSuccess()
        try await rapidMapSelectionRejectsLateResponse()
        await emptyStatsRemainACompletedState()
        await failureStopsLoadingAndRetrySucceeds()
        await mismatchedMapResponseIsRejected()
        await cancellationCannotLeaveAnIndefiniteSpinner()
        placeholderAndIdenticalTeamsHaveDistinctTitles()
        print("Ran 7 Swift match-detail tests: OK")
    }

    @MainActor
    static func loadingTransitionsToSuccess() async throws {
        let state = MatchDetailState()
        let task = Task {
            await state.load(gameID: "all") {
                try await Task.sleep(nanoseconds: 50_000_000)
                return response(gameID: "all", playerName: "Alpha Player")
            }
        }

        await Task.yield()
        require(state.phase == .loading, "request enters loading state")
        await task.value

        require(state.phase == .loaded, "player response enters success state")
        require(state.response?.team1_roster.first?.kd == 1.5, "KD remains in client state")
        require(
            state.response?.team1_roster.first?.team_abbreviation == "AF",
            "team abbreviation remains explicitly named"
        )
    }

    @MainActor
    static func rapidMapSelectionRejectsLateResponse() async throws {
        let state = MatchDetailState()
        let map1 = Task {
            await state.load(gameID: "map-1") {
                try? await Task.sleep(nanoseconds: 200_000_000)
                return response(gameID: "map-1", playerName: "Late Map 1")
            }
        }

        await Task.yield()
        state.invalidatePendingRequest()
        let map2 = Task {
            await state.load(gameID: "map-2") {
                try? await Task.sleep(nanoseconds: 100_000_000)
                return response(gameID: "map-2", playerName: "Late Map 2")
            }
        }

        await Task.yield()
        state.invalidatePendingRequest()
        let map3 = Task {
            await state.load(gameID: "map-3") {
                response(gameID: "map-3", playerName: "Current Map 3")
            }
        }

        await map3.value
        await map2.value
        await map1.value

        require(state.phase == .loaded, "latest map remains loaded")
        require(state.response?.match_info.selected_game_id == "map-3", "Map 3 remains selected")
        require(
            state.response?.team1_roster.first?.name == "Current Map 3",
            "late Map 1 and Map 2 responses cannot overwrite Map 3"
        )
    }

    @MainActor
    static func emptyStatsRemainACompletedState() async {
        let state = MatchDetailState()
        await state.load(gameID: "map-1") {
            response(gameID: "map-1", playerName: nil)
        }

        require(state.phase == .empty, "empty rosters are not treated as loading or failure")
        require(state.response?.match_info.maps.count == 2, "maps remain available with empty stats")
        require(
            state.response?.match_info.map_vetoes == ["Alpha ban Lotus"],
            "vetoes remain available with empty stats"
        )
    }

    @MainActor
    static func failureStopsLoadingAndRetrySucceeds() async {
        let state = MatchDetailState()
        await state.load(gameID: "map-1") {
            throw TestError.offline
        }

        guard case .failed(let message) = state.phase else {
            fatalError("Test failed: error should leave a failed state")
        }
        require(message == "Backend unavailable", "failure exposes a useful message")

        state.invalidatePendingRequest()
        await state.load(gameID: "map-1") {
            response(gameID: "map-1", playerName: "Recovered")
        }
        require(state.phase == .loaded, "retry can recover from failure")
        require(state.response?.team1_roster.first?.name == "Recovered", "retry stores new stats")
    }

    @MainActor
    static func mismatchedMapResponseIsRejected() async {
        let state = MatchDetailState()
        await state.load(gameID: "map-3") {
            response(gameID: "map-1", playerName: "Wrong Map")
        }

        require(state.phase.errorMessage != nil, "mismatched map is an explicit failure")
        require(state.response == nil, "mismatched stats are never displayed")
    }

    @MainActor
    static func cancellationCannotLeaveAnIndefiniteSpinner() async {
        let state = MatchDetailState()
        await state.load(gameID: "map-1") {
            throw CancellationError()
        }

        require(!state.phase.isLoading, "cancelled request cannot remain loading")
        require(state.phase.errorMessage != nil, "standalone cancellation is visible")
    }

    static func placeholderAndIdenticalTeamsHaveDistinctTitles() {
        let placeholders = MatchDetailTeamTitles(team1: "TBD", team2: "TBD")
        require(placeholders.team1 == "Team 1", "first TBD team has a stable title")
        require(placeholders.team2 == "Team 2", "second TBD team has a stable title")

        let identical = MatchDetailTeamTitles(team1: "Valorant", team2: "valorant")
        require(identical.team1 == "Valorant 1", "identical first team remains addressable")
        require(identical.team2 == "valorant 2", "identical second team remains addressable")
    }

    static func response(gameID: String, playerName: String?) -> MatchStatsResponse {
        let player = playerName.map {
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
        }

        return MatchStatsResponse(
            match_info: MatchStatsInfo(
                team1: "Alpha Five",
                team2: "Bravo Crew",
                map_vetoes: ["Alpha ban Lotus"],
                selected_game_id: gameID,
                maps: [
                    MapStatInfo(
                        game_id: "map-1",
                        map_number: 1,
                        map_name: "Haven",
                        team1_round_score: 13,
                        team2_round_score: 9
                    ),
                    MapStatInfo(
                        game_id: "map-3",
                        map_number: 3,
                        map_name: "Lotus",
                        team1_round_score: 11,
                        team2_round_score: 13
                    ),
                ]
            ),
            team1_roster: player.map { [$0] } ?? [],
            team2_roster: []
        )
    }

    static func require(_ condition: @autoclosure () -> Bool, _ message: String) {
        guard condition() else { fatalError("Test failed: \(message)") }
    }
}

private enum TestError: LocalizedError {
    case offline

    var errorDescription: String? {
        "Backend unavailable"
    }
}
