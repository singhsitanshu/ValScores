import SwiftUI

struct PlayerStatRowView: View {
    var playerName: String
    var subtitle: String
    var kills: Int?
    var deaths: Int?
    var assists: Int?
    var kd: Double?
    var plusMinus: Int?
    var kast: Double?
    var adr: Int?
    var acs: Int?
    var firstKills: Int?
    var firstDeaths: Int?
    var accentColor: Color = Color(red: 0.48, green: 0.36, blue: 1.0)
    var opposingColor: Color = Color.white.opacity(0.18)

    private var statColumns: [(label: String, value: String)] {
        [
            ("KDA", "\(PlayerStatFormat.count(kills))/\(PlayerStatFormat.count(deaths))/\(PlayerStatFormat.count(assists))"),
            ("KD", PlayerStatFormat.ratio(kd)),
            ("+/-", PlayerStatFormat.signed(plusMinus)),
            ("KAST", PlayerStatFormat.percent(kast)),
            ("ADR", PlayerStatFormat.count(adr)),
            ("ACS", PlayerStatFormat.count(acs)),
            ("FK", PlayerStatFormat.count(firstKills)),
            ("FD", PlayerStatFormat.count(firstDeaths))
        ]
    }
    
    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            VStack(alignment: .leading, spacing: 4) {
                Text(playerName)
                    .font(.system(size: 16, weight: .bold))
                    .foregroundColor(.white)
                
                Text(subtitle)
                    .font(.system(size: 12, weight: .medium))
                    .foregroundColor(.white.opacity(0.54))
            }

            LazyVGrid(
                columns: Array(repeating: GridItem(.flexible(), spacing: 8), count: 4),
                alignment: .leading,
                spacing: 8
            ) {
                ForEach(statColumns, id: \.label) { stat in
                    VStack(alignment: .leading, spacing: 2) {
                        Text(stat.label)
                            .font(.system(size: 10, weight: .semibold))
                            .foregroundColor(.white.opacity(0.5))

                        Text(stat.value)
                            .font(.system(size: 13, weight: .bold))
                            .foregroundColor(.white)
                            .lineLimit(1)
                            .minimumScaleFactor(0.75)
                    }
                }
            }
        }
        .padding()
        .background(
            RoundedRectangle(cornerRadius: 10, style: .continuous)
                .fill(.ultraThinMaterial)
                .overlay(
                    RoundedRectangle(cornerRadius: 10, style: .continuous)
                        .fill(Color.black.opacity(0.28))
                )
                .overlay(
                    RoundedRectangle(cornerRadius: 10, style: .continuous)
                        .fill(
                            LinearGradient(
                                colors: [
                                    accentColor.opacity(0.14),
                                    Color.white.opacity(0.03),
                                    opposingColor.opacity(0.08)
                                ],
                                startPoint: .leading,
                                endPoint: .trailing
                            )
                        )
                )
        )
        .overlay(
            RoundedRectangle(cornerRadius: 10, style: .continuous)
                .stroke(accentColor.opacity(0.28), lineWidth: 1)
        )
        .shadow(color: .black.opacity(0.18), radius: 8, y: 3)
        .padding(.horizontal)
    }
}

/// Text for optional player statistics. Unavailable values render as a dash so
/// they are never mistaken for a recorded zero.
enum PlayerStatFormat {
    static let unavailable = "–"

    static func count(_ value: Int?) -> String {
        value.map(String.init) ?? unavailable
    }

    static func signed(_ value: Int?) -> String {
        guard let value else { return unavailable }
        return value > 0 ? "+\(value)" : String(value)
    }

    static func ratio(_ value: Double?) -> String {
        guard let value else { return unavailable }
        return String(format: "%.2f", value)
    }

    static func percent(_ value: Double?) -> String {
        guard let value else { return unavailable }
        return value.rounded() == value ? "\(Int(value))%" : String(format: "%.1f%%", value)
    }
}
