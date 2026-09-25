---
type: feature
complexity: high
status: planning
related_issues: []
related_prs: []
estimated_hours: ~372 (≈ 46.5 person-days, gồm buffer)
---

# Kế hoạch: Claude Session/Cache Cleaner (Python + Flet) — phân rã task MVP & Phase 2

> **Ngày lập kế hoạch:** 2026-09-25
> **Nguồn yêu cầu:** [docs/claude-session-cleaner-idea.md](../docs/claude-session-cleaner-idea.md)
> **Scope dự kiến:** repo greenfield `claude-tidy` — package `claude_tidy/` (core + ui), `tests/`, cấu hình build Flet
> **Priority:** high
> **Assumption:** 1 senior dev Python, chỉ build Windows, chưa có code nào trong repo

---

## 1. Phân tích / Bối cảnh

Ứng dụng desktop dọn dẹp dữ liệu Claude Code/Claude Desktop trên Windows: session `.jsonl` theo project, index `~/.claude/sessions/`, cache `%APPDATA%\Claude`, file tạm `%TEMP%\claude`. Mọi thao tác xoá phải qua pipeline: active check → dry-run → backup zip → xoá → ghi log.

### 1.1 Phát hiện khi đối chiếu với cấu trúc `~/.claude` thực tế

Đã khảo sát thư mục `~/.claude` trên máy dev (Claude Code 2.1.x). Một số điểm tài liệu ý tưởng **chưa đề cập** nhưng ảnh hưởng trực tiếp tới thiết kế:

