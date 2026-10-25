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
