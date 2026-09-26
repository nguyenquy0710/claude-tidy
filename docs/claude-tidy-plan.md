# claude-tidy — Phác thảo ý tưởng

**Repository:** https://github.com/nguyenquy0710/claude-tidy
**Description:** Desktop app to safely clean up Claude Code sessions and Claude Desktop cache on Windows — with backup, active-session detection, and per-project session management.

## 1. Bối cảnh & mục tiêu

Ứng dụng desktop giúp dọn dẹp:
- Session `.jsonl` rác trong `~/.claude/projects/<project-slug>/`
- Index session trong `~/.claude/sessions/`
- Cache/log của Claude Desktop app (`%APPDATA%\Claude`)
- Các file tạm trong `%TEMP%\claude`

Bản viết lại bằng **Python**, build thành desktop app native cho Windows.

## 2. Tech stack

| Thành phần | Lựa chọn |
|---|---|
| Ngôn ngữ backend | Python 3.11+ |
| UI | **HTML + Bootstrap 5 (CSS/JS thật)**, render qua **pywebview** |
| Cầu nối Python ↔ JS | `pywebview` `js_api` (gọi hàm Python trực tiếp từ JavaScript) |
| Thư viện frontend | Bootstrap 5 + Alpine.js, **để local** trong repo (không CDN, không bước build) — app chạy offline |
| Đóng gói | PyInstaller **`--onedir --windowed`** (`claude-tidy.spec`) → `dist/claude-tidy/claude-tidy.exe`. **Không dùng `--onefile`**: đã đo cold-start onefile 3.6–5.4s (giải nén `%TEMP%\_MEIxxxx` mỗi lần chạy), onedir chỉ ~1–2.2s |
| An toàn xoá file | Chỉ backup zip + manifest (sha256 từng file, verify trước khi xoá) — **không dùng `send2trash`/Recycle Bin**, vì zip+manifest mới Restore theo lô chính xác được (Phase 2) |
| Detect process | `psutil` — so `Process(pid).create_time()` với `procStart` ghi trong `sessions/<pid>.json`, **không chỉ `pid_exists()`** (PID bị OS tái sử dụng thì `pid_exists()` vẫn `True` nhưng là process khác); không đọc được process (`AccessDenied`) → coi là "có thể đang active" |

**Không nằm trong scope:** build macOS/Linux, code-sign installer, auto-update mechanism.

**Kiến trúc:** pywebview mở một cửa sổ native nhúng WebView2 (Windows), load file `index.html` local (Bootstrap 5 + JS thuần hoặc Alpine.js nhẹ). Toàn bộ logic nghiệp vụ (scan, xoá, backup...) nằm ở Python, expose qua `window.js_api.<method>()` — JS chỉ gọi và render kết quả, không chứa business logic.

**Ranh giới tin cậy:** JS không bao giờ gửi đường dẫn file, chỉ gửi id project/session. Kế hoạch xoá luôn được build ở Python. Mọi kiểm tra an toàn (mục đã tick xác nhận, tên project gõ vào khi xoá tất cả, chỉ một thao tác xoá tại một thời điểm) đều kiểm lại ở Python, không chỉ dựa vào nút bị khoá bên JS. Dữ liệu Python đẩy sang JS qua `evaluate_js` luôn đi qua `json.dumps`.

**WebView2:** bắt buộc engine Edge Chromium (`gui="edgechromium"`). Giả định máy đã có WebView2 runtime (Windows 10 1803+ / Windows 11); nếu thiếu thì báo lỗi kèm link tải bộ cài Evergreen — không đóng kèm bộ cài, không để pywebview rơi về engine IE (Bootstrap 5 không chạy trên IE).

## 3. Cấu trúc UI

- **Trang chính (Sessions)** — master-detail layout (Bootstrap grid `col-3`/`col-9`):
  - Panel trái: danh sách **project** (đọc từ slug thư mục trong `~/.claude/projects/`) — dùng `list-group`; worktree lồng dưới project cha (nhận diện qua `cwd`, không decode slug); chuột phải trên một dòng mở menu ngữ cảnh: mở thư mục project trong Explorer, sao chép đường dẫn, quét lại riêng project đó, xoá tất cả session của project đó
  - Panel phải: bảng **session** của project đang chọn (Bootstrap `table`), mỗi dòng có checkbox + `badge` risk (safe/warning/danger)
  - 3 hành động xoá (nút Bootstrap `btn-danger`/`btn-outline-danger`):
    - Xoá 1 session
    - Xoá các session đã tick (multi-select)
    - Xoá tất cả session của project (dùng Bootstrap `modal` để double-confirm — nhập tên project để xác nhận)
