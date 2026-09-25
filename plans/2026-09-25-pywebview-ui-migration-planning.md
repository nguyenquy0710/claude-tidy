---
type: refactor
complexity: high
status: planning
related_issues: [QUYIT-741]
related_prs: []
estimated_hours: ~160 (≈ 20 person-days, gồm buffer)
---

# Kế hoạch: Chuyển UI claude-tidy từ ttkbootstrap sang pywebview + HTML/Bootstrap 5

> **Ngày lập kế hoạch:** 2026-09-25
> **Nguồn yêu cầu:** [docs/claude-tidy-plan.md](../docs/claude-tidy-plan.md) — bản pywebview, **chưa commit** tại thời điểm lập plan (phân tích bằng `/nqdev-client-requirement-insight`)
> **Kế hoạch liên quan:** [2026-09-25-session-cleaner-mvp-roadmap.md](2026-09-25-session-cleaner-mvp-roadmap.md) (T01–T21), [2026-09-25-ttkbootstrap-ui-migration-planning.md](2026-09-25-ttkbootstrap-ui-migration-planning.md) (T22–T32)
> **Scope dự kiến:** `claude_tidy/webui/` (mới: `api.py`, `dto.py`, `jobs.py`), `claude_tidy/webui/static/` (mới: `index.html`, `app.js`, Bootstrap 5 local), xoá `claude_tidy/ui/`, `main.py`, `claude_tidy/__main__.py`, `pyproject.toml`, `claude-tidy.spec`, các file `.bat`, các `CLAUDE.md` liên quan, `docs/claude-tidy-plan.md`
> **Priority:** high
> **Assumption:** 1 senior dev Python + JS cơ bản; **không đổi** `claude_tidy/core/` và test core hiện có

---

## 1. Phân tích / Bối cảnh

### 1.1 Tài liệu mới khác gì so với bản ttkbootstrap

Đây là lần đổi UI thứ hai trong cùng một ngày. Trình tự: Flet → ttkbootstrap (T22–T32, đã xong) → **pywebview + HTML/Bootstrap 5**.

| Hạng mục | Hiện tại (đã chạy được) | Tài liệu mới |
|---|---|---|
| UI | ttkbootstrap, 4 tab `ttk.Notebook` | **HTML + Bootstrap 5** trong cửa sổ **pywebview** (WebView2) |
| Cầu nối | gọi thẳng `core` trong cùng process Tk | `js_api`: JS → Python; Python → JS qua `window.evaluate_js()` |
| Đóng gói | PyInstaller **`--onedir`** (`claude-tidy.spec`) | PyInstaller **`--onefile`** |
| Module mới | — | `js_api` bridge (1.5d), progress qua `evaluate_js` (1.5d) |
| Prototype | — | `docs/claude-tidy — UI.html` |

Các module core (Scan, Grouping, Disk usage, Active detection, Backup, Risk) **không đổi** và đã implement xong, kể cả test.

### 1.2 Hiện trạng codebase (đã khảo sát)

- `claude_tidy/core/`: không import UI framework nào → **dùng lại 100%**.
- `claude_tidy/ui/`: bản ttkbootstrap khoảng 90KB (`app`, `explorer`, `delete_flow`, `other_views`, `widgets`, `dispatch`, `state`, cùng file mới `theme.py`). Working tree đang có **thay đổi chưa commit** ở 4 file UI và `theme.py` (đang chỉnh giao diện ttkbootstrap).
- Chưa có dòng code pywebview nào. `run_webapp.bat` (commit 387560b) chỉ là script chạy app/venv.
- **Prototype không dùng trực tiếp được:** `docs/claude-tidy — UI.html` (2.6MB) là file xuất từ bundler. Nội dung được nén trong các thẻ `<script type="__bundler/...">` và tự giải nén bằng JS khi mở. Muốn có `index.html` thì phải render rồi trích markup ra (task T34), không copy thẳng được.

### 1.3 Tài liệu mới đảo ngược các quyết định đã chốt

