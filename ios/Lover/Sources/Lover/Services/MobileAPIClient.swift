import Foundation
import Observation

enum APIError: LocalizedError {
    case invalidResponse
    case badStatus(Int, String)
    case missingData

    var errorDescription: String? {
        switch self {
        case .invalidResponse:
            return "服务器响应格式不对。"
        case .badStatus(let code, let body):
            return "请求失败 \(code)：\(body)"
        case .missingData:
            return "没有拿到数据。"
        }
    }
}

@Observable
final class MobileAPIClient {
    var baseURL: URL {
        configuredBaseURL ?? AppConfig.baseURL
    }
    var lastError: String?

    private let configuredBaseURL: URL?
    private let session: URLSession
    let decoder: JSONDecoder
    let encoder: JSONEncoder

    init(baseURL: URL? = nil, session: URLSession = .shared) {
        self.configuredBaseURL = baseURL
        self.session = session
        self.decoder = JSONDecoder()
        self.decoder.keyDecodingStrategy = .convertFromSnakeCase
        self.encoder = JSONEncoder()
        self.encoder.keyEncodingStrategy = .convertToSnakeCase
    }

    func request<T: Decodable, Body: Encodable>(
        _ path: String,
        method: String = "GET",
        query: [URLQueryItem] = [],
        body: Body? = Optional<Int>.none
    ) async throws -> T {
        let data = try await dataRequest(path, method: method, query: query, body: body)
        return try decoder.decode(T.self, from: data)
    }

    func dataRequest<Body: Encodable>(
        _ path: String,
        method: String = "GET",
        query: [URLQueryItem] = [],
        body: Body? = Optional<Int>.none
    ) async throws -> Data {
        var request = URLRequest(url: makeURL(path, query: query))
        request.httpMethod = method
        request.setValue("application/json", forHTTPHeaderField: "Accept")
        applyMobileAuthorization(to: &request)
        if let body {
            request.httpBody = try encoder.encode(body)
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        }
        let (data, response) = try await session.data(for: request)
        guard let http = response as? HTTPURLResponse else { throw APIError.invalidResponse }
        guard (200..<300).contains(http.statusCode) else {
            throw APIError.badStatus(http.statusCode, String(data: data, encoding: .utf8) ?? "")
        }
        return data
    }

    func makeURL(_ path: String, query: [URLQueryItem] = []) -> URL {
        let normalizedPath = path.hasPrefix("/") ? path : "/\(path)"
        var components = URLComponents(url: baseURL.appendingPathComponent(String(normalizedPath.dropFirst())), resolvingAgainstBaseURL: false)!
        if !query.isEmpty {
            components.queryItems = query
        }
        return components.url!
    }

    func applyMobileAuthorization(to request: inout URLRequest) {
        Self.applyMobileAuthorization(to: &request)
    }

    static func applyMobileAuthorization(to request: inout URLRequest) {
        let token = AppConfig.mobileAPIToken
        if !token.isEmpty {
            request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        }
    }
}
