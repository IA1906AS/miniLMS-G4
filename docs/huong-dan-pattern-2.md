# Pattern 2: Idempotency key cho nộp bài — cập nhật theo code nhóm mới

Tài liệu này giữ lại các bước triển khai để bạn học và báo cáo. **Pattern 2 hiện đã được tích hợp vào code ứng dụng**, người dùng đã chạy demo thủ công trước/sau thành công và bộ test bài tập/trắc nghiệm đã đạt 21/21. Không chèn lại những đoạn đã có. Phần của bạn cùng nhóm là pattern 3 (Optimistic locking cho sửa điểm), không sửa trong bài này.

Hướng dẫn sử dụng commit `c7ae285` làm bản trước, bao gồm hai commit mới của nhóm `fc9cb69` và `c7ae285` sau bản cũ `49506b3`. Phân tích dựa trên source local; không khẳng định remote GitHub không có commit mới hơn. Khi hoàn thiện, đã chạy cùng test giữ điểm trên bản cũ trong thư mục tạm: FAIL đúng tại `assert None == 8.5`; bản sau PASS. Xem [báo cáo pattern 2](bao-cao-pattern-2.md) để trình bày kết quả và giới hạn.

Theo PDF: áp dụng cho đúng một tính năng, thêm tối đa một module và một bảng dữ liệu, tự viết logic chính. Thiết kế dưới đây thêm `app/api/idempotency.py` và bảng `submission_idempotency`; các file khác được sửa tại chỗ. File test và tài liệu là phần kiểm chứng, không phải module nghiệp vụ bổ sung.

## 0. Tác vụ mới nào liên quan đến pattern 2?

Kết luận: **không có Idempotency key cho nộp bài trong code mới**. Các file `app/api/assessments.py`, `app/api/assessment_store.py`, `app/static/js/study.js` và `tests/test_assessments.py` không thay đổi giữa `49506b3` và `c7ae285`. Tuy nhiên, các chức năng xung quanh ảnh hưởng đến cách tích hợp, kiểm thử và báo cáo.

| Tác vụ mới | Source cần biết | Liên quan đến phần của bạn |
|---|---|---|
| Dashboard theo vai trò | `app/api/dashboard.py`, `app/static/js/dashboard.js` | Đọc submissions để đếm bài đã nộp, bài chưa nộp và bài chờ chấm. Có thể dùng để quan sát hậu quả của retry nhưng không thay thế bằng chứng file/thời gian/điểm. |
| Nhật ký lưu PostgreSQL và trang ADMIN xem log | `app/api/audit.py`, `PostgresStore.record_audit()`, `app/api/admin.py`, `app/static/js/audit.js` | Liên quan trực tiếp: `_audit("SUBMIT_ASSIGNMENT")` chạy sau commit bài. Ghi log lỗi có thể khiến phản hồi thành 500 dù bài đã lưu. Request lặp cần trả kết quả cũ và không ghi thêm SUBMIT_ASSIGNMENT. |
| Trang điểm riêng `/grades` | `app/templates/grades.html`, `app/static/js/app.js` | Là điểm tổng kết môn theo enrollments. Demo mất điểm của pattern 2 phải chấm bài tập trong `/study`, vì submit_assignment thay dữ liệu submissions. |
| Quản trị khóa tài khoản/đổi vai trò | `app/api/admin.py`, `app/api/gate.py`, `PostgresStore.administer_user()` | Gate từ chối tài khoản bị khóa và kiểm tra token_version. Key không thay thế quyền truy cập: tài khoản bị khóa hoặc đổi quyền không được dùng replay để vượt gate. |
| Đổi mật khẩu và khôi phục mật khẩu/email | `app/api/reset.py`, `app/api/mail.py`, `PostgresStore.change_password_atomic()` | Đổi/reset mật khẩu vô hiệu JWT cũ. Khi demo phải phân biệt 401 do phiên hết hiệu lực với lỗi mạng nhân tạo; không đổi mật khẩu giữa hai lần gửi. |
| Diễn đàn | `app/api/forum.py`, `PostgresStore.forum_write()` | Không thuộc phạm vi nộp bài. Có dùng khóa dòng courses, nên có thể cùng chờ khóa với nộp bài; không tự mở rộng Idempotency key sang diễn đàn. |
| Thông báo lớp và gửi email | `app/api/announcements.py`, `app/api/mail.py` | Không được gọi bởi submit_assignment. Không thêm retry email/outbox vào pattern 2. Có cấu hình SMTP mới cần hợp lệ để ứng dụng khởi động. |
| Xóa khóa học mở rộng | `PostgresStore.delete_course()` | Nay còn xóa forum_posts và course_announcements. Chỉ thêm DELETE bảng key vào cùng transaction; giữ nguyên các DELETE mới của bạn cùng nhóm. |
| Giao diện theo vai trò và điều hướng | `app/templates/base.html`, `app/static/js/courses.js` | Đường vào demo hiện tại là `/catalog` → chọn khóa → “Bài tập, trắc nghiệm và kết quả”, tới `/study?course=c1`. |

