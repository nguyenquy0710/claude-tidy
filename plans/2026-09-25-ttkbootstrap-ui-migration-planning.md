---
type: refactor
complexity: medium
status: planning
related_issues: [QUYIT-741, QUYIT-742, QUYIT-757]
related_prs: []
estimated_hours: ~150 (≈ 19 person-days, gồm buffer)
---

# Kế hoạch: Chuyển UI claude-tidy từ Flet sang ttkbootstrap + PyInstaller

> **Ngày lập kế hoạch:** 2026-09-25
> **Nguồn yêu cầu:** [docs/claude-tidy-plan.md](../docs/claude-tidy-plan.md) (phân tích bằng `/nqdev-client-requirement-insight`)
> **Kế hoạch gốc liên quan:** [2026-09-25-session-cleaner-mvp-roadmap.md](2026-09-25-session-cleaner-mvp-roadmap.md) (T01–T21, epic QUYIT-741)
> **Scope dự kiến:** `claude_tidy/ui/` (viết lại toàn bộ), `main.py`, `claude_tidy/__main__.py`, `pyproject.toml`, file `.spec` PyInstaller (mới), các `CLAUDE.md` liên quan, `docs/claude-tidy-plan.md`
> **Priority:** high
> **Assumption:** 1 senior dev Python; **không đổi** `claude_tidy/core/` và `tests/` hiện có

---

## 1. Phân tích / Bối cảnh

### 1.1 Tài liệu mới khác gì so với tài liệu cũ

`docs/claude-tidy-plan.md` gần như trùng với `docs/claude-session-cleaner-idea.md`. Chỉ có 3 thay đổi thực sự:

| Hạng mục | Tài liệu cũ (đã implement) | Tài liệu mới |
|---|---|---|
| GUI framework | Flet | **ttkbootstrap** (Tkinter + theme kiểu Bootstrap) |
| Đóng gói | `flet build windows` (cần Flutter SDK + VS C++) | **PyInstaller** `--onefile --windowed` |
| Effort GUI | 6d explorer + 1d progress | 6.5d explorer + 1.5d progress (chạy nền qua `threading` + `root.after()`) |

Các module còn lại (Scan, Grouping, Disk usage, Active detection, Backup, Risk) **giống hệt nhau** và đều đã implement xong trong `claude_tidy/core/`.

### 1.2 Hiện trạng codebase (đã khảo sát)

- `claude_tidy/core/` có 11 module, khoảng 1.270 dòng, **không import Flet ở đâu cả** → dùng lại 100%, kể cả toàn bộ test suite (4 file test, khoảng 580 dòng).
- `claude_tidy/ui/` có 5 file, khoảng 580 dòng, gắn chặt với Flet: `app.py`, `state.py`, `explorer.py`, `other_views.py`, `delete_flow.py`.
  - `state.py` (`AppState`) không import Flet → giữ nguyên.
  - 4 file còn lại phải **viết lại** bằng ttkbootstrap.
- T01 (`flet build windows`) đang **bị chặn** vì máy dev chưa có Flutter SDK + VS C++. Đổi sang PyInstaller gỡ được blocker này.

**Kết luận:** đây **không phải** dự án 26.5 ngày như tài liệu ghi (con số đó tính cho việc làm lại từ đầu), mà là **thay lớp UI + thay công cụ đóng gói**.

### 1.3 Chỗ tài liệu mới lạc hậu so với quyết định đã chốt

Các điểm sau đã được chốt ở §6 của roadmap gốc và đã có trong code, nhưng tài liệu mới vẫn ghi theo phiên bản cũ. Nếu không sửa sẽ có hai nguồn sự thật mâu thuẫn nhau (vi phạm quy ước `docs/CLAUDE.md`):