Bản pywebview (chưa commit) đã **ghi đè** phần T32 vừa đồng bộ ở bản ttkbootstrap. Kết quả là các lỗi D1–D6 trong plan ttkbootstrap quay trở lại:

| # | Tài liệu mới ghi | Đã chốt / đã code |
|---|---|---|
| E1 | `send2trash` hoặc backup zip | Chỉ zip + manifest (sha256, verify trước khi xoá) |
| E2 | `psutil.pid_exists()` để tránh PID reuse | Sai về kỹ thuật. Code so `create_time()` với `procStart`; `AccessDenied` được coi là `MAYBE_ACTIVE` |
| E3 | Soft-skip hay chặn toàn bộ vẫn là câu hỏi mở | `ACTIVE` → soft-skip; `MAYBE_ACTIVE` → xác nhận từng mục |
| E4 | Nơi lưu backup vẫn là câu hỏi mở | `%LOCALAPPDATA%\ClaudeTidy\backups\`, giữ 14 ngày, có thể tắt auto-xoá |
| E5 | PyInstaller `--onefile` | Đã đo: onefile khởi động 3.6–5.4s, onedir 1–2.2s → chọn **onedir** |
| E6 | UI chỉ có Explorer + Settings | Còn có Cache/Temp, Index mồ côi, cây worktree, ngưỡng badge 24h |

**Kết luận:** việc thực chất là **thay lớp UI lần hai** (khoảng 16 ngày công), không phải dự án 27.5 ngày như tài liệu ghi.

## 2. Approach / Strategy

**Phương án chọn:** thêm package `claude_tidy/webui/` gồm lớp API bằng Python thuần và frontend tĩnh. Chạy song song với `ui/` ttkbootstrap **chỉ trong lúc port**; khi đạt tương đương thì xoá `ui/` (T40), để không duy trì hai luồng xoá.

### 2.1 Ranh giới tin cậy: logic an toàn nằm ở Python, không nằm ở JS

Tài liệu ghi "JS chỉ gọi và render". Plan này làm chặt hơn cho đúng quy tắc an toàn trong `CLAUDE.md`:

- **JS không bao giờ gửi đường dẫn file.** JS chỉ gửi `project_id` và `session_id`. `DeletePlan` luôn được build ở Python từ dữ liệu scan.
- **Preview dùng token:**
  - `preview_delete(spec)` → Python build plan, chạy `core.deleter.preview`, lưu plan theo `token`, trả DTO 3 nhóm.
  - `execute_delete(token, confirmed_ids, typed_name)`: Python kiểm tra `confirmed_ids ⊆ needs_confirmation` và `typed_name` khớp tên project (với mode `all`) **ở phía Python**, rồi mới gọi `execute()`. Nhập tên để xác nhận không chỉ là một ô bị khoá ở JS.
- **Chỉ một thao tác xoá tại một thời điểm:** dùng `threading.Lock` để khoá, gọi lần hai khi đang xoá sẽ bị từ chối. Token dùng một lần.
- Hàm `run_delete_flow` duy nhất của UI cũ được thay bằng **cặp** `preview_delete`/`execute_delete` duy nhất trong `webui/api.py`. Mọi trang HTML đều phải đi qua cặp này.

### 2.2 Luồng Python → JS

- `js_api` của pywebview chạy mỗi lời gọi trên thread riêng. Tác vụ dài (scan, xoá) thì **trả về `job_id` ngay**, còn tiến độ được đẩy sang JS qua `window.evaluate_js(f"onJobEvent({json.dumps(evt)})")`.
- **Luôn dùng `json.dumps`** cho payload đẩy sang JS. Label chứa đường dẫn Windows có `\`, `'` và ký tự Unicode; ghép chuỗi thủ công sẽ làm vỡ JS hoặc thành lỗ hổng injection.
- Định nghĩa contract DTO trong `webui/dto.py` (dataclass → dict) và viết thành bảng trong `claude_tidy/webui/CLAUDE.md`, để hai phía không lệch nhau (Risk 5 trong tài liệu).

### 2.3 Frontend

