# claude-tidy

Ứng dụng desktop cho Windows giúp dọn dẹp an toàn dữ liệu session của Claude
Code và cache của Claude Desktop — có backup, phát hiện session đang hoạt
động, và quản lý session theo từng project, để không bao giờ xoá nhầm một
session bạn vẫn đang dùng.

## Vì sao cần

`~/.claude/projects/`, `~/.claude/sessions/`, `%APPDATA%\Claude`, và
`%TEMP%\claude` tích luỹ transcript session, cache, và file index mồ côi
theo thời gian. claude-tidy quét toàn bộ các thư mục này, gom các file liên
quan thành từng "session bundle" hoàn chỉnh thay vì từng file rời rạc, và
chỉ xoá qua đúng một pipeline có kiểm tra an toàn: **backup → verify → xoá →
ghi log**.

## Tính năng

- **Sessions** — duyệt project và session của từng project (giao diện
  master-detail, worktree được lồng dưới project cha); xoá 1 session, các
  session đã tick, hoặc toàn bộ session của 1 project.
- **Cache/Temp** — dọn thư mục cache của Claude Desktop và `%TEMP%\claude`,
  có cảnh báo nếu Claude Desktop đang chạy.
- **Index mồ côi** — xoá các file `sessions/<pid>.json` còn sót lại của
  process đã không còn tồn tại, xác nhận từng file một.
- **Cài đặt** — vị trí lưu backup, thời gian giữ backup, và các ngưỡng dùng
  để phát hiện session đang hoạt động.

## Mô hình an toàn

- **Một pipeline xoá duy nhất.** Mọi thao tác xoá — xoá 1 session, multi-select,
  "xoá tất cả", cache, hay index mồ côi — đều đi qua cùng một hàm
  `core.deleter.execute()`. Không tồn tại đường xoá thứ hai với mức an toàn
  thấp hơn.
- **Luôn backup trước khi xoá.** Mọi lần xoá đều được backup vào file `.zip`
  có timestamp + manifest (SHA-256 từng file), và được verify trước khi bất
  kỳ file gốc nào bị xoá.
- **Phát hiện session đang hoạt động một cách chính xác.** Chỉ dựa vào PID
  là chưa đủ — PID có thể bị hệ điều hành tái sử dụng. claude-tidy so sánh
  thời điểm khởi động process đã ghi lại (`procStart`) với thời điểm khởi
  động thực tế của process đang sống, chứ không chỉ kiểm tra *có* process
  nào mang PID đó hay không.
- **Session đang hoạt động không bao giờ bị xoá**, kể cả khi "xoá tất cả" —
  các session này tự động bị bỏ qua và được báo cáo lại. Session có thể đang
  hoạt động sẽ chờ người dùng xác nhận rõ ràng.
- **Danh sách cấm cứng.** `memory/`, `settings*.json`, `.credentials.json`,
  `CLAUDE.md`, `commands/`, `skills/`, và `agents/` không bao giờ được phép
  xoá — được thực thi ngay trong scan engine, không chỉ là cảnh báo ở UI.
- **"Xoá tất cả" bắt buộc gõ đúng tên project** thì nút xoá mới được bật.

## Cài đặt & chạy

Yêu cầu Python 3.11+ trên Windows.

```bat
python -m venv .venv
.venv\Scripts\pip install -e .[dev]
python -m claude_tidy
```

Hoặc dùng [run_webapp.bat](run_webapp.bat) (tên gọi vậy nhưng đây là app
desktop, không phải web app — script làm đúng việc trên).

### Kiểm tra / export danh sách package đã cài

`pyproject.toml` mới là nguồn khai báo dependency chính thức — không có
`requirements.txt` trong repo. Muốn xem chính xác các package (kể cả
dependency gián tiếp) đang nằm trong `.venv` để debug môi trường hoặc đối
chiếu version, dùng:

```bat
.venv\Scripts\pip freeze
```

Nếu cần lưu lại làm mốc tham chiếu khi báo lỗi môi trường (không dùng để cài
đặt lại, không commit vào repo):

```bat
.venv\Scripts\pip freeze > pip-freeze.txt
```

## Build ra file .exe

```bat
.venv\Scripts\pyinstaller claude-tidy.spec
```

Tạo ra `dist/claude-tidy/claude-tidy.exe` (dùng `--onedir`, không phải
`--onefile` — xem lý do trong
[plans/2026-09-25-ttkbootstrap-ui-migration-planning.md](plans/2026-09-25-ttkbootstrap-ui-migration-planning.md),
đo lại và giữ nguyên kết luận ở
[plans/2026-09-25-pywebview-ui-migration-planning.md](plans/2026-09-25-pywebview-ui-migration-planning.md)).

## Phát triển

```bat
.venv\Scripts\python -m pytest
.venv\Scripts\ruff check .
```

Toàn bộ test chạy trên cây `~/.claude` giả lập
(`tests/fixtures/fake_claude.py`) — không bao giờ chạy trên `~/.claude` thật.

## Tech stack

Python 3.11+, **pywebview** + HTML/Bootstrap 5 (UI đang triển khai, xem
[Trạng thái](#trạng-thái)) — thay cho ttkbootstrap (Tkinter), vốn từng thay
cho Flet. `psutil` để phát hiện process, PyInstaller để đóng gói, `pytest` +
`ruff` để test/lint.

## Cấu trúc dự án & tài liệu

Xem [CLAUDE.md](CLAUDE.md) để biết kiến trúc đầy đủ, các quy tắc an toàn
không thể thoả hiệp, và các file `CLAUDE.md` chi tiết theo từng thư mục con.
Product spec và execution plan nằm trong [docs/](docs/CLAUDE.md) và
[plans/](plans/CLAUDE.md).

**Ngoài phạm vi:** build cho macOS/Linux, code-signing/installer, auto-update.

## Trạng thái

Core và đóng gói của bản MVP đã hoàn thành. **UI đang trong lần đổi thứ hai:**
Flet → ttkbootstrap (xong, nay đã bị thay) → **pywebview + Bootstrap 5**
(đang làm, xem
[plans/2026-09-25-pywebview-ui-migration-planning.md](plans/2026-09-25-pywebview-ui-migration-planning.md)).
Bản chạy được hiện tại vẫn là ttkbootstrap cho tới khi bản pywebview đạt
tương đương. Còn thiếu: smoke test trên một máy/VM thật sự sạch (mới chỉ
chạy được trên máy dev), và về lâu dài là Phase 2 (restore từ backup, tự
động dọn theo lịch, system tray).

## Giấy phép

[Apache License 2.0](LICENSE).
