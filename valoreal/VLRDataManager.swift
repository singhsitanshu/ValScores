import Foundation
import Combine

struct MatchInfo: Codable, Identifiable {
    let id: Int
    let team1: String
    let team2: String
    let team1_score: String
    let team2_score: String
    let status: String
    let time: String
    let date_label: String
    let is_live: Bool
    let is_finished: Bool
    let team1_round_score: String?
    let team2_round_score: String?
}

class VLRDataManager: ObservableObject {
    @Published var allMatches: [MatchInfo] = []
    @Published var filteredMatches: [MatchInfo] = []
    @Published var isLoading = false

    // Filter + sort: live first, upcoming next, finished last.
    func filterMatches(for dateLabel: String) {
        let matchesForDate = allMatches.filter { $0.date_label == dateLabel }

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
                let decodedMatches = try JSONDecoder().decode([MatchInfo].self, from: data)

                DispatchQueue.main.async {
                    self.allMatches = decodedMatches
                    self.isLoading = false

                    let formatter = DateFormatter()
                    formatter.dateFormat = "MMM d"
                    let todayString = formatter.string(from: Date())

                    self.filterMatches(for: todayString)

                    print("✅ Loaded \(decodedMatches.count) matches")
                }
            } catch {
                print("❌ DECODING ERROR: \(error)")
                DispatchQueue.main.async { self.isLoading = false }
            }
        }.resume()
    }

    func forceRefresh(for dateLabel: String? = nil) async {
        guard let refreshUrl = URL(string: "http://127.0.0.1:8000/api/matches/refresh") else { return }
        guard let timelineUrl = URL(string: "http://127.0.0.1:8000/api/matches/timeline") else { return }

        do {
            print("🔄 Forcing scrape...")
            _ = try await URLSession.shared.data(from: refreshUrl)

            print("📥 Fetching updated matches...")
            let (data, _) = try await URLSession.shared.data(from: timelineUrl)
            let decodedMatches = try JSONDecoder().decode([MatchInfo].self, from: data)

            await MainActor.run {
                self.allMatches = decodedMatches

                let activeDate: String
                if let dateLabel {
                    activeDate = dateLabel
                } else {
                    let formatter = DateFormatter()
                    formatter.dateFormat = "MMM d"
                    activeDate = formatter.string(from: Date())
                }

                self.filterMatches(for: activeDate)

                print("✅ Refreshed with latest data")
            }

        } catch {
            print("❌ REFRESH ERROR: \(error.localizedDescription)")
        }
    }
}