- Bootstrap 5 và Alpine.js **để local** trong `static/vendor/`, không dùng CDN, vì app phải chạy offline và đóng gói được. Không dùng bước build (không npm/webpack).
- Bắt buộc `webview.start(gui="edgechromium")`. Nếu máy không có WebView2 thì **báo lỗi kèm link tải**, không để pywebview rơi về engine MSHTML/IE (Bootstrap 5 không chạy trên IE).

### 2.4 Milestones

| Milestone | Task | Ngày công |
|---|---|---|
| W-M1 — Spike & nền | T33–T36 | 6d |
| W-M2 — Các trang | T37–T39 | 6d |
| W-M3 — Gỡ ttkbootstrap, đóng gói, QA, tài liệu | T40–T43 | 4d |

## 3. Công việc cần thực hiện (Todo)

Task ID đánh tiếp từ **T33** (T01–T32 đã dùng, nhiều task đã gắn Jira).

### W-M1 — Spike & nền

- [ ] **T33 — Spike pywebview + PyInstaller onedir** (**1d**) · DevOps · Trung bình
  - Cửa sổ pywebview `edgechromium` load `index.html` local. Đo một vòng gọi `js_api` → Python → `evaluate_js` quay lại JS
  - Đóng gói bằng `--onedir`: kiểm tra hidden import `pythonnet`/`clr_loader` (pywebview trên Windows dùng WinForms qua pythonnet), `datas` cho `static/`, kích thước bundle, thời gian khởi động so với ~1–2.2s hiện tại
  - Phát hiện WebView2 bị thiếu (registry `EdgeUpdate\Clients\{F3017226-...}`) → hiện hộp thoại kèm link tải
- [ ] **T34 — Trích prototype → `static/index.html`** (**1d**) · Frontend · Trung bình
  - Render `docs/claude-tidy — UI.html` trên trình duyệt, trích DOM/CSS thật ra thành `index.html` + `app.css`
  - Bỏ thành phần bundler; thay Bootstrap CDN (nếu có) bằng file local
  - Đối chiếu với E6: bổ sung vào layout các trang prototype chưa có (Cache/Temp, Index mồ côi, cây worktree, trường Settings đầy đủ)
- [ ] **T35 — `js_api` + contract DTO + job runner** (**2d**) · Backend · Trung bình · phụ thuộc T33
  - `webui/api.py`: `list_projects`, `list_sessions`, `scan_cache`, `list_orphan_index`, `get_settings`, `save_settings` (validate ở Python), `pick_folder` (`create_file_dialog(FOLDER_DIALOG)`), `start_scan` → `job_id`
  - `webui/dto.py`: chuyển `Project`/`SessionBundle`/`Preview`/`DeleteResult`/`Progress` sang dict JSON-safe (đường dẫn thành `str`, enum thành value)
  - `webui/jobs.py`: chạy job nền, phát event qua `evaluate_js` + `json.dumps`, hỗ trợ huỷ bằng `threading.Event`
  - Test pytest cho `Api` **không cần mở cửa sổ** (inject một `window` giả để ghi lại các lời gọi `evaluate_js`), chạy trên fixture tree
- [ ] **T36 — Luồng xoá phía Python (token)** (**2d**) · Backend · **Cao (an toàn)** · phụ thuộc T35
  - `preview_delete(spec)` → `token` + DTO 3 nhóm; `execute_delete(token, confirmed_ids, typed_name)` → `job_id`
  - Kiểm tra ở Python: token hợp lệ và chỉ dùng một lần; `confirmed_ids ⊆ needs_confirmation`; `typed_name` khớp khi mode `all`; lock một luồng
  - Giữ nguyên `prune_backups` sau khi xoá và cơ chế huỷ giữa các mục
  - Test: token dùng lại bị từ chối; `confirmed_ids` chứa id `ACTIVE` bị từ chối; nhập sai tên bị từ chối; gọi xoá song song bị từ chối

### W-M2 — Các trang

