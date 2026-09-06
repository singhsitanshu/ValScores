import SwiftUI

struct MatchStatsResponse: Codable {
    let match_info: MatchStatsInfo
    let team1_roster: [PlayerStatInfo]
    let team2_roster: [PlayerStatInfo]
}

struct MatchStatsInfo: Codable {
    let team1: String
    let team2: String
    let map_vetoes: [String]
    let selected_game_id: String
    let maps: [MapStatInfo]
}

struct MapStatInfo: Codable, Identifiable {
    var id: String { game_id }
    let game_id: String
    let map_number: Int
    let map_name: String
    let team1_round_score: String
    let team2_round_score: String
}

struct PlayerStatInfo: Codable, Identifiable {
    var id: String { "\(team)-\(name)" }
    let name: String
    let team: String
    let role: String
    let acs: Int
    let kd: Double
    let adr: Int
    let kills: Int
    let deaths: Int
    let assists: Int
    let plus_minus: String
    let kast: String
    let first_kills: Int
    let first_deaths: Int
}

struct GameDetailView: View {
    // 櫨 NEW: Pass the clicked match into this view
    let match: MatchInfo
    
    @State private var selectedTab = "Game"
    @State private var stats: MatchStatsResponse?
    @State private var isLoadingStats = false
    @State private var statsError: String?
    @State private var selectedGameId = "all"
    
    // 櫨 UPDATED: Make tabs dynamic based on the actual team names
    var tabs: [String] {
        ["Game", match.team1, match.team2]
    }
    
    private var availableMaps: [MapStatInfo] {
        stats?.match_info.maps ?? []
    }

    private var team1Color: Color {
        Color.forTeam(match.team1)
    }

    private var team2Color: Color {
        Color.forTeam(match.team2)
    }

    private var selectedAccentColor: Color {
        if selectedTab == match.team1 {
            return team1Color
        }

        if selectedTab == match.team2 {
            return team2Color
        }

        return mixedAccentColor
    }

    private var mixedAccentColor: Color {
        Color(red: 0.48, green: 0.36, blue: 1.0)
    }

    private func mapFilterLabel(_ map: MapStatInfo) -> String {
        if map.game_id == "all" || map.map_number == 0 {
            return "all"
        }

        return "Map \(map.map_number)"
    }
    
    var body: some View {
        ZStack {
            detailScreenBackground
            
            VStack(spacing: 0) {
                MatchDetailHeaderView(match: match)
                    .padding(.horizontal)
                    .padding(.top, 18)
                    .padding(.bottom, 12)
                
                // Custom Top Tab Bar
                HStack(spacing: 0) {
                    ForEach(tabs, id: \.self) { tab in
                        let tabColor = accentColor(for: tab)

                        VStack(spacing: 8) {
                            // 櫨 Ensure long team names fit nicely in the tab bar
                            Text(tab)
                                .font(.system(size: 16, weight: .bold))
                                .foregroundColor(selectedTab == tab ? .white : .white.opacity(0.48))
                                .lineLimit(1)
                                .minimumScaleFactor(0.7)
                                .padding(.horizontal, 4)
                            
                            Rectangle()
                                .fill(selectedTab == tab ? tabColor : Color.clear)
                                .frame(height: 3)
                                .shadow(color: selectedTab == tab ? tabColor.opacity(0.55) : .clear, radius: 4)
                        }
                        .frame(maxWidth: .infinity)
                        .contentShape(Rectangle())
                        .onTapGesture {
                            withAnimation { selectedTab = tab }
                        }
                    }
                }
                .padding(.top, 12)
                .background(topGlassBar(opacity: 0.12))
                
                Divider().background(Color.white.opacity(0.12))
                
                // Main Content Area
                ScrollView {
                    // 櫨 UPDATED: Routing tabs based on the dynamic team names
                    if selectedTab == match.team1 {
                        rosterView(players: stats?.team1_roster ?? [])
                        
                    } else if selectedTab == match.team2 {
                        rosterView(players: stats?.team2_roster ?? [])
                        
                    } else {
                        overviewView
                    }
                }
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .top)
        }
        .navigationBarTitleDisplayMode(.inline)
        .task {
            await fetchStats()
        }
    }

