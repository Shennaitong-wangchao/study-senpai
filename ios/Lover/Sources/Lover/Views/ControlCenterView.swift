import SwiftUI

struct ControlCenterView: View {
    let router: RouterPath
    @Environment(ChatStore.self) private var chat

    private let columns = [
        GridItem(.adaptive(minimum: 116), spacing: 8)
    ]

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 18) {
                ForEach(groups) { group in
                    VStack(alignment: .leading, spacing: 8) {
                        VStack(alignment: .leading, spacing: 2) {
                            Text(group.title)
                                .font(.headline)
                            if !group.subtitle.isEmpty {
                                Text(group.subtitle)
                                    .font(.caption)
                                    .foregroundStyle(.secondary)
                                    .lineLimit(2)
                            }
                        }
                        LazyVGrid(columns: columns, spacing: 8) {
                            ForEach(group.panels.compactMap(DashboardPanel.init(rawValue:))) { panel in
                                Button {
                                    router.navigate(to: .dashboardPanel(panel))
                                } label: {
                                    VStack(alignment: .leading, spacing: 8) {
                                        HStack {
                                            Image(systemName: panel.systemImage)
                                                .font(.system(size: 18, weight: .semibold))
                                                .foregroundStyle(Color.accentColor)
                                            Spacer()
                                            Image(systemName: "chevron.right")
                                                .font(.caption2)
                                                .foregroundStyle(.secondary)
                                        }
                                        Text(panel.title)
                                            .font(.system(size: 14, weight: .semibold))
                                            .foregroundStyle(Color(.label))
                                            .lineLimit(1)
                                    }
                                    .frame(maxWidth: .infinity, minHeight: 76, alignment: .leading)
                                    .padding(10)
                                    .background(Color(.secondarySystemBackground), in: RoundedRectangle(cornerRadius: 8))
                                }
                                .buttonStyle(.plain)
                            }
                        }
                    }
                }
            }
            .padding(16)
        }
        .navigationTitle("控制中心")
        .navigationBarTitleDisplayMode(.inline)
    }

    private var groups: [MobileDashboardGroup] {
        if let dashboardGroups = chat.bootstrap?.dashboardGroups, !dashboardGroups.isEmpty {
            return dashboardGroups
        }
        return [
            MobileDashboardGroup(id: "companion", title: "陪伴状态", subtitle: "学姐当前状态", panels: ["overview", "presence", "companion-day", "modes"]),
            MobileDashboardGroup(id: "memory", title: "记忆与上下文", subtitle: "记忆、事实、关系和附件", panels: ["search", "memories", "candidates", "snapshots", "facts", "relationships", "summaries", "attachments"]),
            MobileDashboardGroup(id: "reality", title: "主动与现实锚点", subtitle: "主动消息、日程、位置和会话", panels: ["proactive", "reality-context", "scopes"]),
            MobileDashboardGroup(id: "ops", title: "运行排查", subtitle: "Turn、任务、错误、健康、性能和日志", panels: ["turns", "tasks", "errors", "health", "performance", "logs"]),
            MobileDashboardGroup(id: "security", title: "安全审计", subtitle: "安全和审计撤销", panels: ["security", "audits"])
        ]
    }
}
