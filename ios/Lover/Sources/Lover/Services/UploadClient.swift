import Foundation
import Observation

struct FileUpload: Hashable {
    var data: Data
    var filename: String
    var mimeType: String
}

@Observable
final class UploadClient {
    private let api: MobileAPIClient

    init(api: MobileAPIClient) {
        self.api = api
    }

    func upload(_ files: [FileUpload]) async throws -> MobileAttachmentUploadResponse {
        let boundary = "Boundary-\(UUID().uuidString)"
        var request = URLRequest(url: api.makeURL("/mobile/attachments"))
        request.httpMethod = "POST"
        request.setValue("multipart/form-data; boundary=\(boundary)", forHTTPHeaderField: "Content-Type")
        api.applyMobileAuthorization(to: &request)
        request.httpBody = makeBody(files: files, boundary: boundary)

        let (data, response) = try await URLSession.shared.data(for: request)
        guard let http = response as? HTTPURLResponse else { throw APIError.invalidResponse }
        guard (200..<300).contains(http.statusCode) else {
            throw APIError.badStatus(http.statusCode, String(data: data, encoding: .utf8) ?? "")
        }
        return try api.decoder.decode(MobileAttachmentUploadResponse.self, from: data)
    }

    private func makeBody(files: [FileUpload], boundary: String) -> Data {
        var data = Data()
        for file in files {
            data.append("--\(boundary)\r\n")
            data.append("Content-Disposition: form-data; name=\"files\"; filename=\"\(file.filename)\"\r\n")
            data.append("Content-Type: \(file.mimeType)\r\n\r\n")
            data.append(file.data)
            data.append("\r\n")
        }
        data.append("--\(boundary)--\r\n")
        return data
    }
}

private extension Data {
    mutating func append(_ string: String) {
        append(Data(string.utf8))
    }
}
