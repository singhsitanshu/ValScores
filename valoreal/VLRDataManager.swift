import Foundation
import Combine

class VLRDataManager: ObservableObject {
    @Published var allMatches: [MatchInfo] = []
    @Published var filteredMatches: [MatchInfo] = []
    @Published var isLoading = false

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

    func fetchTimeline() {
        self.isLoading = true

        guard let url = URL(string: "http://127.0.0.1:8000/api/matches/timeline") else { return }

        URLSession.shared.dataTask(with: url) { data, response, error in
            if let error = error {
                print("❌ NETWORK ERROR: \(error.localizedDescription)")
                DispatchQueue.main.async { self.isLoading = false }
                return
            }

            guard let data = data else {
                print("❌ NO DATA RECEIVED")
                DispatchQueue.main.async { self.isLoading = false }
                return
            }

            do {
                let decodedMatches = try MatchTimeContract.makeDecoder().decode([MatchInfo].self, from: data)

                DispatchQueue.main.async {
                    self.allMatches = decodedMatches
                    self.isLoading = false

                    self.filterMatches(for: Date())

                    print("✅ Loaded \(decodedMatches.count) matches")
                }
            } catch {
                print("❌ DECODING ERROR: \(error)")
                DispatchQueue.main.async { self.isLoading = false }
            }
        }.resume()
    }

    func forceRefresh(for selectedDate: Date? = nil) async {
        guard let refreshUrl = URL(string: "http://127.0.0.1:8000/api/matches/refresh") else { return }
        guard let timelineUrl = URL(string: "http://127.0.0.1:8000/api/matches/timeline") else { return }

        do {
            print("🔄 Forcing scrape...")
            _ = try await URLSession.shared.data(from: refreshUrl)

            print("📥 Fetching updated matches...")
            let (data, _) = try await URLSession.shared.data(from: timelineUrl)
            let decodedMatches = try MatchTimeContract.makeDecoder().decode([MatchInfo].self, from: data)

            await MainActor.run {
                self.allMatches = decodedMatches

                self.filterMatches(for: selectedDate ?? Date())

                print("✅ Refreshed with latest data")
            }

        } catch {
            print("❌ REFRESH ERROR: \(error.localizedDescription)")
        }
    }
}
