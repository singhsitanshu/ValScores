import Foundation
import Combine

class VLRDataManager: ObservableObject {
    @Published var allMatches: [MatchInfo] = []
    @Published var filteredMatches: [MatchInfo] = []
    @Published var isLoading = false

    private let apiRoot = URL(string: "http://127.0.0.1:8000")!

    // Filter + sort: live first, upcoming next, finished last.
    func filterMatches(for selectedDate: Date, calendar: Calendar = .autoupdatingCurrent) {
        let matchesForDate = allMatches.filter {
            MatchTimeContract.isMatch($0, on: selectedDate, calendar: calendar)
        }

        let liveMatches = matchesForDate.filter { $0.is_live }
        let upcomingMatches = matchesForDate.filter { !$0.is_live && !$0.is_finished }
        let finishedMatches = matchesForDate.filter { $0.is_finished && !$0.is_live }

        filteredMatches = liveMatches + upcomingMatches + finishedMatches
    }

    func fetchTimeline(for selectedDate: Date = Date()) {
        isLoading = true

        guard let url = timelineURL(around: selectedDate) else {
            isLoading = false
            return
        }

        URLSession.shared.dataTask(with: url) { data, response, error in
            if let error {
                print("❌ NETWORK ERROR: \(error.localizedDescription)")
                DispatchQueue.main.async { self.isLoading = false }
                return
            }

            guard
                let data,
                let httpResponse = response as? HTTPURLResponse,
                (200..<300).contains(httpResponse.statusCode)
            else {
                print("❌ TIMELINE REQUEST FAILED")
                DispatchQueue.main.async { self.isLoading = false }
                return
            }

            do {
                let decodedMatches = try MatchTimeContract.makeDecoder().decode([MatchInfo].self, from: data)

                DispatchQueue.main.async {
                    self.allMatches = decodedMatches
                    self.isLoading = false
                    self.filterMatches(for: selectedDate)
                    print("✅ Loaded \(decodedMatches.count) matches")
                }
            } catch {
                print("❌ DECODING ERROR: \(error)")
                DispatchQueue.main.async { self.isLoading = false }
            }
        }.resume()
    }

    func forceRefresh(for selectedDate: Date? = nil) async {
        let date = selectedDate ?? Date()
        guard let timelineUrl = timelineURL(around: date) else { return }
        let refreshUrl = apiRoot.appendingPathComponent("api/matches/refresh")
        var refreshRequest = URLRequest(url: refreshUrl)
        refreshRequest.httpMethod = "POST"

        do {
            print("🔄 Forcing scrape...")
            let (_, refreshResponse) = try await URLSession.shared.data(for: refreshRequest)
            try validate(refreshResponse)

            print("📥 Fetching updated matches...")
            let (data, timelineResponse) = try await URLSession.shared.data(from: timelineUrl)
            try validate(timelineResponse)
            let decodedMatches = try MatchTimeContract.makeDecoder().decode([MatchInfo].self, from: data)

            await MainActor.run {
                self.allMatches = decodedMatches
                self.filterMatches(for: date)
                print("✅ Refreshed with latest data")
            }
        } catch {
            print("❌ REFRESH ERROR: \(error.localizedDescription)")
        }
    }

    private func timelineURL(
        around selectedDate: Date,
        calendar: Calendar = .autoupdatingCurrent
    ) -> URL? {
        let selectedDay = calendar.startOfDay(for: selectedDate)
        guard
            let start = calendar.date(byAdding: .day, value: -3, to: selectedDay),
            let end = calendar.date(byAdding: .day, value: 7, to: start)
        else {
            return nil
        }

        var components = URLComponents(
            url: apiRoot.appendingPathComponent("api/matches/timeline"),
            resolvingAgainstBaseURL: false
        )
        let formatter = ISO8601DateFormatter()
        components?.queryItems = [
            URLQueryItem(name: "start", value: formatter.string(from: start)),
            URLQueryItem(name: "end", value: formatter.string(from: end)),
        ]
        return components?.url
    }

    private func validate(_ response: URLResponse) throws {
        guard
            let httpResponse = response as? HTTPURLResponse,
            (200..<300).contains(httpResponse.statusCode)
        else {
            throw URLError(.badServerResponse)
        }
    }
}
