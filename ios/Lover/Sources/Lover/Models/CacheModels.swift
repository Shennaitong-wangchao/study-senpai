import Foundation
import SwiftData

@Model
final class CachedMessage {
    @Attribute(.unique) var id: Int
    var senderType: String
    var content: String
    var createdAt: String
    var metadataText: String

    init(id: Int, senderType: String, content: String, createdAt: String, metadataText: String = "") {
        self.id = id
        self.senderType = senderType
        self.content = content
        self.createdAt = createdAt
        self.metadataText = metadataText
    }
}

@Model
final class CachedTimelineItem {
    @Attribute(.unique) var id: String
    var kind: String
    var createdAt: String
    var senderLabel: String
    var content: String
    var payloadText: String

    init(
        id: String,
        kind: String,
        createdAt: String,
        senderLabel: String,
        content: String,
        payloadText: String
    ) {
        self.id = id
        self.kind = kind
        self.createdAt = createdAt
        self.senderLabel = senderLabel
        self.content = content
        self.payloadText = payloadText
    }
}

@Model
final class DraftState {
    @Attribute(.unique) var key: String
    var text: String
    var updatedAt: Date

    init(key: String = "main", text: String = "", updatedAt: Date = .now) {
        self.key = key
        self.text = text
        self.updatedAt = updatedAt
    }
}

@Model
final class UploadQueueItem {
    @Attribute(.unique) var uploadUid: String
    var filename: String
    var summary: String
    var createdAt: String

    init(uploadUid: String, filename: String, summary: String, createdAt: String) {
        self.uploadUid = uploadUid
        self.filename = filename
        self.summary = summary
        self.createdAt = createdAt
    }
}

@Model
final class DashboardFilter {
    @Attribute(.unique) var panelKey: String
    var query: String
    var status: String
    var updatedAt: Date

    init(panelKey: String, query: String = "", status: String = "", updatedAt: Date = .now) {
        self.panelKey = panelKey
        self.query = query
        self.status = status
        self.updatedAt = updatedAt
    }
}

@Model
final class CachedDashboardPanel {
    @Attribute(.unique) var panelKey: String
    var payloadText: String
    var refreshedAt: Date

    init(panelKey: String, payloadText: String, refreshedAt: Date = .now) {
        self.panelKey = panelKey
        self.payloadText = payloadText
        self.refreshedAt = refreshedAt
    }
}

@Model
final class MobileCursor {
    @Attribute(.unique) var key: String
    var value: String
    var updatedAt: Date

    init(key: String, value: String = "", updatedAt: Date = .now) {
        self.key = key
        self.value = value
        self.updatedAt = updatedAt
    }
}

@Model
final class DeviceContextSnapshot {
    @Attribute(.unique) var key: String
    var locationLabel: String
    var latitude: Double
    var longitude: Double
    var calendarEventCount: Int
    var updatedAt: Date

    init(
        key: String = "latest",
        locationLabel: String = "",
        latitude: Double = 0,
        longitude: Double = 0,
        calendarEventCount: Int = 0,
        updatedAt: Date = .now
    ) {
        self.key = key
        self.locationLabel = locationLabel
        self.latitude = latitude
        self.longitude = longitude
        self.calendarEventCount = calendarEventCount
        self.updatedAt = updatedAt
    }
}
