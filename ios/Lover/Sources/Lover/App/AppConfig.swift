import Foundation

enum AppConfig {
    static let appName = "Lover"
    static let serverBaseURLKey = "studySenpai.serverBaseURL"
    static let mobileAPITokenKey = "studySenpai.mobileAPIToken"
    static let defaultServerBaseURLString = "http://127.0.0.1:8000"
    static var baseURL: URL { serverBaseURL }
    static var serverBaseURL: URL {
        URL(string: serverBaseURLString) ?? URL(string: defaultServerBaseURLString)!
    }
    static var serverBaseURLString: String {
        normalizedServerBaseURLString(
            UserDefaults.standard.string(forKey: serverBaseURLKey) ?? defaultServerBaseURLString
        )
    }
    static var mobileAPIToken: String {
        UserDefaults.standard.string(forKey: mobileAPITokenKey)?
            .trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
    }
    static let mobileBasePath = "/mobile"
    static let companionName = "学姐"
    static let companionFullName = "沈知微"
    static let relationshipLabel = "学姐陪伴"

    static func normalizedServerBaseURLString(_ rawValue: String) -> String {
        var value = rawValue.trimmingCharacters(in: .whitespacesAndNewlines)
        if value.isEmpty {
            value = defaultServerBaseURLString
        }
        if !value.contains("://") {
            value = "http://\(value)"
        }
        while value.hasSuffix("/") {
            value.removeLast()
        }
        return value
    }
}
