---
description: Tạo issue Jira nqdev (qua /tracker-jira-nqdev) từ kết quả phân tích /nqdev-client-requirement-insight (file plan có task Txx), điền sẵn Epic, Labels, Sprint, Fix versions, Original estimate. Idempotent — task đã có key Jira trong plan sẽ bị bỏ qua.
argument-hint: <plan-file.md> [--project KEY] [--epic KEY|new|none] [--labels "L1,L2"] [--sprint "<tên>"|by-milestone|none] [--fix-version "<tên>"|by-milestone|none] [--tasks "T01,T05-T08"] [--dry-run]
allowed-tools: Read, Edit, Glob, Grep, Skill, AskUserQuestion, Bash(python:*), Bash(curl:*)
---

# Tạo issue Jira từ kết quả insight — $ARGUMENTS

Đóng gói quy trình: **plan đã phân rã task (Txx)** → **đọc metadata Jira** → **chốt Epic/Labels/Sprint/Fix version/Estimate** → **preview + xác nhận** → **tạo hàng loạt** → **verify** → **ghi key Jira ngược vào plan**.

Quy ước API (endpoint, cách set Epic Link theo classic/next-gen, Sprint id, fix version, ADF description, estimate) lấy từ skill `/tracker-jira-nqdev` (action `create` + `estimate`). Command này **không định nghĩa lại** các quy ước đó — chỉ thêm phần đọc plan, hỏi metadata và chạy theo lô.

## Bước 0 — Kiểm tra điều kiện tiên quyết

1. `$ARGUMENTS` rỗng → in cú pháp + ví dụ rồi **dừng**:
   ```
   /jira-nqdev-insight-create-issue plans/2026-09-25-session-cleaner-mvp-roadmap.md
   /jira-nqdev-insight-create-issue plans/<file>.md --project QUYIT --epic new --sprint "QUYIT Sprint 34" --fix-version by-milestone
   /jira-nqdev-insight-create-issue plans/<file>.md --tasks "T20,T21" --epic QUYIT-741
   /jira-nqdev-insight-create-issue plans/<file>.md --dry-run
   ```
2. File plan không tồn tại, hoặc không có task dạng `**Txx — <tên>** (**<effort>d**)` → báo rõ, gợi ý chạy `/nqdev-client-requirement-insight` + `/nqdev-write-plan` trước, rồi **dừng**. Không tự bịa task.
3. Kiểm tra `JIRA_BASE_URL`, `JIRA_EMAIL`, `JIRA_API_TOKEN` chỉ bằng `[ -n "$VAR" ]` (in `set`/`MISSING`). Thiếu → yêu cầu người dùng `export` rồi **dừng**. **Không bao giờ** in, hỏi xin hay ghi token ra file.
4. Gọi Skill `tracker-jira-nqdev` để nạp quy ước API cho action `create`/`estimate`.

## Bước 1 — Đọc task từ plan

Với mỗi task `Txx` trong plan, trích:

| Trường | Nguồn trong plan |
|---|---|
| `id`, `summary` | dòng `- [ ] **Txx — <tên>**` |
| `effort` | con số in đậm trong ngoặc; nếu có dạng `Gốc X → **Y**` thì lấy **Y** (điều chỉnh). Không có effort riêng → để trống, ghi lý do |
| `milestone` | heading `### Mx — ...` / `### Phase 2` / `### Bổ sung...` chứa task; task bổ sung lấy milestone theo bảng milestone hoặc hỏi |
| `priority` | `MVP` / `Quan trọng` / `Nice-to-have` nếu có |
| `bullets` | các dòng con thụt lề ngay dưới task → description |

- Nếu plan đã có bảng mapping `Task | Jira` hoặc `related_issues` → task đã có key **bị bỏ qua** (idempotent). Báo số task bị bỏ qua.
- Lọc theo `--tasks` nếu có (hỗ trợ `T01,T05-T08`).

## Bước 2 — Thu thập metadata Jira

Gọi API bằng **Python (`urllib`) và ghi JSON ra file tạm rồi parse** — không pipe `curl` thẳng vào parser (output có thể bị hook/proxy chèn ký tự làm hỏng JSON).

1. Danh sách project + `style` (`classic`/`next-gen`) → `GET /rest/api/3/project/search`.
2. Field id: `Epic Link`, `Epic Name`, `Sprint` → `GET /rest/api/3/field`.
3. Field có trên màn hình tạo của Epic/Task → `GET /rest/api/3/issue/createmeta/<KEY>/issuetypes/<typeId>`. Ghi nhận `timetracking` có trên màn hình tạo hay không (quyết định cách ghi estimate ở Bước 5).
4. Board → sprint `active,future` → `GET /rest/agile/1.0/board?projectKeyOrId=<KEY>` rồi `/board/<id>/sprint`.
5. Fix version → `GET /rest/api/3/project/<KEY>/versions` (lấy cả `id`).

## Bước 3 — Chốt metadata cho từng issue

Tham số nào chưa có trên `$ARGUMENTS` → hỏi bằng **AskUserQuestion** (tối đa 4 câu/lượt, phương án khuyến nghị đứng đầu, dùng dữ liệu thật từ Bước 2 làm option):

