import SwiftUI

struct DateScrollerView: View {
    // This binding connects the selected date back to your GamesListView
    @Binding var selectedDate: String
    
    // Dynamically generates a 7-day window around today
    var dynamicDates: [(dateStr: String, dayStr: String)] {
        var dates: [(String, String)] = []
        let calendar = Calendar.current
        let today = Date()
        
        // Generate 3 days ago up to 3 days in the future
        for i in -3...3 {
            if let date = calendar.date(byAdding: .day, value: i, to: today) {
                let dateFormatter = DateFormatter()
                
                // Formats to "Mar 22"
                dateFormatter.dateFormat = "MMM d"
                let dateString = dateFormatter.string(from: date)
                
                // Formats to "Sun"
                dateFormatter.dateFormat = "E"
                let dayString = dateFormatter.string(from: date)
                
                dates.append((dateString, dayString))
            }
        }
        return dates
    }
    
    var body: some View {
        ScrollView(.horizontal, showsIndicators: false) {
            // Use ScrollViewReader if you want it to auto-scroll to the center later!
            HStack(spacing: 24) {
                ForEach(dynamicDates, id: \.dateStr) { date in
                    let isSelected = selectedDate == date.dateStr
                    
                    VStack(spacing: 4) {
                        Text(date.dateStr) // e.g., "Mar 22"
                            .font(.system(size: 12))
                            .foregroundColor(isSelected ? .white : .gray)
                        Text(date.dayStr) // e.g., "Sun"
                            .font(.system(size: 16, weight: .bold))
                            .foregroundColor(isSelected ? Color(red: 0.4, green: 0.2, blue: 0.9) : .gray)
                    }
                    // The magic tap that changes the selected date
                    .onTapGesture {
                        withAnimation(.easeInOut(duration: 0.2)) {
                            selectedDate = date.dateStr
                        }
                    }
                }
            }
            .padding(.horizontal)
        }
        .padding(.vertical, 10)
    }
}

// Preview to see it right in Xcode!
struct DateScrollerView_Previews: PreviewProvider {
    static var previews: some View {
        ZStack {
            Color.black.ignoresSafeArea()
            DateScrollerView(selectedDate: .constant("Mar 22"))
        }
    }
}