### 0.1. Hai loại điểm khác nhau — cần thống nhất với bạn làm pattern 3

| Nội dung | Nơi lưu | API sửa | Có bị submit_assignment xóa điểm khi gửi lại không? |
|---|---|---|---|
| Điểm tổng kết môn | `enrollments.score` | `PUT /courses/<course_id>/grades/<student_id>` | Không. |
| Điểm và nhận xét bài nộp | `submissions.data` (JSONB) | `PUT /courses/<course_id>/submissions/<submission_id>/grade` | Có, bản hiện tại thay bài và đặt score=null, feedback="". |

Trang `/grades` chỉnh điểm tổng kết. Trong bài demo này giảng viên phải chấm bằng form trong `/study?course=c1`. Không dùng điểm tổng kết để kết luận pattern 2 có giữ điểm bài tập hay không.

Code hiện tại chưa có kiểm tra phiên bản điểm qua version/If-Match/ETag trong hai luồng sửa điểm này. `FOR UPDATE` ở assessment_store là khóa bi quan của transaction, **không phải** triển khai Optimistic locking cho yêu cầu sửa điểm dựa trên dữ liệu cũ. `token_version` là phiên bản xác thực JWT, cũng không phải phiên bản điểm. Hai người nên thống nhất API bạn kia sẽ áp dụng pattern 3; phần bạn không tự thêm version hoặc sửa API chấm điểm.

### 0.2. Nhật ký mới tạo một tình huống lỗi sau commit

Luồng bản hiện tại:

```text
submit_assignment()
  → ghi file
  → transaction lưu submissions kết thúc: COMMIT
  → dọn file cũ
  → _audit("SUBMIT_ASSIGNMENT")
       → INSERT audit_events bằng connection/transaction khác
       → ghi audit.log
  → trả HTTP 201
```

Nếu INSERT nhật ký hoặc ghi file audit.log ném lỗi, error handler có thể trả HTTP 500. Bài đã commit không tự rollback cùng log. Đây là tình huống suy ra từ thứ tự gọi hiện tại, chưa khẳng định nó đã xảy ra trên máy bạn. Không cố làm hỏng PostgreSQL hoặc phân quyền filesystem của project để tạo lỗi; dùng monkeypatch trong test, xem mục 9.1.

Với thiết kế ở hướng dẫn này, trước khi ghi audit thì bài và key đã commit cùng nhau. Retry cùng key sẽ đọc được kết quả đã lưu và trả thành công. **Điều này bảo vệ bài nộp, không bảo đảm khôi phục được audit bị thiếu.** Không đưa ghi audit hiện tại vào bên trong transaction đang giữ khóa rồi gọi hàm mở connection riêng; việc đó cũng không biến audit thành cùng transaction.

### 0.3. Dashboard mới dùng làm bằng chứng bổ sung như thế nào?

`GET /api/dashboard` trả `counts.submissions` và `counts.pending` cho SV, `counts.grading` cho GV. `counts.grading` đếm submissions có score null.

- Nộp lần đầu: SV tăng bài đã nộp, bài đó không còn trong danh sách chưa nộp; GV tăng bài chờ chấm.
- GV chấm: số bài chờ chấm giảm.
- Bản trước, gửi lại yêu cầu cũ: điểm bị xóa nên số bài chờ chấm tăng lại.
- Bản sau, replay cùng key: số bài chờ chấm không đổi sau khi đã chấm.

Dashboard không tự đẩy dữ liệu realtime: phải tải lại dashboard để lấy số mới. `counts.submissions` có thể không đổi cả ở bản trước vì bản cũ chỉ thay cùng một dòng; không lấy số này làm bằng chứng duy nhất. Dùng schema demo sạch và chỉ một bài để so sánh số dễ hiểu.

## 1. Lỗi nhân tạo cần trình diễn

Tình huống: server đã nhận và lưu bài, nhưng trình duyệt mất phản hồi. Sinh viên tưởng thất bại nên bấm Nộp bài lần nữa với cùng file.

Trong bản hiện tại, `submit_assignment()` ở `app/api/assessments.py` vẫn thực hiện lại thao tác: tạo file mới, xóa file cũ, thay `submittedAt`, đặt `score=None` và `feedback=""`. Bảng submissions đã có UNIQUE(parent_id, student_id), nên **không nên báo cáo sai là project đang sinh hai dòng bài nộp**. Lỗi thực tế là thực hiện lặp tác dụng phụ lên cùng bài nộp.

Hai cách chứng minh:

- Cách chính: chụp thời gian nộp và tên file lưu trước/sau khi gửi lại; bản cũ đổi cả hai.
- Cách thể hiện hậu quả: sau lần nộp đầu, giảng viên chấm điểm, rồi sinh viên gửi lại yêu cầu cũ. Bản cũ xóa điểm/nhận xét. Bước chấm xen giữa là tình huống mở rộng, không phải hệ quả bắt buộc của mọi lần mất mạng.

Không cần ngắt mạng thật. Có thể bỏ phản hồi ở trình duyệt sau khi server xử lý xong; đây là mô phỏng xác định của việc client không nhận được xác nhận thành công.