| Field | Cách xác định | Mặc định đề xuất |
|---|---|---|
| **Project** | `--project` hoặc hỏi (liệt kê project từ Bước 2) | project cá nhân phù hợp repo |
| **Epic** | `--epic KEY` (dùng epic có sẵn) · `new` (tạo epic `[<repo>] <tiêu đề plan>`, set `Epic Name` nếu classic) · `none` | `new` |
| **Labels** | `--labels` + tự thêm: `<repo-slug>`, `mvp`/`phase-2`, mã milestone (`m1`…) | như cột trái |
| **Sprint** | tên sprint cụ thể (áp cho mọi issue) · `by-milestone` (M1 → sprint active, mỗi milestone kế tiếp → sprint future kế tiếp, Phase 2 → backlog) · `none` | `by-milestone` |
| **Fix versions** | tên version cụ thể · `by-milestone` (map milestone → version theo tháng dự kiến trong timeline plan) · `none` | `by-milestone` |
| **Original estimate** | từ `effort` của plan, quy đổi **1d = 8h**: `0.5d → 4h`, `1.5d → 1d 4h`, `2.5d → 2d 4h`. Range `X–Y` → lấy trung điểm, nói rõ trong preview | tự động |

Nếu người dùng chọn "tự nhập" nhưng chưa đưa giá trị → hỏi tiếp với danh sách sprint/version thật, **không tự đoán tên**.

## Bước 4 — Preview + Confirmation Gate

In bảng preview **trước khi gọi bất kỳ API ghi nào**:

```
Project: QUYIT (classic) · Epic: <mới> "[claude-tidy] ..." · Sprint: QUYIT Sprint 34 (id 145)

| Task | Summary                          | Labels                  | Fix version    | Estimate |
|------|----------------------------------|-------------------------|----------------|----------|
| T01  | [claude-tidy] T01 — Setup ...    | claude-tidy, mvp, m1    | Tháng 9/2026   | 2d 4h    |
...
Bỏ qua (đã có key): T05 → QUYIT-746, ...
```

Kèm cảnh báo nếu có: tổng estimate trong 1 sprint vượt ~10 ngày công; fix version lệch sprint (vd Phase 2 nằm trong sprint hiện tại); fix version đã `released`.

- `--dry-run` → dừng tại đây.
- Hỏi xác nhận **một lần cho cả lô** (tạo issue mới không ghi đè dữ liệu có sẵn), cho phép người dùng loại bớt task. Người dùng không đồng ý → dừng, không tạo gì.

## Bước 5 — Tạo issue

Viết **một script Python** (stdlib `urllib`, UTF-8) vào thư mục tạm của hệ thống — **không** ghi vào repo — rồi chạy với `PYTHONIOENCODING=utf-8`. Script phải:

1. Đọc credentials từ biến môi trường, không hardcode.
2. Có **file state** (`<tmp>/jira_<repo>_state.json`) lưu `Txx → KEY` sau **mỗi** issue tạo thành công → chạy lại không tạo trùng khi lỗi giữa chừng.
3. Tạo Epic trước (nếu `new`), rồi từng Task với: `summary` = `[<repo>] Txx — <tên>`, `description` ADF (bullet list + dòng `Nguồn: <repo>/<plan-file>`), Epic Link/parent theo `style`, Sprint = **id số**, `fixVersions` = `[{"id": "<version-id>"}]`, `labels`.
4. **Fix version gửi theo `id`, không theo `name`** — tên có dấu tiếng Việt (vd `Tháng 9/2026`) qua Git Bash/curl trên Windows bị hỏng encoding → Jira trả `400`.
5. Estimate: nếu `timetracking` **không** có trên màn hình tạo (Bước 2.3) → `PUT /rest/api/3/issue/<KEY>` với `{"fields":{"timetracking":{"originalEstimate":"..."}}}` sau khi tạo, kỳ vọng `204`.
6. In từng dòng `Txx  KEY  fixVersion  estimate|lỗi`. Lỗi `400` → in nguyên `errors`/`errorMessages`, tiếp tục task sau, không báo thành công khi chưa có `key`.

## Bước 6 — Verify

Truy vấn lại bằng JQL (`"Epic Link" = <EPIC>` với classic, `parent = <EPIC>` với next-gen) qua `/rest/api/3/search/jql`, đếm: số issue con, số có sprint đúng id, số có fix version, số có `originalEstimate`. Lệch với số đã tạo → báo rõ issue nào thiếu field gì.

## Bước 7 — Ghi key Jira ngược vào plan

Hỏi xác nhận rồi mới sửa plan:

- Frontmatter: thêm key epic vào `related_issues`.
- Thêm (hoặc cập nhật, không tạo trùng) mục `### Jira (tạo YYYY-MM-DD)` ngay trước `### Tổng hợp effort`: link epic, sprint, quy tắc fix version, bảng `Task | Jira`.
- Giữ nguyên task ID — không đánh số lại (quy ước `plans/CLAUDE.md`).

## Bước 8 — Tổng kết

- Link epic `$JIRA_BASE_URL/browse/<EPIC>` + bảng `Nhóm | Task | Jira | Fix version`.
- Số issue tạo mới / bỏ qua / lỗi; task không có estimate và lý do.
- Cảnh báo còn tồn (sprint quá tải, fix version lệch timeline).
- Đường dẫn script + file state tạm để chạy lại khi cần.

## Ràng buộc an toàn

- Không tạo/sửa issue nào trước khi người dùng xác nhận ở Bước 4.
- Chỉ **tạo mới**; không sửa/transition/xoá issue có sẵn. Muốn đổi field sau khi tạo → dùng `/tracker-jira-nqdev`.
- Không tự tạo fix version hay sprint mới trừ khi người dùng yêu cầu rõ.
- Không ghi token, email hay response chứa thông tin tài khoản vào repo.
