import SwiftUI

struct GameDetailView: View {
    // 櫨 NEW: Pass the clicked match into this view
    let match: MatchInfo
    
    @State private var selectedTab = "Game"
    
    // 櫨 UPDATED: Make tabs dynamic based on the actual team names
    var tabs: [String] {
        ["Game", match.team1, match.team2]
    }
    
    // 櫨 NEW: Reusing the same helper from GameCardView to handle nil round scores safely
    private func displayScore(_ score: String?) -> String {
        guard let score = score else { return match.is_live ? "0" : "" }
        let cleanScore = score.trimmingCharacters(in: .whitespacesAndNewlines)
        return cleanScore.isEmpty ? (match.is_live ? "0" : "") : cleanScore
    }
    
    var body: some View {
        ZStack {
            Color.black.ignoresSafeArea()
            
            VStack(spacing: 0) {
                // Header Area (Mini scoreboard)
                HStack {
                    // 櫨 UPDATED: Dynamic Team 1 using your TeamView
                    TeamView(name: match.team1,
                             primaryScore: match.is_live ? displayScore(match.team1_round_score) : displayScore(match.team1_score),
                             seriesScore: match.is_live ? displayScore(match.team1_score) : nil,
                             color: Color.forTeam(match.team1))
                    
                    Spacer()
                    
                    // 櫨 UPDATED: Dynamic Time / Status
                    VStack {
                        if match.is_live {
                            Circle().fill(Color.red).frame(width: 8, height: 8)
                            Text("LIVE")
                                .font(.system(size: 14, weight: .bold))
                                .foregroundColor(.red)
                        } else {
                            Text(match.time)
                                .font(.system(size: 14, weight: .bold))
                                .foregroundColor(.white)
                        }
                    }
                    
                    Spacer()
                    
                    // 櫨 UPDATED: Dynamic Team 2 using your TeamView
                    TeamView(name: match.team2,
                             primaryScore: match.is_live ? displayScore(match.team2_round_score) : displayScore(match.team2_score),
                             seriesScore: match.is_live ? displayScore(match.team2_score) : nil,
                             color: Color.forTeam(match.team2))
                }
                .padding()
                .background(Color(white: 0.08))
                
                // Custom Top Tab Bar
                HStack(spacing: 0) {
                    ForEach(tabs, id: \.self) { tab in
                        VStack(spacing: 8) {
                            // 櫨 Ensure long team names fit nicely in the tab bar
                            Text(tab)
                                .font(.system(size: 16, weight: .bold))
                                .foregroundColor(selectedTab == tab ? .white : .gray)
                                .lineLimit(1)
                                .minimumScaleFactor(0.7)
                                .padding(.horizontal, 4)
                            
                            Rectangle()
                                .fill(selectedTab == tab ? Color(red: 0.4, green: 0.2, blue: 0.9) : Color.clear)
                                .frame(height: 3)
                        }
                        .frame(maxWidth: .infinity)
                        .contentShape(Rectangle())
                        .onTapGesture {
                            withAnimation { selectedTab = tab }
                        }
                    }
                }
                .padding(.top, 12)
                .background(Color(white: 0.08))
                
                Divider().background(Color(white: 0.2))
                
                // Main Content Area
                ScrollView {
                    // 櫨 UPDATED: Routing tabs based on the dynamic team names
                    if selectedTab == match.team1 {
                        VStack(spacing: 12) {
                            // Note: These are still your mock stats. The next step is hitting your /api/matches/{id}/stats endpoint!
                            PlayerStatRowView(playerName: "MockPlayer1", role: "Duelist", stats: "265 ACS, 1.3 K/D, 170 ADR", rank30Day: "1st", rankSeason: "3rd")
                            PlayerStatRowView(playerName: "MockPlayer2", role: "Flex", stats: "240 ACS, 1.1 K/D, 155 ADR", rank30Day: "5th", rankSeason: "8th")
                        }
                        .padding(.top)
                        
                    } else if selectedTab == match.team2 {
                        VStack(spacing: 12) {
                            PlayerStatRowView(playerName: "MockPlayer3", role: "Duelist", stats: "258 ACS, 1.25 K/D, 165 ADR", rank30Day: "2nd", rankSeason: "4th")
                            PlayerStatRowView(playerName: "MockPlayer4", role: "Flex", stats: "245 ACS, 1.15 K/D, 158 ADR", rank30Day: "4th", rankSeason: "6th")
                        }
                        .padding(.top)
                        
                    } else {
                        VStack(spacing: 16) {
                            Text("Map Vetoes & Match Overview")
                                .font(.headline)
                                .foregroundColor(.white)
                            Text("Data will appear here once you connect the stats endpoint.")
                                .font(.subheadline)
                                .foregroundColor(.gray)
                                .multilineTextAlignment(.center)
                                .padding(.horizontal)
                        }
                        .padding(.top, 40)
                    }
                }
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .top)
        }
        .navigationBarTitleDisplayMode(.inline)
    }
}
