import Foundation
#if canImport(FoundationNetworking)
import FoundationNetworking
#endif

final class MockURLProtocol: URLProtocol {
    static var handler: ((URLRequest) throws -> (HTTPURLResponse, Data))?

    override class func canInit(with request: URLRequest) -> Bool { true }

    override class func canonicalRequest(for request: URLRequest) -> URLRequest {
        request
    }

    override func startLoading() {
        guard let handler = Self.handler else {
            client?.urlProtocol(self, didFailWithError: URLError(.unknown))
            return
        }

        do {
            let (response, data) = try handler(request)
            client?.urlProtocol(self, didReceive: response, cacheStoragePolicy: .notAllowed)
            client?.urlProtocol(self, didLoad: data)
            client?.urlProtocolDidFinishLoading(self)
        } catch {
            client?.urlProtocol(self, didFailWithError: error)
        }
    }

    override func stopLoading() {}
}

@main
struct APIClientTests {
    static func main() async throws {
        try await configurableBaseURLAndTimelineRequest()
        try await detailAndRefreshRequestsUseSharedTransport()
        try await structuredServerErrorWinsOverDecoding()
        try await badStatusAndDecodingAreDistinct()
        try await invalidURLTransportAndCancellationAreDistinct()
        print("Ran 5 Swift API-client tests: OK")
    }

    static func configurableBaseURLAndTimelineRequest() async throws {
        let client = makeClient(baseURL: "http://192.168.1.20:9000/root") { request in
            require(request.httpMethod == "GET", "timeline should use GET")
            require(request.url?.path == "/root/api/matches/timeline", "timeline path")
            let query = queryItems(request)
            require(query["start"] == "2026-09-07T00:00:00Z", "timeline start")
            require(query["end"] == "2026-09-08T00:00:00Z", "timeline end")
            return response(
                request,
                status: 200,
                body: """
                [{"id":1,"team1":"Alpha","team2":"Bravo","team1_score":null,
                "team2_score":null,"status":"upcoming","start_time":"2026-09-07T12:00:00Z",
                "is_live":false,"is_finished":false,"team1_round_score":null,
                "team2_round_score":null}]
                """
            )
        }

        let matches = try await client.timeline(
            from: isoDate("2026-09-07T00:00:00Z"),
            to: isoDate("2026-09-08T00:00:00Z")
        )
        require(matches.count == 1, "timeline decoding")
        require(matches[0].team1 == "Alpha", "timeline response")
    }

    static func detailAndRefreshRequestsUseSharedTransport() async throws {
        var requestNumber = 0
        let client = makeClient { request in
            requestNumber += 1
            if requestNumber == 1 {
                require(request.httpMethod == "GET", "details should use GET")
                require(request.url?.path == "/api/matches/42/stats", "details path")
                require(queryItems(request)["game_id"] == "map-2", "details game ID")
                return response(
                    request,
                    status: 200,
                    body: """
                    {"match_info":{"team1":"Alpha","team2":"Bravo","map_vetoes":[],
                    "selected_game_id":"map-2","maps":[]},"team1_roster":[{"name":"Ace",
                    "team":"Alpha","team_abbreviation":"ALP","acs":245,"kd":1.5,
                    "adr":160,"kills":21,"deaths":14,"assists":7,"plus_minus":"+7",
                    "kast":"78%","first_kills":4,"first_deaths":1}],"team2_roster":[]}
                    """
                )
            }

            require(request.httpMethod == "POST", "refresh should use POST")
            require(request.url?.path == "/api/matches/refresh", "refresh path")
            let query = queryItems(request)
            require(query["limit"] == "10", "refresh limit")
            require(query["details_limit"] == "3", "refresh details limit")
            require(query["results_limit"] == "20", "refresh results limit")
            return response(
                request,
                status: 200,
                body: """
                {"status":"success","matches_examined":0,"inserted":0,"updated":0,
                "unchanged":0,"details_refreshed":0,"failure_count":0,"failures":[]}
                """
            )
        }

        let details = try await client.matchDetails(matchID: 42, gameID: "map-2")
        require(details.match_info.selected_game_id == "map-2", "details decoding")
        require(details.team1_roster.first?.team_abbreviation == "ALP", "team abbreviation decoding")
        require(details.team1_roster.first?.kd == 1.5, "KD decoding")
        let refresh = try await client.refresh(
            parameters: RefreshParameters(limit: 10, detailsLimit: 3, resultsLimit: 20)
        )
        require(refresh.status == "success", "refresh decoding")
    }