- **Trang Cache/Temp** — nhóm cache Claude Desktop + `%TEMP%\claude`, cảnh báo nếu Claude Desktop đang chạy, xoá thật qua cùng pipeline
- **Trang Index mồ côi** — file `sessions/<pid>.json` của process đã tắt hoặc PID bị tái sử dụng; **xác nhận từng file riêng**, không có nút "xoá tất cả"
- **Trang cấu hình (Settings)** — Bootstrap `form`:
  - Đường dẫn lưu backup (mặc định `%LOCALAPPDATA%\ClaudeTidy\backups\`)
  - Số ngày giữ backup trước khi tự xoá (mặc định 14 ngày), công tắc bật/tắt auto-xoá
  - Ngưỡng thời gian coi là "có thể đang active" (mặc định 5 phút từ lần ghi cuối)
  - Ngưỡng "mới dùng" cho badge cảnh báo (mặc định 24h)

## 4. Pipeline xoá (áp dụng cho cả 3 chế độ xoá)

```
Chọn session(s) cần xoá
        ↓
Active Session Detection (chặn/soft-skip session đang mở)
        ↓
Dry-run preview (hiển thị danh sách sẽ xoá + dung lượng giải phóng)
        ↓
Backup: nén .zip vào thư mục backup có timestamp
        ↓
Xoá file gốc
        ↓
Ghi log thao tác (phục vụ Restore ở Phase 2)
```

**Đã chốt** (không còn là câu hỏi mở): session `active` → tự động bỏ qua (soft-skip), báo cáo sau, không có cách nào ép xoá kể cả ở "xoá tất cả"; session `maybe_active` (bao gồm cả khi không đọc được process — `psutil.AccessDenied`) → chỉ xoá nếu người dùng tick xác nhận từng mục trong modal preview. Active Session Detection được chạy lại ngay trước khi xoá, không chỉ lúc build plan.

## 5. Module — Phase 1 (MVP)

| Module | Loại | Độ phức tạp | Effort |
|---|---|---|---|
| Setup + Packaging (pywebview + PyInstaller onedir) | DevOps | Thấp | 1.5 ngày |
| Scan Engine (projects/, sessions/, temp, cache Desktop app) | Backend | Trung bình | 4 ngày |
| Project/Session Grouping API (list theo project, action single/multi/all) | Backend | Trung bình | 2 ngày |
| Disk Usage Analysis | Backend | Thấp | 1.5 ngày |
| UI — Project & Session Explorer (HTML/Bootstrap, master-detail, multi-select, 3 nút xoá) | Frontend heavy | Cao | 6 ngày |
| `js_api` bridge (expose Python methods cho JS gọi) | Full-stack | Trung bình | 1.5 ngày |
| Trang cấu hình (Settings) | Frontend | Trung bình | 1.5 ngày |
| **Active Session Detection** (PID check qua `sessions/` + `psutil`) | Backend | **Cao — rủi ro cao nhất** | 2.5 ngày |
| Backup + Safe Deletion (áp dụng cho cả 3 chế độ xoá) | Backend | Cao | 4 ngày |
| Risk Level Indicator (badge safe/warning/danger) | Backend | Trung bình | 1 ngày |
| Progress Tracking (bulk/all — số lượng lớn, callback JS qua `evaluate_js`) | Full-stack | Trung bình | 1.5 ngày |
| **Tổng MVP core** | | | **27.5 ngày** |

## 6. Module — Phase 2 (Post-MVP)

| Module | Ưu tiên | Effort |
|---|---|---|
| Restore từ backup | Quan trọng | 1.5 ngày |
| Scheduled Auto-Clean | Nice-to-have | 2 ngày |
| System Tray | Nice-to-have | 1.5 ngày |
| **Tổng Phase 2** | | **5 ngày** |

## 7. Tổng estimate

| Hạng mục | Effort |
|---|---|
| MVP core | 27.5 ngày |
| Phase 2 | 5 ngày |
| Buffer (QA 15% + PM 10%) | 8.1 ngày |
| **Tổng** | **~41 ngày** |
| **Timeline (1 dev)** | **8 tuần** |

## 8. Rủi ro kỹ thuật chính

1. **Active Session Detection** — rủi ro cao nhất. Sai sót ở đây có thể xoá nhầm session đang dùng dở. Cách tiếp cận:
   - Đọc `~/.claude/sessions/*.json` (mỗi file có `pid` + `procStart`) → so `psutil.Process(pid).create_time()` với `procStart` để phát hiện PID bị OS tái sử dụng (`pid_exists()` một mình không phát hiện được)
   - Với `.jsonl` trong `projects/` không có PID kèm theo → suy ra active gián tiếp qua `sessions/` index + `LastWriteTime` gần đây
2. **"Xoá tất cả session của project"** là hành động phá huỷ diện rộng nhất — bắt buộc double-confirm (kiểm lại ở Python, không chỉ ở JS), không có đường tắt bỏ qua active check.
3. ~~Chưa chốt hành vi khi active session lẫn trong nhóm bị chọn~~ — đã chốt, xem mục 4.
4. **WebView2 runtime** là dependency bắt buộc trên Windows (đã có sẵn từ Windows 10 1803+ / Windows 11, máy cũ có thể thiếu) — đã chốt: kiểm tra khi khởi động và báo kèm link tải, không đóng kèm bộ cài.
5. **Giao tiếp Python ↔ JS bất đối xứng**: JS gọi Python qua `js_api` (đồng bộ, dễ), nhưng Python đẩy update ngược lại JS (progress, kết quả scan) phải qua `window.evaluate_js()` — cần thiết kế contract rõ ràng (JSON schema) giữa 2 phía để tránh lệch dữ liệu.

## 9. Đề xuất ngôn ngữ theo từng phần

| Phần | Ngôn ngữ / công cụ | Ghi chú |
|---|---|---|
| Setup + Packaging | Python (`pywebview`) + PyInstaller `--onedir` | Đóng gói `.exe` dùng WebView2 runtime có sẵn trên máy |
| Scan Engine | Python (`pathlib`, `os.scandir`) | Đủ nhanh cho quét file/thư mục; không cần Rust/C trừ khi dataset cực lớn |
| Project/Session Grouping API | Python thuần (`dataclasses`) | Expose qua `js_api`, trả JSON cho JS |
| Disk Usage Analysis | Python (`os.path.getsize`, `collections.Counter`) | |
| UI — Project & Session Explorer | **HTML5 + Bootstrap 5 (CSS/JS)** | Alpine.js (bản local) để bind state, không cần React/Vue hay bước build cho quy mô nhỏ này |
| `js_api` bridge | Python (`pywebview.api`) | Định nghĩa class expose method cho JS gọi trực tiếp (`window.pywebview.api.scan_project(...)`) |
| Trang cấu hình (Settings) | HTML/Bootstrap `form` + Python xử lý lưu | Lưu config dạng `config.json`/`settings.toml` |
| Active Session Detection | Python (`psutil`) | So `create_time()` với `procStart`; nếu cần chi tiết hơn có thể dùng `pywin32` (WinAPI) |
| Backup + Safe Deletion | Python (`zipfile`, `shutil`, `hashlib`) | Zip + manifest sha256, verify trước khi xoá; không dùng `send2trash` |
| Risk Level Indicator | Python thuần | Tái sử dụng kết quả từ Active Session Detection |
| Progress Tracking | Python (`threading`) đẩy update qua `window.evaluate_js()` | pywebview tự chạy `js_api` call trên thread riêng, không block UI — nhưng cần chủ động đẩy progress ngược lại JS |

> **Lưu ý tối ưu sau này:** nếu Scan Engine chậm với dataset lớn, ưu tiên dùng `multiprocessing` trong Python trước; chỉ cân nhắc viết lại bằng Rust (qua PyO3) nếu thực sự cần thiết — không tối ưu sớm ở giai đoạn MVP.

## 10. Prototype

UI prototype (HTML/Bootstrap tĩnh, chưa nối `js_api`) đặt tại:

```
docs/claude-tidy — UI.html
```

Dùng làm tham chiếu layout/markup ban đầu cho module UI — Project & Session Explorer (mục 5), sau đó nối logic thật qua `pywebview.api` khi triển khai.

## 11. Câu hỏi còn mở

Không còn câu hỏi mở. Các câu trước đây đã chốt (2026-09-25):

- **Active session trong nhóm xoá:** `active` → soft-skip + báo cáo; `maybe_active` → xác nhận từng mục; không có tuỳ chọn ép xoá (mục 4).
- **Backup mặc định:** `%LOCALAPPDATA%\ClaudeTidy\backups\`, giữ 14 ngày rồi tự xoá; Settings cho đổi thư mục và tắt auto-xoá.
- **WebView2:** giả định máy đã có sẵn; kiểm tra khi khởi động, thiếu thì báo kèm link tải; không đóng kèm bộ cài.
- **Đóng gói:** `--onedir` (không `--onefile`) theo số đo cold-start.

Chi tiết task/effort: [plans/2026-09-25-pywebview-ui-migration-planning.md](../plans/2026-09-25-pywebview-ui-migration-planning.md).
