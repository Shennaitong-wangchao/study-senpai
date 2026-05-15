import Foundation

enum JSONValue: Codable, Hashable, Identifiable {
    case string(String)
    case number(Double)
    case bool(Bool)
    case object([String: JSONValue])
    case array([JSONValue])
    case null

    var id: String { displayString }

    init(from decoder: Decoder) throws {
        let container = try decoder.singleValueContainer()
        if container.decodeNil() {
            self = .null
        } else if let value = try? container.decode(Bool.self) {
            self = .bool(value)
        } else if let value = try? container.decode(Double.self) {
            self = .number(value)
        } else if let value = try? container.decode(String.self) {
            self = .string(value)
        } else if let value = try? container.decode([JSONValue].self) {
            self = .array(value)
        } else {
            self = .object(try container.decode([String: JSONValue].self))
        }
    }

    func encode(to encoder: Encoder) throws {
        var container = encoder.singleValueContainer()
        switch self {
        case .string(let value):
            try container.encode(value)
        case .number(let value):
            try container.encode(value)
        case .bool(let value):
            try container.encode(value)
        case .object(let value):
            try container.encode(value)
        case .array(let value):
            try container.encode(value)
        case .null:
            try container.encodeNil()
        }
    }

    var objectValue: [String: JSONValue]? {
        if case .object(let object) = self { object } else { nil }
    }

    var arrayValue: [JSONValue]? {
        if case .array(let array) = self { array } else { nil }
    }

    var stringValue: String? {
        switch self {
        case .string(let value): value
        case .number(let value): String(value)
        case .bool(let value): value ? "true" : "false"
        case .null: nil
        case .object, .array: nil
        }
    }

    var boolValue: Bool? {
        switch self {
        case .bool(let value): value
        case .string(let value):
            switch value.lowercased() {
            case "true", "yes", "on": true
            case "false", "no", "off": false
            default: nil
            }
        case .number(let value): value != 0
        case .null, .object, .array: nil
        }
    }

    var displayString: String {
        switch self {
        case .string(let value):
            return value
        case .number(let value):
            return value.truncatingRemainder(dividingBy: 1) == 0 ? String(Int(value)) : String(value)
        case .bool(let value):
            return value ? "true" : "false"
        case .object(let object):
            return object.map { "\($0.key): \($0.value.displayString)" }.sorted().joined(separator: ", ")
        case .array(let array):
            return array.map(\.displayString).joined(separator: ", ")
        case .null:
            return "-"
        }
    }
}