    static func structuredServerErrorWinsOverDecoding() async throws {
        let client = makeClient { request in
            response(
                request,
                status: 500,
                body: "{\"error\":{\"code\":\"database_down\",\"message\":\"Database unavailable\"}}"
            )
        }

        do {
            _ = try await client.matchDetails(matchID: 1)
            fatalError("Expected a structured server error")
        } catch APIClientError.server(let status, let code, let message) {
            require(status == 500, "server status")
            require(code == "database_down", "server error code")
            require(message == "Database unavailable", "server message")
        }
    }

    static func badStatusAndDecodingAreDistinct() async throws {
        var requestNumber = 0
        let client = makeClient { request in
            requestNumber += 1
            return response(
                request,
                status: requestNumber == 1 ? 502 : 200,
                body: requestNumber == 1 ? "upstream failure" : "not-json"
            )
        }

        do {
            _ = try await client.matchDetails(matchID: 1)
            fatalError("Expected badStatus")
        } catch APIClientError.badStatus(let status) {
            require(status == 502, "bad status value")
        }

        do {
            _ = try await client.matchDetails(matchID: 1)
            fatalError("Expected decoding")
        } catch APIClientError.decoding {
            // Expected.
        }
    }

    static func invalidURLTransportAndCancellationAreDistinct() async throws {
        let invalidClient = makeClient(baseURL: "not a URL") { request in
            response(request, status: 200, body: "[]")
        }
        do {
            _ = try await invalidClient.timeline(from: Date(), to: Date())
            fatalError("Expected invalidURL")
        } catch APIClientError.invalidURL {
            // Expected.
        }

        let offlineClient = makeClient { _ in
            throw URLError(.notConnectedToInternet)
        }
        do {
            _ = try await offlineClient.matchDetails(matchID: 1)
            fatalError("Expected transport")
        } catch APIClientError.transport {
            // Expected.
        }

        let cancelledClient = makeClient { _ in
            throw URLError(.cancelled)
        }
        do {
            _ = try await cancelledClient.matchDetails(matchID: 1)
            fatalError("Expected cancelled")
        } catch APIClientError.cancelled {
            // Expected.
        }
    }

    static func makeClient(
        baseURL: String = "http://127.0.0.1:8000",
        handler: @escaping (URLRequest) throws -> (HTTPURLResponse, Data)
    ) -> APIClient {
        MockURLProtocol.handler = handler
        let configuration = URLSessionConfiguration.ephemeral
        configuration.protocolClasses = [MockURLProtocol.self]
        return APIClient(
            baseURLString: baseURL,
            session: URLSession(configuration: configuration)
        )
    }

    static func response(
        _ request: URLRequest,
        status: Int,
        body: String
    ) -> (HTTPURLResponse, Data) {
        let response = HTTPURLResponse(
            url: request.url!,
            statusCode: status,
            httpVersion: nil,
            headerFields: ["Content-Type": "application/json"]
        )!
        return (response, Data(body.utf8))
    }

    static func queryItems(_ request: URLRequest) -> [String: String] {
        let items = URLComponents(url: request.url!, resolvingAgainstBaseURL: false)?.queryItems ?? []
        return Dictionary(uniqueKeysWithValues: items.map { ($0.name, $0.value ?? "") })
    }

    static func isoDate(_ value: String) -> Date {
        ISO8601DateFormatter().date(from: value)!
    }

    static func require(_ condition: @autoclosure () -> Bool, _ message: String) {
        guard condition() else { fatalError("Test failed: \(message)") }
    }
}
