"use strict";

// Called by Python via window.evaluate_js(f"onJobEvent({json.dumps(payload)})")
// — see claude_tidy/webui/jobs.py. Dispatches a CustomEvent so any Alpine
// component can listen without a global mutable job registry.
window.onJobEvent = function (name, payload) {
  window.dispatchEvent(new CustomEvent("ct:" + name, { detail: payload }));
};

function humanSize(n) {
  if (n < 1024) return n + " B";
  const units = ["KB", "MB", "GB"];
  let v = n / 1024;
  for (const u of units) {
    if (v < 1024 || u === "GB") return v.toFixed(u === "KB" ? 0 : 1) + " " + u;
    v /= 1024;
  }
  return v.toFixed(1) + " GB";
}

function relativeTime(ts) {
  if (!ts) return "?";
  const delta = Date.now() / 1000 - ts;
  if (delta < 60) return "vừa xong";
  if (delta < 3600) return Math.floor(delta / 60) + " phút trước";
  if (delta < 86400) return Math.floor(delta / 3600) + " giờ trước";
  const days = Math.floor(delta / 86400);
  if (days < 30) return days + " ngày trước";
  return new Date(ts * 1000).toISOString().slice(0, 10);
}

function riskBadge(session) {
  if (session.risk === "danger") {
    return { cls: "ct-badge ct-badge-danger",
             text: session.active_pid ? `Đang chạy · PID ${session.active_pid}` : "Đang chạy" };
  }
  if (session.risk === "warning") {
    return { cls: "ct-badge ct-badge-warning",
             text: session.activity === "maybe_active" ? "Có thể active" : "Mới dùng (<24h)" };
  }
  return { cls: "ct-badge ct-badge-safe", text: "An toàn" };
}

function api(name, ...args) {
  return window.pywebview.api[name](...args);
}

