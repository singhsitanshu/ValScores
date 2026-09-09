import SwiftUI

struct DateScrollerView: View {
    @Binding var selectedDate: Date
    let referenceDate: Date

    private var calendar: Calendar {
        .autoupdatingCurrent
    }
    
    // Dynamically generates a 7-day window around today
    var dynamicDates: [Date] {
        var dates: [Date] = []
        let today = calendar.startOfDay(for: referenceDate)
        
        // Generate 3 days ago up to 3 days in the future
        for i in -3...3 {
            if let date = calendar.date(byAdding: .day, value: i, to: today) {
                dates.append(date)
            }
        }
        return dates
    }
    
    var body: some View {
        ScrollView(.horizontal, showsIndicators: false) {
            // Use ScrollViewReader if you want it to auto-scroll to the center later!
            HStack(spacing: 24) {
                ForEach(dynamicDates, id: \.self) { date in
                    let isSelected = calendar.isDate(date, inSameDayAs: selectedDate)
                    
                    VStack(spacing: 4) {
                        Text(date.formatted(.dateTime.month(.abbreviated).day()))
                            .font(.system(size: 12))
                            .foregroundColor(isSelected ? .white : .gray)
                        Text(date.formatted(.dateTime.weekday(.abbreviated)))
                            .font(.system(size: 16, weight: .bold))
                            .foregroundColor(isSelected ? Color(red: 0.4, green: 0.2, blue: 0.9) : .gray)
                    }
                    // The magic tap that changes the selected date
                    .onTapGesture {
                        withAnimation(.easeInOut(duration: 0.2)) {
                            selectedDate = date
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
            DateScrollerView(
                selectedDate: .constant(Date()),
                referenceDate: Date()
            )
        }
    }
}
