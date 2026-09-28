---
type: feature
complexity: medium
status: done
related_issues: []
related_prs: []
estimated_hours: ~4
---

# Kế hoạch: Dọn dẹp cache OpenCode CLI qua tab Cache/Temp hiện có

> **Ngày:** 2026-09-28
> **Nguồn yêu cầu:** User yêu cầu "phát triển bộ tính năng xóa cho opencode" — làm rõ qua `AskUserQuestion`: "OpenCode" = OpenCode CLI (opencode.ai), một AI coding CLI khác cài trên máy dev, không liên quan Claude Code.
> **Scope thực tế:** [claude_tidy/core/paths.py](../claude_tidy/core/paths.py), [claude_tidy/core/scanner.py](../claude_tidy/core/scanner.py), `tests/` (conftest, fixture, 4 test file), `CLAUDE.md` (root + `core/` + `tests/`), [docs/claude-tidy-plan.md](../docs/claude-tidy-plan.md). **Không đổi** `webui/` hay frontend — xem lý do ở mục 2.
> **Priority:** medium
> **Trạng thái:** ✅ Đã hoàn thành (code + test), **chưa commit**

---

## 1. Phân tích / Bối cảnh

Trước khi viết code, đã khảo sát trực tiếp trên máy dev (chỉ đọc, không sửa gì) bằng `opencode debug paths` + liệt kê thư mục + query read-only vào SQLite, để không đoán mò cấu trúc dữ liệu của một app xoá-file khác đang chứa dữ liệu thật:

- OpenCode lưu data ở **`%USERPROFILE%\.local\share\opencode`** trên Windows
  (tài liệu chính thức của OpenCode ghi path kiểu XDG cho Linux/macOS —
  không áp dụng trực tiếp cho Windows, phải xác nhận trên máy thật).
- **Lịch sử session/message thật nằm trong 1 file SQLite** —
  `opencode.db` (+ `-wal`/`-shm`), lúc khảo sát: 160MB, 73 sessions, 1341
  messages, 5862 parts, 21 bảng, 38 migration — WAL đang hoạt động nghĩa là
  app có thể đang mở file này. Đây là điểm khác biệt kiến trúc căn bản so
  với Claude Code: Claude Code mỗi session là một *bộ file rời rạc* trên đĩa
  (`.jsonl` + sidecar), nên `check_deletable()` allowlist theo *shape file*
  là đủ an toàn; OpenCode hiện đại không có bộ file rời rạc nào tương ứng
  1-1 với "một session" — muốn xoá 1 session sẽ phải là `DELETE` SQL vào
  schema nội bộ, chưa hề tài liệu hoá và đã đổi 38 lần.
- Ngoài DB, còn 8 thư mục con: `log/` (log xoay vòng), `snapshot/`
  (checkpoint diff dạng content-addressed, 13MB), `tool-output/` (output
  từng lần gọi tool, 308K), `storage/session_diff` (566K) — 4 thư mục này
  rõ ràng là dữ liệu tái tạo được, không phải nguồn chân lý. Còn lại
  `delegations/`, `plans/`, `repos/`, `worktree/` — rỗng lúc khảo sát, ý
  nghĩa không rõ (đặc biệt `worktree/` nghi ngờ có thể chứa git worktree
  thật cho sub-agent task) — **không đủ cơ sở để coi là an toàn**.
- `auth.json`, `account.json`, `mcp-auth.json` là credential — phải denylist
  cứng, giống `.credentials.json` của Claude Code.

## 2. Approach / Strategy

**Quyết định phạm vi (quan trọng nhất của việc này):** chỉ xoá được 4 thư
mục con tái tạo được (`log`, `snapshot`, `tool-output`, `storage`).
**Tuyệt đối không đụng `opencode.db`** — không đọc, không ghi, không xoá.
Lý do: một `DELETE` sai vào schema nội bộ chưa tài liệu hoá của một app
đang có thể mở file ở chế độ WAL là một failure mode khác hẳn (và nặng hơn)
so với xoá nhầm 1 file trong pipeline xoá-file hiện tại — pipeline hiện tại
đã có toàn bộ cơ chế backup+verify+denylist để chống rủi ro "xoá nhầm file",
nhưng hoàn toàn không giúp gì nếu rủi ro là "ghi sai vào một DB đang mở".
Đây là scope cut **có chủ đích**, không phải làm chưa xong — xem mục 6.