// eslint-disable-next-line no-unused-vars
function app() {
  return {
    activeTab: "sessions",
    tabsLoaded: { sessions: false, cache: false, index: false, settings: false },
    statusLeft: "Đang quét…",
    statusRight: "",

    // --- Sessions tab ---
    projects: [],
    projectFilter: "",
    selectedProjectId: null,
    sessions: [],
    project: null,
    checked: {},
    riskFilter: null,
    scanning: false,
    includeWtChecked: false,
    projectMenu: null, // {x, y, project} — right-click menu on a sidebar row

    // --- Cache tab ---
    cacheGroups: [],
    cacheChecked: {},
    claudeDesktopPid: null,

    // --- Index tab ---
    orphanEntries: [],
    selectedOrphanId: null,

    // --- Settings tab ---
    settings: {},
    settingsStatus: "",
    settingsStatusOk: true,

    // --- Delete flow (shared) ---
    preview: null, // {token, will_delete, needs_confirmation, skipped, typed_name_required}
    previewChecked: {},
    typedName: "",
    progress: null, // {phase, done, total, current}
    result: null,
    activeJobId: null,
    deleteBusy: false,

    async init() {
      window.addEventListener("ct:job_progress", (e) => {
        if (e.detail.job_id === this.activeJobId) this.progress = e.detail;
      });
      window.addEventListener("ct:job_done", (e) => {
        if (e.detail.job_id === this.activeJobId) this.onDeleteDone(e.detail.result);
      });
      window.addEventListener("ct:job_error", (e) => {
        if (e.detail.job_id === this.activeJobId) this.onDeleteDone({ error: e.detail.error });
      });
      await this.waitForPywebviewReady();
      await this.selectTab("sessions");
    },

    // Alpine's x-init fires on DOMContentLoaded, but pywebview only creates
    // window.pywebview.api later, on the page's load/NavigationCompleted
    // event — calling into the api before that races ahead of the bridge
    // and the call is silently lost (no error, no resolution, ever).
    waitForPywebviewReady() {
      if (window.pywebview && window.pywebview.api) return Promise.resolve();
      return new Promise((resolve) => {
        window.addEventListener("pywebviewready", () => resolve(), { once: true });
      });
    },

    async selectTab(tab) {
      this.activeTab = tab;
      if (this.tabsLoaded[tab]) return;
      this.tabsLoaded[tab] = true;
      if (tab === "sessions") await this.rescanSessions();
      else if (tab === "cache") await this.rescanCache();
      else if (tab === "index") await this.rescanIndex();
      else if (tab === "settings") await this.loadSettings();
    },

    humanSize,
    relativeTime,
    riskBadge,

    // ----------------------------------------------------------- Sessions

    async rescanSessions() {
      this.scanning = true;
      const t0 = performance.now();
      this.projects = await api("list_projects");
      if (this.selectedProjectId) await this.selectProject(this.selectedProjectId, true);
      const totalSessions = this.projects.reduce((n, p) => n + p.session_count, 0);
      const totalSize = this.projects.reduce((n, p) => n + p.size_bytes, 0);
      this.statusLeft = `Đã quét ${this.projects.length} project · ${totalSessions} session · ` +
        `${humanSize(totalSize)} trong ${((performance.now() - t0) / 1000).toFixed(1)} s`;
      this.scanning = false;
    },

    get filteredProjects() {
      const q = this.projectFilter.trim().toLowerCase();
      if (!q) return this.projects;
      return this.projects.filter((p) => p.display_name.toLowerCase().includes(q));
    },

    async selectProject(id, silent) {
      this.selectedProjectId = id;
      this.checked = {};
      const detail = await api("list_sessions", id);
      if (detail.error) {
        // Most likely: the previously-open project was just deleted entirely.
        this.selectedProjectId = null;
        this.project = null;
        this.sessions = [];
        return;
      }
      this.project = detail.project;
      this.sessions = detail.sessions;
      if (!silent) this.riskFilter = null;
    },

    get visibleSessions() {
      if (!this.riskFilter) return this.sessions;
      return this.sessions.filter((s) => s.risk === this.riskFilter);
    },

    get checkedCount() {
      return Object.values(this.checked).filter(Boolean).length;
    },

    get checkedSize() {
      return this.sessions.filter((s) => this.checked[s.id]).reduce((n, s) => n + s.size_bytes, 0);
    },

    toggleSession(id) {
      this.checked[id] = !this.checked[id];
    },

    async deleteSingle(id) {
      await this.startPreview({ mode: "single", project_id: this.selectedProjectId,
                                session_ids: [id] });
    },

    async deleteChecked() {
      const ids = Object.keys(this.checked).filter((k) => this.checked[k]);
      await this.startPreview({ mode: "multi", project_id: this.selectedProjectId,
                                session_ids: ids });
    },

    async deleteAllProject(includeWorktrees) {
      await this.startPreview({ mode: "all", project_id: this.selectedProjectId,
                                include_worktrees: !!includeWorktrees });
    },

    // ------------------------------------------------- Project context menu

    openProjectMenu(event, project) {
      this.projectMenu = { x: event.clientX, y: event.clientY, project };
    },

    async openProjectFolder() {
      const project = this.projectMenu.project;
      this.projectMenu = null;
      const resp = await api("open_project_folder", project.id);
      if (resp.error) this.statusRight = resp.error;
    },

    async copyProjectPath() {
      const project = this.projectMenu.project;
      this.projectMenu = null;
      if (!project.cwd) {
        this.statusRight = "Project này không có đường dẫn cwd đã biết.";
        return;
      }
      await navigator.clipboard.writeText(project.cwd);
      this.statusRight = "Đã copy đường dẫn project.";
    },

    async rescanProjectMenu() {
      const project = this.projectMenu.project;
      this.projectMenu = null;
      const detail = await api("rescan_project", project.id);
      if (detail.error) {
        this.statusRight = detail.error;
        return;
      }
      this.replaceProjectEverywhere(detail.project);
      if (this.selectedProjectId === project.id) {
        this.project = detail.project;
        this.sessions = detail.sessions;
      }
      this.statusRight = `Đã quét lại ${detail.project.display_name}.`;
    },

    async deleteAllProjectMenu() {
      const project = this.projectMenu.project;
      this.projectMenu = null;
      if (!project.session_count) return;
      await this.selectProject(project.id);
      new bootstrap.Modal("#deleteAllModal").show();
    },

    // Sidebar rows are snapshots from the last list_projects()/rescan_project()
    // call — after a per-project rescan only that one entry needs patching in,
    // not a full re-fetch of every project.
    replaceProjectEverywhere(updated) {
      for (const p of this.projects) {
        if (p.id === updated.id) {
          Object.assign(p, updated);
          return;
        }
        const w = p.worktrees.find((w) => w.id === updated.id);
        if (w) Object.assign(w, updated);
      }
    },

    // ----------------------------------------------------------- Cache

    async rescanCache() {
      const data = await api("scan_cache");
      this.cacheGroups = data.groups;
      this.claudeDesktopPid = data.claude_desktop_pid;
      this.cacheChecked = {};
    },

    get cacheCheckedCount() {
      return Object.values(this.cacheChecked).filter(Boolean).length;
    },

    get cacheCheckedSize() {
      return this.cacheGroups.filter((g) => this.cacheChecked[g.id])
        .reduce((n, g) => n + g.size_bytes, 0);
    },

    async deleteCacheChecked() {
      const ids = Object.keys(this.cacheChecked).filter((k) => this.cacheChecked[k]);
      await this.startPreview({ mode: "cache", group_ids: ids });
    },

    // ----------------------------------------------------------- Index

    async rescanIndex() {
      this.orphanEntries = await api("list_orphan_index");
      this.selectedOrphanId = null;
    },

    async deleteSelectedOrphan() {
      if (!this.selectedOrphanId) return;
      await this.startPreview({ mode: "index", entry_id: this.selectedOrphanId });
    },

    // ----------------------------------------------------------- Settings

    async loadSettings() {
      this.settings = await api("get_settings");
    },

    async saveSettings() {
      const resp = await api("save_settings", this.settings);
      if (resp.error) {
        this.settingsStatus = resp.error;
        this.settingsStatusOk = false;
      } else {
        this.settingsStatus = "Đã lưu.";
        this.settingsStatusOk = true;
        this.statusRight = `Backup → ${this.settings.backup_dir} · giữ ${this.settings.retention_days} ngày`;
      }
    },

    async browseBackupDir() {
      const chosen = await api("pick_folder", this.settings.backup_dir);
      if (chosen) this.settings.backup_dir = chosen;
    },

    // ------------------------------------------------------- Delete flow
    // The one path every tab uses — see claude_tidy/webui/CLAUDE.md.

    async startPreview(spec) {
      this.preview = await api("preview_delete", spec);
      if (this.preview.error) {
        this.result = { error: this.preview.error };
        this.preview = null;
        new bootstrap.Modal("#resultModal").show();
        return;
      }
      this.previewChecked = {};
      this.typedName = "";
      new bootstrap.Modal("#previewModal").show();
    },

    get previewConfirmedIds() {
      return Object.keys(this.previewChecked).filter((k) => this.previewChecked[k]);
    },

    get previewConfirmedSizeBytes() {
      if (!this.preview) return 0;
      const confirmed = new Set(this.previewConfirmedIds);
      const extra = this.preview.needs_confirmation
        .filter((t) => confirmed.has(t.id))
        .reduce((n, t) => n + t.size_bytes, 0);
      return this.preview.size_bytes + extra;
    },

    get previewCanConfirm() {
      if (!this.preview) return false;
      const count = this.preview.will_delete.length + this.previewConfirmedIds.length;
      if (count === 0) return false;
      if (this.preview.typed_name_required != null) {
        return this.typedName === this.preview.typed_name_required;
      }
      return true;
    },

    async confirmDelete() {
      const token = this.preview.token;
      const confirmedIds = this.previewConfirmedIds;
      const typedName = this.typedName;
      bootstrap.Modal.getInstance(document.getElementById("previewModal"))?.hide();
      this.progress = { phase: "backup", done: 0, total: 1, current: "" };
      this.deleteBusy = true;
      new bootstrap.Modal("#progressModal", { backdrop: "static", keyboard: false }).show();
      const resp = await api("execute_delete", token, confirmedIds, typedName);
      if (resp.error) {
        this.onDeleteDone({ error: resp.error });
        return;
      }
      this.activeJobId = resp.job_id;
    },

    cancelDelete() {
      if (this.activeJobId) api("cancel_job", this.activeJobId);
    },

    onDeleteDone(result) {
      this.deleteBusy = false;
      this.activeJobId = null;
      bootstrap.Modal.getInstance(document.getElementById("progressModal"))?.hide();
      this.result = result;
      this.preview = null;
      new bootstrap.Modal("#resultModal").show();
      // Refresh whatever tab is visible so a just-deleted row disappears.
      if (this.activeTab === "sessions") this.rescanSessions();
      else if (this.activeTab === "cache") this.rescanCache();
      else if (this.activeTab === "index") this.rescanIndex();
    },
  };
}