    private var detailScreenBackground: some View {
        ZStack {
            Color.black

            LinearGradient(
                colors: [
                    team1Color.opacity(0.58),
                    mixedAccentColor.opacity(0.22),
                    team2Color.opacity(0.58)
                ],
                startPoint: .topLeading,
                endPoint: .bottomTrailing
            )

            LinearGradient(
                colors: [
                    Color.black.opacity(0.12),
                    Color.black.opacity(0.36),
                    Color.black.opacity(0.62)
                ],
                startPoint: .top,
                endPoint: .bottom
            )
        }
        .ignoresSafeArea()
    }

    private func accentColor(for tab: String) -> Color {
        if tab == match.team1 {
            return team1Color
        }

        if tab == match.team2 {
            return team2Color
        }

        return mixedAccentColor
    }

    private func topGlassBar(opacity: Double) -> some View {
        ZStack {
            Rectangle()
                .fill(.ultraThinMaterial)

            Color.black.opacity(0.22)

            LinearGradient(
                colors: [
                    team1Color.opacity(opacity),
                    Color.white.opacity(0.02),
                    team2Color.opacity(opacity)
                ],
                startPoint: .leading,
                endPoint: .trailing
            )
        }
    }

    private func glassSurface(cornerRadius: CGFloat = 10, opacity: Double = 0.1) -> some View {
        ZStack {
            RoundedRectangle(cornerRadius: cornerRadius, style: .continuous)
                .fill(.ultraThinMaterial)

            RoundedRectangle(cornerRadius: cornerRadius, style: .continuous)
                .fill(Color.black.opacity(0.28))

            RoundedRectangle(cornerRadius: cornerRadius, style: .continuous)
                .fill(
                    LinearGradient(
                        colors: [
                            team1Color.opacity(opacity),
                            Color.white.opacity(0.03),
                            team2Color.opacity(opacity)
                        ],
                        startPoint: .leading,
                        endPoint: .trailing
                    )
                )
        }
    }

    private func sectionSurface(opacity: Double = 0.1) -> some View {
        glassSurface(cornerRadius: 10, opacity: opacity)
    }

    private func mapChipSurface(isSelected: Bool) -> some View {
        RoundedRectangle(cornerRadius: 6, style: .continuous)
            .fill(isSelected ? mixedAccentColor.opacity(0.72) : Color.black.opacity(0.18))
            .background(
                RoundedRectangle(cornerRadius: 6, style: .continuous)
                    .fill(.ultraThinMaterial)
            )
    }

    private var overviewView: some View {
        VStack(spacing: 16) {
            if isLoadingStats {
                ProgressView()
                    .tint(selectedAccentColor)
                    .padding(.top, 40)
            } else if let statsError {
                Text(statsError)
                    .font(.subheadline)
                    .foregroundColor(.gray)
                    .multilineTextAlignment(.center)
                    .padding(.horizontal)
                    .padding(.top, 40)
            } else if let stats, !availableMaps.isEmpty || !stats.match_info.map_vetoes.isEmpty {
                VStack(alignment: .leading, spacing: 18) {
                    if !availableMaps.isEmpty {
                        VStack(alignment: .leading, spacing: 10) {
                            Text("Maps")
                                .font(.headline)
                                .foregroundColor(.white)

                            ForEach(availableMaps) { map in
                                Button {
                                    selectMap(map)
                                    selectedTab = match.team1
                                } label: {
                                    mapRow(map)
                                }
                                .buttonStyle(.plain)
                            }
                        }
                        .padding(12)
                        .background(sectionSurface())
                        .overlay(
                            RoundedRectangle(cornerRadius: 10, style: .continuous)
                                .stroke(Color.white.opacity(0.14), lineWidth: 1)
                        )
                    }

                    if !stats.match_info.map_vetoes.isEmpty {
                        VStack(alignment: .leading, spacing: 10) {
                            Text("Map Vetoes")
                                .font(.headline)
                                .foregroundColor(.white)

                            ForEach(stats.match_info.map_vetoes, id: \.self) { veto in
                                Text(veto)
                                    .font(.system(size: 13))
                                    .foregroundColor(.gray)
                                    .frame(maxWidth: .infinity, alignment: .leading)
                            }
                        }
                        .padding(12)
                        .background(sectionSurface(opacity: 0.08))
                        .overlay(
                            RoundedRectangle(cornerRadius: 10, style: .continuous)
                                .stroke(Color.white.opacity(0.12), lineWidth: 1)
                        )
                    }
                }
                .padding()
            } else {
                Text("No map vetoes available yet.")
                    .font(.subheadline)
                    .foregroundColor(.gray)
                    .padding(.top, 40)
            }
        }
    }