| # | Phát hiện | Ảnh hưởng |
|---|---|---|
| F1 | `sessions/<pid>.json` có sẵn `pid`, `sessionId`, `cwd`, `procStart`, `status` (`idle`/…), `updatedAt` | Active detection **dễ và chính xác hơn** dự kiến: so `procStart` với `psutil.Process(pid).create_time()` để chống PID bị tái sử dụng. Lưu ý: `psutil.pid_exists()` một mình **không** chống được PID reuse như tài liệu ghi. |
| F2 | Một session không chỉ là 1 file `.jsonl`: còn thư mục `projects/<slug>/<sessionId>/` (subagents, tool results), sidecar `*.jsonl.wakatime`, và `file-history/<sessionId>/`, `session-env/<sessionId>/`, `tasks/<sessionId>/` | Nếu chỉ xoá `.jsonl` sẽ để lại rác mồ côi → Scan Engine phải gom **"session bundle"** (mọi artifact theo `sessionId`). |
| F3 | Trong `projects/<slug>/` có thư mục `memory/` (auto-memory của Claude) | **Tuyệt đối không xoá** khi "xoá tất cả session của project" — phải có allowlist/denylist rõ ràng. |
| F4 | Slug project (`D--nqdev-wps-dakia-group-dakia-crm`) mã hoá mất thông tin (`\`, `:`, `.` và `-` đều thành `-`) | Không decode slug ngược ra path; lấy tên hiển thị từ trường `cwd` trong `.jsonl` hoặc `sessions/*.json`. |
| F5 | Có slug worktree (`...--claude-worktrees-happy-clarke-858e1b`) | Cân nhắc nhóm worktree dưới project cha trong UI (nice-to-have). |
| F6 | Tài liệu có Scan cho cache Desktop + `%TEMP%\claude` nhưng UI chỉ mô tả màn project/session | **Thiếu màn hình** cho cache/temp → bổ sung task T15 (cần chốt scope). |

### 1.2 Constraints

- Không build macOS/Linux, không code-sign, không auto-update (theo tài liệu).
- `flet build windows` cần Flutter SDK + Visual Studio (C++ desktop workload) → setup lần đầu thường tốn hơn dự kiến.
- File của Claude Desktop có thể bị lock khi app đang chạy → xoá cache phải xử lý `PermissionError` từng file, không fail toàn batch.

## 2. Approach / Strategy

**Kiến trúc 2 lớp, core không phụ thuộc UI:**

```
claude_tidy/
  core/
    paths.py        # resolve ~/.claude, %APPDATA%\Claude, %TEMP%\claude (inject được để test)
    models.py       # Project, SessionBundle, RiskLevel, DeletePlan, OperationRecord
    scanner.py      # quét + gom SessionBundle theo sessionId
    grouping.py     # list theo project, build DeletePlan cho single/multi/all
    usage.py        # tính dung lượng
    activity.py     # active session detection
    risk.py         # tính badge safe/warning/danger
    backup.py       # nén zip có manifest
    deleter.py      # pipeline xoá + progress callback
    oplog.py        # ghi log thao tác (JSON lines) cho Restore
    settings.py     # đọc/ghi config
  ui/               # Flet views: explorer, settings, cache view, dialogs
tests/fixtures/     # cây ~/.claude giả lập
```

- **Tại sao tách core/ui:** toàn bộ logic nguy hiểm (active check, xoá) test được bằng pytest trên fixture giả, không cần mở GUI; Phase 2 (scheduler/tray) tái sử dụng core.
- **Pipeline xoá là 1 hàm duy nhất** `execute(plan, on_progress)` dùng chung cho cả 3 chế độ — tránh 3 đường code khác nhau với 3 mức an toàn khác nhau.
- **Backup mặc định bằng zip tự viết** thay vì `send2trash`: zip có manifest (đường dẫn gốc, sessionId, hash) nên Restore ở Phase 2 làm được chính xác; Recycle Bin không cho restore theo lô có kiểm soát.
- **Chạy tác vụ nặng trong thread nền**, đẩy progress về UI qua `page.update()` — tránh treo cửa sổ Flet khi xoá hàng nghìn file.

**Milestones:**

| Milestone | Nội dung | Tuần |
|---|---|---|
| M1 — Nền tảng | Setup, paths, fixtures, Scan Engine | 1–2 |
| M2 — Phân tích an toàn | Grouping, Disk usage, Active detection, Risk | 3–4 |
| M3 — Xoá an toàn | Backup, Delete pipeline, Operation log | 5–6 |
| M4 — Giao diện | Explorer, Settings, Progress, Cache view | 6–8 |
| M5 — Đóng gói & QA | Build `.exe`, test trên máy sạch, UAT | 9 |
| Phase 2 | Restore, Scheduled clean, System tray | 10–11 |

## 3. Công việc cần thực hiện (Todo)

Effort tính theo person-days (1 senior dev). Cột "Gốc" là estimate trong tài liệu ý tưởng; "Điều chỉnh" là estimate sau khi phân tích.

### M1 — Nền tảng

- [ ] **T01 — Setup project & toolchain** (Gốc 1.5 → **2.5d**) · DevOps · Thấp
  - Khởi tạo `pyproject.toml` (Python 3.11+, flet, psutil, send2trash, pytest), ruff, cấu trúc package
  - Cài Flutter SDK + VS C++ workload, chạy thử `flet build windows` với app "hello" để phát hiện sớm lỗi toolchain
  - Tăng 1d vì build Flet Windows lần đầu thường vướng môi trường
- [ ] **T02 — Path resolver & Settings model** (**0.5d**, tách từ Settings) · Backend · Thấp
  - Resolve các root dir, cho phép override qua biến môi trường/tham số để test
- [ ] **T03 — Test fixtures `~/.claude` giả lập** (**1.5d**, mới) · QA · Trung bình
  - Sinh cây thư mục giả: nhiều project, session bundle đầy đủ (F2), `memory/` (F3), `sessions/*.json` với PID sống/chết/tái sử dụng
  - Là nền cho mọi test của Active detection & Delete — không có thì không dám xoá thật
- [ ] **T04 — Scan Engine** (**4d**) · Backend · Trung bình · phụ thuộc T02, T03
  - Quét `projects/`, gom `SessionBundle` theo `sessionId` gồm cả `<sessionId>/`, `.wakatime`, `file-history/`, `session-env/`, `tasks/`
  - Đọc `cwd` + thời điểm ghi cuối từ `.jsonl` (chỉ đọc vài dòng đầu/cuối, không load cả file)
  - Quét cache `%APPDATA%\Claude` và `%TEMP%\claude` thành nhóm riêng
  - Denylist cứng: `memory/`, `settings*.json`, `.credentials.json`, `CLAUDE.md`, `commands/`, `skills/`, `agents/`…

### M2 — Phân tích an toàn

- [ ] **T05 — Project/Session Grouping API** (**2d**) · Backend · Trung bình · phụ thuộc T04
  - `list_projects()`, `list_sessions(project)`, `build_plan(mode=single|multi|all, ids)` → `DeletePlan`
  - Tên hiển thị project lấy từ `cwd` (F4)
- [ ] **T06 — Disk Usage Analysis** (**1.5d**) · Backend · Thấp · phụ thuộc T04
  - Dung lượng theo bundle / project / cache; tổng "sẽ giải phóng" cho dry-run
- [ ] **T07 — Active Session Detection** (**2.5d**) · Backend · Cao (rủi ro cao nhất) · phụ thuộc T03, T04
  - Nguồn 1: `sessions/*.json` → `pid` còn sống **và** `create_time()` khớp `procStart` (F1)
  - Nguồn 2 (fallback): `.jsonl` có `LastWriteTime` < ngưỡng cấu hình (mặc định 5 phút) → coi là "có thể active"
  - Kết quả 3 trạng thái: `active` / `maybe_active` / `inactive`
  - Test đủ case: PID chết, PID tái sử dụng, file `sessions/*.json` hỏng, không có quyền đọc process
- [ ] **T08 — Risk Level Indicator** (**1d**) · Backend · Trung bình · phụ thuộc T06, T07
  - Tiêu chí đã chốt (mục 6.3): danger = `active`; warning = `maybe_active` hoặc ghi lần cuối trong 24h; safe = còn lại
  - Ngưỡng 24h cấu hình được trong Settings (T13)
  - Badge chỉ để hiển thị; hành vi xoá vẫn theo mục 6.1 (warning do "mới dùng trong 24h" không bắt xác nhận lại)

### M3 — Xoá an toàn

- [ ] **T09 — Backup (zip + manifest)** (**2d**, tách từ 4d gốc) · Backend · Cao · phụ thuộc T05
  - Zip vào `<backup_dir>/<timestamp>_<project>.zip`, kèm `manifest.json` (đường dẫn gốc, size, sha256)
  - Kiểm tra dung lượng ổ trống trước khi nén; verify zip sau khi ghi
- [ ] **T10 — Delete pipeline** (**2d**, tách từ 4d gốc) · Backend · Cao · phụ thuộc T07, T09
  - `execute(plan, on_progress)`: re-check active ngay trước khi xoá → backup → xoá → báo cáo
  - Chỉ xoá khi backup verify thành công; lỗi từng file (lock) ghi nhận, không dừng toàn batch
  - Active session trong nhóm (đã chốt, mục 6): `active` → soft-skip + báo cáo; `maybe_active` → trả về danh sách cần xác nhận, chỉ xoá những bundle người dùng đồng ý; không có cờ ép xoá
- [ ] **T11 — Operation log** (**0.5d**, mới — tài liệu có trong pipeline nhưng chưa tính effort) · Backend · Thấp
  - JSON lines: thời gian, mode, danh sách bundle, đường dẫn zip, kết quả → input cho Restore
  - Kèm dọn backup quá hạn theo retention trong Settings (mặc định 14 ngày; bỏ qua nếu người dùng tắt auto-xoá)

### M4 — Giao diện

- [ ] **T12 — GUI Project & Session Explorer** (**6d**) · Frontend heavy · Cao · phụ thuộc T05–T08
  - Master-detail, checkbox multi-select, risk badge, 3 nút xoá
  - Dialog dry-run (danh sách + dung lượng), double-confirm nhập tên project cho "xoá tất cả"
  - Dry-run tách 3 nhóm: sẽ xoá / sẽ bỏ qua (`active`) / cần xác nhận (`maybe_active`, có checkbox riêng)
  - Báo cáo sau khi xoá liệt kê các session đã bỏ qua và lý do
  - Scan trong thread nền, không chặn UI với project có hàng nghìn session
- [ ] **T13 — Trang Settings** (**1d**, 1.5d gốc − 0.5d đã tách sang T02) · Frontend · Trung bình
  - Thư mục backup (mặc định `%LOCALAPPDATA%\ClaudeTidy\backups\`), số ngày giữ backup (mặc định 14), công tắc bật/tắt auto-xoá backup, ngưỡng "có thể active" (mặc định 5 phút), ngưỡng "mới dùng" cho badge warning (mặc định 24h)
- [ ] **T14 — Progress Tracking** (**1d**) · Full-stack · Thấp · phụ thuộc T10, T12
  - Progress bar + đếm file, nút huỷ an toàn (dừng sau file hiện tại, không để bundle xoá dở)
- [ ] **T15 — Màn Cache/Temp cleaner** (**1.5d**, mới — F6; đã chốt thuộc MVP) · Frontend · Thấp · phụ thuộc T04, T10
  - Danh sách nhóm cache Desktop / temp + dung lượng, cảnh báo nếu Claude Desktop đang chạy

### M5 — Đóng gói & QA

- [ ] **T16 — Packaging & smoke test** (gộp trong buffer QA) · DevOps
  - `flet build windows`, chạy `.exe` trên máy/VM sạch, kiểm tra với dữ liệu `~/.claude` thật (đã backup trước)

### Bổ sung sau khi chốt câu hỏi (2026-09-25)

Task ID mới đánh tiếp từ T20 để không làm lệch ID đã có.

- [ ] **T20 — Dọn index mồ côi `sessions/<pid>.json`** (**1d**, mới — quyết định 6.5) · Full-stack · Thấp · phụ thuộc T07, T10
  - Mồ côi = PID không còn sống **hoặc** PID sống nhưng `create_time()` không khớp `procStart` (PID đã bị tái sử dụng)
  - Xoá kèm file `<pid>.<hash>.key` đi cùng
  - UI: danh sách từng file (cwd, tên session, thời điểm cập nhật cuối); **người dùng xác nhận từng file**, không có nút "xoá tất cả"
  - Vẫn đi qua pipeline T10 (backup + log) cho nhất quán
- [ ] **T21 — Nhóm worktree dưới project cha** (**1.5d**, mới — quyết định 6.6) · Full-stack · Trung bình · phụ thuộc T05, T12
  - Nhận diện worktree từ `cwd` chứa `\.claude\worktrees\<name>` (không dựa vào decode slug — F4); fallback theo pattern slug `<parent>--claude-worktrees-<name>`
  - Panel trái dạng cây: project cha → các worktree; worktree có thư mục đã bị xoá vẫn hiển thị (đánh dấu "worktree không còn tồn tại")
  - "Xoá tất cả" ở project cha: hỏi có áp dụng cho cả worktree con không (mặc định **không**)

### Phase 2 — Post-MVP

- [ ] **T17 — Restore từ backup** (**1.5d**) · Quan trọng · phụ thuộc T09, T11
  - Đọc manifest, cảnh báo nếu file đích đã tồn tại
- [ ] **T18 — Scheduled Auto-Clean** (**2d**) · Nice-to-have
  - Chỉ xoá bundle `safe`, tái sử dụng pipeline T10
- [ ] **T19 — System Tray** (**1.5d**) · Nice-to-have

### Tổng hợp effort

| Hạng mục | Gốc | Điều chỉnh v1 | Điều chỉnh v2 (sau khi chốt 6.4–6.6) |
|---|---|---|---|
| MVP core (T01–T15, T20–T21) | 25.5d | 29.5d | **32d** |
| Phase 2 (T17–T19) | 5d | 5d | 5d |
| Buffer QA 15% + PM 10% | 7.5d | 8.5d | **9.5d** |
| **Tổng** | ~38d | ~43d (range 38–48d) | **~46.5d** (range 42–52d) |
| **Timeline 1 dev** (Total ÷ 0.8) | 7–8 tuần | ~10–11 tuần (MVP ~8–9 tuần) | **~11–12 tuần** (MVP ~10 tuần) |

Chênh lệch v1 (+4d): toolchain Flet (+1d), test fixtures (+1.5d), operation log (+0.5d), màn cache/temp (+1.5d), trừ phần Settings đã tách (−0.5d).
Chênh lệch v2 (+2.5d): dọn index mồ côi T20 (+1d), nhóm worktree T21 (+1.5d). Màn cache/temp T15 đã có trong v1 nên không đổi.

**Chưa bao gồm:** macOS/Linux, code-sign/installer, auto-update, tài liệu hướng dẫn người dùng, hỗ trợ các version Claude Code có cấu trúc `~/.claude` khác trong tương lai.

## 4. Risks & Unknowns

- **Risk 1 — Xoá nhầm session đang dùng:** → **Mitigation:** check theo `pid` + `procStart` (F1), fallback theo mtime, re-check ngay trước khi xoá (T10), backup bắt buộc trước khi xoá, test fixture đủ case PID reuse.
- **Risk 2 — Xoá nhầm dữ liệu không phải session (`memory/`, config, credentials):** → **Mitigation:** allowlist chỉ các pattern session bundle + denylist cứng trong Scan Engine; test riêng cho "xoá tất cả" không đụng `memory/`.
- **Risk 3 — Cấu trúc `~/.claude` thay đổi theo version Claude Code:** → **Mitigation:** parser chịu lỗi (bỏ qua file lạ, không crash), log cảnh báo khi gặp schema lạ; ghi rõ version đã kiểm thử.
- **Risk 4 — Toolchain `flet build windows`:** → **Mitigation:** build thử ngay ở T01, không để đến cuối.
- **Risk 5 — File bị lock (Claude Desktop đang chạy):** → **Mitigation:** xử lý lỗi từng file, báo cáo cuối; cảnh báo trước ở T15.
- **Unknown 1 — Ý nghĩa `status` trong `sessions/*.json` (`idle`, …) có đủ tin cậy làm tín hiệu không:** → **Plan:** khảo sát thêm vài session đang chạy/đã tắt khi làm T07.
- **Unknown 2 — Kích thước dữ liệu thực tế (số session lớn nhất / project):** → **Plan:** đo trên máy dev ở T04 để quyết định có cần lazy-load danh sách ở T12.

## 5. Success Criteria

- Xoá single/multi/all đều đi qua cùng một pipeline; mọi lần xoá đều có zip backup verify được và 1 dòng operation log.
- Không bao giờ xoá session `active` (test tự động với fixture PID sống + PID reuse đều pass).
- "Xoá tất cả" không đụng `memory/` và file ngoài session bundle (có test).
- Không để lại artifact mồ côi (`file-history/`, `session-env/`, `tasks/`, `<sessionId>/`) sau khi xoá một session.
- UI không treo khi scan/xoá project có ≥ 1.000 session.
- `.exe` chạy được trên máy Windows sạch không cài Python.

## 6. Questions / Dependencies

Cần chủ dự án chốt trước khi làm các task liên quan:

1. ✅ **Đã chốt (2026-09-25) — Active session trong nhóm bị chọn (T10, T12):**
   - `active` → tự động bỏ qua (soft-skip), liệt kê trong báo cáo sau khi xoá.
   - `maybe_active` → hỏi lại người dùng trước khi xoá.
   - Không có tuỳ chọn ép xoá session `active`, kể cả ở chế độ "xoá tất cả".
2. ✅ **Đã chốt (2026-09-25) — Backup mặc định (T09, T11, T13):**
   - Thư mục mặc định `%LOCALAPPDATA%\ClaudeTidy\backups\`, giữ 14 ngày rồi tự xoá.
   - Settings cho phép đổi thư mục backup và tắt auto-xoá.
4. ✅ **Đã chốt (2026-09-25) — Màn Cache/Temp (T15):** nằm trong MVP, có xoá thật (qua pipeline T10), không chỉ hiển thị dung lượng.
5. ✅ **Đã chốt (2026-09-25) — Index mồ côi `sessions/<pid>.json`:** có dọn, nhưng **người dùng xác nhận từng file** → task mới T20.
6. ✅ **Đã chốt (2026-09-25) — Nhóm worktree (F5):** nằm trong MVP, worktree hiển thị lồng dưới project cha → task mới T21.
3. ✅ **Đã chốt (2026-09-25) — Tiêu chí risk badge (T08):** phương án A — theo trạng thái chạy + độ mới.
   - 🔴 danger: `active`
   - 🟡 warning: `maybe_active` **hoặc** ghi lần cuối trong 24h (ngưỡng chỉnh trong Settings)
   - 🟢 safe: còn lại
   - Đã cân nhắc: B (chỉ theo trạng thái chạy — không nhắc session mới dùng), C (thêm session có tên thủ công là warning — bị loại).

Tất cả câu hỏi đã chốt, không còn blocker cho MVP.