| # | Tài liệu mới ghi | Thực tế đã chốt / đã code |
|---|---|---|
| D1 | "`send2trash` (Recycle Bin) hoặc backup zip" | Chỉ dùng zip + manifest (để Restore theo lô chính xác) |
| D2 | "`psutil.pid_exists()` để tránh PID reuse" | Sai: `pid_exists` không chống được PID reuse. Code so `create_time()` với `procStart` |
| D3 | Mục 4 và 10: soft-skip hay chặn toàn bộ vẫn là câu hỏi mở | Đã chốt: `ACTIVE` → soft-skip; `MAYBE_ACTIVE` → xác nhận từng mục |
| D4 | Mục 10: backup mặc định vẫn là câu hỏi mở | Đã chốt: `%LOCALAPPDATA%\ClaudeTidy\backups\`, giữ 14 ngày, cho phép tắt auto-xoá |
| D5 | Settings chỉ có 3 mục | Thực tế có thêm công tắc auto-xoá backup và ngưỡng 24h cho badge warning |
| D6 | UI chỉ có Explorer + Settings | Thực tế có thêm màn Cache/Temp (T15), màn Index mồ côi (T20), cây worktree (T21) |

## 2. Approach / Strategy

**Phương án chọn:** viết lại `claude_tidy/ui/` bằng ttkbootstrap, **giữ đúng hợp đồng** giữa UI và core. Sau khi các màn mới đạt tương đương bản Flet thì **xoá hẳn Flet**, không để hai UI song song.

- **Tại sao không giữ song song:** hai UI thì mỗi thay đổi an toàn ở luồng xoá phải sửa hai nơi. Điều này đi ngược quy tắc "một luồng xoá duy nhất" trong `CLAUDE.md`.
- **Giữ nguyên hợp đồng an toàn của UI** (theo `claude_tidy/ui/CLAUDE.md`):
  - Mọi thao tác xoá chỉ đi qua **một** hàm `delete_flow.run_delete_flow(...)`.
  - Luồng đó gồm: preview 3 nhóm → checkbox cho `MAYBE_ACTIVE` → nhập tên project khi xoá tất cả → gọi `core.deleter.execute()` trên thread nền → báo cáo.
  - Nút huỷ chỉ có hiệu lực **giữa các mục**, không cắt ngang một mục đang xoá.
- **Threading:** Tkinter không thread-safe. Code hiện tại gọi `on_progress` thẳng từ worker thread (Flet cho phép). Với Tk phải có helper `ui_dispatch` đẩy callback vào `queue.Queue`, rồi main thread rút ra bằng `root.after(50, ...)`. **Tuyệt đối không** đụng widget từ worker thread.
- **Checkbox trong Treeview:** `ttk.Treeview` không có checkbox sẵn. Viết **một** widget dùng chung `CheckTreeview` (ký tự ☐/☑ hoặc image, tick-all, tag màu theo `RiskLevel`) cho Explorer, Cache, Index và dialog preview, thay vì mỗi màn tự chế một kiểu.
- **Điều hướng:** dùng `ttk.Notebook` (4 tab: Explorer / Cache & Temp / Index mồ côi / Settings) để thay `NavigationRail` của Flet. Đây là widget native, không cần tự vẽ sidebar.
- **Rủi ro đóng gói làm trước:** spike PyInstaller + ttkbootstrap ngay ở task đầu tiên, rút kinh nghiệm từ T01 bị chặn vì toolchain.

**Milestones:**

| Milestone | Nội dung | Ngày công |
|---|---|---|
| U-M1 — Spike & nền | T22–T24 | 4d |
| U-M2 — Port các màn | T25–T28 | 7.5d |
| U-M3 — Gỡ Flet, đóng gói, QA | T29–T32 | 3.5d |

## 3. Công việc cần thực hiện (Todo)

Task ID đánh tiếp từ **T22** để không trùng T01–T21 của roadmap gốc (đã gắn Jira QUYIT-742…762).

### U-M1 — Spike & nền

- [ ] **T22 — Spike ttkbootstrap + PyInstaller** (**1d**) · DevOps · Trung bình
  - App "hello" ttkbootstrap → `pyinstaller --onefile --windowed`, chạy `.exe` trên máy dev
  - Kiểm tra: theme/asset của ttkbootstrap có vào bundle không (có thể cần `--collect-data ttkbootstrap`), thời gian khởi động onefile, Windows Defender có báo nhầm không
  - Bật DPI awareness (`ctypes.windll.shcore.SetProcessDpiAwareness`) để chữ không bị mờ trên màn hình scale 125–150%
  - Kết quả spike quyết định câu hỏi 6.2 (onefile hay onedir)
- [ ] **T23 — Khung UI: cửa sổ chính, Notebook, `ui_dispatch`** (**1.5d**) · Frontend · Trung bình · phụ thuộc T22
  - `app.py`: `ttkbootstrap.Window`, Notebook 4 tab, giữ `AppState`
  - `ui/threading.py` (hoặc tên tương đương): `run_in_background(work, on_done)` + `ui_dispatch(fn)` qua queue + `root.after`
  - Test đơn vị cho dispatcher: không cần hiển thị cửa sổ, chỉ cần test logic hàng đợi
- [ ] **T24 — Widget `CheckTreeview` dùng chung** (**1.5d**) · Frontend · Trung bình · phụ thuộc T23
  - Cột checkbox, tick/untick bằng click hoặc phím Space, tick-all, `checked_ids()`
  - Tag màu theo `RiskLevel`, dùng lại **một** bảng màu `BADGE` chung
  - Hỗ trợ cây 2 cấp (project → worktree) cho T25

### U-M2 — Port các màn

- [ ] **T25 — Explorer view** (**3d**) · Frontend heavy · Cao · phụ thuộc T24
  - Panel trái: cây project, worktree lồng dưới project cha (giữ hành vi T21)
  - Panel phải: danh sách session có checkbox, badge, dung lượng, thời điểm ghi cuối
  - 3 nút xoá: 1 session / các session đã tick / tất cả của project; cả ba đều gọi `run_delete_flow`
  - Scan trên thread nền, có trạng thái "Đang quét…"; `rescan()` sau khi xoá xong
- [ ] **T26 — `delete_flow` bản ttkbootstrap** (**2d**) · Frontend · **Cao (an toàn)** · phụ thuộc T23, T24
  - Dialog modal (`Toplevel` + `grab_set`) có 3 nhóm: Sẽ xoá / Có thể đang dùng (checkbox) / Sẽ bỏ qua
  - Ô nhập tên project cho "xoá tất cả"; nút Xoá bị khoá tới khi nhập khớp
  - Dialog tiến độ có `Progressbar` và nút huỷ (`threading.Event`); `on_progress` luôn đi qua `ui_dispatch`
  - Dialog kết quả liệt kê: đã xoá, dung lượng giải phóng, đường dẫn backup (copy được), mục bị bỏ qua, mục chưa xác nhận, file lỗi
  - Gọi `prune_backups` sau khi xoá, giống bản hiện tại
- [ ] **T27 — Màn Cache/Temp + Index mồ côi** (**1.5d**) · Frontend · Thấp · phụ thuộc T26
  - Giữ cảnh báo khi Claude Desktop đang chạy
  - Index mồ côi: người dùng xác nhận **từng file**, không có nút xoá tất cả (quyết định 6.5 của roadmap gốc)
- [ ] **T28 — Màn Settings** (**1d**) · Frontend · Thấp · phụ thuộc T23
  - Thư mục backup (`filedialog.askdirectory`), số ngày giữ, bật/tắt auto-xoá, ngưỡng 5 phút, ngưỡng 24h
  - Kiểm tra dữ liệu nhập (số nguyên dương) trước khi gọi `save_settings`

### U-M3 — Gỡ Flet, đóng gói, QA

- [ ] **T29 — Gỡ Flet** (**0.5d**) · DevOps · Thấp · phụ thuộc T25–T28
  - Xoá code Flet cũ; `pyproject.toml`: bỏ `flet` và `[tool.flet]`, thêm `ttkbootstrap`, thêm `pyinstaller` vào `dev`
  - Cập nhật `main.py`, `claude_tidy/__main__.py`, root `CLAUDE.md` và `claude_tidy/ui/CLAUDE.md` (thay `page.run_thread` bằng `ui_dispatch`, thay `NavigationRail` bằng `Notebook`)
- [ ] **T30 — Đóng gói PyInstaller** (**1.5d**, thay cho T01 + T16 của roadmap gốc) · DevOps · Trung bình · phụ thuộc T22, T29
  - File `.spec` commit vào repo, icon, version info (`--version-file`), script build 1 lệnh
  - Smoke test `.exe` trên máy/VM sạch không cài Python, dùng `~/.claude` thật đã backup trước
- [ ] **T31 — Checklist smoke test UI** (**1d**) · QA · Trung bình · phụ thuộc T30
  - Kịch bản thủ công: 3 chế độ xoá, session `ACTIVE` bị bỏ qua, `MAYBE_ACTIVE` phải tick mới xoá, huỷ giữa chừng, project có ≥ 1.000 session không treo UI, DPI 150%
  - `pytest` và `ruff` phải sạch (core không đổi nên test cũ vẫn phải pass nguyên vẹn)
- [ ] **T32 — Đồng bộ tài liệu** (**0.5d**) · Docs · Thấp
  - Sửa `docs/claude-tidy-plan.md` theo bảng D1–D6 (mục 1.3)
  - Quyết định số phận `docs/claude-session-cleaner-idea.md`: giữ làm lịch sử (thêm dòng "đã thay bằng…") hay xoá (câu hỏi 6.3)

### Phase 2 (không đổi, chỉ ghi chú ảnh hưởng)

- T17 Restore, T18 Scheduled Auto-Clean: không đổi.
- T19 System Tray: Tk không có tray sẵn → cần thêm `pystray` chạy trên thread riêng, có thể **+0.5d** so với estimate gốc 1.5d.

### Tổng hợp effort

| Hạng mục | Tài liệu mới (làm từ đầu) | Điều chỉnh (dùng lại core) |
|---|---|---|
| Phần việc thực tế | 26.5d | **15d** (T22–T32) |
| Buffer QA 15% + PM 10% | 6.6d | **3.75d** |
| **Tổng** | ~33d (MVP) | **~19d** (range 16–22d) |
| **Timeline 1 dev** (Total ÷ 0.8) | 7–8 tuần | **~4.5–5 tuần** |

Tiết kiệm được khoảng 12 ngày vì Scan, Grouping, Disk usage, Active detection, Backup, Risk và toàn bộ test core đã xong. Riêng phần GUI (T24–T28, 9d) **không** rẻ hơn estimate của tài liệu: Tk thiếu checkbox trong Treeview và bắt buộc tự marshal thread.

**Chưa bao gồm:** code-sign `.exe` (liên quan trực tiếp tới rủi ro Defender báo nhầm, xem Risk 2), installer, auto-update, macOS/Linux, Phase 2.

## 4. Risks & Unknowns

- **Risk 1 — Cập nhật widget Tk từ worker thread** (lỗi ngẫu nhiên, crash khó tái hiện): → **Mitigation:** mọi callback từ core đi qua `ui_dispatch`; review T25–T27 phải grep không còn gọi widget trong `work()`.
- **Risk 2 — PyInstaller onefile bị Windows Defender/antivirus báo nhầm** (hay gặp với exe không ký): → **Mitigation:** kiểm ở T22; nếu bị thì chuyển sang onedir + zip, hoặc cân nhắc code-sign (ngoài scope).
- **Risk 3 — Onefile khởi động chậm** vì mỗi lần chạy phải giải nén vào `%TEMP%\_MEIxxxx`: → **Mitigation:** đo ở T22. Thư mục này nằm ngoài `%TEMP%\claude` nên không bị app tự quét nhầm.
- **Risk 4 — Làm mất tính năng khi port** (worktree, index mồ côi, badge 24h, huỷ an toàn): → **Mitigation:** checklist tương đương theo bảng D6 + T12–T15, T20–T21 của roadmap gốc, kiểm ở T31 trước khi gỡ Flet (T29).
- **Risk 5 — Hiệu năng Treeview với hàng nghìn dòng:** → **Mitigation:** insert theo lô trong `after()`, cân nhắc lazy-load theo project; đo ở T25.
- **Unknown 1 — ttkbootstrap có cần khai báo thêm data khi đóng gói không** (tuỳ version): → **Plan:** xác định ở T22.

## 5. Success Criteria

- Không còn `import flet` trong repo; `pyproject.toml` không còn phụ thuộc Flet.
- `claude_tidy/core/` và `tests/` **không bị sửa** (trừ khi phát hiện bug thật); `pytest` + `ruff` sạch.
- Mọi thao tác xoá trong UI mới đều đi qua đúng một `run_delete_flow` → `core.deleter.execute()`.
- Đạt tương đương bản Flet: 4 màn, 3 chế độ xoá, preview 3 nhóm, nhập tên khi xoá tất cả, tiến độ + huỷ an toàn, báo cáo, cây worktree, index mồ côi xác nhận từng file.
- UI không treo khi scan/xoá project ≥ 1.000 session.
- `.exe` (PyInstaller) chạy được trên máy Windows sạch, chữ không mờ ở DPI 150%.
- `docs/claude-tidy-plan.md` không còn mâu thuẫn với quyết định đã chốt (D1–D6).

## 6. Questions / Dependencies

1. **Thay hẳn Flet hay giữ song song?**
   → *Đề xuất:* **thay hẳn** sau khi đạt tương đương (T29). Giữ song song thì luồng xoá an toàn phải bảo trì ở hai nơi.
2. **PyInstaller `--onefile` (như tài liệu) hay `--onedir`?**
   → *Đề xuất:* thử onefile ở T22. Nếu khởi động > 3 giây hoặc bị antivirus báo nhầm thì chuyển onedir + zip.
3. **Tài liệu cũ `docs/claude-session-cleaner-idea.md`:**
   → *Đề xuất:* giữ lại làm lịch sử, thêm dòng đầu "Đã thay bằng `claude-tidy-plan.md` (2026-09-25)"; sửa tài liệu mới theo D1–D6.
4. **Jira:** QUYIT-742 (T01 `flet build`) và QUYIT-757 (T16 packaging) không còn đúng. Các task UI đã làm bằng Flet (T12–T15, T21) nay phải làm lại.
   → *Đề xuất:* chuyển QUYIT-742 / QUYIT-757 sang trạng thái huỷ hoặc thay thế, rồi tạo T22–T32 dưới epic QUYIT-741 bằng `/jira-nqdev-insight-create-issue`.
5. **Theme ttkbootstrap mặc định** (vd `cosmo` sáng / `darkly` tối) và có cho đổi theme trong Settings không?
   → *Đề xuất:* mặc định `cosmo`, chưa cho đổi trong MVP.
