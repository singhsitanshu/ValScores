import Foundation

struct MatchInfo: Codable, Identifiable {
    let id: Int
    let team1: String
    let team2: String
    let team1_score: Int?
    let team2_score: Int?
    let status: String
    let startTime: Date?
    let is_live: Bool
    let is_finished: Bool
    let team1_round_score: Int?
    let team2_round_score: Int?

    enum CodingKeys: String, CodingKey {
        case id
        case team1
        case team2
        case team1_score
        case team2_score
        case status
        case startTime = "start_time"
        case is_live
        case is_finished
        case team1_round_score
        case team2_round_score
    }
}

enum MatchTimeContract {
    static func makeDecoder() -> JSONDecoder {
        let decoder = JSONDecoder()
        decoder.dateDecodingStrategy = .iso8601
        return decoder
    }

    static func isMatch(
        _ match: MatchInfo,
        on selectedDate: Date,
        calendar: Calendar = .autoupdatingCurrent
    ) -> Bool {
        guard let startTime = match.startTime else { return false }
        return calendar.isDate(startTime, inSameDayAs: selectedDate)
    }

    static func displayTime(
        for date: Date?,
        locale: Locale = .autoupdatingCurrent,
        timeZone: TimeZone = .autoupdatingCurrent
    ) -> String {
        guard let date else { return "TBD" }
        let formatter = DateFormatter()
        formatter.locale = locale
        formatter.timeZone = timeZone
        formatter.dateStyle = .none
        formatter.timeStyle = .short
        return formatter.string(from: date)
    }
}

extension MatchInfo {
    var displayTime: String {
        MatchTimeContract.displayTime(for: startTime)
    }
}
