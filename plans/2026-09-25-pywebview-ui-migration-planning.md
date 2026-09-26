---
type: refactor
complexity: high
status: done
related_issues: [QUYIT-741, QUYIT-774, QUYIT-775, QUYIT-776, QUYIT-777, QUYIT-778, QUYIT-779, QUYIT-780, QUYIT-781, QUYIT-782, QUYIT-783, QUYIT-784]
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

- [x] **T33 — Spike pywebview + PyInstaller onedir** (**1d**) · DevOps · Trung bình — **2026-09-26**
  - Xác nhận bằng script spike thật (không phải HTML tĩnh giả lập): cửa sổ pywebview `edgechromium`
    load `static/index.html` thật, gắn `Api` thật + cây `~/.claude` giả từ fixture. Gọi
    `window.pywebview.api.list_projects()` từ JS, nhận về đúng 2 project — vòng JS → Python → JS
    hoạt động đúng.
  - **Phát hiện quan trọng:** `window.evaluate_js(script)` (chiều Python → JS) mặc định **không**
    tự resolve Promise — nếu script trả về Promise mà không truyền tham số `callback`, kết quả nhận
    được chỉ là `{}` (Promise bị serialize rỗng), không phải lỗi. Phải gọi
    `evaluate_js(script, callback=...)` để nhận giá trị đã resolve. Không ảnh hưởng chiều
    `onJobEvent` hiện có (`jobs.py` không đọc giá trị trả về của `evaluate_js`), nhưng **phải nhớ
    quy tắc này** nếu sau này cần Python đọc lại giá trị từ JS.
  - Đóng gói `--onedir` với `--collect-all webview --collect-all clr_loader --collect-all pythonnet`:
    build thành công, `Python.Runtime.dll` và `WebView2Loader.dll` (x86/x64/arm64) được gói đúng,
    bundle ~46MB. Đây là flag cần đưa vào `claude-tidy.spec` ở T41.
  - Xác nhận máy dev có WebView2 Runtime (registry `EdgeUpdate\Clients\{F3017226-...}`, bản
    153.0.4234.32) — chưa test được nhánh "thiếu WebView2" vì máy dev luôn có sẵn.
  - Ghi chú: `pywebview`/`pythonnet`/`clr_loader` đang cài thủ công trong `.venv`, **chưa** khai báo
    trong `pyproject.toml` — cần bổ sung ở T40.
- [x] **T34 — Trích prototype → `static/index.html`** (**1d**) · Frontend · Trung bình — **2026-09-26**
  - Viết trực tiếp `index.html` (4 tab Bootstrap 5 + Alpine.js `x-data="app()"`) khớp với `app.js`/`app.css`
    đã có sẵn, thay vì trích DOM từ file bundler gốc (cách nhanh hơn, cùng kết quả markup).
  - Đối chiếu E6: đủ cả 4 trang (Sessions, Cache/Temp, Index mồ côi, Settings), cây worktree lồng
    dưới project cha, badge rủi ro dạng pill thật.
- [x] **T35 — `js_api` + contract DTO + job runner** (**2d**) · Backend · Trung bình · phụ thuộc T33 — **Done** (đã hoàn thành trước phiên 2026-09-26, xác nhận lại qua `tests/test_webui_api.py` 8 test pass)
- [x] **T36 — Luồng xoá phía Python (token)** (**2d**) · Backend · **Cao (an toàn)** · phụ thuộc T35 — **Done** (đã hoàn thành trước phiên 2026-09-26; `test_concurrent_delete_is_rejected`, `test_token_is_one_time_use`, `test_delete_all_requires_matching_typed_name`, `test_active_session_is_never_deleted_even_if_confirmed` đều pass)

### W-M2 — Các trang

