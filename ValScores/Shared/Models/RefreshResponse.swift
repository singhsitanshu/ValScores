import Foundation

/// Result of `POST /api/matches/refresh`. `status` and `failure_count` reflect
/// failures only; `warnings` describe data stored with incomplete upstream fields.
struct RefreshResponse: Decodable {
    let status: String
    let matches_examined: Int
    let inserted: Int
    let updated: Int
    let unchanged: Int
    let details_refreshed: Int
    let failure_count: Int
    let failures: [RefreshFailure]
    let warning_count: Int
    let warnings: [RefreshWarning]
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

struct RefreshWarning: Decodable {
    let stage: String
    let message: String
    let source: String?
    let vlr_match_id: String?
    let url: String?
    let card_index: Int?
    let href: String?
    let field: String?
}
