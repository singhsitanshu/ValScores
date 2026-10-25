import Foundation

// Decoding models for docs/API-CONTRACT.md. Optional numbers are nil when the
// backend reports the value as unavailable; views must not show them as zero.

struct MatchStatsResponse: Decodable {
    let match_info: MatchStatsInfo
    let team1_roster: [PlayerStatInfo]
    let team2_roster: [PlayerStatInfo]
}

struct MatchStatsInfo: Decodable {
    let match_id: Int
    let vlr_match_id: String
    let team1: String
    let team2: String
    let status: MatchStatus
    let map_vetoes: [String]
    let selected_game_id: String
    let maps: [MapStatInfo]
}

struct MapStatInfo: Decodable, Identifiable {
    static let allMapsGameID = "all"

    var id: String { game_id }
    let game_id: String
    let map_number: Int?
    let map_name: String
    let team1_round_score: Int?
    let team2_round_score: Int?

    var isAllMaps: Bool { game_id == Self.allMapsGameID }
}

struct PlayerStatInfo: Decodable, Identifiable {
    var id: String { "\(team)-\(team_abbreviation)-\(name)" }
    let name: String
    let team: String
    let team_abbreviation: String
    let role: String?
    let acs: Int?
    let kd: Double?
    let adr: Int?
    let kills: Int?
    let deaths: Int?
    let assists: Int?
    let plus_minus: Int?
    let kast: Double?
    let first_kills: Int?
    let first_deaths: Int?
}

struct RefreshResponse: Decodable {
    let status: String
    let matches_examined: Int
    let inserted: Int
    let updated: Int
    let unchanged: Int
    let details_refreshed: Int
    let failure_count: Int
    let failures: [RefreshFailure]
}

struct RefreshFailure: Decodable {
    let stage: String
    let error: String
    let source: String?
    let vlr_match_id: String?
    let url: String?
    let card_index: Int?
    let href: String?
}

/// Error codes from the backend's `{"error":{"code","message"}}` envelope.
/// Codes added by a newer backend decode as `.unknown`.
enum APIErrorCode: Equatable, Sendable {
    case validationError
    case invalidRange
    case notFound
    case matchNotFound
    case gameNotFound
    case methodNotAllowed
    case refreshInProgress
    case ambiguousRoster
    case httpError
    case internalError
    case unknown(String)

    init(rawValue: String) {
        switch rawValue {
        case "validation_error": self = .validationError
        case "invalid_range": self = .invalidRange
        case "not_found": self = .notFound
        case "match_not_found": self = .matchNotFound
        case "game_not_found": self = .gameNotFound
        case "method_not_allowed": self = .methodNotAllowed
        case "refresh_in_progress": self = .refreshInProgress
        case "ambiguous_roster": self = .ambiguousRoster
        case "http_error": self = .httpError
        case "internal_error": self = .internalError
        default: self = .unknown(rawValue)
        }
    }
}

struct APIErrorEnvelope: Decodable {
    let error: APIErrorDetail
}

struct APIErrorDetail: Decodable {
    let code: String
    let message: String

    var errorCode: APIErrorCode { APIErrorCode(rawValue: code) }
}
