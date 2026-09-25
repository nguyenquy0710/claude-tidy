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
| Ngôn ngữ | Python 3.11+ |
| GUI framework | **ttkbootstrap** (Tkinter + theme Bootstrap-style) |
| Đóng gói | PyInstaller (`--onefile --windowed`) → `.exe` |
| An toàn xoá file | `send2trash` (Recycle Bin) hoặc backup zip tự viết |
| Detect process | `psutil` (kiểm tra PID còn sống) |

**Không nằm trong scope:** build macOS/Linux, code-sign installer, auto-update mechanism.

## 3. Cấu trúc UI

- **Trang chính** — master-detail layout:
  - Panel trái: danh sách **project** (đọc từ slug thư mục trong `~/.claude/projects/`)
  - Panel phải: danh sách **session** của project đang chọn, mỗi dòng có checkbox + risk badge (safe/warning/danger)
  - 3 hành động xoá:
    - Xoá 1 session
    - Xoá các session đã tick (multi-select)
    - Xoá tất cả session của project (có bước xác nhận kép — nhập tên project hoặc double-confirm)
- **Trang cấu hình (Settings)**:
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
| Setup + Packaging (ttkbootstrap + PyInstaller) | DevOps | Thấp | 1.5 ngày |
| Scan Engine (projects/, sessions/, temp, cache Desktop app) | Backend | Trung bình | 4 ngày |
| Project/Session Grouping API (list theo project, action single/multi/all) | Backend | Trung bình | 2 ngày |
| Disk Usage Analysis | Backend | Thấp | 1.5 ngày |
| GUI — Project & Session Explorer (master-detail, multi-select, 3 nút xoá) | Frontend heavy | Cao | 6.5 ngày |
| Trang cấu hình (Settings) | Frontend | Trung bình | 1.5 ngày |
| **Active Session Detection** (PID check qua `sessions/` + `psutil`) | Backend | **Cao — rủi ro cao nhất** | 2.5 ngày |
| Backup + Safe Deletion (áp dụng cho cả 3 chế độ xoá) | Backend | Cao | 4 ngày |
| Risk Level Indicator (badge safe/warning/danger) | Backend | Trung bình | 1 ngày |
| Progress Tracking (bulk/all — số lượng lớn, chạy nền qua threading) | Full-stack | Trung bình | 1.5 ngày |
| **Tổng MVP core** | | | **26.5 ngày** |

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
| MVP core | 26.5 ngày |
| Phase 2 | 5 ngày |
| Buffer (QA 15% + PM 10%) | 7.9 ngày |
| **Tổng** | **~39 ngày** |
| **Timeline (1 dev)** | **7–8 tuần** |

## 8. Rủi ro kỹ thuật chính

1. **Active Session Detection** — rủi ro cao nhất. Sai sót ở đây có thể xoá nhầm session đang dùng dở. Cách tiếp cận:
   - Đọc `~/.claude/sessions/*.json` (mỗi file có PID) → check `psutil.pid_exists()` để tránh PID bị OS tái sử dụng
   - Với `.jsonl` trong `projects/` không có PID kèm theo → suy ra active gián tiếp qua `sessions/` index + `LastWriteTime` gần đây
2. **"Xoá tất cả session của project"** là hành động phá huỷ diện rộng nhất — bắt buộc double-confirm, không có đường tắt bỏ qua active check.
3. Chưa chốt hành vi khi active session lẫn trong nhóm bị chọn (soft-skip vs chặn toàn bộ) — xem mục 4.
4. **Tkinter/ttkbootstrap là single-threaded UI** — mọi thao tác I/O nặng (scan, backup, xoá bulk) bắt buộc chạy trên thread riêng (`threading.Thread`) rồi cập nhật UI qua `root.after()`, không được block main loop.

## 9. Đề xuất ngôn ngữ theo từng phần

Toàn bộ dự án dùng **duy nhất Python 3.11+** — không cần chia đa ngôn ngữ. ttkbootstrap là lớp theme Bootstrap-style phủ lên Tkinter chuẩn, vẫn 100% Python, không cần cài thêm runtime ngoài.

| Phần | Ngôn ngữ / công cụ | Ghi chú |
|---|---|---|
| Setup + Packaging | Python (ttkbootstrap) + PyInstaller | `pyinstaller --onefile --windowed` đóng gói thành `.exe` |
| Scan Engine | Python (`pathlib`, `os.scandir`) | Đủ nhanh cho quét file/thư mục; không cần Rust/C trừ khi dataset cực lớn |
| Project/Session Grouping API | Python thuần (`dataclasses`) | Logic nghiệp vụ đơn giản |
| Disk Usage Analysis | Python (`os.path.getsize`, `collections.Counter`) | |
| GUI — Project & Session Explorer | Python (ttkbootstrap: `Treeview`, `Frame`, `Checkbutton`) | Treeview dùng cho panel trái (project) + panel phải (session list có checkbox) |
| Trang cấu hình (Settings) | Python (ttkbootstrap) + JSON/TOML cho config file | Đọc/ghi bằng `json`/`tomllib` chuẩn |
| Active Session Detection | Python (`psutil`) | Cross-platform process check; nếu cần chi tiết hơn có thể dùng `pywin32` (WinAPI) |
| Backup + Safe Deletion | Python (`zipfile`, `shutil`, `send2trash`) | Thư viện chuẩn đủ dùng, không cần binding ngoài |
| Risk Level Indicator | Python thuần | Tái sử dụng kết quả từ Active Session Detection |
| Progress Tracking | Python (`threading` + `queue`, cập nhật UI qua `root.after()`) | Tkinter không có async handler sẵn như Flet — bắt buộc chạy I/O nặng trên thread riêng để tránh đơ UI |

> **Lưu ý tối ưu sau này:** nếu Scan Engine chậm với dataset lớn, ưu tiên dùng `multiprocessing` trong Python trước; chỉ cân nhắc viết lại bằng Rust (qua PyO3) nếu thực sự cần thiết — không tối ưu sớm ở giai đoạn MVP.

## 10. Câu hỏi còn mở

- Soft-skip hay chặn toàn bộ thao tác khi có active session trong nhóm xoá? (mục 4)
- Vị trí lưu backup mặc định: `%LOCALAPPDATA%\ClaudeCleanerBackup\` tự xoá sau N ngày, hay để người dùng tự chọn thư mục + không auto-xoá?
