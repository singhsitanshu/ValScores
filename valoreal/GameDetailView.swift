import SwiftUI

private enum MatchDetailTab: CaseIterable, Hashable, Identifiable {
    case game
    case team1
    case team2

    var id: Self { self }
}

private struct MatchDetailRequestKey: Hashable {
    let gameID: String
    let revision: Int
}

struct GameDetailView: View {
    let match: MatchInfo

    @EnvironmentObject private var dataManager: VLRDataManager

    @StateObject private var detailState = MatchDetailState()
    @State private var selectedTab: MatchDetailTab = .game
    @State private var selectedGameId = "all"
    @State private var requestRevision = 0

    private var stats: MatchStatsResponse? {
        detailState.response
    }

    private var availableMaps: [MapStatInfo] {
        stats?.match_info.maps ?? []
    }

    private var team1Name: String {
        stats?.match_info.team1 ?? match.team1
    }

    private var team2Name: String {
        stats?.match_info.team2 ?? match.team2
    }

    private var teamTitles: MatchDetailTeamTitles {
        MatchDetailTeamTitles(team1: team1Name, team2: team2Name)
    }

    private var team1Color: Color {
        Color.forTeam(match.team1)
    }

    private var team2Color: Color {
        Color.forTeam(match.team2)
    }

    private var selectedAccentColor: Color {
        if selectedTab == .team1 {
            return team1Color
        }

        if selectedTab == .team2 {
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
                    ForEach(MatchDetailTab.allCases) { tab in
                        let tabColor = accentColor(for: tab)

                        VStack(spacing: 8) {
                            Text(tabTitle(for: tab))
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
                    if selectedTab == .team1 {
                        rosterView(players: stats?.team1_roster ?? [])

                    } else if selectedTab == .team2 {
                        rosterView(players: stats?.team2_roster ?? [])

                    } else {
                        overviewView
                    }
                }
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .top)
        }
        .navigationBarTitleDisplayMode(.inline)
        .task(id: MatchDetailRequestKey(gameID: selectedGameId, revision: requestRevision)) {
            await fetchStats(for: selectedGameId)
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

    private func accentColor(for tab: MatchDetailTab) -> Color {
        if tab == .team1 {
            return team1Color
        }

        if tab == .team2 {
            return team2Color
        }

        return mixedAccentColor
    }

    private func tabTitle(for tab: MatchDetailTab) -> String {
        switch tab {
        case .game:
            return "Game"
        case .team1:
            return teamTitles.team1
        case .team2:
            return teamTitles.team2
        }
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
            if stats == nil {
                if detailState.phase.isLoading || detailState.phase == .idle {
                    loadingStatsView(topPadding: 40)
                } else if let message = detailState.phase.errorMessage {
                    statsErrorView(message: message, topPadding: 40)
                } else {
                    emptyOverviewView
                }
            } else if let stats {
                if detailState.phase.isLoading {
                    loadingStatsView(label: "Loading selected map…", topPadding: 12)
                } else if let message = detailState.phase.errorMessage {
                    statsErrorView(message: message, topPadding: 12)
                }

                if !availableMaps.isEmpty || !stats.match_info.map_vetoes.isEmpty {
                    VStack(alignment: .leading, spacing: 18) {
                        if !availableMaps.isEmpty {
                            VStack(alignment: .leading, spacing: 10) {
                                Text("Maps")
                                    .font(.headline)
                                    .foregroundColor(.white)

                                ForEach(availableMaps) { map in
                                    Button {
                                        selectMap(map)
                                        selectedTab = .team1
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
                    emptyOverviewView
                }
            }
        }
    }

    private var emptyOverviewView: some View {
        Text("No map or veto information is available yet.")
            .font(.subheadline)
            .foregroundColor(.gray)
            .multilineTextAlignment(.center)
            .padding(.horizontal)
            .padding(.top, 40)
    }

    private func loadingStatsView(
        label: String = "Loading match details…",
        topPadding: CGFloat
    ) -> some View {
        VStack(spacing: 10) {
            ProgressView()
                .tint(selectedAccentColor)
            Text(label)
                .font(.subheadline)
                .foregroundColor(.gray)
        }
        .padding(.top, topPadding)
    }

    private func statsErrorView(message: String, topPadding: CGFloat) -> some View {
        VStack(spacing: 10) {
            Text("Couldn’t load match details")
                .font(.headline)
                .foregroundColor(.white.opacity(0.84))
            Text(message)
                .font(.subheadline)
                .foregroundColor(.gray)
                .multilineTextAlignment(.center)
            Button("Retry") {
                retryStats()
            }
            .buttonStyle(.borderedProminent)
            .tint(selectedAccentColor)
        }
        .padding(.horizontal)
        .padding(.top, topPadding)
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

                if let team1Score = map.team1_round_score,
                   let team2Score = map.team2_round_score {
                    Text("\(team1Score)-\(team2Score)")
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

            if detailState.phase.isLoading {
                loadingStatsView(label: "Loading player stats…", topPadding: 28)
            } else if let message = detailState.phase.errorMessage {
                statsErrorView(message: message, topPadding: 28)
            } else if players.isEmpty {
                Text("No player stats available yet.")
                    .font(.subheadline)
                    .foregroundColor(.gray)
                    .padding(.top, 28)
            } else {
                ForEach(players) { player in
                    PlayerStatRowView(
                        playerName: player.name,
                        subtitle: player.team_abbreviation.isEmpty
                            ? "Team abbreviation unavailable"
                            : player.team_abbreviation,
                        kills: player.kills,
                        deaths: player.deaths,
                        assists: player.assists,
                        kd: player.kd,
                        plusMinus: player.plus_minus,
                        kast: player.kast,
                        adr: player.adr,
                        acs: player.acs,
                        firstKills: player.first_kills,
                        firstDeaths: player.first_deaths,
                        accentColor: selectedTab == .team2 ? team2Color : team1Color,
                        opposingColor: selectedTab == .team2 ? team1Color : team2Color
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

        detailState.invalidatePendingRequest()
        selectedGameId = map.game_id
    }

    private func retryStats() {
        detailState.invalidatePendingRequest()
        requestRevision += 1
    }

    private func fetchStats(for gameID: String) async {
        await detailState.load(gameID: gameID) {
            try await dataManager.matchDetails(
                matchID: match.id,
                gameID: gameID
            )
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
            return match.displayTime
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

    private func cleanScore(_ score: Int?) -> String {
        score.map(String.init) ?? ""
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