## 2. Giữ hai bản riêng trước khi sửa

**Bản trước phải lấy code nhóm mới `c7ae285`, không lấy `49506b3` nữa.** Như vậy cả hai bản đều có dashboard/audit/diễn đàn/thông báo mới; khác biệt bạn báo cáo chỉ là bổ sung pattern 2. Commit cũ chỉ dùng để xem lịch sử.

Trong terminal tại thư mục project, xuất bản trước thành ZIP:

```powershell
git archive --format=zip --output=../miniLMS-before-idempotency-c7ae285.zip c7ae285
```

ZIP chứa source đã commit; không chứa `.env`, `.venv`, file nộp hoặc database. Giải nén vào thư mục riêng để lưu bản trước. Không cần reset main, không ghi đè project đang làm. Bản sau là project hiện tại sau khi bạn thực hiện các bước dưới đây.

Để chạy bản trước và sau với cùng PostgreSQL mà không làm lẫn dữ liệu, dùng schema riêng cho mỗi bản. Trong terminal chạy bản trước:

```powershell
$env:DATABASE_SCHEMA = 'demo_idempotency_before'
```

Trong terminal chạy bản sau:

```powershell
$env:DATABASE_SCHEMA = 'demo_idempotency_after'
```

Sau đó chạy ứng dụng theo README. Mỗi schema mới sẽ được khởi tạo và seed riêng. Cần `.env` hợp lệ ở từng bản và cài dependencies cho bản giải nén; không đưa `.env` vào Git. Chạy lần lượt trên port 5000, dừng bản trước bằng Ctrl+C trước khi chạy bản sau. Nếu chạy song song phải dùng port khác và thư mục upload riêng; demo này không cần chạy song song.

Trong các schema demo, hãy tạo bài tập riêng, còn hạn nộp, và dùng tài khoản sinh viên đã ghi danh. Không dùng bài thật của nhóm để cố tình tái hiện mất điểm.

Cấu hình thêm ở bản mới: ứng dụng kiểm tra PUBLIC_BASE_URL và SMTP khi khởi tạo. Demo nộp bài không cần gửi mail: có thể đặt `$env:SMTP_ENABLED = '0'` trong terminal demo và dùng PUBLIC_BASE_URL hợp lệ như `http://127.0.0.1:5000`. Không cần ghi đè cấu hình email đang dùng của nhóm trong `.env`. Biến môi trường terminal được ưu tiên hơn `.env`.

Lối vào giao diện hiện tại: đăng nhập GV → `/catalog` → chọn khóa c1 → “Bài tập, trắc nghiệm và kết quả” → tạo bài còn hạn. Đăng nhập SV ở cửa sổ trình duyệt riêng → cùng đường dẫn → chọn bài và file. GV chấm trong chính trang `/study?course=c1`; ADMIN chỉ dùng để xem nhật ký khi cần.

## 3. Chuẩn bị thao tác bỏ phản hồi trên trình duyệt

Mở trang Học tập, chọn bài tập và file TXT hợp lệ. Nhấn F12 → Console, nhập đoạn sau một lần:

```javascript
window.demoOriginalFetch = window.fetch;
window.demoDropNextSubmission = true;
window.fetch = async function (...args) {
    const response = await window.demoOriginalFetch.apply(window, args);
    const url = String(args[0]);
    const method = (args[1]?.method || 'GET').toUpperCase();
    if (window.demoDropNextSubmission && method === 'POST' &&
        /\/assignments\/[^/]+\/submissions$/.test(url) && response.ok) {
        window.demoDropNextSubmission = false;
        console.info('DEMO: server da thanh cong; client bo phan hoi.');
        throw new TypeError('DEMO: mat phan hoi sau khi server luu bai');
    }
    return response;
};
```

Bấm Nộp bài. Server xử lý thành công, nhưng giao diện báo lỗi nhân tạo vì fetch ném lỗi. Tab Network vẫn có thể thấy HTTP 201: đó là bằng chứng server đã thành công; đoạn demo chỉ chặn việc giao diện nhận kết quả.

Không tải lại trang sinh viên, không chọn lại file. Mở tài khoản giảng viên bằng cửa sổ riêng, vào `/study?course=c1`, chọn đúng bài tập, xem bài nộp và chấm 8.5, nhận xét “Đã chấm”. **Không chấm ở trang `/grades`.** Quay lại trang sinh viên ban đầu, bấm Nộp bài lần nữa. Chỉ lần đầu bị bỏ phản hồi.

Nếu muốn xem dashboard hoặc audit trong lúc giữ pending request, mở chúng ở tab/cửa sổ khác; đừng điều hướng khỏi trang SV đang giữ file và key.

Kết thúc demo, khôi phục:

```javascript
window.fetch = window.demoOriginalFetch;
```

Hoặc tải lại trang. Không đưa đoạn giả lập này vào source ứng dụng. Không tắt Docker hoặc PostgreSQL để demo mất phản hồi: khi đó bài có thể chưa lưu, không đúng tình huống đang cần chứng minh.

