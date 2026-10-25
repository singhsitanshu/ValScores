import Foundation

/// Canonical match status from the backend contract (docs/API-CONTRACT.md).
/// Values added by a newer backend decode as `.unknown` instead of failing.
enum MatchStatus: Equatable, Hashable, Sendable {
    case upcoming
    case live
    case postponed
    case finished
    case cancelled
    case unknown(String)

    init(rawValue: String) {
        switch rawValue.lowercased() {
        case "upcoming": self = .upcoming
        case "live": self = .live
        case "postponed": self = .postponed
        case "finished": self = .finished
        case "cancelled": self = .cancelled
        default: self = .unknown(rawValue)
        }
    }

    var displayName: String {
        switch self {
        case .upcoming: return "Upcoming"
        case .live: return "Live"
        case .postponed: return "Postponed"
        case .finished: return "Final"
        case .cancelled: return "Cancelled"
        case .unknown(let rawValue): return rawValue.isEmpty ? "Unknown" : rawValue.capitalized
        }
    }
}

extension MatchStatus: Codable {
    init(from decoder: Decoder) throws {
        self.init(rawValue: try decoder.singleValueContainer().decode(String.self))
    }

    func encode(to encoder: Encoder) throws {
        var container = encoder.singleValueContainer()
        switch self {
        case .upcoming: try container.encode("upcoming")
        case .live: try container.encode("live")
        case .postponed: try container.encode("postponed")
        case .finished: try container.encode("finished")
        case .cancelled: try container.encode("cancelled")
        case .unknown(let rawValue): try container.encode(rawValue)
        }
    }
}

/// One timeline entry. `id` is the ValScores match ID used in API paths;
/// `vlr_match_id` is the upstream identifier and is informational only.
/// Null scores mean unknown, never zero.
struct MatchInfo: Codable, Identifiable {
    let id: Int
    let vlr_match_id: String
    let team1: String
    let team2: String
    let team1_score: Int?
    let team2_score: Int?
    let status: MatchStatus
    let startTime: Date
    let is_live: Bool
    let is_finished: Bool
    let team1_round_score: Int?
    let team2_round_score: Int?

    enum CodingKeys: String, CodingKey {
        case id
        case vlr_match_id
        case team1
        case team2
        case team1_score
        case team2_score
        case status
        case startTime = "start_time"
        case is_live
        case is_finished
        case team1_round_score
        case team2_round_score
    }
}
