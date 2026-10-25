import Foundation

/// Timestamp decoding and device-calendar grouping for match start times.
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
        calendar.isDate(match.startTime, inSameDayAs: selectedDate)
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
