import SwiftUI

struct GameCardView: View {
    let match: MatchInfo
    
    // 櫨 UPDATED: Now accepts an optional string (since round scores might be nil)
    private func displayScore(_ score: String?) -> String {
        guard let score = score else { return match.is_live ? "0" : "" }
        let cleanScore = score.trimmingCharacters(in: .whitespacesAndNewlines)
        
        if cleanScore.isEmpty {
            return match.is_live ? "0" : ""
        }
        
        return cleanScore
    }
    
    var body: some View {
        HStack {
            // Left Side: Teams
            VStack(alignment: .leading, spacing: 12) {
                
                // 櫨 UPDATED: Pass round score as primary and series score as secondary when LIVE
                TeamView(name: match.team1,
                         primaryScore: match.is_live ? displayScore(match.team1_round_score) : displayScore(match.team1_score),
                         seriesScore: match.is_live ? displayScore(match.team1_score) : nil,
                         color: Color.forTeam(match.team1))
                
                TeamView(name: match.team2,
                         primaryScore: match.is_live ? displayScore(match.team2_round_score) : displayScore(match.team2_score),
                         seriesScore: match.is_live ? displayScore(match.team2_score) : nil,
                         color: Color.forTeam(match.team2))
            }
            
            Spacer()
            
            // Right Side: Details
            VStack(alignment: .trailing, spacing: 4) {
                HStack(spacing: 4) {
                    if match.is_live {
                        Circle()
                            .fill(Color.red)
                            .frame(width: 6, height: 6)
                    }
                    
                    Text(match.time)
                        .font(.system(size: 16, weight: .bold))
                        .foregroundColor(match.is_live ? .red : .white)
                }
                
                HStack(spacing: 2) {
                    Image(systemName: "bubble.right.fill")
                        .font(.system(size: 10))
                }
                .foregroundColor(.gray)
                .padding(.top, 4)
            }
        }
        .padding(12)
        .frame(maxWidth: .infinity)
        .frame(height: 110)
        .background(Color(red: 0.05, green: 0.05, blue: 0.05))
        .overlay(
            RoundedRectangle(cornerRadius: 8)
                .stroke(match.is_live ? Color.red.opacity(0.5) : Color(white: 0.15), lineWidth: 1)
        )
        .cornerRadius(8)
    }
}

// MARK: - Subviews & Extensions

struct TeamView: View {
    var name: String
    var primaryScore: String
    var seriesScore: String? // 櫨 NEW: Optional series score parameter
    var color: Color
    
    var body: some View {
        HStack(spacing: 8) {
            Circle()
                .fill(color)
                .frame(width: 24, height: 24)
            
            VStack(alignment: .leading, spacing: 0) {
                
                // 櫨 NEW: Horizontal stack to hold Primary Score (Big) and Series Score (Small)
                HStack(alignment: .lastTextBaseline, spacing: 6) {
                    Text(primaryScore)
                        .font(.system(size: 16, weight: .semibold))
                        .foregroundColor(.white)
                    
                    // Only displays if there is a valid series score passed in (i.e. if live)
                    if let seriesScore = seriesScore, !seriesScore.isEmpty {
                        Text("Series: \(seriesScore)")
                            .font(.system(size: 10, weight: .medium))
                            .foregroundColor(.gray)
                            .lineLimit(1) // <-- Forces text to stay on one line
                            .fixedSize(horizontal: true, vertical: false) // <-- Prevents wrapping
                    }
                }
                
                Text(name)
                    .font(.system(size: 12))
                    .foregroundColor(.gray)
                    .lineLimit(1)
                    .minimumScaleFactor(0.8)
            }
        }
    }
}

extension Color {
    /// Generates a consistent, attractive color based on a team's name.
    static func forTeam(_ name: String) -> Color {
        var hash = 0
        for char in name {
            if let scalar = String(char).unicodeScalars.first {
                hash = scalar.value.hashValue &+ hash
            }
        }
        
        let palette: [Color] = [
            .red, .blue, .green, .orange, .purple,
            .pink, .cyan, .mint, .indigo, .teal, .yellow
        ]
        
        let index = abs(hash) % palette.count
        return palette[index]
    }
}
