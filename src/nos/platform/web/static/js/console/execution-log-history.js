/**
 * execution-log-history.js
 * Renders the Execution Log (history) tab.
 *
 * Public API (window.__execHistory):
 *   .load()         — fetch & render history from REST API
 *   .refresh()      — alias for load()
 *   .clear()        — clear rendered list (no DB delete)
 */
(function () {
  "use strict";

  /* ── DOM refs (resolved lazily) ─────────────────────────── */
  let _root = null;          // #exec-history-root
  let _toolbar = null;       // toolbar with refresh button

  function root() {
    if (!_root) _root = document.getElementById("exec-history-root");
    return _root;
  }

  /* ── Status badge style maps ─────────────────────────────── */
  const STATUS_CLASS = {
    running:   "exec-badge--running",
    completed: "exec-badge--ok",
    success:   "exec-badge--ok",
    error:     "exec-badge--error",
    cancelled: "exec-badge--warn",
  };

  const STATUS_ICON = {
    running:   "⟳",
    completed: "✓",
    success:   "✓",
    error:     "✕",
    cancelled: "⊘",
  };

  /* ── Helpers ─────────────────────────────────────────────── */
  function fmtDate(ts) {
    if (!ts) return "—";
    const d = new Date(ts * 1000);
    return d.toLocaleDateString(undefined, { day: "2-digit", month: "short", year: "numeric" });
  }

  function fmtDateKey(ts) {
    if (!ts) return "unknown";
    const d = new Date(ts * 1000);
    return d.toISOString().slice(0, 10); // "YYYY-MM-DD"
  }

  function fmtTime(ts) {
    if (!ts) return "";
    const d = new Date(ts * 1000);
    return d.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit", second: "2-digit" });
  }

  function groupByDay(runs) {
    const map = {};
    for (const r of runs) {
      const key = fmtDateKey(r.started_at);
      if (!map[key]) map[key] = { label: fmtDate(r.started_at), items: [] };
      map[key].items.push(r);
    }
    return Object.entries(map).sort((a, b) => b[0].localeCompare(a[0]));
  }

  /* ── Render ──────────────────────────────────────────────── */
  function renderEmpty() {
    root().innerHTML = `
      <div class="exec-history-empty">
        <span class="exec-history-empty__icon">📋</span>
        <p>No executions yet.</p>
        <p class="exec-history-empty__hint">Run a node or workflow to populate the history.</p>
      </div>`;
  }

  function renderRow(run) {
    const statusCls = STATUS_CLASS[run.status] || "exec-badge--warn";
    const statusIcon = STATUS_ICON[run.status] || "?";
    const hasFile = !!run.execution_log;

    const row = document.createElement("div");
    row.className = "exec-history-row";
    row.dataset.executionId = run.execution_id;

    row.innerHTML = `
      <span class="exec-badge ${statusCls}" title="${run.status}">${statusIcon}</span>
      <span class="exec-row__type">${run.execution_type}</span>
      <span class="exec-row__plugin" title="${run.plugin_id || ''}">${run.plugin_id || "—"}</span>
      <span class="exec-row__time">${fmtTime(run.started_at)}</span>
      <span class="exec-row__elapsed">${run.elapsed_time || "—"}</span>
      <span class="exec-row__msg" title="${_esc(run.message || '')}">${_esc(run.message || "")}</span>
      <span class="exec-row__actions">
        <button type="button" class="exec-row__icon-btn" title="Download full saved result (JSON) or run metadata if no file was saved"
                data-exec-action="download" data-exec-id="${_esc(run.execution_id)}" data-has-file="${hasFile ? "1" : "0"}">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="14" height="14" aria-hidden="true"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>
        </button>
        <button type="button" class="exec-row__icon-btn exec-row__icon-btn--primary" title="Open in Result document (Terminal → Result)"
                data-exec-action="open-result" data-exec-id="${_esc(run.execution_id)}">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="14" height="14" aria-hidden="true"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/><line x1="10" y1="9" x2="8" y2="9"/></svg>
        </button>
      </span>`;

    row.querySelectorAll("[data-exec-action]").forEach((btn) => {
      btn.addEventListener("click", (ev) => {
        ev.stopPropagation();
        const id = btn.getAttribute("data-exec-id");
        const action = btn.getAttribute("data-exec-action");
        if (!id) return;
        if (action === "download") {
          _downloadFullResult(id, btn.getAttribute("data-has-file") === "1");
        } else if (action === "open-result" && window.__workspaceOpenExecutionFromHistory) {
          window.__workspaceOpenExecutionFromHistory(id, run);
        }
      });
    });

    return row;
  }

  function renderGroup(dateLabel, items) {
    const groupId = `exec-group-${dateLabel.replace(/\s/g, "-")}`;
    const wrap = document.createElement("div");
    wrap.className = "exec-history-group";

    const header = document.createElement("div");
    header.className = "exec-history-group__header";
    header.innerHTML = `
      <span class="exec-history-group__arrow">▾</span>
      <span class="exec-history-group__date">${dateLabel}</span>
      <span class="exec-history-group__count">${items.length} run${items.length !== 1 ? "s" : ""}</span>`;

    const body = document.createElement("div");
    body.className = "exec-history-group__body";
    body.id = groupId;

    // Column header row
    body.innerHTML = `
      <div class="exec-history-row exec-history-row--header">
        <span></span>
        <span>Type</span>
        <span>Plugin</span>
        <span>Time</span>
        <span>Elapsed</span>
        <span>Message</span>
        <span class="exec-history-row__actions-hdr">Actions</span>
      </div>`;

    for (const run of items) body.appendChild(renderRow(run));

    // Toggle collapse
    let collapsed = false;
    header.addEventListener("click", () => {
      collapsed = !collapsed;
      body.style.display = collapsed ? "none" : "";
      header.querySelector(".exec-history-group__arrow").textContent = collapsed ? "▸" : "▾";
    });

    wrap.appendChild(header);
    wrap.appendChild(body);
    return wrap;
  }

  function render(runs) {
    const el = root();
    if (!el) return;
    el.innerHTML = "";

    if (!runs || runs.length === 0) {
      renderEmpty();
      return;
    }

    const groups = groupByDay(runs);
    for (const [_key, { label, items }] of groups) {
      el.appendChild(renderGroup(label, items));
    }
  }

  /* ── Download full result (saved JSON file) or execution_run metadata ── */
  async function _downloadFullResult(executionId, hasFile) {
    if (hasFile) {
      const url = `/api/execution-run/download/${encodeURIComponent(executionId)}`;
      const a = document.createElement("a");
      a.href = url;
      a.download = `${executionId}-NodeOrWorkflowResult.json`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      return;
    }
    try {
      const rj = await fetch(
        `/api/execution-run/result-json/${encodeURIComponent(executionId)}`
      );
      if (rj.ok) {
        const body = await rj.json();
        if (body.payload != null) {
          const blob = new Blob([JSON.stringify(body.payload, null, 2)], {
            type: "application/json",
          });
          const url = URL.createObjectURL(blob);
          const a = document.createElement("a");
          a.href = url;
          a.download = `${executionId}-NodeOrWorkflowResult.json`;
          document.body.appendChild(a);
          a.click();
          document.body.removeChild(a);
          URL.revokeObjectURL(url);
          return;
        }
      }
      const resp = await fetch(`/api/execution-run/${encodeURIComponent(executionId)}`);
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      const data = await resp.json();
      const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `${executionId}-execution-run-header-only.json`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
    } catch (err) {
      alert("Download failed: " + (err && err.message ? err.message : String(err)));
    }
  }

  /* ── Fetch & load ────────────────────────────────────────── */
  async function load() {
    const el = root();
    if (!el) return;

    el.innerHTML = `<div class="exec-history-loading">Loading…</div>`;

    try {
      const resp = await fetch("/api/execution-run/history?limit=200");
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      const data = await resp.json();
      render(data);
    } catch (err) {
      el.innerHTML = `<div class="exec-history-error">Failed to load history: ${_esc(err.message)}</div>`;
    }
  }

  /* ── Escape helper ───────────────────────────────────────── */
  function _esc(s) {
    return String(s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  /* ── Init: wire refresh button + tab activation ─────────── */
  function init() {
    // Refresh button
    const btn = document.getElementById("exec-history-refresh");
    if (btn) btn.addEventListener("click", load);

    // History tab has no panel-tab button (opened from header menu); observe panel visibility
    const historyTab = document.getElementById("tab-history");
    if (historyTab) {
      const onShow = () => {
        if (historyTab.classList.contains("active")) setTimeout(load, 50);
      };
      const mo = new MutationObserver(onShow);
      mo.observe(historyTab, { attributes: true, attributeFilter: ["class"] });
      onShow();
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }

  /* ── Public API ──────────────────────────────────────────── */
  window.__execHistory = { load, refresh: load, clear: () => { if (root()) root().innerHTML = ""; } };
})();
