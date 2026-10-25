import Foundation

/// Result of `POST /api/matches/refresh`.
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
