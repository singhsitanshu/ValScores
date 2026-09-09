import Foundation

struct MatchStatsResponse: Decodable {
    let match_info: MatchStatsInfo
    let team1_roster: [PlayerStatInfo]
    let team2_roster: [PlayerStatInfo]
}

struct MatchStatsInfo: Decodable {
    let team1: String
    let team2: String
    let map_vetoes: [String]
    let selected_game_id: String
    let maps: [MapStatInfo]
}

struct MapStatInfo: Decodable, Identifiable {
    var id: String { game_id }
    let game_id: String
    let map_number: Int
    let map_name: String
    let team1_round_score: Int?
    let team2_round_score: Int?
}

struct PlayerStatInfo: Decodable, Identifiable {
    var id: String { "\(team)-\(name)" }
    let name: String
    let team: String
    let role: String
    let acs: Int
    let kd: Double
    let adr: Int
    let kills: Int
    let deaths: Int
    let assists: Int
    let plus_minus: String
    let kast: String
    let first_kills: Int
    let first_deaths: Int
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
