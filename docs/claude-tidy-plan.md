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
| Đóng gói | PyInstaller `--onedir --windowed` (`claude-tidy.spec`) → `dist/claude-tidy/claude-tidy.exe`. **Không dùng `--onefile`**: spike đo cold-start 3.6–5.4s (giải nén `%TEMP%\_MEIxxxx` mỗi lần chạy), vượt ngưỡng 3s; `--onedir` chỉ ~1–2.2s. |
| An toàn xoá file | Chỉ backup zip + manifest (sha256 từng file, verify trước khi xoá) — **không dùng `send2trash`/Recycle Bin**, vì zip+manifest mới Restore theo lô chính xác được (Phase 2) |
| Detect process | `psutil` — so `Process(pid).create_time()` với `procStart` ghi trong `sessions/<pid>.json`, **không chỉ `pid_exists()`** (PID bị OS tái sử dụng thì `pid_exists()` vẫn `True` nhưng là process khác) |

**Không nằm trong scope:** build macOS/Linux, code-sign installer, auto-update mechanism.

## 3. Cấu trúc UI

4 tab (`ttk.Notebook`):

- **Sessions** — master-detail layout:
  - Panel trái: cây **project** (`ttk.Treeview`, đọc từ slug thư mục trong `~/.claude/projects/`), worktree lồng dưới project cha (nhận diện qua `cwd`, không decode slug)
  - Panel phải: danh sách **session** của project đang chọn, mỗi dòng có checkbox + risk badge (safe/warning/danger)
  - 3 hành động xoá:
    - Xoá 1 session
    - Xoá các session đã tick (multi-select)
    - Xoá tất cả session của project (xác nhận kép — nhập đúng tên project mới bật nút Xoá)