- [x] **T37 — Trang Explorer + các modal xoá** (**3.5d**) · Frontend heavy · Cao · phụ thuộc T34, T36 — **2026-09-26**
  - Xác minh bằng Playwright (không phải chỉ đọc code): 4 tab, danh sách project + worktree, bảng
    session với checkbox/badge/dung lượng, 3 luồng xoá (single/multi/all) qua modal preview 3 nhóm →
    modal tiến độ → modal kết quả, đúng số lượng/dung lượng tính toán ở mỗi bước.
  - **2 lỗi thật phát hiện và đã sửa trong lúc verify:**
    1. `includeWtChecked` (checkbox "áp dụng cho worktree con" trong modal xoá tất cả) được dùng
       trong `index.html` nhưng chưa khai báo trong state `app()` của `app.js` → Alpine báo lỗi
       `ReferenceError`. Đã thêm `includeWtChecked: false` vào state.
    2. `x-show` của Alpine đặt trên phần tử có class Bootstrap `.d-flex` (là `display:flex
       !important`) bị chính class đó đè, nên tab Sessions **không bao giờ ẩn thật sự** khi chuyển
       sang tab khác (dù DOM nội bộ đã đúng, phần tử vẫn hiển thị đè lên tab mới do CSS
       `!important` thắng inline style thường). Sửa bằng modifier `x-show.important` (Alpine 3) ở
       2 chỗ: wrapper tab Sessions và alert cảnh báo Claude Desktop đang chạy trong tab Cache/Temp
       (cùng pattern, cùng lỗi).
  - Chưa làm: virtual scroll cho project ≥ 1.000 session (chưa có dữ liệu lớn để test).
- [x] **T38 — Trang Cache/Temp + Index mồ côi** (**1.5d**) · Frontend · Thấp · phụ thuộc T37 — **2026-09-26**
  - Xác minh qua Playwright: cảnh báo khoá hiện đúng khi `claude_desktop_pid` có giá trị, ẩn đúng khi
    `null` (test cả 2 trường hợp). Tab Index mồ côi: mỗi dòng xác nhận riêng, nút xoá chỉ bật khi có
    dòng được chọn, không có nút xoá tất cả (đúng quyết định roadmap §6.5).
- [x] **T39 — Trang Settings** (**1d**) · Frontend · Thấp · phụ thuộc T35 — **2026-09-26**
  - Xác minh qua Playwright: form load đúng giá trị từ `get_settings`, nút Lưu gọi `save_settings`
    và hiện "Đã lưu." + cập nhật status bar.

### W-M3 — Gỡ ttkbootstrap, đóng gói, QA, tài liệu

- [x] **T40 — Gỡ UI ttkbootstrap** (**0.5d**) · DevOps · Thấp · phụ thuộc T37–T39 — **2026-09-26**
  - Xoá toàn bộ `claude_tidy/ui/` (9 file) + `tests/test_ui_dispatch.py` (test riêng cho
    `ui.dispatch`, không còn gì để test sau khi xoá `ui/`).
  - Chuyển `AppState` từ `claude_tidy/ui/state.py` sang `claude_tidy/webui/state.py` (module này
    vốn không import Tk, chỉ là data loading — thuộc về lớp UI hiện tại).
  - Viết `claude_tidy/webui/app.py`: `run()` — kiểm tra WebView2 qua registry (3 khoá: HKLM
    WOW6432Node, HKLM native, HKCU — theo đúng key `EdgeUpdate\Clients\{F3017226-...}` đã xác nhận ở
    T33), thiếu thì hiện `MessageBoxW` (không import `tkinter`) kèm link tải, có thì
    `webview.create_window(...) + webview.start(gui="edgechromium")`.
  - `pyproject.toml`: bỏ `ttkbootstrap>=1.10`, thêm `pywebview>=6.2`. `claude_tidy/__main__.py` gọi
    `webui.app.run()` thay vì `ui.app.run()`. `.bin/run_webapp.bat` sửa comment (hành vi không đổi).
  - Viết `claude_tidy/webui/CLAUDE.md` (ranh giới tin cậy, contract DTO, quy tắc
    `evaluate_js`/Promise phát hiện ở T33, quy tắc `x-show.important` phát hiện ở T37); cập nhật
    `claude_tidy/CLAUDE.md` bỏ hết tham chiếu `ui/`. Root `CLAUDE.md` đã được cập nhật trước đó.
  - `pytest`: 71 pass (77 trước đó trừ 6 test của `test_ui_dispatch.py` đã xoá cùng `ui/`); `ruff`
    sạch. `python -c "import claude_tidy.webui.app"` không lỗi, `_webview2_installed()` trả `True`
    trên máy dev.
