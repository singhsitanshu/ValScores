import Foundation

@main
struct MatchTimeContractTests {
    static func main() throws {
        try decodesUTCISO8601TimestampAsDate()
        try UTCDateCrossesToPreviousLocalDay()
        try UTCDateCrossesYearBoundaryInLocalTimezone()
        try changingToNonEnglishLocaleDoesNotChangeGrouping()
        try nullLegacyTimestampDoesNotMatchAnyDate()
        print("Ran 5 Swift time-contract tests: OK")
    }

    static func decodesUTCISO8601TimestampAsDate() throws {
        let match = try makeMatch(timestamp: "2026-09-06T13:00:00Z")
        require(match.startTime == isoDate("2026-09-06T13:00:00Z"), "UTC timestamp decoding")
    }

    static func UTCDateCrossesToPreviousLocalDay() throws {
        let match = try makeMatch(timestamp: "2026-09-07T00:30:00Z")
        let calendar = localCalendar(timeZone: "America/Chicago", locale: "en_US")

        require(
            MatchTimeContract.isMatch(
                match,
                on: isoDate("2026-09-06T18:00:00Z"),
                calendar: calendar
            ),
            "midnight crossing should match the previous Chicago day"
        )
        require(
            !MatchTimeContract.isMatch(
                match,
                on: isoDate("2026-09-07T18:00:00Z"),
                calendar: calendar
            ),
            "midnight crossing should not match the next Chicago day"
        )
    }

    static func UTCDateCrossesYearBoundaryInLocalTimezone() throws {
        let match = try makeMatch(timestamp: "2026-12-31T23:30:00Z")
        let calendar = localCalendar(timeZone: "Asia/Tokyo", locale: "en_US")

        require(
            MatchTimeContract.isMatch(
                match,
                on: isoDate("2027-01-01T03:00:00Z"),
                calendar: calendar
            ),
            "year boundary should match January 1 in Tokyo"
        )
    }

    static func changingToNonEnglishLocaleDoesNotChangeGrouping() throws {
        let match = try makeMatch(timestamp: "2026-09-07T00:30:00Z")
        let selectedDate = isoDate("2026-09-06T18:00:00Z")
        let english = localCalendar(timeZone: "America/Chicago", locale: "en_US")
        let french = localCalendar(timeZone: "America/Chicago", locale: "fr_FR")
        let englishResult = MatchTimeContract.isMatch(match, on: selectedDate, calendar: english)
        let frenchResult = MatchTimeContract.isMatch(match, on: selectedDate, calendar: french)

        require(englishResult == frenchResult, "locale must not change date grouping")
        require(frenchResult, "French locale should retain the match")
    }

    static func nullLegacyTimestampDoesNotMatchAnyDate() throws {
        let match = try makeMatch(timestamp: nil)
        require(match.startTime == nil, "null legacy timestamp should decode as nil")
        require(!MatchTimeContract.isMatch(match, on: Date()), "nil timestamps should not match a date")
    }

    static func makeMatch(timestamp: String?) throws -> MatchInfo {
        let payload: [String: Any] = [
            "id": 1,
            "team1": "Alpha",
            "team2": "Bravo",
            "team1_score": NSNull(),
            "team2_score": NSNull(),
            "status": "Upcoming",
            "start_time": timestamp ?? NSNull(),
            "is_live": false,
            "is_finished": false,
            "team1_round_score": 0,
            "team2_round_score": 0,
        ]
        let data = try JSONSerialization.data(withJSONObject: payload)
        return try MatchTimeContract.makeDecoder().decode(MatchInfo.self, from: data)
    }

    static func isoDate(_ value: String) -> Date {
        ISO8601DateFormatter().date(from: value)!
    }

    static func localCalendar(timeZone identifier: String, locale identifierLocale: String) -> Calendar {
        var calendar = Calendar(identifier: .gregorian)
        calendar.timeZone = TimeZone(identifier: identifier)!
        calendar.locale = Locale(identifier: identifierLocale)
        return calendar
    }

    static func require(_ condition: @autoclosure () -> Bool, _ message: String) {
        guard condition() else {
            fatalError("Test failed: \(message)")
        }
    }
}