    private func mapRow(_ map: MapStatInfo) -> some View {
        let isSelected = map.game_id == selectedGameId

        return HStack(spacing: 12) {
            Text(map.map_number == 0 ? "All" : "\(map.map_number)")
                .font(.system(size: 13, weight: .bold))
                .foregroundColor(isSelected ? .white : .white.opacity(0.54))
                .frame(width: 34, height: 28)
                .background(
                    mapChipSurface(isSelected: isSelected)
                )

            VStack(alignment: .leading, spacing: 2) {
                Text(map.map_name)
                    .font(.system(size: 15, weight: .semibold))
                    .foregroundColor(.white)

                if !map.team1_round_score.isEmpty || !map.team2_round_score.isEmpty {
                    Text("\(map.team1_round_score)-\(map.team2_round_score)")
                        .font(.system(size: 12, weight: .medium))
                        .foregroundColor(.white.opacity(0.54))
                }
            }

            Spacer()
        }
        .padding(10)
        .background(sectionSurface(opacity: isSelected ? 0.16 : 0.07))
        .overlay(
            RoundedRectangle(cornerRadius: 10, style: .continuous)
                .stroke(isSelected ? mixedAccentColor.opacity(0.78) : Color.white.opacity(0.12), lineWidth: 1)
        )
    }

    @ViewBuilder
    private func rosterView(players: [PlayerStatInfo]) -> some View {
        VStack(spacing: 12) {
            if availableMaps.count > 1 {
                mapFilterStrip
                    .padding(.top, 12)
            }

            if isLoadingStats {
                ProgressView()
                    .tint(selectedAccentColor)
                    .padding(.top, 28)
            } else if let statsError {
                Text(statsError)
                    .font(.subheadline)
                    .foregroundColor(.gray)
                    .multilineTextAlignment(.center)
                    .padding(.horizontal)
                    .padding(.top, 28)
            } else if players.isEmpty {
                Text("No player stats available yet.")
                    .font(.subheadline)
                    .foregroundColor(.gray)
                    .padding(.top, 28)
            } else {
                ForEach(players) { player in
                    PlayerStatRowView(
                        playerName: player.name,
                        role: player.role.isEmpty ? player.team : player.role,
                        kills: player.kills,
                        deaths: player.deaths,
                        assists: player.assists,
                        plusMinus: player.plus_minus,
                        kast: player.kast,
                        adr: player.adr,
                        acs: player.acs,
                        firstKills: player.first_kills,
                        firstDeaths: player.first_deaths,
                        accentColor: selectedTab == match.team2 ? team2Color : team1Color,
                        opposingColor: selectedTab == match.team2 ? team1Color : team2Color
                    )
                }
            }
        }
    }

    private var mapFilterStrip: some View {
        ScrollView(.horizontal, showsIndicators: false) {
            HStack(spacing: 8) {
                ForEach(availableMaps) { map in
                    let isSelected = map.game_id == selectedGameId

                    Button {
                        selectMap(map)
                    } label: {
                        Text(mapFilterLabel(map))
                            .font(.system(size: 13, weight: .bold))
                            .foregroundColor(isSelected ? .white : .white.opacity(0.54))
                            .lineLimit(1)
                            .minimumScaleFactor(0.8)
                            .padding(.horizontal, 14)
                            .frame(height: 32)
                            .background(
                                RoundedRectangle(cornerRadius: 7)
                                    .fill(isSelected ? selectedAccentColor.opacity(0.72) : Color.black.opacity(0.16))
                                    .background(
                                        RoundedRectangle(cornerRadius: 7)
                                            .fill(.ultraThinMaterial)
                                    )
                            )
                            .overlay(
                                RoundedRectangle(cornerRadius: 7)
                                    .stroke(isSelected ? selectedAccentColor : Color.white.opacity(0.14), lineWidth: 1)
                            )
                    }
                    .buttonStyle(.plain)
                }
            }
            .padding(.horizontal)
        }
    }

    private func selectMap(_ map: MapStatInfo) {
        guard selectedGameId != map.game_id else { return }

        selectedGameId = map.game_id
        Task { await fetchStats(force: true) }
    }