## 4. Bước sửa 1 — thêm một bảng

File `app/database/db.py`: thêm SQL sau vào trong chuỗi `_SCHEMA`, trước dấu kết thúc chuỗi. Không sửa bảng điểm của pattern 3.

```sql
CREATE TABLE IF NOT EXISTS submission_idempotency (
    student_id TEXT NOT NULL,
    course_id TEXT NOT NULL,
    assignment_id TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    request_hash TEXT NOT NULL,
    response_status INTEGER NOT NULL,
    response_body JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (student_id, course_id, assignment_id, idempotency_key)
);
```

Trong `PostgresStore.delete_course()`, sau câu SELECT khóa khóa học và trước DELETE courses, thêm đoạn sau. **Giữ nguyên các lệnh xóa forum_posts và course_announcements của code mới; chỉ chèn thêm, không thay toàn bộ hàm bằng phiên bản cũ.**

```python
conn.execute(
    "DELETE FROM submission_idempotency WHERE course_id = %s",
    (course_id,),
)
```

Khởi động lại ứng dụng để cơ chế khởi tạo hiện tại tạo bảng trong schema được chọn. Bảng giữ key cho đến khi xóa khóa học; phiên bản bài tập này chưa bổ sung TTL.

## 5. Bước sửa 2 — tạo module idempotency.py

Tạo file `app/api/idempotency.py`, nội dung:

```python
"""Idempotency records for assignment submissions only."""

import hashlib
import json
from uuid import UUID

from flask import request
from psycopg.types.json import Jsonb

from app.api.errors import APIError


class IdempotencyError(APIError):
    def __init__(self, code, status=400):
        self.error_code = code
        self.status_code = status
        super().__init__(code)


def submission_key():
    raw = request.headers.get("Idempotency-Key", "")
    if not raw:
        raise IdempotencyError("IDEMPOTENCY_KEY_REQUIRED")
    if len(raw) > 36:
        raise IdempotencyError("INVALID_IDEMPOTENCY_KEY")
    try:
        return str(UUID(raw))
    except ValueError as exc:
        raise IdempotencyError("INVALID_IDEMPOTENCY_KEY") from exc


def submission_hash(course_id, assignment_id, filename, content):
    metadata = json.dumps(
        [course_id, assignment_id, filename],
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    digest = hashlib.sha256(metadata + b"\x00")
    digest.update(content)
    return digest.hexdigest()


def find_response(connection, scope, request_hash):
    row = connection.execute(
        "SELECT request_hash, response_status, response_body "
        "FROM submission_idempotency WHERE student_id = %s "
        "AND course_id = %s AND assignment_id = %s AND idempotency_key = %s",
        scope,
    ).fetchone()
    if row is not None and row["request_hash"] != request_hash:
        raise IdempotencyError("IDEMPOTENCY_KEY_REUSED", 409)
    return row


def save_response(connection, scope, request_hash, body, status=201):
    connection.execute(
        "INSERT INTO submission_idempotency "
        "(student_id, course_id, assignment_id, idempotency_key, "
        "request_hash, response_status, response_body) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s)",
        (*scope, request_hash, status, Jsonb(body)),
    )
```

`scope` gồm sinh viên đã đăng nhập, khóa học, bài tập và key. Không lấy mã sinh viên từ form. Hash phát hiện cùng key nhưng khác dữ liệu. Không băm multipart thô vì boundary có thể đổi giữa hai request. Các hàm này nhận connection từ bên ngoài để dùng cùng transaction với bài nộp.

## 6. Bước sửa 3 — tích hợp vào submit_assignment()

File `app/api/assessments.py`: bổ sung import:

```python
from app.api.idempotency import (
    find_response,
    save_response,
    submission_hash,
    submission_key,
)
```

Trong hàm `submit_assignment()`, ngay sau `_authorize(course_id)` thêm:

```python
key = submission_key()
```

Giữ phần kiểm tra file hiện tại, từ `request.max_content_length` đến `_validate_document(filename, content)`. Thay phần còn lại của hàm (bắt đầu từ `storage_name = ...` đến `return ... , 201`) bằng:

```python
    request_hash = submission_hash(course_id, assignment_id, filename, content)
    scope = (g.actor["id"], course_id, assignment_id, key)
    path = None
    previous = None
    try:
        with _records(course_id) as records:
            assignment = records.get("assignments", assignment_id)
            saved = find_response(records.connection, scope, request_hash)
            if saved is not None:
                response = jsonify(saved["response_body"])
                response.status_code = saved["response_status"]
                response.headers["Idempotency-Replayed"] = "true"
                return response

            if time.time() >= assignment["deadline"]:
                raise AssessmentConflict("ASSIGNMENT_CLOSED")
            existing = records.list(
                "submissions", parent_id=assignment_id, student_id=g.actor["id"]
            )
            if existing:
                previous = existing[0]["storageName"]

            storage_name = secrets.token_hex(16)
            path = _file_path(storage_name)
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("xb") as file:
                file.write(content)
            item = _new(
                course_id,
                parentId=assignment_id,
                studentId=g.actor["id"],
                fileName=filename,
                storageName=storage_name,
                size=len(content),
                submittedAt=_iso(time.time()),
                score=None,
                feedback="",
            )
            if existing:
                item["id"] = existing[0]["id"]
            records.save("submissions", item)
            result = _submission_public(item)
            save_response(records.connection, scope, request_hash, result)
    except Exception:
        if path is not None:
            path.unlink(missing_ok=True)
        raise
    if previous:
        remove_submission_files([previous])
    _audit("SUBMIT_ASSIGNMENT")
    return jsonify(result), 201
```

