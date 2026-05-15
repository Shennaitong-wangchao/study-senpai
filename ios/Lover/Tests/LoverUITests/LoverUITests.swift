import XCTest

final class LoverUITests: XCTestCase {
    func testLaunchesHomeShell() {
        let app = XCUIApplication()
        app.launch()
        XCTAssertTrue(app.buttons["设置"].waitForExistence(timeout: 5))
        XCTAssertTrue(app.buttons["语音"].exists)
        XCTAssertTrue(app.buttons["工具"].exists)
        XCTAssertTrue(app.buttons["发送"].exists)
    }

    func testControlCenterEntryExists() {
        let app = XCUIApplication()
        app.launch()
        XCTAssertTrue(app.buttons["设置"].waitForExistence(timeout: 5))
        app.buttons["设置"].tap()
        if !app.staticTexts["控制中心"].waitForExistence(timeout: 2), app.buttons["设置"].exists {
            app.buttons["设置"].tap()
        }
        XCTAssertTrue(app.staticTexts["控制中心"].waitForExistence(timeout: 5))
    }
}