- [ ] **T37 — Trang Explorer + các modal xoá** (**3.5d**) · Frontend heavy · Cao · phụ thuộc T34, T36
  - `list-group` project, worktree lồng dưới project cha; bảng session có checkbox, badge (safe/warning/danger), dung lượng, thời điểm ghi cuối
  - 3 nút xoá → modal preview 3 nhóm (checkbox cho `MAYBE_ACTIVE`) → ô nhập tên khi xoá tất cả → modal tiến độ có nút huỷ → modal kết quả
  - Render theo lô / virtual scroll cho project có ≥ 1.000 session
- [ ] **T38 — Trang Cache/Temp + Index mồ côi** (**1.5d**) · Frontend · Thấp · phụ thuộc T37
  - Cảnh báo khi Claude Desktop đang chạy; Index mồ côi xác nhận **từng file**, không có nút xoá tất cả
- [ ] **T39 — Trang Settings** (**1d**) · Frontend · Thấp · phụ thuộc T35
  - Form: thư mục backup (nút chọn thư mục), số ngày giữ, bật/tắt auto-xoá, ngưỡng 5 phút, ngưỡng 24h; lỗi validate trả về từ Python

### W-M3 — Gỡ ttkbootstrap, đóng gói, QA, tài liệu

- [ ] **T40 — Gỡ UI ttkbootstrap** (**0.5d**) · DevOps · Thấp · phụ thuộc T37–T39
  - Xoá `claude_tidy/ui/`; `pyproject.toml` bỏ `ttkbootstrap`, thêm `pywebview`; cập nhật `main.py`, `__main__.py`, các `.bat`
  - Viết lại `claude_tidy/ui/CLAUDE.md` thành `claude_tidy/webui/CLAUDE.md` (ranh giới tin cậy, contract DTO, quy tắc `json.dumps`); cập nhật root `CLAUDE.md`
- [ ] **T41 — Đóng gói PyInstaller** (**1.5d**) · DevOps · Trung bình · phụ thuộc T33, T40
  - Cập nhật `claude-tidy.spec`: `datas` cho `static/`, hidden import của pywebview/pythonnet, **giữ onedir**
  - Smoke test `.exe` trên máy dev; kiểm lại trường hợp không có WebView2
- [ ] **T42 — Test E2E frontend + smoke** (**1.5d**) · QA · Trung bình · phụ thuộc T37–T39
  - Playwright chạy `index.html` với `window.pywebview.api` giả (trả DTO mẫu). Kiểm tra: 3 chế độ xoá, `MAYBE_ACTIVE` phải tick mới xoá, nhập tên khi xoá tất cả, huỷ, kết quả
  - `pytest` + `ruff` sạch; test core cũ pass nguyên vẹn
  - Kế thừa phần còn mở của **T31**: smoke test trên máy/VM sạch (kèm kiểm tra antivirus báo nhầm)
- [ ] **T43 — Đồng bộ tài liệu** (**0.5d**) · Docs · Thấp
  - Sửa `docs/claude-tidy-plan.md` theo E1–E6, **không** đưa lại các câu hỏi đã chốt vào mục "Câu hỏi còn mở"
  - Ghi quyết định WebView2 (câu hỏi 6.3) vào tài liệu

### Phase 2 (không đổi, chỉ ghi chú ảnh hưởng)

- T17 Restore: thêm một trang HTML + method `js_api`, effort gần như không đổi.
- T19 System Tray: pywebview chiếm main thread → `pystray` phải chạy trên thread riêng và phối hợp với vòng đời cửa sổ. Có thể **+0.5–1d** so với 1.5d gốc.

### Tổng hợp effort

| Hạng mục | Tài liệu mới (làm từ đầu) | Điều chỉnh (dùng lại core) |
|---|---|---|
| Phần việc thực tế | 27.5d | **16d** (T33–T43) |
| Buffer QA 15% + PM 10% | 6.9d | **4d** |
| **Tổng** | ~34d (MVP) | **~20d** (range 17–24d) |
| **Timeline 1 dev** (Total ÷ 0.8) | 8 tuần | **~5 tuần** |

Tiết kiệm khoảng 11.5 ngày vì core và test core đã xong. Phần UI lại **tốn hơn** bản ttkbootstrap (15d) vì thêm lớp bridge/DTO/job (T35–T36, 4d) và test E2E cho JS.