**Không tạo pipeline/tab mới.** Vì phạm vi đã thu hẹp về "vài thư mục cache
tái tạo được", nó khớp y hệt khái niệm `CacheGroup`/`TargetKind.CACHE`/
`PlanMode.CACHE` đã có sẵn cho tab Cache/Temp (vốn đang dùng cho cache
Claude Desktop) — nên chọn cách **mở rộng `scan_cache()`** để trả thêm các
nhóm `"OpenCode: log"`, `"OpenCode: snapshot"`, `"OpenCode: tool-output"`,
`"OpenCode: storage"`, đi qua đúng `check_deletable()` → `deleter.execute()`
sẵn có (root `CLAUDE.md` rule 1: một pipeline xoá duy nhất). Đã xác nhận
`webui/api.py`, `webui/dto.py`, `static/app.js` đều generic theo
`CacheGroup.name`/`.id` (không hardcode "Desktop"/"Temp" ở đâu) — nên
**không cần sửa gì ở tầng UI/frontend**, tab Cache/Temp tự động hiện thêm
4 nhóm mới.

`ClaudePaths` (frozen dataclass) được thêm field `opencode_data_dir`, resolve
qua `ClaudePaths.from_env()` với env var `CLAUDE_TIDY_OPENCODE_DATA_DIR` mới
— giữ đúng pattern các root khác đã dùng (mọi root đều override được qua
env, đó là thứ giúp test suite an toàn).

## 3. Công việc đã thực hiện

- [x] **T01 — Khảo sát cấu trúc thật của OpenCode trên máy dev** (**0.5d**) ·
  Research · Cao — `opencode debug paths`, liệt kê thư mục + size, query
  read-only `sqlite_master` để biết tên bảng/số bảng/số migration. Chỉ đọc,
  không ghi gì vào `~/.local/share/opencode` thật.
- [x] **T02 — `ClaudePaths.opencode_data_dir` + `CLAUDE_TIDY_OPENCODE_DATA_DIR`**
  (**0.25d**) · Backend · Thấp — [core/paths.py](../claude_tidy/core/paths.py).
- [x] **T03 — Allowlist/denylist cho root OpenCode trong `check_deletable()`**
  (**0.5d**) · Backend · **Cao (an toàn)** — `OPENCODE_CACHE_DIRS`,
  `_allowed_in_opencode()`, mở rộng `PROTECTED_PATTERNS` với
  `opencode.db*`/`auth.json`/`account.json`/`mcp-auth.json` —
  [core/scanner.py](../claude_tidy/core/scanner.py).
- [x] **T04 — Mở rộng `scan_cache()`** (**0.25d**) · Backend · Thấp — thêm
  vòng lặp theo `OPENCODE_CACHE_DIRS`, tái dùng nguyên `CacheGroup`.
- [x] **T05 — Cách ly test khỏi `~/.local/share/opencode` thật** (**0.5d**)
  · QA · **Cao (an toàn)** — `tests/conftest.py`'s `_isolate_env` (autouse)
  redirect thêm `ENV_OPENCODE_DATA_DIR` vào sandbox tmp dir + assert; đây là
  phần bắt buộc phải đúng trước khi viết test khác, nếu quên thì test có
  nguy cơ trỏ vào 160MB dữ liệu OpenCode thật của máy dev.
- [x] **T06 — Mở rộng fixture `fake_claude.build()`** (**0.5d**) · QA ·
  Trung bình — 4 thư mục cache giả + `opencode.db`/`opencode.db-wal`/
  `auth.json`/`account.json`/`mcp-auth.json` (protected) +
  `worktree/`/`repos/` (cố ý để ngoài allowlist, dùng để test âm).
- [x] **T07 — Test mới + cập nhật test cũ** (**1d**) · QA · Trung bình —
  test mới `test_check_deletable_allows_opencode_cache_dirs_only`; cập nhật
  số đếm cache-group cứng (4→8 groups, +160 bytes) trong
  `test_scanner.py`/`test_deleter.py`/`test_grouping_risk_settings.py`/
  `test_webui_api.py` do có thêm 4 nhóm OpenCode.
- [x] **T08 — Đồng bộ tài liệu** (**0.5d**) · Docs · Thấp — root `CLAUDE.md`
  (rule 11), `core/CLAUDE.md` (mục "OpenCode CLI cleanup" + module map),
  `tests/CLAUDE.md` (đoạn `fixture.protected`), `docs/claude-tidy-plan.md`
  (mục 1, mục 3, mục 11 "câu hỏi đã chốt").

