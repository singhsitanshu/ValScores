import Foundation
import XCTest
@testable import ValScores

final class XCTestMockURLProtocol: URLProtocol {
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

@MainActor
class ValScoresTestCase: XCTestCase {
    override func tearDown() {
        XCTestMockURLProtocol.handler = nil
        super.tearDown()
    }

    func makeClient(
        handler: @escaping (URLRequest) throws -> (HTTPURLResponse, Data)
    ) -> APIClient {
        XCTestMockURLProtocol.handler = handler
        let configuration = URLSessionConfiguration.ephemeral
        configuration.protocolClasses = [XCTestMockURLProtocol.self]
        return APIClient(
            baseURLString: "http://127.0.0.1:8000",
            session: URLSession(configuration: configuration)
        )
    }

    func makeManager(
        handler: @escaping (URLRequest) throws -> (HTTPURLResponse, Data)
    ) -> VLRDataManager {
        VLRDataManager(apiClient: makeClient(handler: handler))
    }

    func response(
        _ request: URLRequest,
        status: Int = 200,
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

    func queryItems(_ request: URLRequest) -> [String: String] {
        let items = URLComponents(
            url: request.url!,
            resolvingAgainstBaseURL: false
        )?.queryItems ?? []
        return Dictionary(
            uniqueKeysWithValues: items.map { ($0.name, $0.value ?? "") }
        )
    }

    func matchJSON(
        id: Int,
        team1: String,
        status: String = "upcoming",
        startTime: String,
        isLive: Bool = false,
        isFinished: Bool = false
    ) -> String {
        """
        {"id":\(id),"team1":"\(team1)","team2":"Opponent",\
        "team1_score":null,"team2_score":null,"status":"\(status)",\
        "start_time":"\(startTime)","is_live":\(isLive),\
        "is_finished":\(isFinished),"team1_round_score":null,\
        "team2_round_score":null}
        """
    }

    func detailJSON(gameID: String = "map-1") -> String {
        """
        {"match_info":{"team1":"Alpha Five","team2":"Bravo Crew",\
        "map_vetoes":["Alpha ban Lotus"],"selected_game_id":"\(gameID)",\
        "maps":[{"game_id":"map-1","map_number":1,"map_name":"Haven",\
        "team1_round_score":13,"team2_round_score":9}]},\
        "team1_roster":[{"name":"Ace","team":"Alpha Five",\
        "team_abbreviation":"AF","acs":245,"kd":1.5,"adr":160,\
        "kills":21,"deaths":14,"assists":7,"plus_minus":"+7",\
        "kast":"78%","first_kills":4,"first_deaths":1}],\
        "team2_roster":[{"name":"Bolt","team":"Bravo Crew",\
        "team_abbreviation":"BC","acs":201,"kd":0.88,"adr":138,\
        "kills":15,"deaths":17,"assists":5,"plus_minus":"-2",\
        "kast":"69%","first_kills":2,"first_deaths":3}]}
        """
    }

    func isoDate(_ value: String) -> Date {
        ISO8601DateFormatter().date(from: value)!
    }

    func calendar(timeZone: String, locale: String = "en_US") -> Calendar {
        var calendar = Calendar(identifier: .gregorian)
        calendar.timeZone = TimeZone(identifier: timeZone)!
        calendar.locale = Locale(identifier: locale)
        return calendar
    }

    func waitUntil(
        timeoutNanoseconds: UInt64 = 2_000_000_000,
        condition: @escaping @MainActor () -> Bool
    ) async throws {
        let deadline = DispatchTime.now().uptimeNanoseconds + timeoutNanoseconds
        while !condition() {
            if DispatchTime.now().uptimeNanoseconds >= deadline {
                XCTFail("Timed out waiting for state")
                return
            }
            try await Task.sleep(nanoseconds: 10_000_000)
        }
    }
}

extension TimelineLoadState {
    var isLoadedForTests: Bool {
        if case .loaded = self { return true }
        return false
    }

    var isEmptyForTests: Bool {
        if case .empty = self { return true }
        return false
    }

    var isFailedForTests: Bool {
        if case .failed = self { return true }
        return false
    }
}

enum XCTestFailure: LocalizedError {
    case offline

    var errorDescription: String? {
        "Backend unavailable"
    }
}