**Chưa bao gồm:** code-sign, installer (kể cả việc đóng kèm bộ cài WebView2), auto-update, macOS/Linux, Phase 2.

## 4. Risks & Unknowns

- **Risk 1 — Logic an toàn bị đẩy sang JS** (vd kiểm tra tên xác nhận chỉ ở frontend): → **Mitigation:** mọi kiểm tra ở T36 nằm trong Python và có test; review T37 để chắc JS không tự build plan.
- **Risk 2 — Injection/vỡ JS qua `evaluate_js`** (đường dẫn có `\`, `'`, Unicode): → **Mitigation:** chỉ dùng `json.dumps`; test với label chứa ký tự đặc biệt.
- **Risk 3 — Máy thiếu WebView2**, pywebview rơi về MSHTML/IE: → **Mitigation:** ép `gui="edgechromium"` + kiểm tra khi khởi động (T33).
- **Risk 4 — PyInstaller + pythonnet** (hidden import, bundle phình to, antivirus): → **Mitigation:** spike T33 trước khi làm các trang.
- **Risk 5 — Mất tính năng khi port lần hai** (worktree, index mồ côi, badge 24h, huỷ an toàn): → **Mitigation:** checklist E6 ở T42 trước khi gỡ ttkbootstrap (T40).
- **Risk 6 — Mất công việc chưa commit ở UI ttkbootstrap** (`theme.py` + 4 file đang sửa): → **Mitigation:** commit hoặc stash trước khi bắt đầu T33 (câu hỏi 6.1).
- **Unknown 1 — Prototype có đủ các trang không** (mới thấy được bản bundler): → **Plan:** xác định ở T34.

## 5. Success Criteria

- Không còn `ttkbootstrap`/`tkinter` trong `claude_tidy/`; `pyproject.toml` phụ thuộc `pywebview`.
- `claude_tidy/core/` không bị sửa (trừ khi phát hiện bug thật); test core cũ pass nguyên vẹn; test mới cho `webui/api.py` pass; `ruff` sạch.
- JS không truyền đường dẫn file; mọi thao tác xoá đi qua cặp `preview_delete` → `execute_delete` duy nhất, với các kiểm tra an toàn ở Python.
- Đạt tương đương bản ttkbootstrap: 4 trang, 3 chế độ xoá, preview 3 nhóm, nhập tên khi xoá tất cả, tiến độ + huỷ an toàn, báo cáo, cây worktree, index mồ côi xác nhận từng file.
- UI không treo khi xem hoặc xoá project ≥ 1.000 session.
- `.exe` onedir chạy được; báo lỗi rõ ràng khi thiếu WebView2.
- `docs/claude-tidy-plan.md` không còn mâu thuẫn E1–E6.

## 6. Questions / Dependencies

Tất cả đã chốt ngày 2026-09-25 (chủ dự án đồng ý toàn bộ đề xuất):

1. ✅ **Chuyển sang pywebview — đã chắc chắn.** Các thay đổi ttkbootstrap chưa commit (`theme.py` + 4 file UI) được commit trước để còn đường quay lại. Nếu spike T33 gặp vấn đề nặng (pythonnet/antivirus) thì dừng và giữ ttkbootstrap.
2. ✅ **Đóng gói: `--onedir`**, theo số đo khởi động đã có (E5).
3. ✅ **WebView2: giả định máy đã có** (Windows 10 1803+ / 11), kiểm tra khi khởi động và hiện link tải bộ cài Evergreen nếu thiếu. Không đóng kèm bộ cài.
4. ✅ **Frontend: Alpine.js bản local**, không có bước build.
5. ✅ **Sửa tài liệu theo E1–E6: làm ngay** cùng lúc commit tài liệu pywebview, không đợi tới T43. T43 chỉ còn cập nhật phần phát sinh trong lúc làm.
6. ✅ **Jira:** tạo T33–T43 dưới epic QUYIT-741 bằng `/jira-nqdev-insight-create-issue`. T31 (QUYIT-772) được gộp vào T42.