Phần code trên thụt 4 dấu cách vì nằm trong hàm hiện tại. Không xóa decorator `@require_role("STUDENT")`.

Các điểm phải hiểu:

1. Xác thực và kiểm tra quyền vẫn chạy trước khi đọc kết quả cũ.
2. `_records()` đã khóa dòng khóa học bằng FOR UPDATE. Hai request đồng thời cùng khóa học phải lần lượt kiểm tra key. Không được đưa bước đọc key ra ngoài khối này.
3. Request lặp được nhận diện trước khi ghi file và trước khi kiểm tra hạn nộp. Lần đầu đã nộp thành công trước hạn thì gửi lại sau hạn vẫn nhận xác nhận cũ.
4. Bài nộp và key được lưu bằng **cùng connection, cùng transaction**. Lỗi lưu key khiến thay đổi database của bài nộp rollback.
5. File mới được dọn khi có ngoại lệ. File cũ chỉ xóa sau khi transaction thay thế thành công.
6. Request lặp trả thẳng kết quả cũ, không ghi lại audit SUBMIT_ASSIGNMENT.
7. Phản hồi lưu trong bảng là ảnh chụp lúc nộp, có thể có score=null. Muốn xem điểm hiện tại dùng API tra cứu hiện có. Không dùng phản hồi lịch sử để suy luận rằng điểm hiện tại bị xóa.

Giới hạn: khóa khóa học hiện có làm các thao tác trong cùng khóa học chờ nhau; phù hợp phạm vi bài tập nhưng phạm vi khóa khá rộng. Database không rollback được file trên ổ đĩa. Tiến trình bị tắt đột ngột có thể để lại file không được tham chiếu; bài này xử lý ngoại lệ thông thường, không tuyên bố đảm bảo toàn bộ filesystem và database commit nguyên tử.

## 7. Bước sửa 4 — cho api() nhận header

File `app/static/js/app.js`, sửa phần đầu hàm api thành:

```javascript
async function api(path, {
    method = 'GET',
    body,
    auth = false,
    headers: extraHeaders = {}
} = {}) {
    const headers = {
        'Accept': 'application/json',
        ...extraHeaders
    };
```

Giữ nguyên phần còn lại. Code Authorization hiện có chạy sau bước này nên token vẫn do ứng dụng đặt. Khi gửi FormData không tự đặt Content-Type: trình duyệt cần tự thêm multipart boundary.

`app.js` nay còn quản lý workspace theo vai trò, trang điểm và đổi mật khẩu. Chỉ sửa chữ ký/khởi tạo headers của api(), không thay toàn bộ file bằng code cũ. Hàm này dùng chung, nên sau khi sửa cần thử đăng nhập, dashboard, quản lý khóa học và thao tác của vai trò tương ứng.

## 8. Bước sửa 5 — giữ key qua lần thử lại

File `app/static/js/study.js`: thêm gần các biến đầu file:

```javascript
let pendingSubmission = null;
```

Trong handler `studyForm($('submission-upload'), ...)`, giữ các bước lấy id, file và kiểm tra kích thước. Thay từ dòng tạo FormData đến trước dòng xóa giá trị submission-file bằng:

```javascript
            if (!pendingSubmission || pendingSubmission.assignmentId !== id ||
                pendingSubmission.file !== file) {
                pendingSubmission = {
                    assignmentId: id,
                    file,
                    key: crypto.randomUUID()
                };
            }
            const body = new FormData();
            body.append('file', file);
            try {
                await api(studyBase + '/assignments/' + encodeURIComponent(id) + '/submissions', {
                    method: 'POST', auth: true, body,
                    headers: { 'Idempotency-Key': pendingSubmission.key }
                });
            } catch (error) {
                // Giữ key khi lỗi mạng/5xx: chưa biết server đã commit hay chưa.
                if (error.status && error.status < 500) pendingSubmission = null;
                throw error;
            }
            pendingSubmission = null;
```

Giữ các dòng xóa file input, tải lại danh sách và thông báo thành công phía sau.

Trong `translate()` ở app.js, bổ sung vào object messages (giữ các thông báo hiện có):

```javascript
        IDEMPOTENCY_KEY_REQUIRED: 'Yêu cầu nộp bài thiếu mã thao tác.',
        INVALID_IDEMPOTENCY_KEY: 'Mã thao tác nộp bài không hợp lệ.',
        IDEMPOTENCY_KEY_REUSED: 'Mã thao tác đã được dùng cho dữ liệu khác. Hãy chọn lại file để nộp bản mới.',
```

