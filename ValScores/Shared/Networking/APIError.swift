import Foundation

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
