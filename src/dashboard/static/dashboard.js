(function () {
  const bootstrapNode = document.getElementById("dashboard-bootstrap");
  const bootstrap = bootstrapNode ? JSON.parse(bootstrapNode.textContent || "{}") : {};

  function escapeHtml(value) {
    return String(value ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  function formatDateTime(value) {
    if (!value) return "-";
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return escapeHtml(value);
    return date.toLocaleString("zh-CN", { hour12: false });
  }

  function formatNumber(value, digits = 2) {
    if (value === null || value === undefined || value === "") return "-";
    const number = Number(value);
    if (Number.isNaN(number)) return escapeHtml(value);
    return number.toFixed(digits);
  }

  function compactText(value) {
    return String(value ?? "").replace(/\s+/g, " ").trim();
  }

  function renderBadge(text, tone = "neutral") {
    const className = tone === "danger" ? "pill danger" : tone === "success" ? "pill success" : "pill";
    return `<span class="${className}">${escapeHtml(text)}</span>`;
  }

  function renderCollapsibleText(text, preview = 120) {
    const normalized = compactText(text);
    if (!normalized) return '<span class="text-soft">-</span>';
    if (normalized.length <= preview) return escapeHtml(normalized);
    return `
      <details class="collapse">
        <summary>展开查看</summary>
        <pre>${escapeHtml(normalized)}</pre>
      </details>
    `;
  }

  function renderCodeBlock(value) {
    const text = typeof value === "string" ? value : JSON.stringify(value ?? {}, null, 2);
    return `<pre>${escapeHtml(text)}</pre>`;
  }

  function renderSparkline(points) {
    if (!points || !points.length) return "";
    const values = points.map((item) => Number(item.latency_ms || 0));
    const max = Math.max(...values, 1);
    const width = 280;
    const height = 64;
    const path = values
      .map((value, index) => {
        const x = (index / Math.max(values.length - 1, 1)) * width;
        const y = height - (value / max) * (height - 8) - 4;
        return `${index === 0 ? "M" : "L"} ${x.toFixed(2)} ${y.toFixed(2)}`;
      })
      .join(" ");
    return `
      <svg class="sparkline" viewBox="0 0 ${width} ${height}" preserveAspectRatio="none" aria-hidden="true">
        <path class="grid" d="M 0 ${height - 1} L ${width} ${height - 1}"></path>
        <path d="${path}"></path>
      </svg>
    `;
  }

  function buildPagination(meta, panelKey) {
    if (!meta) return "";
    return `
      <div class="pagination-row">
        <div class="page-info">
          第 ${escapeHtml(meta.page)} / ${escapeHtml(meta.total_pages || 1)} 页，共 ${escapeHtml(meta.total)} 条
        </div>
        <div class="inline-group">
          <button class="ghost small" data-action="page-prev" data-panel="${panelKey}" ${meta.page <= 1 ? "disabled" : ""}>上一页</button>
          <button class="ghost small" data-action="page-next" data-panel="${panelKey}" ${meta.page >= meta.total_pages ? "disabled" : ""}>下一页</button>
        </div>
      </div>
    `;
  }

  async function apiFetch(url, options = {}) {
    const requestOptions = { ...options };
    requestOptions.headers = { Accept: "application/json", ...(options.headers || {}) };
    if (requestOptions.body && !requestOptions.headers["Content-Type"]) {
      requestOptions.headers["Content-Type"] = "application/json";
    }
    if (requestOptions.method && requestOptions.method !== "GET") {
      requestOptions.headers["x-csrf-token"] = state.csrfToken || "";
      requestOptions.headers.Origin = window.location.origin;
    }
    const started = performance.now();
    const response = await fetch(url, requestOptions);
    const duration = performance.now() - started;
    if (response.status === 401) {
      // P0-4: 如果已经在登录页，不需要（也不能）做跳转，否则错误提示会被刷掉
      if (window.location.pathname !== "/login") {
        window.location.href = "/login";
      }
      throw new Error("登录已失效，请重新登录。");
    }
    const contentType = response.headers.get("content-type") || "";
    const payload = contentType.includes("application/json") ? await response.json() : await response.text();
    if (!response.ok) {
      const detail = typeof payload === "string" ? payload : payload.detail || payload.message || response.statusText;
      throw new Error(detail);
    }
    return { payload, duration };
  }

  const state = {
    bootstrap,
    csrfToken: bootstrap.csrfToken || "",
    activeTab: localStorage.getItem("zhiwei.activeTab") || "overview",
    refreshMode: localStorage.getItem("zhiwei.refreshMode") || "manual",
    theme: localStorage.getItem("zhiwei.theme") || "sand",
    density: localStorage.getItem("zhiwei.density") || "comfortable",
    scopes: { items: [], activeScope: bootstrap.activeScope || null },
    globalQuery: "",
    timerId: null,
    panels: {
      overview: { data: null },
      search: { page: 1, page_size: 10, q: "" },
      memories: { page: 1, page_size: 20, q: "", sort: "importance" },
      candidates: { page: 1, page_size: 20, q: "", status: "pending", memory_type: "", category: "", selected: [] },
      turns: { page: 1, page_size: 20, q: "", request_type: "", scene: "" },
      attachments: { page: 1, page_size: 20, q: "", artifact_type: "" },
      proactive: { page: 1, page_size: 20, q: "", status: "" },
      presence: { data: null },
      "companion-day": { data: null },
      "reality-context": { data: null },
      facts: { page: 1, page_size: 20, q: "", namespace: "" },
      relationships: { page: 1, page_size: 20, q: "", dimension: "" },
      summaries: { page: 1, page_size: 12, q: "" },
      snapshots: { page: 1, page_size: 12, q: "" },
      tasks: { page: 1, page_size: 20, q: "", status: "", task_type: "", scope_mode: "active" },
      errors: { page: 1, page_size: 20, q: "", status: "open", component: "" },
      performance: { scope_mode: "all" },
      health: { history_limit: 80 },
      security: {},
      audits: { page: 1, page_size: 20, q: "" },
      logs: { page: 1, page_size: 50, q: "" },
    },
  };

  const panelHost = document.getElementById("panel-host");
  const successBanner = document.getElementById("success-banner");
  const errorBanner = document.getElementById("error-banner");
  const scopeSummary = document.getElementById("scope-summary");
  const lastRefreshInfo = document.getElementById("last-refresh-info");
  const panelRefreshInfo = document.getElementById("panel-refresh-info");

  function setBodyPreferences() {
    document.body.classList.remove("theme-ink", "density-compact");
    if (state.theme === "ink") document.body.classList.add("theme-ink");
    if (state.density === "compact") document.body.classList.add("density-compact");
  }

  function setSuccess(message) {
    if (!successBanner) return;
    successBanner.textContent = message;
    successBanner.classList.remove("hidden");
    setTimeout(() => successBanner.classList.add("hidden"), 3200);
  }

  function setGlobalError(message) {
    if (!errorBanner) return;
    errorBanner.textContent = message;
    errorBanner.classList.remove("hidden");
  }

  function clearGlobalError() {
    if (!errorBanner) return;
    errorBanner.classList.add("hidden");
    errorBanner.textContent = "";
  }

  function updateScopeSummary() {
    if (!scopeSummary) return;
    const scope = state.scopes.activeScope;
    if (!scope) {
      scopeSummary.textContent = "当前没有可管理的活跃 Scope";
      return;
    }
    scopeSummary.textContent = `${scope.display_name} · ${scope.conversation_id} · 待审 ${scope.pending_candidates} / 记忆 ${scope.active_memories}`;
  }

  function updateRefreshMeta(label, duration) {
    const now = new Date();
    if (lastRefreshInfo) {
      lastRefreshInfo.textContent = `上次刷新：${now.toLocaleTimeString("zh-CN", { hour12: false })}`;
    }
    if (panelRefreshInfo) {
      panelRefreshInfo.textContent = `当前面板：${label} · ${formatNumber(duration, 1)}ms`;
    }
  }

  function panelQueryString(panelKey) {
    const config = state.panels[panelKey] || {};
    const params = new URLSearchParams();
    Object.entries(config).forEach(([key, value]) => {
      if (value === undefined || value === null || value === "" || Array.isArray(value)) return;
      params.set(key, String(value));
    });
    return params.toString();
  }

  function panelEndpoint(panelKey) {
    if (panelKey === "overview") return "/api/overview";
    if (panelKey === "search") {
      const q = state.panels.search.q || state.globalQuery || "";
      return `/api/search?${new URLSearchParams({ q }).toString()}`;
    }
    return `/api/${panelKey}?${panelQueryString(panelKey)}`;
  }

  async function loadScopes() {
    const { payload } = await apiFetch("/api/scopes");
    state.scopes = payload;
    const select = document.getElementById("scope-select");
    if (select) {
      select.innerHTML = "";
      (payload.items || []).forEach((item) => {
        const option = document.createElement("option");
        option.value = `${item.user_id}::${item.conversation_id}`;
        option.textContent = `${item.display_name} · ${item.latest_preview}`;
        if (payload.active_scope && payload.active_scope.conversation_id === item.conversation_id) {
          option.selected = true;
        }
        select.appendChild(option);
      });
    }
    state.scopes.activeScope = payload.active_scope || null;
    updateScopeSummary();
  }

  async function fetchPanel(panelKey, { silent = false } = {}) {
    const panelState = state.panels[panelKey] || (state.panels[panelKey] = {});
    if (!silent) panelState.loading = true;
    panelState.error = "";
    if (!silent) renderActivePanel();
    try {
      const { payload, duration } = await apiFetch(panelEndpoint(panelKey));
      panelState.data = payload;
      panelState.duration = duration;
      panelState.loading = false;
      panelState.error = "";
      updateRefreshMeta(tabLabel(panelKey), duration);
      renderActivePanel();
      return payload;
    } catch (error) {
      panelState.loading = false;
      panelState.error = error.message || String(error);
      renderActivePanel();
      throw error;
    }
  }

  function tabLabel(key) {
    const button = document.querySelector(`.tab-button[data-tab="${key}"]`);
    return button ? button.textContent.trim() : key;
  }

  function renderActivePanel() {
    if (!panelHost) return;
    const key = state.activeTab;
    const panelState = state.panels[key] || {};
    const errorHtml = panelState.error ? `<div class="banner error">${escapeHtml(panelState.error)}</div>` : "";
    const loadingHtml = panelState.loading ? `<div class="banner">${escapeHtml("加载中…")}</div>` : "";
    let content = "";
    switch (key) {
      case "overview":
        content = renderOverview(panelState.data);
        break;
      case "search":
        content = renderSearch(panelState.data);
        break;
      case "memories":
        content = renderMemories(panelState.data);
        break;
      case "candidates":
        content = renderCandidates(panelState.data);
        break;
      case "turns":
        content = renderTurns(panelState.data);
        break;
      case "attachments":
        content = renderAttachments(panelState.data);
        break;
      case "proactive":
        content = renderProactive(panelState.data);
        break;
      case "presence":
        content = renderPresence(panelState.data);
        break;
      case "companion-day":
        content = renderCompanionDay(panelState.data);
        break;
      case "reality-context":
        content = renderRealityContext(panelState.data);
        break;
      case "facts":
        content = renderFacts(panelState.data);
        break;
      case "relationships":
        content = renderRelationships(panelState.data);
        break;
      case "summaries":
        content = renderSummaries(panelState.data);
        break;
      case "snapshots":
        content = renderSnapshots(panelState.data);
        break;
      case "tasks":
        content = renderTasks(panelState.data);
        break;
      case "errors":
        content = renderErrors(panelState.data);
        break;
      case "performance":
        content = renderPerformance(panelState.data);
        break;
      case "health":
        content = renderHealth(panelState.data);
        break;
      case "security":
        content = renderSecurity(panelState.data);
        break;
      case "audits":
        content = renderAudits(panelState.data);
        break;
      case "logs":
        content = renderLogs(panelState.data);
        break;
      default:
        content = '<section class="empty-card"><p>面板不存在。</p></section>';
        break;
    }
    panelHost.innerHTML = `${errorHtml}${loadingHtml}${content}`;
  }

  function renderSummaryCards(cards) {
    return `
      <div class="summary-grid">
        ${cards
          .map(
            (card) => `
              <article class="stat-card">
                <div class="stat-title">${escapeHtml(card.title)}</div>
                <div class="stat-value">${escapeHtml(card.value)}</div>
                <div class="text-soft">${escapeHtml(card.note || "")}</div>
              </article>
            `,
          )
          .join("")}
      </div>
    `;
  }

  function renderOverview(data) {
    if (!data) return '<section class="empty-card"><p>点击“立即刷新”开始加载总览。</p></section>';
    const overview = data.overview || {};
    const health = overview.health || [];
    return `
      <section class="panel-card">
        <div class="panel-header">
          <div>
            <h2>总览</h2>
            <div class="panel-subtitle">当前 scope、记忆规模、错误与主动消息概览。</div>
          </div>
        </div>
        ${renderSummaryCards([
          { title: "消息总数", value: overview.messages ?? 0, note: "当前活跃用户累计消息" },
          { title: "长期记忆", value: overview.long_term_memories ?? 0, note: "active 记忆数" },
          { title: "待审候选", value: overview.candidate_memories ?? 0, note: "等待人工审核" },
          { title: "开放错误", value: overview.errors_open ?? 0, note: "仍未闭环的问题" },
          { title: "主动接受率", value: formatNumber((overview.proactive_acceptance_rate || 0) * 100, 1) + "%", note: "主动触达效果" },
          { title: "冷响应率", value: formatNumber((overview.proactive_cold_rate || 0) * 100, 1) + "%", note: "需要继续收敛" },
        ])}
        <div class="summary-grid">
          <article class="summary-card">
            <h3>当前 Health</h3>
            <div class="chip-row">
              ${health.map((item) => renderBadge(`${item.component}:${item.status}`, item.status === "ok" || item.status === "healthy" ? "success" : "danger")).join("")}
            </div>
          </article>
          <article class="summary-card">
            <h3>快捷入口</h3>
            <div class="chip-row">
              ${(data.quick_links || [])
                .map((link) => `<button class="ghost small" data-action="switch-tab" data-target-tab="${escapeHtml(link.tab)}">${escapeHtml(link.label)}</button>`)
                .join("")}
            </div>
          </article>
        </div>
      </section>
    `;
  }

  function renderSearch(data) {
    const value = state.panels.search.q || state.globalQuery || "";
    if (!data) {
      return `
        <section class="panel-card">
          <h2>全局搜索</h2>
          <form class="filter-row" data-panel-form="search">
            <input name="q" value="${escapeHtml(value)}" placeholder="输入关键词、request id 或内容片段">
            <button class="primary" type="submit">搜索</button>
          </form>
        </section>
      `;
    }
    return `
      <section class="panel-card">
        <div class="panel-header">
          <div>
            <h2>全局搜索</h2>
            <div class="panel-subtitle">跨记忆、turn 和错误的统一排查视角。</div>
          </div>
          <div>${renderBadge(`命中 ${data.total_hits || 0} 条`, "success")}</div>
        </div>
        <form class="filter-row" data-panel-form="search">
          <input name="q" value="${escapeHtml(value)}" placeholder="输入关键词、request id 或内容片段">
          <button class="primary" type="submit">搜索</button>
        </form>
        <div class="summary-grid">
          ${(data.groups || [])
            .map(
              (group) => `
                <article class="summary-card">
                  <h3>${escapeHtml(group.label)}</h3>
                  <div class="table-wrap">
                    <table>
                      <tbody>
                        ${(group.items || [])
                          .map(
                            (item) => `
                              <tr>
                                <td class="nowrap">${escapeHtml(item.id)}</td>
                                <td>${escapeHtml(item.title)}</td>
                                <td>${escapeHtml(item.preview)}</td>
                                <td class="nowrap">${escapeHtml(formatDateTime(item.updated_at))}</td>
                              </tr>
                            `,
                          )
                          .join("") || '<tr><td colspan="4" class="text-soft">暂无结果</td></tr>'}
                      </tbody>
                    </table>
                  </div>
                </article>
              `,
            )
            .join("")}
        </div>
      </section>
    `;
  }

  function renderMemories(data) {
    const panel = state.panels.memories;
    const items = (data && data.items) || [];
    return `
      <section class="panel-card">
        <div class="panel-header">
          <div>
            <h2>长期记忆</h2>
            <div class="panel-subtitle">支持按命中数、更新时间、重要度重排，并追踪来源消息与批准来源。</div>
          </div>
        </div>
        <form class="filter-row" data-panel-form="memories">
          <input name="q" value="${escapeHtml(panel.q)}" placeholder="搜 content / tag / type / source id">
          <select name="sort">
            ${["importance", "updated", "hits", "last_used"]
              .map((option) => `<option value="${option}" ${panel.sort === option ? "selected" : ""}>${escapeHtml(option)}</option>`)
              .join("")}
          </select>
          <button class="primary" type="submit">应用</button>
        </form>
        ${(data && data.highlights && data.highlights.top_hits && data.highlights.top_hits.length)
          ? `
            <div class="chip-row">
              ${data.highlights.top_hits
                .map((item) => `<span class="chip">${escapeHtml(item.memory_type)} · 命中 ${escapeHtml(item.hit_count)}</span>`)
                .join("")}
            </div>
          `
          : ""}
        <div class="table-wrap">
          <table>
            <thead>
              <tr>
                <th>记忆</th>
                <th>来源追溯</th>
                <th>命中/使用</th>
                <th>操作</th>
              </tr>
            </thead>
            <tbody>
              ${items
                .map(
                  (item) => `
                    <tr>
                      <td>
                        <div><strong>${escapeHtml(item.memory_type)}</strong> / ${escapeHtml(item.category)}</div>
                        <div class="text-soft">重要度 ${escapeHtml(formatNumber(item.importance))} · 置信度 ${escapeHtml(formatNumber(item.confidence))}</div>
                        <div>${renderCollapsibleText(item.content, 96)}</div>
                        <div class="chip-row">${(item.tags || []).map((tag) => `<span class="chip">${escapeHtml(tag)}</span>`).join("")}</div>
                      </td>
                      <td>
                        <div>source ids: ${escapeHtml((item.source_message_ids || []).join(", ") || "-")}</div>
                        <div>approved_from: ${escapeHtml(item.approved_from_candidate || "-")}</div>
                        <div class="text-soft">${escapeHtml(formatDateTime(item.updated_at))}</div>
                      </td>
                      <td>
                        <div>hit_count: ${escapeHtml(item.hit_count)}</div>
                        <div>last_hit: ${escapeHtml(formatDateTime(item.last_hit_at))}</div>
                        <div>last_used: ${escapeHtml(formatDateTime(item.last_used_at))}</div>
                      </td>
                      <td>
                        <button class="danger small" data-action="archive-memory" data-id="${escapeHtml(item.memory_uid)}">归档</button>
                      </td>
                    </tr>
                  `,
                )
                .join("") || '<tr><td colspan="4" class="text-soft">暂无长期记忆。</td></tr>'}
            </tbody>
          </table>
        </div>
        ${buildPagination(data ? data.meta : null, "memories")}
      </section>
    `;
  }

  function renderCandidates(data) {
    const panel = state.panels.candidates;
    const items = (data && data.items) || [];
    const selected = new Set(panel.selected || []);
    return `
      <section class="panel-card">
        <div class="panel-header">
          <div>
            <h2>候选记忆</h2>
            <div class="panel-subtitle">支持备注、批量审核和 dedupe 视图。</div>
          </div>
        </div>
        <form class="filter-row" data-panel-form="candidates">
          <input name="q" value="${escapeHtml(panel.q)}" placeholder="搜 content / reason / review note">
          <select name="status">
            ${["pending", "approved", "rejected", "all"]
              .map((value) => `<option value="${value}" ${panel.status === value ? "selected" : ""}>${escapeHtml(value)}</option>`)
              .join("")}
          </select>
          <input name="memory_type" value="${escapeHtml(panel.memory_type)}" placeholder="memory_type">
          <input name="category" value="${escapeHtml(panel.category)}" placeholder="category">
          <button class="primary" type="submit">应用</button>
        </form>
        <div class="action-row">
          <input id="candidate-batch-review-note" placeholder="批量审核备注（对选中的批量操作生效）">
          <button class="primary" data-action="batch-candidate-approve" ${selected.size === 0 ? "disabled" : ""}>批量批准 (${selected.size})</button>
          <button class="ghost" data-action="batch-candidate-reject" ${selected.size === 0 ? "disabled" : ""}>批量拒绝 (${selected.size})</button>
        </div>
        ${(data && data.groups && data.groups.length)
          ? `<div class="chip-row">${data.groups
              .map((group) => `<span class="chip">相似合并：${escapeHtml(group.dedupe_signature || "未分类")} · ${escapeHtml(group.item_count)} 条</span>`)
              .join("")}</div>`
          : ""}
        <div class="table-wrap">
          <table>
            <thead>
              <tr>
                <th class="checkbox-cell"><input type="checkbox" data-action="select-all-candidates"></th>
                <th>候选内容</th>
                <th>类型与来源</th>
                <th>状态与备注</th>
                <th>操作</th>
              </tr>
            </thead>
            <tbody>
              ${items
                .map(
                  (item) => `
                    <tr>
                      <td class="checkbox-cell"><input type="checkbox" data-action="toggle-candidate" data-id="${escapeHtml(item.candidate_uid)}" ${selected.has(item.candidate_uid) ? "checked" : ""}></td>
                      <td>
                        <div>${renderCollapsibleText(item.content, 100)}</div>
                        <div class="text-soft">reason: ${escapeHtml(item.reason || "-")}</div>
                      </td>
                      <td>
                        <div>${escapeHtml(item.memory_type)} / ${escapeHtml(item.category)}</div>
                        <div class="text-soft">来源: ${escapeHtml((item.source_message_ids || []).join(", ") || "-")}</div>
                      </td>
                      <td>
                        <div>${renderBadge(item.status, item.status === "approved" ? "success" : item.status === "rejected" ? "danger" : "neutral")}</div>
                        <div class="text-soft">${escapeHtml(item.review_note || "-")}</div>
                      </td>
                      <td>
                        ${item.status === "pending" ? `<div class="action-row" style="margin-bottom: 0.5rem;"><input id="note-${escapeHtml(item.candidate_uid)}" placeholder="单条备注" style="width: 120px;"></div>` : ""}
                        <div class="chip-row">
                          ${item.status === "pending" ? `<button class="primary small" data-action="approve-candidate" data-id="${escapeHtml(item.candidate_uid)}">批准</button>` : ""}
                          ${item.status === "pending" ? `<button class="ghost small" data-action="reject-candidate" data-id="${escapeHtml(item.candidate_uid)}">拒绝</button>` : ""}
                          ${item.status === "rejected" ? `<button class="ghost small" data-action="reopen-candidate" data-id="${escapeHtml(item.candidate_uid)}">重开</button>` : ""}
                        </div>
                      </td>
                    </tr>
                  `,
                )
                .join("") || '<tr><td colspan="5" class="text-soft">暂无候选记忆。</td></tr>'}
            </tbody>
          </table>
        </div>
        ${buildPagination(data ? data.meta : null, "candidates")}
      </section>
    `;
  }

  function updateCandidateBatchControls() {
    const panel = state.panels.candidates || {};
    const items = (((panel || {}).data || {}).items || []).map((item) => item.candidate_uid);
    const selected = new Set(panel.selected || []);
    const selectedCount = selected.size;
    const approveButton = document.querySelector('[data-action="batch-candidate-approve"]');
    const rejectButton = document.querySelector('[data-action="batch-candidate-reject"]');
    if (approveButton) {
      approveButton.disabled = selectedCount === 0;
      approveButton.textContent = `批量批准 (${selectedCount})`;
    }
    if (rejectButton) {
      rejectButton.disabled = selectedCount === 0;
      rejectButton.textContent = `批量拒绝 (${selectedCount})`;
    }
    const selectAll = document.querySelector('[data-action="select-all-candidates"]');
    if (selectAll) {
      selectAll.checked = items.length > 0 && items.every((item) => selected.has(item));
      selectAll.indeterminate = selectedCount > 0 && !selectAll.checked;
    }
  }

  function renderTurns(data) {
    const panel = state.panels.turns;
    const items = (data && data.items) || [];
    return `
      <section class="panel-card">
        <div class="panel-header">
          <div>
            <h2>Turn Trace</h2>
            <div class="panel-subtitle">补齐 prompt 长度、token、成本、附件数量、search 数量与 request id 关联。</div>
          </div>
        </div>
        <form class="filter-row" data-panel-form="turns">
          <input name="q" value="${escapeHtml(panel.q)}" placeholder="搜 turn uid / request id / input / output">
          <input name="request_type" value="${escapeHtml(panel.request_type)}" placeholder="request_type">
          <input name="scene" value="${escapeHtml(panel.scene)}" placeholder="scene">
          <button class="primary" type="submit">应用</button>
        </form>
        <div class="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Turn</th>
                <th>Prompt/Cost</th>
                <th>检索与上下文</th>
                <th>文本</th>
              </tr>
            </thead>
            <tbody>
              ${items
                .map(
                  (item) => `
                    <tr>
                      <td>
                        <div><strong>${escapeHtml(item.turn_uid)}</strong></div>
                        <div class="text-soft">request_id: ${escapeHtml(item.request_id || "-")}</div>
                        <div class="text-soft">${escapeHtml(item.scene)} / ${escapeHtml(item.request_type)} / ${escapeHtml(item.model_name || "-")}</div>
                        <div class="text-soft">${escapeHtml(formatDateTime(item.created_at))}</div>
                      </td>
                      <td>
                        <div>chars: ${escapeHtml(item.prompt_char_count)}</div>
                        <div>tokens: ${escapeHtml(item.estimated_total_tokens)}</div>
                        <div>cost: $${escapeHtml(formatNumber(item.estimated_cost_usd, 6))}</div>
                        <div>attachments: ${escapeHtml(item.attachment_count)} · search: ${escapeHtml(item.search_count)}</div>
                      </td>
                      <td>
                        <div>latency: ${escapeHtml(formatNumber(item.latency_ms, 1))}ms</div>
                        <div>${renderCollapsibleText(JSON.stringify(item.retrieval?.used_prompt || {}, null, 2), 90)}</div>
                      </td>
                      <td>
                        <div>${renderCollapsibleText(item.user_input, 70)}</div>
                        <div class="text-soft">${renderCollapsibleText(item.assistant_reply, 90)}</div>
                      </td>
                    </tr>
                  `,
                )
                .join("") || '<tr><td colspan="4" class="text-soft">暂无 turn 记录。</td></tr>'}
            </tbody>
          </table>
        </div>
        ${buildPagination(data ? data.meta : null, "turns")}
      </section>
    `;
  }

  function renderAttachments(data) {
    const panel = state.panels.attachments;
    const items = (data && data.items) || [];
    return `
      <section class="panel-card">
        <h2>附件工件</h2>
        <form class="filter-row" data-panel-form="attachments">
          <input name="q" value="${escapeHtml(panel.q)}" placeholder="搜 filename / summary / content type">
          <input name="artifact_type" value="${escapeHtml(panel.artifact_type)}" placeholder="artifact_type">
          <button class="primary" type="submit">应用</button>
        </form>
        <div class="table-wrap">
          <table>
            <thead><tr><th>文件</th><th>提炼内容</th><th>元信息</th></tr></thead>
            <tbody>
              ${items
                .map(
                  (item) => `
                    <tr>
                      <td>
                        <div>${escapeHtml(item.filename)}</div>
                        <div class="text-soft">${escapeHtml(item.artifact_type)} / ${escapeHtml(item.content_type || "-")}</div>
                      </td>
                      <td>${renderCollapsibleText(item.summary_text || item.extracted_text, 120)}</td>
                      <td>${renderCodeBlock(item.metadata)}</td>
                    </tr>
                  `,
                )
                .join("") || '<tr><td colspan="3" class="text-soft">暂无附件工件。</td></tr>'}
            </tbody>
          </table>
        </div>
        ${buildPagination(data ? data.meta : null, "attachments")}
      </section>
    `;
  }

  function renderProactive(data) {
    const panel = state.panels.proactive;
    const items = (data && data.items) || [];
    const summary = (data && data.summary) || {};
    const preferences = summary.preferences || {};
    const gate = summary.gate || {};
    const policy = gate.policy || {};
    const cadence = preferences.cadence || "low";
    return `
      <section class="panel-card">
        <h2>主动消息</h2>
        <div class="metric-grid compact">
          <div class="metric-card">
            <div class="metric-label">开关</div>
            <div class="metric-value">${preferences.enabled ? "开启" : "关闭"}</div>
            <div class="inline-group">
              <button class="ghost small" data-action="proactive-preferences" data-enabled="true">开启</button>
              <button class="ghost small" data-action="proactive-preferences" data-enabled="false">关闭</button>
            </div>
          </div>
          <div class="metric-card">
            <div class="metric-label">频率</div>
            <div class="metric-value">${escapeHtml(cadence)}</div>
            <div class="inline-group">
              <button class="ghost small" data-action="proactive-preferences" data-cadence="low">低频</button>
              <button class="ghost small" data-action="proactive-preferences" data-cadence="normal">中频</button>
              <button class="ghost small" data-action="proactive-preferences" data-cadence="high">高频</button>
            </div>
          </div>
          <div class="metric-card">
            <div class="metric-label">节奏</div>
            <div class="metric-value">${escapeHtml(policy.min_interval_minutes || "-")}-${escapeHtml(policy.max_interval_minutes || "-")} min</div>
            <div class="metric-note">每日最多 ${escapeHtml(policy.daily_max || "-")} 条</div>
          </div>
        </div>
        <form class="filter-row" data-panel-form="proactive">
          <input name="q" value="${escapeHtml(panel.q)}" placeholder="搜 trigger / opening text">
          <input name="status" value="${escapeHtml(panel.status)}" placeholder="status">
          <button class="primary" type="submit">应用</button>
        </form>
        <div class="table-wrap">
          <table>
            <thead><tr><th>主动消息</th><th>接受情况</th><th>元信息</th></tr></thead>
            <tbody>
              ${items
                .map(
                  (item) => `
                    <tr>
                      <td>
                        <div>${renderCollapsibleText(item.opening_text, 110)}</div>
                        <div class="text-soft">${escapeHtml(item.trigger_type)} / ${escapeHtml(item.status)}</div>
                      </td>
                      <td>
                        <div>accepted: ${escapeHtml(item.accepted)}</div>
                        <div>cold_response: ${escapeHtml(item.cold_response)}</div>
                        <div>latency: ${escapeHtml(formatNumber(item.response_latency_minutes, 1))} min</div>
                        <div class="inline-group">
                          <button class="ghost small" data-action="proactive-feedback" data-id="${escapeHtml(item.proactive_uid)}" data-feedback="good">好</button>
                          <button class="ghost small" data-action="proactive-feedback" data-id="${escapeHtml(item.proactive_uid)}" data-feedback="too_frequent">太频繁</button>
                          <button class="ghost small" data-action="proactive-feedback" data-id="${escapeHtml(item.proactive_uid)}" data-feedback="bad">不合适</button>
                        </div>
                      </td>
                      <td>${renderCodeBlock(item.metadata)}</td>
                    </tr>
                  `,
                )
                .join("") || '<tr><td colspan="3" class="text-soft">暂无主动消息。</td></tr>'}
            </tbody>
          </table>
        </div>
        ${buildPagination(data ? data.meta : null, "proactive")}
      </section>
    `;
  }

  function renderPresence(data) {
    const summary = (data && data.summary) || {};
    const presence = summary.presence_state || {};
    const triggerState = summary.proactive_trigger_state || {};
    const loops = (data && data.items) || [];
    const timeline = ((data && data.highlights) || {}).trigger_timeline || [];
    return `
      <section class="panel-card">
        <h2>沉浸状态</h2>
        <form class="filter-row" data-presence-form="true">
          <select name="user_sleep_state">
            ${["unknown", "awake", "asleep", "probably_awake", "probably_asleep"].map((value) => `<option value="${value}" ${presence.user_sleep_state === value ? "selected" : ""}>${value}</option>`).join("")}
          </select>
          <input name="user_sleep_state_confidence" value="${escapeHtml(presence.user_sleep_state_confidence ?? "")}" placeholder="sleep confidence">
          <input name="current_scene_label" value="${escapeHtml(presence.current_scene_label || "")}" placeholder="她这边当前场景">
          <input name="daily_detail" value="${escapeHtml(presence.daily_detail || "")}" placeholder="今天已连续的生活细节">
          <input name="assistant_location_label" value="${escapeHtml(presence.assistant_location_label || "")}" placeholder="位置感">
          <input name="assistant_mood_label" value="${escapeHtml(presence.assistant_mood_label || "")}" placeholder="心情">
          <input name="note" value="" placeholder="手动备注，不碰长期记忆">
          <button class="primary" type="submit">保存</button>
        </form>
        <div class="metric-grid">
          <div class="metric-card">
            <div class="metric-label">用户睡醒状态</div>
            <div class="metric-value">${escapeHtml(presence.user_sleep_state || "unknown")}</div>
            <div class="text-soft">confidence ${escapeHtml(formatNumber(presence.user_sleep_state_confidence, 2))}</div>
          </div>
          <div class="metric-card">
            <div class="metric-label">她这边</div>
            <div class="metric-value">${escapeHtml(presence.assistant_activity_band || "-")}</div>
            <div class="text-soft">${escapeHtml(presence.current_scene_label || presence.assistant_activity_label || "-")}</div>
          </div>
          <div class="metric-card">
            <div class="metric-label">生活细节</div>
            <div class="metric-value">${escapeHtml((presence.shared_details || []).length || 0)}</div>
            <div class="text-soft">${escapeHtml(presence.last_life_share_detail || presence.daily_detail || "-")}</div>
          </div>
          <div class="metric-card">
            <div class="metric-label">最近计划</div>
            <div class="metric-value">${escapeHtml((triggerState.last_plan || {}).trigger_type || "-")}</div>
            <div class="text-soft">${escapeHtml((triggerState.last_plan || {}).reason || "-")}</div>
          </div>
          <div class="metric-card">
            <div class="metric-label">情绪底色</div>
            <div class="metric-value">${escapeHtml(((presence.assistant_emotion_state || {}).label) || presence.assistant_mood_label || "-")}</div>
            <div class="text-soft">longing ${escapeHtml(formatNumber((presence.assistant_emotion_state || {}).longing, 2))} / hurt ${escapeHtml(formatNumber((presence.assistant_emotion_state || {}).hurt, 2))}</div>
          </div>
        </div>
        <h3>未收事项</h3>
        <div class="table-wrap">
          <table>
            <thead><tr><th>事项</th><th>状态</th><th>来源</th></tr></thead>
            <tbody>
              ${loops.map((item) => `
                <tr>
                  <td>${renderCollapsibleText(item.content, 120)}</td>
                  <td>
                    <div>${escapeHtml(item.status || "open")}</div>
                    <div class="text-soft">prompted ${escapeHtml(item.prompt_count || 0)} 次</div>
                  </td>
                  <td>
                    <div>${escapeHtml(item.kind || "-")}</div>
                    <div class="text-soft">${escapeHtml(formatDateTime(item.updated_at))}</div>
                  </td>
                </tr>
              `).join("") || '<tr><td colspan="3" class="text-soft">暂无明确未收事项。</td></tr>'}
            </tbody>
          </table>
        </div>
        <h3>主动触发轨迹</h3>
        <div class="table-wrap">
          <table>
            <thead><tr><th>trigger</th><th>原因</th><th>候选细节</th></tr></thead>
            <tbody>
              ${timeline.map((item) => `
                <tr>
                  <td>
                    <div>${escapeHtml(item.trigger_type || "-")}</div>
                    <div class="text-soft">score ${escapeHtml(formatNumber(item.score, 2))}</div>
                  </td>
                  <td>
                    <div>${escapeHtml(item.reason || "-")}</div>
                    <div class="text-soft">${escapeHtml(formatDateTime(item.planned_at))}</div>
                  </td>
                  <td>${renderCollapsibleText(item.selected_detail || "", 100)}</td>
                </tr>
              `).join("") || '<tr><td colspan="3" class="text-soft">暂无 trigger plan。</td></tr>'}
            </tbody>
          </table>
        </div>
      </section>
    `;
  }

  function renderCompanionDay(data) {
    const summary = (data && data.summary) || {};
    const route = summary.route || {};
    const routeBody = route.route || {};
    const settings = summary.settings || {};
    const events = (data && data.items) || [];
    const diary = ((data && data.highlights) || {}).diary || [];
    const beats = routeBody.beats || [];
    const unanswered = summary.unanswered_event || null;
    return `
      <section class="panel-card">
        <div class="panel-header">
          <div>
            <h2>她的一天</h2>
            <div class="panel-subtitle">查看今天路线、主动片段、未回反应和共同日记；这里只改角色日常，不碰长期用户记忆。</div>
          </div>
          <div class="inline-group">
            <button class="ghost small" data-action="companion-day-regenerate">重生成今天路线</button>
          </div>
        </div>
        <form class="filter-row" data-companion-day-form="true">
          <input name="current_scene" value="${escapeHtml(route.current_scene || "")}" placeholder="当前场景">
          <input name="mood_label" value="${escapeHtml(route.mood_label || "")}" placeholder="心情">
          <input name="longing_level" value="${escapeHtml(route.longing_level ?? "")}" placeholder="想你强度 0-1">
          <label class="inline-label"><input type="checkbox" name="quiet_mode" value="true" ${route.quiet_mode ? "checked" : ""}> 安静模式</label>
          <input name="note" value="" placeholder="手动备注，不碰长期记忆">
          <button class="primary" type="submit">保存</button>
        </form>
        <div class="metric-grid">
          <div class="metric-card">
            <div class="metric-label">今天日期</div>
            <div class="metric-value">${escapeHtml(route.local_date || "-")}</div>
            <div class="text-soft">${escapeHtml(route.timezone || "-")}</div>
          </div>
          <div class="metric-card">
            <div class="metric-label">当前场景</div>
            <div class="metric-value">${escapeHtml(route.mood_label || "-")}</div>
            <div class="text-soft">${escapeHtml(route.current_scene || "-")}</div>
          </div>
          <div class="metric-card">
            <div class="metric-label">想你强度</div>
            <div class="metric-value">${escapeHtml(formatNumber(route.longing_level, 2))}</div>
            <div class="text-soft">${route.quiet_mode ? "quiet mode" : "active stream"}</div>
          </div>
          <div class="metric-card">
            <div class="metric-label">发送节奏</div>
            <div class="metric-value">${escapeHtml(settings.min_interval_minutes ?? "-")} - ${escapeHtml(settings.max_interval_minutes ?? "-")}m</div>
            <div class="text-soft">${settings.status_cards_enabled ? "status cards on" : "text fallback"}</div>
          </div>
        </div>
        ${unanswered ? `<div class="banner">未回片段：${renderCollapsibleText(unanswered.content || "", 140)}</div>` : ""}
        <h3>今天路线</h3>
        <div class="table-wrap">
          <table>
            <thead><tr><th>beat</th><th>场景</th><th>心情</th></tr></thead>
            <tbody>
              ${beats.map((beat) => `
                <tr>
                  <td>
                    <div>${escapeHtml(beat.key || "-")}</div>
                    <div class="text-soft">${escapeHtml(beat.hour_hint || "-")}</div>
                  </td>
                  <td>${renderCollapsibleText(beat.scene || "", 140)}</td>
                  <td>${escapeHtml(beat.mood || "-")}</td>
                </tr>
              `).join("") || '<tr><td colspan="3" class="text-soft">暂无路线。</td></tr>'}
            </tbody>
          </table>
        </div>
        <h3>主动片段</h3>
        <div class="table-wrap">
          <table>
            <thead><tr><th>片段</th><th>回应状态</th><th>反馈</th><th>元信息</th></tr></thead>
            <tbody>
              ${events.map((item) => `
                <tr>
                  <td>
                    <div>${renderCollapsibleText(item.content || "", 130)}</div>
                    <div class="text-soft">${escapeHtml(item.event_type || "-")} / ${escapeHtml(item.status || "-")}</div>
                  </td>
                  <td>
                    <div>expected: ${escapeHtml(item.response_expected)}</div>
                    <div>sent: ${escapeHtml(formatDateTime(item.sent_at))}</div>
                    <div>responded: ${escapeHtml(formatDateTime(item.responded_at))}</div>
                  </td>
                  <td>
                    <div>${escapeHtml(item.feedback || "-")}</div>
                    <div class="inline-group">
                      <button class="ghost small" data-action="companion-day-feedback" data-id="${escapeHtml(item.event_uid)}" data-feedback="good">好</button>
                      <button class="ghost small" data-action="companion-day-feedback" data-id="${escapeHtml(item.event_uid)}" data-feedback="too_frequent">太频繁</button>
                      <button class="ghost small" data-action="companion-day-feedback" data-id="${escapeHtml(item.event_uid)}" data-feedback="bad">不合适</button>
                    </div>
                  </td>
                  <td>${renderCodeBlock(item.metadata || {})}</td>
                </tr>
              `).join("") || '<tr><td colspan="4" class="text-soft">暂无主动片段。</td></tr>'}
            </tbody>
          </table>
        </div>
        <h3>共同日记</h3>
        <div class="table-wrap">
          <table>
            <thead><tr><th>条目</th><th>内容</th><th>范围</th></tr></thead>
            <tbody>
              ${diary.map((item) => `
                <tr>
                  <td>
                    <div>${escapeHtml(item.title || item.entry_type || "-")}</div>
                    <div class="text-soft">${escapeHtml(formatDateTime(item.created_at))}</div>
                  </td>
                  <td>${renderCollapsibleText(item.content || "", 150)}</td>
                  <td>
                    <div>${escapeHtml(item.role_scope || "-")} / ${escapeHtml(item.source || "-")}</div>
                    <div class="chip-row">${(item.tags || []).map((tag) => `<span class="chip">${escapeHtml(tag)}</span>`).join("")}</div>
                  </td>
                </tr>
              `).join("") || '<tr><td colspan="3" class="text-soft">暂无共同日记。</td></tr>'}
            </tbody>
          </table>
        </div>
      </section>
    `;
  }

  function renderRealityContext(data) {
    const summary = (data && data.summary) || {};
    const location = summary.location || {};
    const weather = summary.weather || {};
    const sources = summary.sources || [];
    const events = (data && data.items) || [];
    const highlights = (data && data.highlights) || {};
    const snapshots = highlights.snapshots || [];
    const audits = highlights.audits || [];
    return `
      <section class="panel-card">
        <div class="panel-header">
          <div>
            <h2>现实锚点</h2>
            <div class="panel-subtitle">天气和只读日程只作为聊天里的轻锚点；这里不会显示完整 ICS URL，也不写入长期记忆。</div>
          </div>
          <div class="inline-group">
            <button class="ghost small" data-action="reality-refresh">刷新现实锚点</button>
          </div>
        </div>
        <form class="filter-row" data-reality-location-form="true">
          <input name="label" value="${escapeHtml(location.label || "")}" placeholder="地点标签">
          <input name="latitude" value="${escapeHtml(location.latitude ?? "")}" placeholder="纬度">
          <input name="longitude" value="${escapeHtml(location.longitude ?? "")}" placeholder="经度">
          <input name="note" value="" placeholder="备注">
          <button class="primary" type="submit">保存地点</button>
        </form>
        <div class="metric-grid">
          <div class="metric-card">
            <div class="metric-label">地点</div>
            <div class="metric-value">${escapeHtml(location.label || "-")}</div>
            <div class="text-soft">${escapeHtml(location.latitude ?? "-")}, ${escapeHtml(location.longitude ?? "-")}</div>
          </div>
          <div class="metric-card">
            <div class="metric-label">天气缓存</div>
            <div class="metric-value">${escapeHtml(weather.status || "-")}</div>
            <div class="text-soft">${escapeHtml(formatDateTime(weather.fetched_at))}</div>
          </div>
          <div class="metric-card">
            <div class="metric-label">日程窗口</div>
            <div class="metric-value">${escapeHtml(summary.lookahead_hours ?? "-")}h</div>
            <div class="text-soft">${escapeHtml(events.length)} events</div>
          </div>
          <div class="metric-card">
            <div class="metric-label">刷新节奏</div>
            <div class="metric-value">${escapeHtml(summary.refresh_minutes ?? "-")}m</div>
            <div class="text-soft">${summary.enabled ? "enabled" : "disabled"}</div>
          </div>
        </div>
        <div class="banner">${escapeHtml(weather.summary_text || "天气暂时没有可用摘要。")}</div>
        <h3>日历订阅</h3>
        <form class="filter-row" data-reality-source-form="true">
          <input name="label" value="" placeholder="日历名称">
          <input name="url" value="" placeholder="ICS / webcal URL，保存后只显示脱敏摘要">
          <label class="inline-label"><input type="checkbox" name="enabled" value="true" checked> 启用</label>
          <button class="primary" type="submit">添加订阅</button>
        </form>
        <div class="table-wrap">
          <table>
            <thead><tr><th>来源</th><th>状态</th><th>脱敏 URL</th><th>操作</th></tr></thead>
            <tbody>
              ${sources.map((source) => `
                <tr>
                  <td>
                    <div>${escapeHtml(source.label || "-")}</div>
                    <div class="text-soft">${escapeHtml(source.source_uid || "-")}</div>
                  </td>
                  <td>${source.enabled ? renderBadge("enabled", "success") : renderBadge("disabled", "danger")} ${source.readonly ? renderBadge("readonly") : ""}</td>
                  <td>${escapeHtml(source.masked_url || "-")}</td>
                  <td>
                    ${source.readonly ? '<span class="text-soft">配置项</span>' : `
                      <button class="ghost small" data-action="reality-source-toggle" data-id="${escapeHtml(source.source_uid)}" data-enabled="${source.enabled ? "false" : "true"}">${source.enabled ? "停用" : "启用"}</button>
                    `}
                  </td>
                </tr>
              `).join("") || '<tr><td colspan="4" class="text-soft">暂无 ICS 订阅。</td></tr>'}
            </tbody>
          </table>
        </div>
        <h3>手动日程</h3>
        <form class="filter-row" data-reality-event-form="true">
          <input name="title" value="" placeholder="日程标题">
          <input name="start_at" value="" placeholder="开始时间，如 2026-04-26T20:00">
          <input name="end_at" value="" placeholder="结束时间，可空">
          <input name="location" value="" placeholder="地点，可空">
          <label class="inline-label"><input type="checkbox" name="is_all_day" value="true"> 全天</label>
          <input name="note" value="" placeholder="备注">
          <button class="primary" type="submit">加入锚点</button>
        </form>
        <div class="table-wrap">
          <table>
            <thead><tr><th>日程</th><th>时间</th><th>来源</th></tr></thead>
            <tbody>
              ${events.map((item) => `
                <tr>
                  <td>
                    <div>${escapeHtml(item.title || "-")}</div>
                    <div class="text-soft">${escapeHtml(item.location || "-")}</div>
                  </td>
                  <td>
                    <div>${escapeHtml(formatDateTime(item.start_at))}</div>
                    <div class="text-soft">${escapeHtml(formatDateTime(item.end_at))}</div>
                  </td>
                  <td>
                    <div>${escapeHtml(item.source_label || item.source_uid || "-")}</div>
                    <div class="text-soft">${item.is_all_day ? "all-day" : "timed"} / ${escapeHtml(item.status || "-")}</div>
                  </td>
                </tr>
              `).join("") || '<tr><td colspan="3" class="text-soft">暂无 48 小时内日程。</td></tr>'}
            </tbody>
          </table>
        </div>
        <h3>最近缓存和失败</h3>
        <div class="table-wrap">
          <table>
            <thead><tr><th>类型</th><th>状态</th><th>摘要</th><th>时间</th></tr></thead>
            <tbody>
              ${snapshots.map((item) => `
                <tr>
                  <td>${escapeHtml(item.source_type || "-")}</td>
                  <td>${escapeHtml(item.status || "-")}</td>
                  <td>${renderCollapsibleText(item.summary_text || item.error_text || "", 120)}</td>
                  <td>${escapeHtml(formatDateTime(item.fetched_at))}</td>
                </tr>
              `).join("") || '<tr><td colspan="4" class="text-soft">暂无缓存。</td></tr>'}
            </tbody>
          </table>
        </div>
        <h3>现实锚点审计</h3>
        <div class="table-wrap">
          <table>
            <thead><tr><th>动作</th><th>状态</th><th>细节</th></tr></thead>
            <tbody>
              ${audits.map((item) => `
                <tr>
                  <td>
                    <div>${escapeHtml(item.source_type || "-")} / ${escapeHtml(item.action || "-")}</div>
                    <div class="text-soft">${escapeHtml(formatDateTime(item.created_at))}</div>
                  </td>
                  <td>${escapeHtml(item.status || "-")}</td>
                  <td>${renderCollapsibleText(item.error_text || JSON.stringify(item.details || {}), 120)}</td>
                </tr>
              `).join("") || '<tr><td colspan="3" class="text-soft">暂无审计。</td></tr>'}
            </tbody>
          </table>
        </div>
      </section>
    `;
  }

  function renderFacts(data) {
    const panel = state.panels.facts;
    const items = (data && data.items) || [];
    return `
      <section class="panel-card">
        <h2>Structured Facts</h2>
        <form class="filter-row" data-panel-form="facts">
          <input name="q" value="${escapeHtml(panel.q)}" placeholder="搜 namespace / key / value">
          <input name="namespace" value="${escapeHtml(panel.namespace)}" placeholder="namespace">
          <button class="primary" type="submit">应用</button>
        </form>
        <div class="table-wrap">
          <table>
            <thead><tr><th>键</th><th>值</th><th>来源</th></tr></thead>
            <tbody>
              ${items
                .map(
                  (item) => `
                    <tr>
                      <td>${escapeHtml(item.namespace)} / ${escapeHtml(item.key)}</td>
                      <td>${renderCollapsibleText(item.value, 120)}</td>
                      <td>confidence ${escapeHtml(formatNumber(item.confidence))} · source ${escapeHtml((item.source_message_ids || []).join(", ") || "-")}</td>
                    </tr>
                  `,
                )
                .join("") || '<tr><td colspan="3" class="text-soft">暂无 structured facts。</td></tr>'}
            </tbody>
          </table>
        </div>
        ${buildPagination(data ? data.meta : null, "facts")}
      </section>
    `;
  }

  function renderRelationships(data) {
    const panel = state.panels.relationships;
    const items = (data && data.items) || [];
    return `
      <section class="panel-card">
        <h2>Relationship States</h2>
        <form class="filter-row" data-panel-form="relationships">
          <input name="q" value="${escapeHtml(panel.q)}" placeholder="搜 dimension / value / note">
          <input name="dimension" value="${escapeHtml(panel.dimension)}" placeholder="dimension">
          <button class="primary" type="submit">应用</button>
        </form>
        <div class="table-wrap">
          <table>
            <thead><tr><th>维度</th><th>内容</th><th>权重</th></tr></thead>
            <tbody>
              ${items
                .map(
                  (item) => `
                    <tr>
                      <td>${escapeHtml(item.dimension)}</td>
                      <td>${renderCollapsibleText(item.value, 120)}<div class="text-soft">${escapeHtml(item.note || "-")}</div></td>
                      <td>${escapeHtml(formatNumber(item.weight))} / ${escapeHtml(formatNumber(item.confidence))}</td>
                    </tr>
                  `,
                )
                .join("") || '<tr><td colspan="3" class="text-soft">暂无 relationship states。</td></tr>'}
            </tbody>
          </table>
        </div>
        ${buildPagination(data ? data.meta : null, "relationships")}
      </section>
    `;
  }

  function renderSummaries(data) {
    const panel = state.panels.summaries;
    const items = (data && data.items) || [];
    return `
      <section class="panel-card">
        <h2>Summary</h2>
        <form class="filter-row" data-panel-form="summaries">
          <input name="q" value="${escapeHtml(panel.q)}" placeholder="搜 summary content">
          <button class="primary" type="submit">应用</button>
        </form>
        <div class="summary-grid">
          ${items
            .map(
              (item) => `
                <article class="summary-card">
                  <h3>v${escapeHtml(item.version)} · ${escapeHtml(item.summary_kind)}</h3>
                  <div class="text-soft">${escapeHtml(formatDateTime(item.updated_at))} · messages ${escapeHtml(item.message_count)}</div>
                  <div>${renderCollapsibleText(item.content, 180)}</div>
                </article>
              `,
            )
            .join("") || '<article class="empty-card"><p>暂无 summary。</p></article>'}
        </div>
        ${buildPagination(data ? data.meta : null, "summaries")}
      </section>
    `;
  }

  function renderSnapshots(data) {
    const panel = state.panels.snapshots;
    const items = (data && data.items) || [];
    return `
      <section class="panel-card">
        <h2>快照 Diff</h2>
        <form class="filter-row" data-panel-form="snapshots">
          <input name="q" value="${escapeHtml(panel.q)}" placeholder="搜 snapshot uid / turn uid">
          <button class="primary" type="submit">应用</button>
        </form>
        <div class="summary-grid">
          ${items
            .map(
              (item) => `
                <article class="summary-card">
                  <h3>${escapeHtml(item.snapshot_uid)}</h3>
                  <div class="text-soft">${escapeHtml(formatDateTime(item.created_at))} · turn ${escapeHtml(item.turn_uid || "-")}</div>
                  <div class="chip-row">${(item.diff.changed_keys || []).map((key) => `<span class="chip">${escapeHtml(key)}</span>`).join("") || '<span class="text-soft">无变更</span>'}</div>
                  ${renderCodeBlock(item.diff.changes)}
                </article>
              `,
            )
            .join("") || '<article class="empty-card"><p>暂无快照。</p></article>'}
        </div>
        ${buildPagination(data ? data.meta : null, "snapshots")}
      </section>
    `;
  }

  function renderTasks(data) {
    const panel = state.panels.tasks;
    const items = (data && data.items) || [];
    return `
      <section class="panel-card">
        <h2>后台任务</h2>
        <form class="filter-row" data-panel-form="tasks">
          <input name="q" value="${escapeHtml(panel.q)}" placeholder="搜 task uid / type / request id">
          <input name="status" value="${escapeHtml(panel.status)}" placeholder="status">
          <input name="task_type" value="${escapeHtml(panel.task_type)}" placeholder="task_type">
          <select name="scope_mode">
            <option value="active" ${panel.scope_mode === "active" ? "selected" : ""}>active scope</option>
            <option value="all" ${panel.scope_mode === "all" ? "selected" : ""}>all scope</option>
          </select>
          <button class="primary" type="submit">应用</button>
        </form>
        <div class="table-wrap">
          <table>
            <thead><tr><th>任务</th><th>状态</th><th>payload/result</th><th>操作</th></tr></thead>
            <tbody>
              ${items
                .map(
                  (item) => `
                    <tr>
                      <td>
                        <div><strong>${escapeHtml(item.task_uid)}</strong></div>
                        <div class="text-soft">${escapeHtml(item.task_type)} · request ${escapeHtml(item.request_id || "-")}</div>
                        <div class="text-soft">${escapeHtml(formatDateTime(item.created_at))}</div>
                      </td>
                      <td>
                        <div>${renderBadge(item.status, item.status === "retrying" ? "danger" : "neutral")}</div>
                        <div>attempts ${escapeHtml(item.attempts)} / ${escapeHtml(item.max_attempts)}</div>
                        <div>next_retry ${escapeHtml(formatDateTime(item.next_retry_at))}</div>
                      </td>
                      <td>${renderCodeBlock({ payload: item.payload, result: item.result, last_error: item.last_error })}</td>
                      <td class="chip-row">
                        <button class="ghost small" data-action="retry-task" data-id="${escapeHtml(item.task_uid)}">重试</button>
                        <button class="ghost small" data-action="boost-task" data-id="${escapeHtml(item.task_uid)}">提权</button>
                        <button class="danger small" data-action="cancel-task" data-id="${escapeHtml(item.task_uid)}">取消</button>
                      </td>
                    </tr>
                  `,
                )
                .join("") || '<tr><td colspan="4" class="text-soft">暂无后台任务。</td></tr>'}
            </tbody>
          </table>
        </div>
        ${buildPagination(data ? data.meta : null, "tasks")}
      </section>
    `;
  }

  function renderErrors(data) {
    const panel = state.panels.errors;
    const items = (data && data.items) || [];
    const statusCounts = (data && data.summary && data.summary.status_counts) || {};
    return `
      <section class="panel-card">
        <h2>错误闭环</h2>
        <form class="filter-row" data-panel-form="errors">
          <input name="q" value="${escapeHtml(panel.q)}" placeholder="搜 error uid / request id / details">
          <input name="status" value="${escapeHtml(panel.status)}" placeholder="status">
          <input name="component" value="${escapeHtml(panel.component)}" placeholder="component">
          <button class="primary" type="submit">应用</button>
        </form>
        <div class="chip-row">
          ${Object.entries(statusCounts)
            .map(([key, value]) => `<span class="chip">${escapeHtml(key)}: ${escapeHtml(value)}</span>`)
            .join("")}
        </div>
        <div class="table-wrap">
          <table>
            <thead><tr><th>错误</th><th>关联</th><th>详情</th><th>动作</th></tr></thead>
            <tbody>
              ${items
                .map(
                  (item) => `
                    <tr>
                      <td>
                        <div><strong>${escapeHtml(item.error_uid)}</strong></div>
                        <div>${escapeHtml(item.component)} / ${escapeHtml(item.severity)}</div>
                        <div class="text-soft">${escapeHtml(item.message)}</div>
                      </td>
                      <td>
                        <div>request: ${escapeHtml(item.request_id || "-")}</div>
                        <div>turn: ${escapeHtml(item.related_turn_uid || "-")}</div>
                        <div>task: ${escapeHtml(item.related_task_uid || "-")}</div>
                      </td>
                      <td>${renderCodeBlock(item.details)}</td>
                      <td class="chip-row">
                        <button class="ghost small" data-action="error-status" data-id="${escapeHtml(item.error_uid)}" data-status="processed">已处理</button>
                        <button class="ghost small" data-action="error-status" data-id="${escapeHtml(item.error_uid)}" data-status="ignored">已忽略</button>
                        <button class="danger small" data-action="error-status" data-id="${escapeHtml(item.error_uid)}" data-status="archived">已归档</button>
                      </td>
                    </tr>
                  `,
                )
                .join("") || '<tr><td colspan="4" class="text-soft">暂无错误事件。</td></tr>'}
            </tbody>
          </table>
        </div>
        ${buildPagination(data ? data.meta : null, "errors")}
      </section>
    `;
  }

  function renderPerformance(data) {
    if (!data) return '<section class="empty-card"><p>暂无性能数据。</p></section>';
    const perf = data.performance || {};
    const experience = data.experience || {};
    const jsonExtraction = data.json_extraction || {};
    return `
      <section class="panel-card">
        <div class="panel-header">
          <div>
            <h2>性能成本</h2>
            <div class="panel-subtitle">增加 P95/P99、模型成本、失败重试成本和 JSON 解析统计。</div>
          </div>
        </div>
        ${renderSummaryCards([
          { title: "Turn 数", value: perf.turn_count ?? 0, note: `scope ${perf.scope_mode || "all"}` },
          { title: "平均延迟", value: `${formatNumber(perf.avg_latency_ms || 0, 1)}ms`, note: "整体平均" },
          { title: "P95", value: `${formatNumber((perf.percentiles_ms || {}).p95 || 0, 1)}ms`, note: "尾延迟" },
          { title: "P99", value: `${formatNumber((perf.percentiles_ms || {}).p99 || 0, 1)}ms`, note: "异常抖动" },
          { title: "Fallback Rate", value: `${formatNumber((perf.fallback_rate || 0) * 100, 1)}%`, note: "模型退避占比" },
          { title: "结构化输出", value: escapeHtml((experience.structure_distribution && Object.keys(experience.structure_distribution).length) || 0), note: "不同结构分布" },
        ])}
        <div class="summary-grid">
          <article class="summary-card">
            <h3>Model Cost</h3>
            ${renderCodeBlock(perf.cost_by_model || {})}
          </article>
          <article class="summary-card">
            <h3>Stage Latency Avg</h3>
            ${renderCodeBlock(perf.stage_latency_avg_ms || {})}
          </article>
          <article class="summary-card">
            <h3>JSON Extraction Stats</h3>
            ${renderCodeBlock(jsonExtraction)}
          </article>
        </div>
      </section>
    `;
  }

  function renderHealth(data) {
    if (!data) return '<section class="empty-card"><p>暂无健康数据。</p></section>';
    return `
      <section class="panel-card">
        <h2>健康趋势</h2>
        <div class="summary-grid">
          ${(data.items || [])
            .map(
              (item) => `
                <article class="summary-card">
                  <h3>${escapeHtml(item.component)}</h3>
                  <div>${renderBadge(item.status, item.status === "ok" || item.status === "healthy" ? "success" : "danger")}</div>
                  <div class="text-soft">${escapeHtml(item.message)}</div>
                  <div>latency: ${escapeHtml(formatNumber(item.latency_ms, 1))}ms</div>
                  ${renderSparkline((data.trends && data.trends[item.component] && data.trends[item.component].history) || [])}
                </article>
              `,
            )
            .join("")}
        </div>
      </section>
    `;
  }

  function renderSecurity(data) {
    if (!data) return '<section class="empty-card"><p>暂无安全数据。</p></section>';
    return `
      <section class="panel-card">
        <h2>安全控制</h2>
        ${renderSummaryCards([
          { title: "失败尝试", value: data.metrics.failed_last_window ?? 0, note: "近窗口失败数" },
          { title: "锁定次数", value: data.metrics.lockouts_last_window ?? 0, note: "近窗口锁定数" },
          { title: "改密要求", value: data.password_policy.change_required ? "是" : "否", note: "首次登录要求" },
          { title: "Secure Cookie", value: data.password_policy.session_https_only ? "启用" : "关闭", note: "会话 cookie 策略" },
        ])}
        <div class="summary-grid">
          <article class="summary-card">
            <h3>安全事件</h3>
            ${renderCodeBlock(data.events || [])}
          </article>
          <article class="summary-card">
            <h3>审计片段</h3>
            ${renderCodeBlock(data.audits || [])}
          </article>
        </div>
      </section>
    `;
  }

  function renderAudits(data) {
    const panel = state.panels.audits;
    const items = (data && data.items) || [];
    return `
      <section class="panel-card">
        <h2>审计日志</h2>
        <form class="filter-row" data-panel-form="audits">
          <input name="q" value="${escapeHtml(panel.q)}" placeholder="搜 action / target / actor">
          <button class="primary" type="submit">应用</button>
        </form>
        <div class="table-wrap">
          <table>
            <thead><tr><th>动作</th><th>详情</th><th>撤销</th></tr></thead>
            <tbody>
              ${items
                .map(
                  (item) => `
                    <tr>
                      <td>
                        <div>${escapeHtml(item.action_type)}</div>
                        <div class="text-soft">${escapeHtml(item.actor_username)} / ${escapeHtml(formatDateTime(item.created_at))}</div>
                      </td>
                      <td>${renderCodeBlock(item.details)}</td>
                      <td>
                        ${item.undo_available && item.status === "applied" ? `<button class="ghost small" data-action="undo-audit" data-id="${escapeHtml(item.audit_uid)}">撤销</button>` : '<span class="text-soft">不可撤销</span>'}
                      </td>
                    </tr>
                  `,
                )
                .join("") || '<tr><td colspan="3" class="text-soft">暂无审计记录。</td></tr>'}
            </tbody>
          </table>
        </div>
        ${buildPagination(data ? data.meta : null, "audits")}
      </section>
    `;
  }

  function renderLogs(data) {
    const panel = state.panels.logs;
    const items = (data && data.items) || [];
    const downloadUrl = data && data.summary ? data.summary.download_url : "/api/logs/download";
    return `
      <section class="panel-card">
        <div class="panel-header">
          <div>
            <h2>运行日志</h2>
            <div class="panel-subtitle">支持关键字过滤、下载和复制。P2-1: 下载的链接是基于当前上方筛选条件的切片，如未筛选则是全量。P2-2: 行号仅供界面参考，并非原日志文件真实行号。</div>
          </div>
          <div class="chip-row">
            <a class="ghost small" href="${escapeHtml(downloadUrl)}">下载日志</a>
            <button class="ghost small" data-action="copy-logs">复制当前筛选</button>
          </div>
        </div>
        <form class="filter-row" data-panel-form="logs">
          <input name="q" value="${escapeHtml(panel.q)}" placeholder="搜日志关键字">
          <button class="primary" type="submit">应用</button>
        </form>
        <div class="table-wrap">
          <table>
            <thead><tr><th>行号</th><th>内容</th></tr></thead>
            <tbody>
              ${items
                .map(
                  (item) => `
                    <tr>
                      <td class="nowrap">${escapeHtml(item.line_no)}</td>
                      <td><pre>${escapeHtml(item.text)}</pre></td>
                    </tr>
                  `,
                )
                .join("") || '<tr><td colspan="2" class="text-soft">暂无日志。</td></tr>'}
            </tbody>
          </table>
        </div>
        ${buildPagination(data ? data.meta : null, "logs")}
      </section>
    `;
  }

  async function doAction(path, method = "POST", body = null) {
    clearGlobalError();
    const options = { method };
    if (body) options.body = JSON.stringify(body);
    const { payload } = await apiFetch(path, options);
    if (payload.message) setSuccess(payload.message);
    return payload;
  }

  async function refreshCurrentPanel() {
    try {
      clearGlobalError();
      if (state.activeTab === "overview") {
        await loadScopes();
      }
      await fetchPanel(state.activeTab);
    } catch (error) {
      setGlobalError(error.message || String(error));
    }
  }

  async function applyPanelForm(panelKey, form) {
    const panelState = state.panels[panelKey];
    const formData = new FormData(form);
    Object.keys(panelState).forEach((key) => {
      if (Array.isArray(panelState[key])) return;
      if (formData.has(key)) panelState[key] = formData.get(key);
    });
    panelState.page = 1;
    if (panelKey === "search") {
      state.globalQuery = String(panelState.q || "");
    }
    await refreshCurrentPanel();
  }

  function switchTab(tabKey) {
    state.activeTab = tabKey;
    localStorage.setItem("zhiwei.activeTab", tabKey);
    document.querySelectorAll(".tab-button").forEach((button) => {
      button.classList.toggle("active", button.dataset.tab === tabKey);
    });
    renderActivePanel();
    refreshCurrentPanel();
  }

  async function handlePanelAction(target) {
    const action = target.dataset.action;
    const id = target.dataset.id;
    if (action === "switch-tab") {
      switchTab(target.dataset.targetTab);
      return;
    }
    if (action === "archive-memory") {
      await doAction(`/api/memories/${id}/archive`);
      await refreshCurrentPanel();
      return;
    }
    if (action === "approve-candidate") {
      const noteInput = document.getElementById(`note-${id}`);
      await doAction(`/api/candidates/${id}/approve`, "POST", { note: noteInput?.value || "" });
      if (noteInput) noteInput.value = "";
      await refreshCurrentPanel();
      return;
    }
    if (action === "reject-candidate") {
      const noteInput = document.getElementById(`note-${id}`);
      await doAction(`/api/candidates/${id}/reject`, "POST", { note: noteInput?.value || "" });
      if (noteInput) noteInput.value = "";
      await refreshCurrentPanel();
      return;
    }
    if (action === "reopen-candidate") {
      await doAction(`/api/candidates/${id}/reopen`);
      await refreshCurrentPanel();
      return;
    }
    if (action === "select-all-candidates") {
      const items = (((state.panels.candidates || {}).data || {}).items || []).map((item) => item.candidate_uid);
      state.panels.candidates.selected = target.checked ? items : [];
      document.querySelectorAll('[data-action="toggle-candidate"]').forEach((checkbox) => {
        checkbox.checked = target.checked;
      });
      updateCandidateBatchControls();
      return;
    }
    if (action === "toggle-candidate") {
      const selected = new Set(state.panels.candidates.selected || []);
      if (target.checked) selected.add(id);
      else selected.delete(id);
      state.panels.candidates.selected = Array.from(selected);
      updateCandidateBatchControls();
      return;
    }
    if (action === "batch-candidate-approve" || action === "batch-candidate-reject") {
      const actionName = action.endsWith("approve") ? "approve" : "reject";
      const noteInput = document.getElementById("candidate-batch-review-note");
      await doAction("/api/candidates/batch-review", "POST", {
        candidate_uids: state.panels.candidates.selected || [],
        action: actionName,
        note: noteInput?.value || "",
      });
      state.panels.candidates.selected = [];
      if (noteInput) noteInput.value = "";
      await refreshCurrentPanel();
      return;
    }
    if (action === "proactive-feedback") {
      await doAction(`/api/proactive/${id}/feedback`, "POST", {
        feedback: target.dataset.feedback || "good",
        note: "",
      });
      await refreshCurrentPanel();
      return;
    }
    if (action === "proactive-preferences") {
      const body = {};
      if (target.dataset.enabled !== undefined) body.enabled = target.dataset.enabled === "true";
      if (target.dataset.cadence) body.cadence = target.dataset.cadence;
      await doAction("/api/proactive/preferences", "PATCH", body);
      await refreshCurrentPanel();
      return;
    }
    if (action === "companion-day-regenerate") {
      await doAction("/api/companion-day/regenerate", "POST");
      await refreshCurrentPanel();
      return;
    }
    if (action === "companion-day-feedback") {
      await doAction(`/api/companion-day/events/${id}/feedback`, "POST", {
        feedback: target.dataset.feedback || "good",
        note: "",
      });
      await refreshCurrentPanel();
      return;
    }
    if (action === "reality-refresh") {
      await doAction("/api/reality-context/refresh", "POST");
      await refreshCurrentPanel();
      return;
    }
    if (action === "reality-source-toggle") {
      await doAction(`/api/reality-context/calendar-sources/${id}`, "PATCH", {
        enabled: target.dataset.enabled === "true",
      });
      await refreshCurrentPanel();
      return;
    }
    if (action === "retry-task") {
      await doAction(`/api/tasks/${id}/retry`);
      await refreshCurrentPanel();
      return;
    }
    if (action === "boost-task") {
      await doAction(`/api/tasks/${id}/boost`, "POST", { priority: 1.0 });
      await refreshCurrentPanel();
      return;
    }
    if (action === "cancel-task") {
      await doAction(`/api/tasks/${id}/cancel`);
      await refreshCurrentPanel();
      return;
    }
    if (action === "error-status") {
      await doAction(`/api/errors/${id}/status`, "POST", { status: target.dataset.status });
      await refreshCurrentPanel();
      return;
    }
    if (action === "undo-audit") {
      await doAction(`/api/audits/${id}/undo`);
      await refreshCurrentPanel();
      return;
    }
    if (action === "copy-logs") {
      const items = (((state.panels.logs || {}).data || {}).items || []).map((item) => item.text).join("\n");
      await navigator.clipboard.writeText(items);
      setSuccess("当前筛选日志已复制。");
      return;
    }
    if (action === "page-prev" || action === "page-next") {
      const panelKey = target.dataset.panel;
      const panelState = state.panels[panelKey];
      const delta = action === "page-prev" ? -1 : 1;
      panelState.page = Math.max(Number(panelState.page || 1) + delta, 1);
      if (panelKey === state.activeTab) {
        await refreshCurrentPanel();
      }
      return;
    }
  }

  async function submitPasswordChange() {
    const body = {
      old_password: document.getElementById("password-old").value,
      new_password: document.getElementById("password-new").value,
      confirm_password: document.getElementById("password-confirm").value,
    };
    await doAction("/api/account/password", "POST", body);
    document.getElementById("password-dialog").close();
  }

  async function logout() {
    await doAction("/api/logout");
    window.location.href = "/login";
  }

  function scheduleRefresh() {
    if (state.timerId) window.clearInterval(state.timerId);
    if (state.refreshMode === "paused" || state.refreshMode === "manual") return;
    const delay = state.refreshMode === "15s" ? 15000 : 5000;
    state.timerId = window.setInterval(() => {
      refreshCurrentPanel();
    }, delay);
  }

  async function setActiveScope() {
    const select = document.getElementById("scope-select");
    if (!select || !select.value) return;
    const [user_id, conversation_id] = select.value.split("::");
    await doAction("/api/scopes/active", "POST", { user_id, conversation_id });
    await loadScopes();
    await refreshCurrentPanel();
  }

  async function initDashboard() {
    setBodyPreferences();
    document.getElementById("theme-select").value = state.theme;
    document.getElementById("density-select").value = state.density;
    const refreshSelect = document.getElementById("refresh-mode-select");
    (bootstrap.refreshModes || ["manual", "paused", "5s", "15s"]).forEach((mode) => {
      const option = document.createElement("option");
      option.value = mode;
      option.textContent = mode;
      refreshSelect.appendChild(option);
    });
    refreshSelect.value = state.refreshMode;
    document.querySelectorAll(".tab-button").forEach((button) => {
      button.addEventListener("click", () => switchTab(button.dataset.tab));
    });
    document.getElementById("scope-apply-button").addEventListener("click", setActiveScope);
    document.getElementById("refresh-now-button").addEventListener("click", refreshCurrentPanel);
    document.getElementById("global-search-button").addEventListener("click", () => {
      state.globalQuery = document.getElementById("global-search-input").value.trim();
      state.panels.search.q = state.globalQuery;
      switchTab("search");
    });
    // P1-2: 搜索框直接回车搜索
    document.getElementById("global-search-input").addEventListener("keypress", (event) => {
      if (event.key === "Enter") {
        event.preventDefault();
        state.globalQuery = document.getElementById("global-search-input").value.trim();
        state.panels.search.q = state.globalQuery;
        switchTab("search");
      }
    });
    document.getElementById("logout-button").addEventListener("click", logout);
    document.getElementById("change-password-button").addEventListener("click", () => document.getElementById("password-dialog").showModal());
    document.getElementById("password-cancel").addEventListener("click", () => document.getElementById("password-dialog").close());
    document.getElementById("password-form").addEventListener("submit", async (event) => {
      event.preventDefault();
      try {
        await submitPasswordChange();
      } catch (error) {
        setGlobalError(error.message || String(error));
      }
    });
    document.getElementById("theme-select").addEventListener("change", (event) => {
      state.theme = event.target.value;
      localStorage.setItem("zhiwei.theme", state.theme);
      setBodyPreferences();
    });
    document.getElementById("density-select").addEventListener("change", (event) => {
      state.density = event.target.value;
      localStorage.setItem("zhiwei.density", state.density);
      setBodyPreferences();
    });
    refreshSelect.addEventListener("change", (event) => {
      state.refreshMode = event.target.value;
      localStorage.setItem("zhiwei.refreshMode", state.refreshMode);
      scheduleRefresh();
    });
    panelHost.addEventListener("click", async (event) => {
      const target = event.target.closest("[data-action]");
      if (!target) return;
      try {
        await handlePanelAction(target);
      } catch (error) {
        setGlobalError(error.message || String(error));
      }
    });
    panelHost.addEventListener("submit", async (event) => {
      const presenceForm = event.target.closest("[data-presence-form]");
      if (presenceForm) {
        event.preventDefault();
        const formData = new FormData(presenceForm);
        const body = {};
        formData.forEach((value, key) => {
          if (String(value).trim() !== "") body[key] = value;
        });
        if (body.user_sleep_state_confidence !== undefined) {
          body.user_sleep_state_confidence = Number(body.user_sleep_state_confidence);
        }
        try {
          await doAction("/api/presence", "POST", body);
          await refreshCurrentPanel();
        } catch (error) {
          setGlobalError(error.message || String(error));
        }
        return;
      }
      const companionDayForm = event.target.closest("[data-companion-day-form]");
      if (companionDayForm) {
        event.preventDefault();
        const formData = new FormData(companionDayForm);
        const body = {};
        formData.forEach((value, key) => {
          if (String(value).trim() !== "") body[key] = value;
        });
        if (body.longing_level !== undefined) {
          body.longing_level = Number(body.longing_level);
        }
        const quietMode = companionDayForm.querySelector('[name="quiet_mode"]');
        body.quiet_mode = Boolean(quietMode && quietMode.checked);
        try {
          await doAction("/api/companion-day", "PATCH", body);
          await refreshCurrentPanel();
        } catch (error) {
          setGlobalError(error.message || String(error));
        }
        return;
      }
      const realityLocationForm = event.target.closest("[data-reality-location-form]");
      if (realityLocationForm) {
        event.preventDefault();
        const formData = new FormData(realityLocationForm);
        const body = {
          label: formData.get("label") || "",
          latitude: Number(formData.get("latitude") || 0),
          longitude: Number(formData.get("longitude") || 0),
          note: formData.get("note") || "",
        };
        try {
          await doAction("/api/reality-context/location", "PATCH", body);
          await refreshCurrentPanel();
        } catch (error) {
          setGlobalError(error.message || String(error));
        }
        return;
      }
      const realitySourceForm = event.target.closest("[data-reality-source-form]");
      if (realitySourceForm) {
        event.preventDefault();
        const formData = new FormData(realitySourceForm);
        const enabledBox = realitySourceForm.querySelector('[name="enabled"]');
        const body = {
          label: formData.get("label") || "",
          url: formData.get("url") || "",
          enabled: Boolean(enabledBox && enabledBox.checked),
        };
        try {
          await doAction("/api/reality-context/calendar-sources", "POST", body);
          realitySourceForm.reset();
          await refreshCurrentPanel();
        } catch (error) {
          setGlobalError(error.message || String(error));
        }
        return;
      }
      const realityEventForm = event.target.closest("[data-reality-event-form]");
      if (realityEventForm) {
        event.preventDefault();
        const formData = new FormData(realityEventForm);
        const allDayBox = realityEventForm.querySelector('[name="is_all_day"]');
        const body = {
          title: formData.get("title") || "",
          start_at: formData.get("start_at") || "",
          end_at: formData.get("end_at") || "",
          location: formData.get("location") || "",
          is_all_day: Boolean(allDayBox && allDayBox.checked),
          note: formData.get("note") || "",
        };
        try {
          await doAction("/api/reality-context/manual-events", "POST", body);
          realityEventForm.reset();
          await refreshCurrentPanel();
        } catch (error) {
          setGlobalError(error.message || String(error));
        }
        return;
      }
      const form = event.target.closest("[data-panel-form]");
      if (!form) return;
      event.preventDefault();
      try {
        await applyPanelForm(form.dataset.panelForm, form);
      } catch (error) {
        setGlobalError(error.message || String(error));
      }
    });
    window.setActiveScope = setActiveScope;
    window.refreshDashboard = refreshCurrentPanel;
    await loadScopes();
    scheduleRefresh();
    switchTab(state.activeTab);
    if (bootstrap.forcePasswordChange) {
      document.getElementById("password-dialog").showModal();
      setGlobalError("当前账号需要先修改密码，写操作才会恢复。");
    }
  }

  async function initLoginPage() {
    const toggle = document.getElementById("toggle-password");
    const passwordInput = document.getElementById("password-input");
    const errorNode = document.getElementById("login-error");
    toggle.addEventListener("click", () => {
      const visible = passwordInput.type === "text";
      passwordInput.type = visible ? "password" : "text";
      toggle.textContent = visible ? "显示" : "隐藏";
    });
    document.getElementById("login-form").addEventListener("submit", async (event) => {
      event.preventDefault();
      errorNode.classList.add("hidden");
      try {
        const body = {
          username: document.getElementById("username-input").value.trim(),
          password: document.getElementById("password-input").value,
        };
        await apiFetch("/api/login", { method: "POST", body: JSON.stringify(body) });
        window.location.href = "/";
      } catch (error) {
        errorNode.textContent = error.message || String(error);
        errorNode.classList.remove("hidden");
      }
    });
  }

  if (document.body.classList.contains("dashboard-page")) {
    initDashboard().catch((error) => setGlobalError(error.message || String(error)));
  } else if (document.body.classList.contains("login-page")) {
    initLoginPage();
  }
})();
