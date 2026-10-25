import SwiftUI

/// Stable accent color for a team name, shared by timeline and detail views.
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
