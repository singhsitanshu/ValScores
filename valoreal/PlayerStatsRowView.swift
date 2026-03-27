import SwiftUI

struct PlayerStatRowView: View {
    var playerName: String
    var role: String
    var stats: String
    var rank30Day: String
    var rankSeason: String
    
    var body: some View {
        HStack {
            // Left Side: Player Name & Role
            VStack(alignment: .leading, spacing: 4) {
                Text(playerName)
                    .font(.system(size: 16, weight: .bold))
                    .foregroundColor(.white)
                
                Text(role)
                    .font(.system(size: 12, weight: .medium))
                    .foregroundColor(.gray)
            }
            
            Spacer()
            
            // Right Side: Stats & Ranks
            VStack(alignment: .trailing, spacing: 4) {
                Text(stats)
                    .font(.system(size: 14, weight: .semibold))
                    .foregroundColor(.white)
                
                HStack(spacing: 8) {
                    Text("30D: \(rank30Day)")
                        .font(.system(size: 10))
                        .foregroundColor(.gray)
                    
                    Text("Season: \(rankSeason)")
                        .font(.system(size: 10))
                        .foregroundColor(.gray)
                }
            }
        }
        .padding()
        .background(Color(white: 0.12)) // Slightly lighter than the background to pop
        .cornerRadius(8)
        .padding(.horizontal)
    }
}