Quy tắc: lỗi mạng/5xx giữ cùng key + cùng File; thành công kết thúc thao tác; file khác hoặc bài tập khác tạo key mới. Key này chỉ được giữ trong phiên trang hiện tại. Tải lại trang sẽ mất key; demo phải giữ nguyên trang. Hỗ trợ qua tải lại trang cần thiết kế lưu pending operation và xác minh file riêng, chưa có trong ví dụ này.

## 9. Kiểm thử tự động và cập nhật test cũ

Do API mới yêu cầu header, trong `tests/test_assessments.py` thêm `import uuid`. Sửa helper `submit_file()` để mỗi lần nộp mới mặc định có key mới:

```python
def submit_file(
    client, student, assignment_id, course="c1", content=b"Bai lam", *, key=None
):
    return client.post(
        f"/courses/{course}/assignments/{assignment_id}/submissions",
        headers={**student, "Idempotency-Key": key or str(uuid.uuid4())},
        data={"file": (io.BytesIO(content), "../../report.txt")},
    )
```

Rà lại các test gọi trực tiếp API POST submissions: các test cần đi qua bước kiểm tra key phải thêm header hợp lệ; không đổi kỳ vọng các test role/permission. Không chỉ đổi assertion cho test chạy xanh.

Test chứng minh lỗi trước/sau: thêm hàm sau vào cùng file. Nó dùng các fixture/helper có sẵn. Có thể thêm test và helper mới này vào bản trước để thấy FAIL, rồi chạy nguyên test trên bản sau để thấy PASS.

```python
def test_idempotency_replay_preserves_graded_submission(assessment_app):
    client = assessment_app.test_client()
    teacher = auth(client, "an.gv@lms.test")
    student = auth(client, "chi.sv@lms.test")
    task = assignment(client, teacher)
    key = str(uuid.uuid4())

    # Gửi thành công nhưng giả sử client không nhận được xác nhận.
    first = submit_file(client, student, task["id"], key=key)
    assert first.status_code == 201
    directory = Path(assessment_app.config["SUBMISSION_UPLOAD_DIR"])
    stored_files = set(directory.iterdir())
    grade_url = f"/courses/c1/submissions/{first.json['id']}/grade"
    assert (
        client.put(
            grade_url,
            headers=teacher,
            json={"score": 8.5, "feedback": "Da cham"},
        ).status_code
        == 200
    )

    # Sinh viên gửi lại đúng yêu cầu cũ.
    replay = submit_file(client, student, task["id"], key=key)
    assert replay.status_code == 201
    rows = client.get(
        f"/courses/c1/assignments/{task['id']}/submissions", headers=teacher
    ).json
    assert len(rows) == 1
    assert rows[0]["score"] == 8.5
    assert rows[0]["feedback"] == "Da cham"
    assert rows[0]["submittedAt"] == first.json["submittedAt"]
    assert set(directory.iterdir()) == stored_files
    assert replay.json == first.json
    assert replay.headers["Idempotency-Replayed"] == "true"
```

Ở bản trước, request vẫn được chấp nhận dù có header lạ nhưng server chưa dùng key; assertion giữ điểm sẽ FAIL. Đó là lỗi mong đợi của bài demo, không đưa bản FAIL lên main CI. Bản sau phải PASS cùng tình huống.

Các test bổ sung cần có trước khi hoàn tất:

| Trường hợp | Kỳ vọng |
|---|---|
| Thiếu key / key sai định dạng | 400, không tạo bài/file |
| Cùng key, file khác hoặc tên file khác | 409, bài và điểm cũ không đổi |
| Key mới, file mới, trước hạn | Thay bài hợp lệ, điểm bị xóa theo nghiệp vụ nộp bản mới |
| Cùng key và dữ liệu, gửi đồng thời bằng hai client | Chỉ một lần thực hiện, hai phản hồi cùng nội dung, một phản hồi replay |
| Key đã thành công, retry sau hạn | Trả xác nhận cũ |
| Key mới sau hạn | ASSIGNMENT_CLOSED |
| Tạo app instance mới dùng cùng schema rồi retry | Vẫn replay vì key lưu PostgreSQL |
| Ép save_response ném lỗi | Không commit bài mới, không để file mới, bản cũ giữ nguyên; retry sau khi bỏ lỗi thành công |
| Sinh viên khác dùng cùng chuỗi key | Không xem được kết quả của người trước |

Để ép lỗi lưu key trong test, monkeypatch `app.api.assessments.save_response` cho ném RuntimeError. Đây là điểm hàm được import và gọi. Chỉ monkeypatch trong test, không thêm nút gây lỗi ở web.

Nếu TEST_DATABASE_URL đã được cấu hình đúng như README:

```powershell
uv run pytest tests/test_assessments.py -k idempotency -v
uv run ruff check .
uv run ruff format --check .
uv run mypy app
uv run pytest
```