- **Cache/Temp** — danh sách nhóm cache Claude Desktop + `%TEMP%\claude`, cảnh báo nếu Claude Desktop đang chạy, xoá thật qua cùng pipeline
- **Index mồ côi** — file `sessions/<pid>.json` của process đã tắt hoặc PID bị tái sử dụng; **xác nhận từng file riêng**, không có nút "xoá tất cả"
- **Cài đặt**:
  - Đường dẫn lưu backup (mặc định `%LOCALAPPDATA%\ClaudeTidy\backups\`)
  - Số ngày giữ backup trước khi tự xoá (mặc định 14 ngày), công tắc bật/tắt auto-xoá
  - Ngưỡng thời gian coi là "có thể đang active" (mặc định 5 phút từ lần ghi cuối)
  - Ngưỡng "mới dùng" cho badge cảnh báo (mặc định 24h)

## 4. Pipeline xoá (áp dụng cho cả 4 chế độ xoá: single / multi / all / cache / index mồ côi)

```
Chọn mục cần xoá
        ↓
Active Session Detection (re-check ngay trước khi xoá, không chỉ lúc build plan)
        ↓
Dry-run preview (3 nhóm: sẽ xoá / cần xác nhận / sẽ bỏ qua)
        ↓
Backup: nén .zip + manifest (sha256), verify trước khi xoá
        ↓
Xoá đúng những gì backup đã ghi nhận
        ↓
Ghi log thao tác (phục vụ Restore ở Phase 2)
```

**Đã chốt** (không còn là câu hỏi mở): session `active` → tự động bỏ qua (soft-skip), không có cách nào ép xoá kể cả ở "xoá tất cả"; session `maybe_active` (bao gồm cả khi không đọc được process — `psutil.AccessDenied`) → chỉ xoá nếu người dùng tick xác nhận từng mục trong dialog preview.

## 5. Module — Phase 1 (MVP)

**Đã hoàn thành** (2026-09-25) — xem chi tiết task/effort thực tế trong
[plans/2026-09-25-ttkbootstrap-ui-migration-planning.md](../plans/2026-09-25-ttkbootstrap-ui-migration-planning.md)
(T22–T32) và [plans/2026-09-25-session-cleaner-mvp-roadmap.md](../plans/2026-09-25-session-cleaner-mvp-roadmap.md)
(T02–T21, phần core dùng lại nguyên vẹn từ bản Flet). Bảng dưới giữ nguyên
làm tham chiếu estimate gốc:

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
   - Đọc `~/.claude/sessions/*.json` (mỗi file có PID **và** `procStart`) → so
     `psutil.Process(pid).create_time()` với `procStart`. **`psutil.pid_exists()`
     một mình không đủ**: PID bị OS tái sử dụng thì vẫn `True` nhưng là process
     khác — đây là lỗi thật tài liệu bản đầu mắc phải, đã sửa trong code.
   - Với `.jsonl` trong `projects/` không có PID kèm theo (hoặc không đọc được
     process — `AccessDenied`) → coi là `maybe_active`, không suy diễn là an toàn.
2. **"Xoá tất cả session của project"** là hành động phá huỷ diện rộng nhất — bắt buộc nhập đúng tên project mới bật nút Xoá, không có đường tắt bỏ qua active check.
3. ~~Chưa chốt hành vi khi active session lẫn trong nhóm bị chọn~~ **Đã chốt** (mục 4): `active` → soft-skip; `maybe_active` → xác nhận từng mục.
4. **Tkinter/ttkbootstrap là single-threaded UI** — mọi thao tác I/O nặng (scan, backup, xoá bulk) chạy trên thread riêng, cập nhật UI chỉ qua một hàng đợi (`ui/dispatch.py`: `Dispatcher.post()` từ worker thread, `root.after()` rút ra và chạy trên main thread) — không được gọi thẳng vào widget Tk từ thread nền.

## 9. Đề xuất ngôn ngữ theo từng phần

Toàn bộ dự án dùng **duy nhất Python 3.11+** — không cần chia đa ngôn ngữ. ttkbootstrap là lớp theme Bootstrap-style phủ lên Tkinter chuẩn, vẫn 100% Python, không cần cài thêm runtime ngoài.

| Phần | Ngôn ngữ / công cụ | Ghi chú |
|---|---|---|
| Setup + Packaging | Python (ttkbootstrap) + PyInstaller | `pyinstaller claude-tidy.spec` (`--onedir --windowed`) đóng gói thành `dist/claude-tidy/claude-tidy.exe` — xem mục 2 vì sao không dùng `--onefile` |
| Scan Engine | Python (`pathlib`, `os.scandir`) | Đủ nhanh cho quét file/thư mục; đo thực tế 51 project/628 session/503MB quét trong ~2.7s, không cần Rust/C |
| Project/Session Grouping API | Python thuần (`dataclasses`) | Logic nghiệp vụ đơn giản |
| Disk Usage Analysis | Python (`os.path.getsize`, `collections.Counter`) | |
| GUI — Project & Session Explorer | Python (ttkbootstrap: `Treeview`, `Frame`, `Checkbutton`) | Treeview dùng cho panel trái (project, worktree lồng bằng parent/child native) + panel phải (session list, checkbox tự vẽ bằng widget `CheckTreeview` dùng chung — `ttk.Treeview` không có checkbox sẵn) |
| Trang cấu hình (Settings) | Python (ttkbootstrap) + JSON cho config file | Đọc/ghi bằng `json` chuẩn |
| Active Session Detection | Python (`psutil`) | So `Process(pid).create_time()` với `procStart`, không chỉ `pid_exists()` |
| Backup + Safe Deletion | Python (`zipfile`, `hashlib`) | Zip + manifest sha256 tự viết, không dùng `send2trash` (xem mục 2) |
| Risk Level Indicator | Python thuần | Tái sử dụng kết quả từ Active Session Detection |
| Progress Tracking | Python (`threading` + `queue.Queue`, cập nhật UI qua `root.after()`) | Tkinter không thread-safe: `on_progress` từ worker thread chỉ được gọi `Dispatcher.post(...)`; `root.after` rút hàng đợi và chạy trên main thread — không gọi thẳng vào widget từ thread nền |

> **Lưu ý tối ưu sau này:** nếu Scan Engine chậm với dataset lớn, ưu tiên dùng `multiprocessing` trong Python trước; chỉ cân nhắc viết lại bằng Rust (qua PyO3) nếu thực sự cần thiết — không tối ưu sớm ở giai đoạn MVP.

## 10. Câu hỏi còn mở

Không còn câu hỏi mở chặn MVP — cả hai mục dưới đây đã chốt ngày 2026-09-25
(xem `plans/2026-09-25-session-cleaner-mvp-roadmap.md` §6):

- ~~Soft-skip hay chặn toàn bộ thao tác khi có active session trong nhóm xoá?~~
  **Đã chốt:** soft-skip cho `active`, xác nhận từng mục cho `maybe_active`.
- ~~Vị trí lưu backup mặc định~~ **Đã chốt:** `%LOCALAPPDATA%\ClaudeTidy\backups\`,
  tự xoá sau 14 ngày, Settings cho phép đổi thư mục và tắt auto-xoá.

Câu hỏi mở còn lại thuộc riêng lần chuyển UI này (T22–T32) — xem mục 6 của
[plans/2026-09-25-ttkbootstrap-ui-migration-planning.md](../plans/2026-09-25-ttkbootstrap-ui-migration-planning.md),
đã chốt: dùng PyInstaller `--onedir` (không `--onefile`), theme mặc định
`cosmo`, thay hẳn Flet (không giữ song song).
