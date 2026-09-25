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
| Đóng gói | PyInstaller (`--onefile --windowed`) → `.exe` |
| An toàn xoá file | `send2trash` (Recycle Bin) hoặc backup zip tự viết |
| Detect process | `psutil` (kiểm tra PID còn sống) |

**Không nằm trong scope:** build macOS/Linux, code-sign installer, auto-update mechanism.

**Kiến trúc:** pywebview mở một cửa sổ native nhúng WebView2 (Windows), load file `index.html` local (Bootstrap 5 + JS thuần hoặc Alpine.js nhẹ). Toàn bộ logic nghiệp vụ (scan, xoá, backup...) nằm ở Python, expose qua `window.js_api.<method>()` — JS chỉ gọi và render kết quả, không chứa business logic.

## 3. Cấu trúc UI

- **Trang chính** — master-detail layout (Bootstrap grid `col-3`/`col-9`):
  - Panel trái: danh sách **project** (đọc từ slug thư mục trong `~/.claude/projects/`) — dùng `list-group`
  - Panel phải: bảng **session** của project đang chọn (Bootstrap `table`), mỗi dòng có checkbox + `badge` risk (safe/warning/danger)
  - 3 hành động xoá (nút Bootstrap `btn-danger`/`btn-outline-danger`):
    - Xoá 1 session
    - Xoá các session đã tick (multi-select)
    - Xoá tất cả session của project (dùng Bootstrap `modal` để double-confirm — nhập tên project để xác nhận)
- **Trang cấu hình (Settings)** — Bootstrap `form`:
  - Đường dẫn lưu backup
  - Thời gian giữ backup trước khi tự xoá
  - Ngưỡng thời gian coi là "có thể đang active" (ví dụ < 5 phút từ lần ghi cuối)

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

> **Câu hỏi mở chưa chốt:** khi có session active nằm trong nhóm bị chọn xoá (multi-select / xoá tất cả) — nên **tự động bỏ qua và xoá phần còn lại** (soft-skip, báo cáo sau), hay **chặn toàn bộ thao tác** bắt người dùng bỏ chọn thủ công?

## 5. Module — Phase 1 (MVP)

| Module | Loại | Độ phức tạp | Effort |
|---|---|---|---|
| Setup + Packaging (pywebview + PyInstaller) | DevOps | Thấp | 1.5 ngày |
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
   - Đọc `~/.claude/sessions/*.json` (mỗi file có PID) → check `psutil.pid_exists()` để tránh PID bị OS tái sử dụng
   - Với `.jsonl` trong `projects/` không có PID kèm theo → suy ra active gián tiếp qua `sessions/` index + `LastWriteTime` gần đây
2. **"Xoá tất cả session của project"** là hành động phá huỷ diện rộng nhất — bắt buộc double-confirm, không có đường tắt bỏ qua active check.
3. Chưa chốt hành vi khi active session lẫn trong nhóm bị chọn (soft-skip vs chặn toàn bộ) — xem mục 4.
4. **WebView2 runtime** là dependency bắt buộc trên Windows (đã có sẵn từ Windows 10/11 bản mới, nhưng máy cũ có thể thiếu) — cần kiểm tra/cài kèm khi đóng gói installer.
5. **Giao tiếp Python ↔ JS bất đối xứng**: JS gọi Python qua `js_api` (đồng bộ, dễ), nhưng Python đẩy update ngược lại JS (progress, kết quả scan) phải qua `window.evaluate_js()` — cần thiết kế contract rõ ràng (JSON schema) giữa 2 phía để tránh lệch dữ liệu.

## 9. Đề xuất ngôn ngữ theo từng phần

| Phần | Ngôn ngữ / công cụ | Ghi chú |
|---|---|---|
| Setup + Packaging | Python (`pywebview`) + PyInstaller | Đóng gói `.exe`, nhúng WebView2 |
| Scan Engine | Python (`pathlib`, `os.scandir`) | Đủ nhanh cho quét file/thư mục; không cần Rust/C trừ khi dataset cực lớn |
| Project/Session Grouping API | Python thuần (`dataclasses`) | Expose qua `js_api`, trả JSON cho JS |
| Disk Usage Analysis | Python (`os.path.getsize`, `collections.Counter`) | |
| UI — Project & Session Explorer | **HTML5 + Bootstrap 5 (CSS/JS)** | Có thể thêm Alpine.js hoặc vanilla JS để bind state, không cần React/Vue cho quy mô nhỏ này |
| `js_api` bridge | Python (`pywebview.api`) | Định nghĩa class expose method cho JS gọi trực tiếp (`window.pywebview.api.scan_project(...)`) |
| Trang cấu hình (Settings) | HTML/Bootstrap `form` + Python xử lý lưu | Lưu config dạng `config.json`/`settings.toml` |
| Active Session Detection | Python (`psutil`) | Cross-platform process check; nếu cần chi tiết hơn có thể dùng `pywin32` (WinAPI) |
| Backup + Safe Deletion | Python (`zipfile`, `shutil`, `send2trash`) | Thư viện chuẩn đủ dùng, không cần binding ngoài |
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

- Soft-skip hay chặn toàn bộ thao tác khi có active session trong nhóm xoá? (mục 4)
- Vị trí lưu backup mặc định: `%LOCALAPPDATA%\ClaudeCleanerBackup\` tự xoá sau N ngày, hay để người dùng tự chọn thư mục + không auto-xoá?
- Có cần bundle sẵn WebView2 runtime installer vào gói cài đặt, hay giả định máy Windows đã có sẵn (Windows 10 1803+ / Windows 11 đều có sẵn)?