Kết quả: `pytest -q` → 93 passed; `ruff check .` → all checks passed.

## 4. Risks & Unknowns

- **Risk: một bản OpenCode tương lai đổi ý nghĩa 4 thư mục đang allowlist**
  (vd. `snapshot/` không còn là cache mà trở thành nguồn chân lý) →
  **Mitigation:** allowlist là whitelist tường minh
  (`OPENCODE_CACHE_DIRS`), không phải "xoá mọi thứ trừ X" — nếu OpenCode đổi
  cấu trúc, hành vi mặc định là **từ chối xoá** (an toàn hơn), không phải
  âm thầm xoá nhầm thứ mới.
- **Unknown: `repos/`, `delegations/`, `worktree/` có thể chứa gì** → **Plan:**
  cố ý để ngoài allowlist ở version này; nếu sau này muốn thêm, phải xác
  nhận lại trên máy thật (`opencode debug paths` + xem nội dung thực tế),
  giống hệt cách `DESKTOP_CACHE_DIRS` đã được xác nhận trước đây cho Claude
  Desktop — xem `core/CLAUDE.md` mục "OpenCode CLI cleanup".
- **Unknown: xoá `snapshot/`/`tool-output/` của một session vẫn còn trong
  `opencode.db`** → khi user mở lại session cũ đó trong OpenCode, một số
  diff/tool-output cũ có thể hiển thị "không tìm thấy file". Đây là hành vi
  **giống hệt** cách tab Cache/Temp hiện tại xử lý cache Desktop (xoá cả
  nhóm, không phân biệt "mồ côi" hay "còn dùng") — không phải hồi quy so
  với thiết kế hiện có, nhưng khác với tab Index mồ côi (vốn có phân biệt
  orphan/live) — xem mục 6 để biết vì sao chưa làm phân biệt tương tự cho
  OpenCode ở version này.

## 5. Success Criteria

- `pytest -q` pass toàn bộ, không có test nào trỏ vào
  `~/.local/share/opencode` thật (đã tự kiểm bằng assert trong
  `_isolate_env`).
- `ruff check .` sạch.
- Tab Cache/Temp hiện có (không cần sửa `webui/`/frontend) hiển thị thêm 4
  nhóm `"OpenCode: ..."` và xoá được qua đúng pipeline backup+verify+delete
  hiện tại.
- `opencode.db`, `opencode.db-wal`/`-shm`, `auth.json`, `account.json`,
  `mcp-auth.json` không bao giờ lọt vào bất kỳ `DeletePlan` nào, kể cả ở
  path `worktree`/`repos` cùng root — có test riêng khẳng định điều này
  (`test_check_deletable_allows_opencode_cache_dirs_only`).

## 6. Questions / Dependencies

- **Xoá từng OpenCode session riêng lẻ (mirror tab Sessions của Claude
  Code) — cố ý chưa làm, không phải thiếu sót.** Muốn làm được cần: (a)
  reverse-engineer đầy đủ schema `opencode.db` hiện tại (21 bảng, có thể
  đổi ở bản OpenCode sau), (b) xử lý an toàn ghi vào DB đang mở WAL bởi
  process khác (không giống mô hình "so `psutil` PID" hiện tại — cần cơ chế
  khác hẳn để biết OpenCode có đang chạy hay không trước khi ghi), (c) một
  thiết kế an toàn riêng (rollback/verify cho SQL, không thể tái dùng
  backup zip+manifest nguyên xi). **Khuyến nghị:** không làm trừ khi có yêu
  cầu rõ ràng kèm chấp nhận rủi ro — nếu làm, nên là một file plan riêng,
  không phải mở rộng lặng lẽ `OPENCODE_CACHE_DIRS`.
- **Cross-reference `opencode.db` để biết mục nào trong `snapshot/`/
  `tool-output/` thực sự "mồ côi"** (session tương ứng đã bị soft-delete/
  không còn) trước khi xoá, thay vì xoá cả nhóm — cũng cố ý để sau, vì lý do
  tương tự (phải đọc schema nội bộ chưa tài liệu hoá). Nếu làm, có thể dùng
  read-only connection (`mode=ro`) — không rủi ro ghi — nhưng vẫn cần
  validate kỹ trước khi tin kết quả cross-reference.
- Không có Jira issue cho việc này (ad-hoc theo yêu cầu trong phiên làm
  việc) — `related_issues` để trống.
