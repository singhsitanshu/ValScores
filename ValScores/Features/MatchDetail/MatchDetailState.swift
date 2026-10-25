import Foundation
import Combine

struct MatchDetailTeamTitles: Equatable {
    let team1: String
    let team2: String

    init(team1: String, team2: String) {
        let first = team1.trimmingCharacters(in: .whitespacesAndNewlines)
        let second = team2.trimmingCharacters(in: .whitespacesAndNewlines)
        let namesAreIdentical = !first.isEmpty && first.caseInsensitiveCompare(second) == .orderedSame

        self.team1 = Self.title(for: first, side: 1, namesAreIdentical: namesAreIdentical)
        self.team2 = Self.title(for: second, side: 2, namesAreIdentical: namesAreIdentical)
    }

    private static func title(for name: String, side: Int, namesAreIdentical: Bool) -> String {
        if name.isEmpty || ["tbd", "to be determined"].contains(name.lowercased()) {
            return "Team \(side)"
        }
        return namesAreIdentical ? "\(name) \(side)" : name
    }
}

enum MatchDetailLoadPhase: Equatable {
    case idle
    case loading
    case loaded
    case empty
    case failed(message: String)

    var isLoading: Bool {
        self == .loading
    }

    var errorMessage: String? {
        guard case .failed(let message) = self else { return nil }
        return message
    }
}

private enum MatchDetailStateError: LocalizedError {
    case mismatchedGame(expected: String, received: String)

    var errorDescription: String? {
        switch self {
        case .mismatchedGame(let expected, let received):
            return "The backend returned stats for \(received) instead of \(expected)."
        }
    }
}

@MainActor
final class MatchDetailState: ObservableObject {
    @Published private(set) var response: MatchStatsResponse?
    @Published private(set) var phase: MatchDetailLoadPhase = .idle

    private var requestGeneration = 0

    func invalidatePendingRequest() {
        requestGeneration += 1
    }

    func load(
        gameID: String,
        operation: () async throws -> MatchStatsResponse
    ) async {
        requestGeneration += 1
        let generation = requestGeneration
        phase = .loading

        do {
            let result = try await operation()
            try Task.checkCancellation()
            guard generation == requestGeneration else { return }
            guard result.match_info.selected_game_id == gameID else {
                throw MatchDetailStateError.mismatchedGame(
                    expected: gameID,
                    received: result.match_info.selected_game_id
                )
            }

            response = result
            phase = result.team1_roster.isEmpty && result.team2_roster.isEmpty
                ? .empty
                : .loaded
        } catch let error as APIClientError where error.isCancelled {
            finishCancellation(generation: generation)
        } catch is CancellationError {
            finishCancellation(generation: generation)
        } catch {
            guard generation == requestGeneration else { return }
            phase = .failed(message: error.localizedDescription)
        }
    }

    private func finishCancellation(generation: Int) {
        guard generation == requestGeneration else { return }
        guard let response else {
            phase = .failed(message: APIClientError.cancelled.localizedDescription)
            return
        }
        phase = response.team1_roster.isEmpty && response.team2_roster.isEmpty
            ? .empty
            : .loaded
    }
}