Nếu chưa có TEST_DATABASE_URL, xem phần kiểm thử PostgreSQL của README trước. Không trỏ test vào schema demo để xem dữ liệu bằng tay: fixture tự tạo và xóa schema ngẫu nhiên cho từng test.

Code nhóm mới có thêm test dashboard/audit/admin/change-password/reset-email/forum/announcements. Sau test tập trung cho pattern phải chạy cả bộ test, vì api() dùng chung và database có thêm bảng. Không hạ assertion các chức năng mới để che lỗi tích hợp.

### 9.1. Test lỗi nhân tạo phù hợp với nhật ký mới

Thêm test sau vào `tests/test_assessments.py`, dùng helper submit_file đã có tham số key ở trên. Đoạn này không làm hỏng dữ liệu thật: fixture tạo schema và thư mục riêng. Nó giả lập _audit ném lỗi một lần sau commit, không giả lập lỗi ghi bảng key.

```python
def test_idempotency_retry_after_audit_failure(assessment_app, monkeypatch):
    import app.api.assessments as assessment_api

    client = assessment_app.test_client()
    teacher = auth(client, "an.gv@lms.test")
    student = auth(client, "chi.sv@lms.test")
    task = assignment(client, teacher)
    key = str(uuid.uuid4())
    real_audit = assessment_api._audit

    def broken_audit(action):
        if action == "SUBMIT_ASSIGNMENT":
            raise OSError("DEMO: audit unavailable after submission commit")
        return real_audit(action)

    monkeypatch.setattr(assessment_api, "_audit", broken_audit)
    failed = submit_file(client, student, task["id"], key=key)
    assert failed.status_code == 500

    # Error handler đã trả 500 nhưng bài nộp đã lưu.
    url = f"/courses/c1/assignments/{task['id']}/submissions"
    before = client.get(url, headers=teacher).json
    assert len(before) == 1
    directory = Path(assessment_app.config["SUBMISSION_UPLOAD_DIR"])
    stored_files = set(directory.iterdir())
    monkeypatch.setattr(assessment_api, "_audit", real_audit)

    retried = submit_file(client, student, task["id"], key=key)
    assert retried.status_code == 201
    assert client.get(url, headers=teacher).json == before
    assert set(directory.iterdir()) == stored_files
    assert retried.headers["Idempotency-Replayed"] == "true"
```

Bản trước sẽ thực hiện lại và đổi file/thời gian, nên test yêu cầu giữ nguyên sẽ FAIL. Bản sau cần PASS. Test này không chứng minh nhật ký bị thiếu sẽ được phục hồi; request replay bỏ qua _audit, đúng giới hạn nêu ở mục 0.2.

Hai kịch bản khác nhau cần phân biệt: demo Console là HTTP 201 bị client bỏ đi; test audit là server trả HTTP 500 sau commit. Cả hai đều khiến client chưa biết bài đã thành công và cần gửi lại cùng key.

## 10. Demo lại bản sau và thu bằng chứng

Lặp đúng kịch bản mục 3 trên schema demo_idempotency_after: nộp lần đầu bị bỏ phản hồi → giảng viên chấm → sinh viên bấm lại, cùng file, không reload trang.

Trong tab Network của trình duyệt kiểm tra:

- Hai request có cùng Idempotency-Key.
- Lần hai trả 201 và response header Idempotency-Replayed: true.
- Trên trang giảng viên, tải lại dữ liệu và thấy điểm 8.5, nhận xét, thời gian nộp giữ nguyên.

Tận dụng tác vụ mới để có thêm bằng chứng:

- ADMIN vào `/admin/audit`, lọc action `SUBMIT_ASSIGNMENT`, actorId là mã SV (seed c1: chi.sv@lms.test là u4). Đối chiếu resource của đúng bài đang demo. Lần đầu thành công ghi một event; bản trước retry thêm một event, bản sau replay không thêm event nộp bài. Các log LOGIN/GRADE_SUBMISSION là sự kiện khác, không đếm chung.
- Có thể gọi `GET /admin/api/audit?action=SUBMIT_ASSIGNMENT&actorId=u4` bằng JWT ADMIN hoặc dùng giao diện lọc. Số total là tổng của bộ lọc, không nhất thiết chỉ một bài; kiểm tra resource hoặc dùng dữ liệu demo sạch.
- GV tải lại `/dashboard`: bài đã chấm ở bản sau không quay lại số bài chờ chấm. Đây là minh họa bổ sung từ tính năng dashboard mới.
- Kịch bản audit lỗi ở mục 9.1 có thể thiếu event lần đầu, nên không áp dụng kỳ vọng “một event” của kịch bản Console cho nó.

Chụp bằng chứng thành bảng:

| Nội dung | Bản trước | Bản sau |
|---|---|---|
| Server đã lưu nhưng giao diện báo lỗi mô phỏng | Có | Có |
| Gửi lại cùng thao tác | Thực hiện lại | Trả kết quả cũ |
| submittedAt | Đổi | Giữ nguyên |
| File lưu nội bộ | Thay file | Giữ nguyên |
| Điểm/nhận xét đã chấm | Bị xóa | Giữ nguyên |
| Key mới để chủ động nộp bản khác | Nộp lại như cũ | Vẫn nộp lại hợp lệ trước hạn |

