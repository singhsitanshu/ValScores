import Foundation
#if canImport(FoundationNetworking)
import FoundationNetworking
#endif

enum APIClientConfiguration {
    static let baseURLKey = "VALSCORES_API_BASE_URL"
    static let simulatorBaseURL = "http://127.0.0.1:8000"

    static var baseURLString: String {
        let environmentValue = ProcessInfo.processInfo.environment[baseURLKey]
        let defaultsValue = UserDefaults.standard.string(forKey: baseURLKey)
        let bundleValue = Bundle.main.object(forInfoDictionaryKey: baseURLKey) as? String

        return [environmentValue, defaultsValue, bundleValue]
            .compactMap { $0?.trimmingCharacters(in: .whitespacesAndNewlines) }
            .first(where: { !$0.isEmpty })
            ?? simulatorBaseURL
    }
}

enum APIClientError: Error, LocalizedError, Sendable {
    case invalidURL
    case transport(String)
    case badStatus(Int)
    case decoding(String)
    case server(statusCode: Int, code: String, message: String)
    case cancelled

    var isCancelled: Bool {
        if case .cancelled = self { return true }
        return false
    }

    var errorDescription: String? {
        switch self {
        case .invalidURL:
            return "The backend address is invalid."
        case .transport:
            return "Could not reach the ValScores backend."
        case .badStatus(let statusCode):
            return "The backend returned HTTP \(statusCode)."
        case .decoding:
            return "The backend returned data in an unexpected format."
        case .server(_, _, let message):
            return message
        case .cancelled:
            return "The request was cancelled."
        }
    }
}

struct RefreshParameters: Sendable {
    var limit = 50
    var detailsLimit = 12
    var resultsLimit = 100
}

struct APIClient {
    static let live = APIClient()

    private let baseURL: URL?
    private let session: URLSession

    init(
        baseURLString: String = APIClientConfiguration.baseURLString,
        session: URLSession = .shared
    ) {
        self.baseURL = Self.validatedBaseURL(from: baseURLString)
        self.session = session
    }

    func timeline(from start: Date, to end: Date) async throws -> [MatchInfo] {
        let formatter = ISO8601DateFormatter()
        let request = try makeRequest(
            method: "GET",
            pathComponents: ["api", "matches", "timeline"],
            queryItems: [
                URLQueryItem(name: "start", value: formatter.string(from: start)),
                URLQueryItem(name: "end", value: formatter.string(from: end)),
            ]
        )
        return try await send(request, as: [MatchInfo].self)
    }

    func matchDetails(matchID: Int, gameID: String = "all") async throws -> MatchStatsResponse {
        let request = try makeRequest(
            method: "GET",
            pathComponents: ["api", "matches", String(matchID), "stats"],
            queryItems: [URLQueryItem(name: "game_id", value: gameID)]
        )
        return try await send(request, as: MatchStatsResponse.self)
    }

    @discardableResult
    func refresh() async throws -> RefreshResponse {
        try await refresh(parameters: RefreshParameters())
    }

    @discardableResult
    func refresh(parameters: RefreshParameters) async throws -> RefreshResponse {
        let request = try makeRequest(
            method: "POST",
            pathComponents: ["api", "matches", "refresh"],
            queryItems: [
                URLQueryItem(name: "limit", value: String(parameters.limit)),
                URLQueryItem(name: "details_limit", value: String(parameters.detailsLimit)),
                URLQueryItem(name: "results_limit", value: String(parameters.resultsLimit)),
            ]
        )
        return try await send(request, as: RefreshResponse.self)
    }

    private static func validatedBaseURL(from value: String) -> URL? {
        guard
            var components = URLComponents(string: value),
            let scheme = components.scheme?.lowercased(),
            ["http", "https"].contains(scheme),
            components.host?.isEmpty == false
        else {
            return nil
        }

        components.query = nil
        components.fragment = nil
        return components.url
    }

    private func makeRequest(
        method: String,
        pathComponents: [String],
        queryItems: [URLQueryItem]
    ) throws -> URLRequest {
        guard var url = baseURL else { throw APIClientError.invalidURL }
        for component in pathComponents {
            url.appendPathComponent(component)
        }

        guard var components = URLComponents(url: url, resolvingAgainstBaseURL: false) else {
            throw APIClientError.invalidURL
        }
        components.queryItems = queryItems
        guard let requestURL = components.url else { throw APIClientError.invalidURL }

        var request = URLRequest(url: requestURL)
        request.httpMethod = method
        request.setValue("application/json", forHTTPHeaderField: "Accept")
        return request
    }

    private func send<Response: Decodable>(
        _ request: URLRequest,
        as responseType: Response.Type
    ) async throws -> Response {
        do {
            try Task.checkCancellation()
            let (data, response) = try await session.data(for: request)
            try Task.checkCancellation()

            guard let httpResponse = response as? HTTPURLResponse else {
                throw APIClientError.transport("The response was not HTTP.")
            }
            guard (200..<300).contains(httpResponse.statusCode) else {
                if let serverError = try? JSONDecoder().decode(ServerErrorEnvelope.self, from: data) {
                    throw APIClientError.server(
                        statusCode: httpResponse.statusCode,
                        code: serverError.error.code,
                        message: serverError.error.message
                    )
                }
                throw APIClientError.badStatus(httpResponse.statusCode)
            }

            do {
                return try MatchTimeContract.makeDecoder().decode(responseType, from: data)
            } catch {
                throw APIClientError.decoding(String(describing: error))
            }
        } catch let error as APIClientError {
            throw error
        } catch is CancellationError {
            throw APIClientError.cancelled
        } catch let error as URLError where error.code == .cancelled {
            throw APIClientError.cancelled
        } catch let error as URLError {
            throw APIClientError.transport(error.localizedDescription)
        } catch {
            throw APIClientError.transport(error.localizedDescription)
        }
    }
}

private struct ServerErrorEnvelope: Decodable {
    let error: ServerErrorDetail
}

private struct ServerErrorDetail: Decodable {
    let code: String
    let message: String
}
