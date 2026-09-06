import SwiftUI

struct GameCardView: View {
    let match: MatchInfo

    private func displayScore(_ score: String?) -> String {
        guard let score = score else { return match.is_live ? "0" : "" }
        let cleanScore = score.trimmingCharacters(in: .whitespacesAndNewlines)
        return cleanScore.isEmpty ? (match.is_live ? "0" : "") : cleanScore
    }

    private var team1PrimaryScore: String {
        match.is_live ? displayScore(match.team1_round_score) : displayScore(match.team1_score)
    }

    private var team2PrimaryScore: String {
        match.is_live ? displayScore(match.team2_round_score) : displayScore(match.team2_score)
    }

    private var team1SeriesScore: String? {
        match.is_live ? displayScore(match.team1_score) : nil
    }

    private var team2SeriesScore: String? {
        match.is_live ? displayScore(match.team2_score) : nil
    }

    private var statusLabel: String {
        if match.is_live {
            return match.status.isEmpty ? "LIVE" : match.status.uppercased()
        }

        if match.is_finished {
            return "FINAL"
        }

        return match.displayTime
    }

    private var substatusLabel: String? {
        if match.is_live {
            return match.displayTime
        }

        if match.is_finished {
            return match.displayTime
        }

        return "Upcoming"
    }

    private var statusColor: Color {
        if match.is_live {
            return Color(red: 1.0, green: 0.23, blue: 0.24)
        }

        if match.is_finished {
            return Color(white: 0.62)
        }

        return .white
    }

    private var strokeColor: Color {
        if match.is_live {
            return Color(red: 1.0, green: 0.23, blue: 0.24).opacity(0.8)
        }

        if match.is_finished {
            return Color.white.opacity(0.1)
        }

        return Color.white.opacity(0.14)
    }

    var body: some View {
        HStack(spacing: 10) {
            ScoreTeamView(
                name: match.team1,
                score: team1PrimaryScore,
                seriesScore: team1SeriesScore,
                color: Color.forTeam(match.team1),
                side: .leading,
                showScore: match.is_live || match.is_finished
            )

            Spacer(minLength: 4)

            VStack(spacing: 5) {
                if match.is_live {
                    Circle()
                        .fill(statusColor)
                        .frame(width: 7, height: 7)
                        .shadow(color: statusColor.opacity(0.65), radius: 5)
                }

                Text(statusLabel)
                    .font(.system(size: 13, weight: .bold))
                    .foregroundColor(statusColor)
                    .lineLimit(1)
                    .minimumScaleFactor(0.75)

                if let substatusLabel {
                    Text(substatusLabel)
                        .font(.system(size: 10, weight: .semibold))
                        .foregroundColor(.white.opacity(0.48))
                        .lineLimit(1)
                        .minimumScaleFactor(0.75)
                }
            }
            .frame(width: 76)

            Spacer(minLength: 4)

            ScoreTeamView(
                name: match.team2,
                score: team2PrimaryScore,
                seriesScore: team2SeriesScore,
                color: Color.forTeam(match.team2),
                side: .trailing,
                showScore: match.is_live || match.is_finished
            )
        }
        .padding(.horizontal, 12)
        .padding(.vertical, 10)
        .frame(maxWidth: .infinity)
        .frame(height: 78)
        .background(cardBackground)
        .clipShape(RoundedRectangle(cornerRadius: 10, style: .continuous))
        .overlay(
            RoundedRectangle(cornerRadius: 10, style: .continuous)
                .stroke(strokeColor, lineWidth: match.is_live ? 1.4 : 1)
        )
        .shadow(color: .black.opacity(0.22), radius: 10, y: 4)
    }

    private var cardBackground: some View {
        ZStack {
            RoundedRectangle(cornerRadius: 10, style: .continuous)
                .fill(Color(red: 0.08, green: 0.08, blue: 0.08))

            LinearGradient(
                colors: [
                    Color.forTeam(match.team1).opacity(match.is_finished ? 0.18 : 0.32),
                    Color(red: 0.08, green: 0.08, blue: 0.08).opacity(0.94),
                    Color.forTeam(match.team2).opacity(match.is_finished ? 0.18 : 0.32)
                ],
                startPoint: .leading,
                endPoint: .trailing
            )

            if match.is_finished {
                Color.black.opacity(0.2)
            }
        }
    }
}

private struct ScoreTeamView: View {
    enum Side {
        case leading
        case trailing
    }

    let name: String
    let score: String
    let seriesScore: String?
    let color: Color
    let side: Side
    let showScore: Bool

    var body: some View {
        HStack(spacing: 9) {
            if side == .leading {
                TeamBadge(name: name, color: color)
                teamName
                scoreGroup
            } else {
                scoreGroup
                teamName
                TeamBadge(name: name, color: color)
            }
        }
        .frame(maxWidth: .infinity, alignment: side == .leading ? .leading : .trailing)
    }

    private var teamName: some View {
        Text(name)
            .font(.system(size: 12, weight: .semibold))
            .foregroundColor(.white.opacity(0.72))
            .lineLimit(2)
            .multilineTextAlignment(side == .leading ? .leading : .trailing)
            .minimumScaleFactor(0.76)
            .frame(maxWidth: 74, alignment: side == .leading ? .leading : .trailing)
    }

    @ViewBuilder
    private var scoreGroup: some View {
        if showScore {
            VStack(spacing: 2) {
                Text(score.isEmpty ? "-" : score)
                    .font(.system(size: 28, weight: .black, design: .rounded))
                    .foregroundColor(.white)
                    .monospacedDigit()
                    .lineLimit(1)
                    .minimumScaleFactor(0.65)

                if let seriesScore, !seriesScore.isEmpty {
                    Text(seriesScore)
                        .font(.system(size: 10, weight: .bold))
                        .foregroundColor(.white.opacity(0.68))
                        .monospacedDigit()
                        .padding(.horizontal, 6)
                        .padding(.vertical, 2)
                        .background(
                            Capsule()
                                .fill(Color.white.opacity(0.1))
                        )
                }
            }
            .frame(minWidth: 34)
        } else {
            Text("vs")
                .font(.system(size: 12, weight: .bold))
                .foregroundColor(.white.opacity(0.48))
                .frame(minWidth: 34)
        }
    }
}

private struct TeamBadge: View {
    let name: String
    let color: Color

    private var initials: String {
        let words = name.split(separator: " ")
        let letters = words.prefix(2).compactMap { $0.first }
        let fallback = name.first.map(String.init) ?? "?"
        return letters.isEmpty ? fallback.uppercased() : String(letters).uppercased()
    }

    var body: some View {
        ZStack {
            Circle()
                .fill(color.opacity(0.28))

            Circle()
                .stroke(color.opacity(0.85), lineWidth: 1)

            Text(initials)
                .font(.system(size: 11, weight: .black, design: .rounded))
                .foregroundColor(.white)
                .lineLimit(1)
                .minimumScaleFactor(0.6)
        }
        .frame(width: 32, height: 32)
    }
}

extension Color {
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
