//
//  valorealApp.swift
//  valoreal
//
//  Created by Sitanshu Singh on 3/22/26.
//

import SwiftUI

@main
struct valorealApp: App {
    private var isRunningTests: Bool {
        let environment = ProcessInfo.processInfo.environment
        return environment["VALSCORES_XCTEST"] == "1"
            || environment["XCTestConfigurationFilePath"] != nil
            || environment["XCTestBundlePath"] != nil
            || NSClassFromString("XCTestCase") != nil
    }

    var body: some Scene {
        WindowGroup {
            if isRunningTests {
                EmptyView()
            } else {
                ContentView()
            }
        }
    }
}
