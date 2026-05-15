import CoreLocation
import EventKit
import Foundation
import Observation

@MainActor
@Observable
final class DeviceContextSyncService: NSObject, CLLocationManagerDelegate {
    var authorizationSummary: String = "未同步"
    var lastSyncMessage: String?

    private let api: MobileAPIClient
    private let locationManager = CLLocationManager()
    private let eventStore = EKEventStore()
    private var latestLocation: CLLocation?

    init(api: MobileAPIClient) {
        self.api = api
        super.init()
        locationManager.delegate = self
    }

    func requestPermissionsAndSync() async {
        locationManager.requestWhenInUseAuthorization()
        locationManager.requestLocation()
        let calendarGranted = await requestCalendarAccess()
        let events = calendarGranted ? fetchUpcomingEvents() : []
        let payload = DeviceContextPayload(
            location: latestLocation.map {
                DeviceLocationPayload(
                    label: "iPhone 当前位置",
                    latitude: $0.coordinate.latitude,
                    longitude: $0.coordinate.longitude,
                    note: "ios_location"
                )
            },
            calendarEvents: events,
            source: "ios"
        )
        do {
            let _: JSONValue = try await api.request("/mobile/device-context", method: "POST", body: payload)
            authorizationSummary = calendarGranted ? "位置和日程已同步" : "位置已尝试同步，日程未授权"
            lastSyncMessage = authorizationSummary
        } catch {
            lastSyncMessage = error.localizedDescription
        }
    }

    nonisolated func locationManager(_ manager: CLLocationManager, didUpdateLocations locations: [CLLocation]) {
        Task { @MainActor in
            latestLocation = locations.last
        }
    }

    nonisolated func locationManager(_ manager: CLLocationManager, didFailWithError error: Error) {
        Task { @MainActor in
            lastSyncMessage = error.localizedDescription
        }
    }

    private func requestCalendarAccess() async -> Bool {
        do {
            if #available(iOS 17.0, *) {
                return try await eventStore.requestFullAccessToEvents()
            } else {
                return try await eventStore.requestAccess(to: .event)
            }
        } catch {
            lastSyncMessage = error.localizedDescription
            return false
        }
    }

    private func fetchUpcomingEvents() -> [DeviceCalendarEventPayload] {
        let start = Date()
        let end = Calendar.current.date(byAdding: .hour, value: 48, to: start) ?? start
        let predicate = eventStore.predicateForEvents(withStart: start, end: end, calendars: nil)
        return eventStore.events(matching: predicate).prefix(80).map { event in
            DeviceCalendarEventPayload(
                title: event.title ?? "未命名日程",
                startAt: ISO8601DateFormatter().string(from: event.startDate),
                endAt: event.endDate.map { ISO8601DateFormatter().string(from: $0) },
                location: event.location,
                isAllDay: event.isAllDay,
                note: "ios_calendar"
            )
        }
    }
}