- [x] **T41 — Đóng gói PyInstaller** (**1.5d**) · DevOps · Trung bình · phụ thuộc T33, T40 — **2026-09-26**
  - Cập nhật `claude-tidy.spec`: `collect_all()` cho `webview`/`clr_loader`/`pythonnet` (không chỉ
    `collect_data_files` — cần cả binary `Python.Runtime.dll`/`WebView2Loader.dll`, không chỉ data),
    `datas` thêm `claude_tidy/webui/static` → `claude_tidy/webui/static`. Giữ nguyên `--onedir`.
  - **Build thật + chạy thật** `dist/claude-tidy/claude-tidy.exe` (không phải spike riêng): xác nhận
    `_internal/claude_tidy/webui/static/` có đủ `index.html`/`app.css`/`app.js`/`vendor/`,
    `WebView2Loader.dll` (x86/x64/arm64) và `Python.Runtime.dll` có mặt, tổng bundle **26.8MB**. Khởi
    chạy exe đóng gói, xác nhận tiến trình chạy ổn định (không crash ngay), rồi đóng — không thao
    tác gì bên trong cửa sổ thật (tránh đụng dữ liệu `~/.claude` thật của máy dev).
  - Chưa làm: kiểm tra nhánh "thiếu WebView2" (máy dev luôn có sẵn runtime — cần máy/VM không có để
    test nhánh này, kế thừa sang phần "smoke test máy sạch" của T42).
- [x] **T42 — Test E2E frontend + smoke** (**1.5d**) · QA · Trung bình · phụ thuộc T37–T39 — **2026-09-26**
  - Playwright chạy `index.html` với `window.pywebview.api` giả (trả DTO mẫu). Kiểm tra: 3 chế độ xoá, `MAYBE_ACTIVE` phải tick mới xoá, nhập tên khi xoá tất cả, huỷ, kết quả
  - `pytest` + `ruff` sạch; test core cũ pass nguyên vẹn
  - Kế thừa phần còn mở của **T31**: smoke test trên máy/VM sạch (kèm kiểm tra antivirus báo nhầm)
  - **Xác nhận hoàn thành qua test thủ công bởi chủ dự án (2026-09-26), thay
    cho Playwright tự động** ở trên (chưa viết). Trong lúc test thủ công phát
    hiện 1 bug thật khớp đúng acceptance criteria "UI không treo khi xoá
    project ≥ 1.000 session": `backup._verify()` rehash toàn bộ file sau khi
    ghi zip mà không báo tiến độ, khiến UI đứng yên ở "Đang backup N/N" một
    khoảng dài trông như treo — đã sửa bằng cách thêm phase tiến độ `verify`
    (xem commit `feat(backup): add progress reporting for backup verification
    phase`). Test tự động Playwright cho T42 vẫn để ngỏ nếu sau này cần hồi
    quy tự động.
- [x] **T43 — Đồng bộ tài liệu** (**0.5d**) · Docs · Thấp — **2026-09-26** (nội dung do một tiến
  trình khác đồng bộ trước đó — xem mục 1.3/6 ở trên; phiên này chỉ **xác minh lại**, không viết
  lại)
  - Đối chiếu `docs/claude-tidy-plan.md` với code thật: `retention_days=14`,
    `maybe_active_minutes=5` khớp `Settings` (`core/settings.py`); mục "11. Câu hỏi còn mở" đã ghi
    đúng 4 quyết định (active/maybe_active, backup mặc định, WebView2, `--onedir`), không còn câu
    hỏi treo, không lặp lại câu đã chốt.

### Phase 2 (không đổi, chỉ ghi chú ảnh hưởng)

- T17 Restore: thêm một trang HTML + method `js_api`, effort gần như không đổi.
- T19 System Tray: pywebview chiếm main thread → `pystray` phải chạy trên thread riêng và phối hợp với vòng đời cửa sổ. Có thể **+0.5–1d** so với 1.5d gốc.

### Jira (tạo 2026-09-25)

Epic [QUYIT-741](https://nhquydev.atlassian.net/browse/QUYIT-741). Tất cả 11 issue trong **QUYIT Sprint 34** (id 145), fix version **Tháng 9/2026** (id 10050), labels `claude-tidy, mvp, pywebview, w-m1|w-m2|w-m3` — theo lựa chọn của chủ dự án, không rải theo milestone. Lưu ý: tổng 16 ngày công vượt sức chứa một sprint và timeline plan (~5 tuần) vượt quá tháng 9, nên cần dời phần còn lại khi đóng sprint/version. T31 (QUYIT-772) được gộp vào T42.

| Task | Jira | Task | Jira | Task | Jira |
|---|---|---|---|---|---|
| T33 | QUYIT-774 | T37 | QUYIT-778 | T41 | QUYIT-782 |
| T34 | QUYIT-775 | T38 | QUYIT-779 | T42 | QUYIT-783 |
| T35 | QUYIT-776 | T39 | QUYIT-780 | T43 | QUYIT-784 |
| T36 | QUYIT-777 | T40 | QUYIT-781 | | |

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