Nếu muốn xem bảng key bằng SQL, thay UUID bài tập/key bằng giá trị thực từ tab Network. Trong công cụ quản trị PostgreSQL:

```sql
SELECT student_id, assignment_id, idempotency_key,
       request_hash, response_status, created_at
FROM demo_idempotency_after.submission_idempotency
ORDER BY created_at DESC;
```

Hai lần gửi cùng thao tác chỉ có một bản ghi key. Lưu ý số dòng submissions của bản trước và sau đều có thể là một, nên riêng phép đếm đó không chứng minh đã sửa lỗi.

## 11. Nội dung báo cáo và câu hỏi thường gặp

Chuẩn bị 5 phần: tình huống lỗi; bằng chứng bản trước; thiết kế key/hash/transaction; bằng chứng bản sau; giới hạn.

Giải thích ngắn: “Em gắn một key cho mỗi thao tác nộp bài. Khi server đã commit nhưng phản hồi bị mất, client retry bằng cùng key. Server so hash và trả kết quả đã lưu, không ghi lại bài. Nếu dùng key đó với dữ liệu khác thì trả 409. Bài và kết quả idempotency được lưu cùng transaction PostgreSQL.”

- **Vì sao UNIQUE bài tập/sinh viên chưa đủ?** Nó chống thêm dòng trùng, nhưng bản cũ vẫn cập nhật file, thời gian và xóa điểm.
- **Vì sao không tạo UUID mỗi lần bấm retry?** Key mới khiến server hiểu là thao tác mới; phải giữ key khi chưa biết kết quả lần trước.
- **Vì sao sinh viên nộp lại bản sửa vẫn được?** Đó là thao tác mới, dùng key mới và vẫn kiểm tra hạn nộp.
- **Vì sao cần hash?** Ngăn cùng key bị dùng cho hai dữ liệu khác nhau.
- **Hai request đến cùng lúc thì sao?** Khóa dòng khóa học đã có giữ toàn bộ kiểm tra và lưu trong cùng transaction; request sau chờ rồi đọc kết quả request trước.
- **Khởi động lại server có mất key không?** Không, key nằm trong PostgreSQL.
- **Có bảo đảm mọi request trên toàn hệ thống chỉ chạy một lần không?** Không. Phạm vi là nộp bài với cùng scope/key và dữ liệu, khi bản ghi key còn được giữ; file và audit còn có giới hạn riêng.
- **Khác pattern 3 thế nào?** Pattern 2 nhận diện một thao tác bị gửi lặp; pattern 3 phát hiện hai thay đổi độc lập cùng dựa trên phiên bản dữ liệu cũ.
- **Code mới đã có token_version, có phải pattern 3 chưa?** Không, đó là vô hiệu phiên đăng nhập. Phiên bản điểm cần được kiểm tra tại API sửa điểm tương ứng.
- **Dashboard đã đếm một bài nộp, vì sao cần pattern 2?** Bản trước vẫn giữ một dòng nhưng thay file/thời gian và xóa điểm; số đếm không phản ánh các tác dụng phụ đó.
- **Có cần áp dụng key cho diễn đàn/email luôn không?** Không trong phần này: đề giới hạn đúng một tính năng, bạn chọn nộp bài.

## 12. Checklist thực hiện trên bản nhóm mới

1. Lưu ZIP c7ae285 làm bản trước; dùng schema demo riêng, không reset project hoặc database đang làm.
2. Tái hiện bằng Console trên bản trước; chấm điểm bài tập trong /study, thu bằng chứng thời gian/file/điểm và audit.
3. Thêm bảng vào _SCHEMA; chèn DELETE key vào delete_course, giữ nguyên phần forum/announcements.
4. Tạo một module idempotency.py; tích hợp key/hash/replay trong transaction của submit_assignment.
5. Sửa api() để nhận headers, giữ nguyên workspace/grades/password trong app.js; thêm thông báo lỗi.
6. Sửa handler nộp bài trong study.js để giữ key khi retry; không áp dụng toàn cục cho mọi request.
7. Cập nhật helper test, kiểm tra key/dữ liệu/quyền/concurrency/rollback và lỗi audit sau commit.
8. Chạy Ruff, mypy và toàn bộ pytest trên PostgreSQL test; thử lại các luồng gọi api() dùng chung.
9. Demo cùng kịch bản trên bản sau, cùng điều kiện nhưng schema riêng; chụp cùng loại bằng chứng.
10. Báo cáo phạm vi, kết quả và giới hạn; trao đổi với bạn làm pattern 3 về hai API điểm, không gộp hai bài thành một.

Cuối cùng lưu ZIP/source của cả hai bản, ảnh/video cùng kịch bản, kết quả test FAIL có chủ đích của bản trước và PASS của bản sau. Không push bản cố tình FAIL vào main. Chỉ commit thay đổi sau khi chạy các kiểm tra và đọc lại diff; không đưa .env hoặc dữ liệu demo vào Git.