    private func fetchStats(force: Bool = false) async {
        guard !isLoadingStats || force else { return }

        var components = URLComponents(string: "http://127.0.0.1:8000/api/matches/\(match.id)/stats")
        components?.queryItems = [
            URLQueryItem(name: "game_id", value: selectedGameId)
        ]

        guard let url = components?.url else { return }

        await MainActor.run {
            isLoadingStats = true
            statsError = nil
        }

        do {
            let (data, _) = try await URLSession.shared.data(from: url)
            let decodedStats = try JSONDecoder().decode(MatchStatsResponse.self, from: data)

            await MainActor.run {
                stats = decodedStats
                selectedGameId = decodedStats.match_info.selected_game_id
                isLoadingStats = false
            }
        } catch {
            await MainActor.run {
                statsError = "Could not load player stats."
                isLoadingStats = false
            }
        }
    }

}

private struct MatchDetailHeaderView: View {
    let match: MatchInfo

    private var team1Color: Color {
        Color.forTeam(match.team1)
    }

    private var team2Color: Color {
        Color.forTeam(match.team2)
    }

    private var isUpcoming: Bool {
        !match.is_live && !match.is_finished
    }

    private var team1Score: String {
        cleanScore(match.team1_score)
    }

    private var team2Score: String {
        cleanScore(match.team2_score)
    }

    private var hasSeriesScore: Bool {
        !team1Score.isEmpty && !team2Score.isEmpty
    }

    private var centerText: String {
        if hasSeriesScore {
            return "\(team1Score) - \(team2Score)"
        }

        return isUpcoming ? "VS" : "-"
    }

    private var statusText: String? {
        if match.is_live {
            return "LIVE"
        }

        if isUpcoming {
            return match.time
        }

        return nil
    }

    var body: some View {
        HStack(alignment: .center, spacing: 14) {
            TeamHeaderNameView(name: match.team1, color: team1Color, isLeading: true)

            VStack(spacing: 6) {
                if match.is_live {
                    Circle()
                        .fill(Color.red)
                        .frame(width: 8, height: 8)
                }

                Text(centerText)
                    .font(.system(size: hasSeriesScore ? 34 : 24, weight: .heavy))
                    .foregroundColor(.white)
                    .lineLimit(1)
                    .minimumScaleFactor(0.75)
                    .monospacedDigit()

                if let statusText {
                    Text(statusText)
                        .font(.system(size: 13, weight: .bold))
                        .foregroundColor(match.is_live ? .red : .gray)
                        .lineLimit(1)
                }
            }
            .frame(width: 86)

            TeamHeaderNameView(name: match.team2, color: team2Color, isLeading: false)
        }
        .frame(maxWidth: .infinity)
        .padding(12)
        .background(
            RoundedRectangle(cornerRadius: 18, style: .continuous)
                .fill(.ultraThinMaterial)
                .overlay(
                    RoundedRectangle(cornerRadius: 18, style: .continuous)
                        .fill(Color.black.opacity(0.24))
                )
                .overlay(
                    RoundedRectangle(cornerRadius: 18, style: .continuous)
                        .fill(
                            LinearGradient(
                                colors: [
                                    team1Color.opacity(0.12),
                                    Color.white.opacity(0.04),
                                    team2Color.opacity(0.12)
                                ],
                                startPoint: .leading,
                                endPoint: .trailing
                            )
                        )
                )
        )
        .overlay(
            RoundedRectangle(cornerRadius: 18, style: .continuous)
                .stroke(Color.white.opacity(0.16), lineWidth: 1)
        )
    }

    private func cleanScore(_ score: String?) -> String {
        score?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
    }
}

private struct TeamHeaderNameView: View {
    let name: String
    let color: Color
    let isLeading: Bool

    private var horizontalAlignment: HorizontalAlignment {
        isLeading ? .leading : .trailing
    }

    private var frameAlignment: Alignment {
        isLeading ? .leading : .trailing
    }

    var body: some View {
        VStack(alignment: horizontalAlignment, spacing: 8) {
            Circle()
                .fill(color)
                .frame(width: 18, height: 18)

            Text(name)
                .font(.system(size: 24, weight: .bold))
                .foregroundColor(.white)
                .lineLimit(2)
                .minimumScaleFactor(0.72)
                .multilineTextAlignment(isLeading ? .leading : .trailing)
        }
        .frame(maxWidth: .infinity, alignment: frameAlignment)
    }
}
