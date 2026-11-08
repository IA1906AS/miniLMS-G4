# miniLMS — Flask và PostgreSQL

## Pattern 03: Optimistic locking khi sửa điểm

Điểm có `version`; yêu cầu lưu từ dữ liệu cũ nhận `409 GRADE_CONFLICT`.

Hệ thống quản lý học tập với ba vai trò `ADMIN`, `INSTRUCTOR`, `STUDENT`.
PostgreSQL lưu toàn bộ dữ liệu nghiệp vụ, reset token, JWT đã thu hồi,
khóa tạm tài khoản và rate limiting dùng chung giữa các tiến trình.

## Yêu cầu

- Python >= 3.12 và `uv` (khuyến nghị) hoặc `pip`.
- PostgreSQL 17, hoặc Docker Desktop để chạy `compose.yaml` có sẵn.

## Cài đặt và chạy trên Windows

Trong thư mục gốc project:

```powershell
uv sync --dev
Copy-Item .env.example .env
docker compose up -d --wait postgres
```

Docker Desktop phải đang chạy. Không ghi đè `.env` nếu đã có cấu hình riêng.
File này được gitignore và được ứng dụng đọc tự động. Các giá trị mẫu chỉ
dành cho phát triển local. Khi đổi mật khẩu, sửa cả `POSTGRES_PASSWORD`
và mật khẩu trong `DATABASE_URL`; ký tự đặc biệt trong URL phải được URL-encode.

**Nếu cần giữ dữ liệu SQLite cũ, thực hiện phần chuyển dữ liệu bên dưới trước
khi chạy Flask lần đầu.** Khi database chưa có người dùng, ứng dụng sẽ tự tạo
tài khoản và khóa học mẫu từ `seed.json`.

```powershell
.\.venv\Scripts\python.exe -m flask --app app run --debug
```

Mở **http://127.0.0.1:5000**. Các lần sau có thể dùng `.\scripts\run.ps1`
để khởi động PostgreSQL rồi chạy web. Nhấn Ctrl+C để dừng web;
`docker compose stop postgres` dừng database và giữ dữ liệu trong volume.

Nếu đã có PostgreSQL riêng, không cần Docker: tạo database, cấu hình
`DATABASE_URL` trong `.env` và chạy Flask. Tài khoản kết nối cần quyền tạo
bảng/schema trong database đó. Ví dụ kết nối:

```dotenv
DATABASE_URL=postgresql://minilms:minilms_local_dev_password@127.0.0.1:5432/mini_lms
DATABASE_SCHEMA=public
JWT_SECRET=dev-only-secret-at-least-32-characters-long!!
```

Thay khóa JWT và thông tin đăng nhập trước khi triển khai thực tế.

## Đổi mật khẩu và email khôi phục

Chế độ thử cục bộ: đặt `SMTP_ENABLED=0`, `LOCAL_EMAIL_ENABLED=1` trong `.env`
và chạy `uv run flask --app app run --debug`. Thư reset nằm trong
`instance/mailbox/reset-*.txt`: mở file và dùng liên kết để đặt mật khẩu mới.
Thư thông báo lớp học được lưu riêng cho từng người nhận tại
`instance/mailbox/announcement-*.txt`. Không cần Gmail hoặc email thật ở chế độ này.

Trang tài khoản có liên kết tới `/changepassword`. Người dùng xác nhận mật khẩu
hiện tại trước khi đặt mật khẩu mới. Đổi thành công sẽ vô hiệu hóa mọi JWT và
token khôi phục cũ của tài khoản, yêu cầu đăng nhập lại.

### Link khôi phục lưu trong instance/mailbox

Cấu hình local mặc định đã bật `LOCAL_EMAIL_ENABLED=1` và tắt SMTP
(`SMTP_ENABLED=0`). Không cần nhập tài khoản hay mật khẩu gửi mail.

Chạy ứng dụng bằng `.\scripts\run.ps1` hoặc:

```powershell
.\.venv\Scripts\python.exe -m flask --app app run --debug
```

Mở `/resetpassword`, nhập email của tài khoản đã tồn tại rồi gửi yêu cầu.
Mở file `reset-*.txt` mới nhất trong `instance/mailbox/`, sao chép liên kết
vào trình duyệt và đặt mật khẩu mới. Thư được lưu thành file trên máy.

Liên kết mặc định hết hạn sau 15 phút và chỉ dùng được một lần. Chức năng
lưu thư local chỉ hoạt động khi chạy debug. Nếu chưa thấy file, kiểm tra email
đã đăng ký và cấu hình `LOCAL_EMAIL_ENABLED=1`, `SMTP_ENABLED=0`.

## Chuyển dữ liệu SQLite hiện có

Ứng dụng không còn backend SQLite hoặc memory. `sqlite3` chỉ được dùng bởi
công cụ nhập dữ liệu một lần và kiểm thử công cụ đó. File nguồn không bị sửa/xóa.

1. Dừng web cũ để dữ liệu không thay đổi trong lúc chuyển.
2. Khởi động PostgreSQL và chuẩn bị `.env` như trên.
3. Nhập vào database/schema đích đang trống, trước khi khởi động Flask:

```powershell
.\.venv\Scripts\python.exe -m app.database.migrate_sqlite --source instance/mini_lms.sqlite3 --rate-source instance/rate_limits.sqlite3
```

Bỏ `--rate-source` nếu không có file rate-limit hoặc không cần chuyển bộ đếm cũ.
Công cụ giữ nguyên password hash, tài khoản/hồ sơ, khóa học, ghi danh/điểm,
metadata tài liệu/bài nộp, bài tập, trắc nghiệm/lượt làm, reset token và JWT đã thu hồi.
Bảng chưa tồn tại trong database cũ được bỏ qua. Toàn bộ dữ liệu nhập được commit
trong một giao dịch; lỗi sẽ rollback. Đích có dữ liệu sẽ bị từ chối để tránh ghi đè.

Nếu đã chạy Flask và có seed, hãy đặt `DATABASE_SCHEMA=lms_import` trong `.env`
để chọn schema mới, nhập dữ liệu rồi chạy lại web; không cần xóa dữ liệu cũ.
Giữ nguyên `JWT_SECRET` cũ nếu cần tiếp tục xác thực token đã phát hành.

Tệp ảnh, tài liệu và bài nộp vẫn nằm ở thư mục `instance/` của project. Khi chuyển
máy, phải sao lưu PostgreSQL **và** các thư mục tệp này. Công cụ chỉ chuyển metadata,
không di chuyển hoặc xóa tệp tải lên.

## Tài khoản mẫu

Chỉ được tạo khi database chưa có người dùng. Mật khẩu chung: `Lms@2026`.

| Email | Vai trò |
|---|---|
| `admin@lms.test` | ADMIN |
| `an.gv@lms.test`, `binh.gv@lms.test` | INSTRUCTOR |
| `chi.sv@lms.test`, `dung.sv@lms.test`, `em.sv@lms.test` | STUDENT |

## Các chức năng và giao diện

- **Sáng/tối:** nút chuyển giao diện ở thanh trên, mặc định dùng màu tối navy cũ;
  lựa chọn được lưu trên trình duyệt và áp dụng cho tất cả trang.
- **Điểm số** (`/grades`): trang riêng cho kết quả SV và quản lý điểm GV;
  không có form cập nhật hồ sơ. `/account` chỉ dành cho hồ sơ, ảnh và thông tin tài khoản.

- **Dashboard theo vai trò** (`/dashboard`): sau đăng nhập, ADMIN xem số người dùng,
  tài khoản khóa, khóa học và nhật ký gần đây; GV xem lớp phụ trách, số sinh viên,
  bài cần chấm và hạn nộp; SV xem khóa đã ghi danh, bài chưa nộp còn hạn,
  bài đã nộp và thông báo. Số liệu lấy từ PostgreSQL qua `GET /api/dashboard`,
  có kiểm tra JWT và giới hạn dữ liệu theo vai trò. Sidebar, liên kết nhanh và
  điều hướng trên điện thoại dùng chung cho các trang chức năng.

- **Diễn đàn khóa học** (`/forum?course=<id>`): mở từ chi tiết khóa học.
  SV đã ghi danh và GV phụ trách tạo chủ đề, bình luận, sửa/xóa nội dung của mình.
  GV không được sửa/xóa bài của SV; ADMIN chỉ xem. Xóa chủ đề xóa cả bình luận.
  Mỗi trang 20 mục, nội dung hiển thị dạng văn bản, giới hạn 30 bài mới/giờ/người.
  Hủy ghi danh thu hồi quyền diễn đàn; xóa khóa học xóa thảo luận liên quan.
- **Nhật ký hoạt động** (`/admin/audit`): ADMIN mở từ trang quản lý người dùng,
  lọc theo tên sự kiện và mã người dùng, xem theo trang. Nhật ký ghi vào PostgreSQL
  và tiếp tục ghi file theo `AUDIT_LOG_PATH`. Có đăng nhập thành công/thất bại,
  sửa điểm, thao tác quản trị, thông báo và diễn đàn; không lưu mật khẩu/JWT/token reset.
  Các file log cũ chưa tự nhập vào PostgreSQL.
- **Quản trị khóa học:** trong chi tiết khóa học, ADMIN có thể chuyển GV và xóa khóa.
  Giao diện yêu cầu xác nhận trước thao tác; xóa khóa xóa dữ liệu/tệp liên quan.
- **Trang chủ:** xác thực JWT trước khi hiện lời chào và các liên kết theo vai trò;
  người đã đăng nhập không còn thấy nút đăng nhập/tạo tài khoản ở nội dung chính.

- **Thông báo khóa học:** trong `/catalog`, chọn khóa học để xem thông báo.
  GV phụ trách có thể đăng tiêu đề/nội dung và chọn gửi email; SV chỉ xem được
  khi còn ghi danh. ADMIN được xem, GV khác không được truy cập. Mỗi trang có
  20 thông báo, mới nhất trước. Email gửi riêng tới SV đang hoạt động trong lớp,
  dùng cấu hình SMTP/Gmail hiện có. SMTP tắt hoặc gửi lỗi không làm mất thông báo;
  GV thấy trạng thái và số thư đã gửi/thất bại. Việc gửi diễn ra trong yêu cầu đăng,
  chưa có hàng đợi hoặc tự gửi lại; không đăng lại chỉ để thử gửi vì sẽ tạo thông báo mới.
  Giới hạn 10 thông báo/giờ/GV. API `GET/POST /courses/<id>/announcements`,
  POST nhận `title`, `body`, `sendEmail` (boolean, mặc định true); GET có `page`.

- **Quản trị người dùng** (`/admin/users`): ADMIN mở từ trang tài khoản, tìm theo mã,
  email/họ tên, xem danh sách phân trang, khóa/mở tài khoản và thay đổi vai trò.
  Khóa hoặc đổi vai trò thu hồi JWT và token khôi phục cũ. ADMIN không thể tự khóa
  hoặc hạ quyền mình; giảng viên phải chuyển khóa học trước khi đổi sang vai trò khác.
  Trạng thái khóa được lưu trong PostgreSQL, không bị xóa khi reset mật khẩu.
  API: `GET /admin/api/users?q=...&page=1`, `PUT /admin/api/users/<id>` với
  `role` (`ADMIN`, `INSTRUCTOR`, `STUDENT`) và/hoặc `isLocked` (boolean).

- **Xác thực:** đăng ký sinh viên, đăng nhập, đăng xuất thu hồi JWT, quên/reset mật khẩu.
- **Tài khoản** (`/account`): sửa họ tên, giới thiệu, thông tin liên hệ; tải/thay/xóa
  ảnh PNG/JPEG/WebP tối đa 2 MiB. Ảnh được kiểm tra, loại metadata và thu nhỏ 512 × 512.
  Email/liên hệ là thông tin riêng. Thành viên có chung khóa học xem được tên,
  vai trò, giới thiệu và ảnh; ADMIN có quyền kiểm tra toàn hệ thống.
- **Khóa học** (`/catalog`): tìm tên không phân biệt hoa thường, lọc giảng viên.
  Giảng viên tạo khóa cho mình, sửa khóa phụ trách, thêm/hủy ghi danh theo mã SV.
  Sinh viên tự ghi danh bằng mã khóa học (chính là `id`, ví dụ `c1`, `c2`).
  ADMIN có quyền quản lý toàn hệ thống; chỉ ADMIN xóa khóa/chuyển giảng viên qua API.
- **Tài liệu:** PDF, TXT UTF-8, DOCX, PPTX, XLSX tối đa 10 MiB; không nhận Office có VBA.
  Sinh viên phải còn ghi danh để xem/tải. Tệp được phục vụ dưới dạng đính kèm,
  có JWT và kiểm tra quyền dù người dùng biết URL trực tiếp.
- **Bài tập và trắc nghiệm** (`/study?course=<id>`): mở từ chi tiết khóa học.
  Giảng viên tạo bài tập với yêu cầu/hạn nộp, xem bài nộp của lớp, chấm 0–10 kèm nhận xét.
  SV nộp tệp PDF/TXT/DOCX/PPTX/XLSX/ZIP tối đa 10 MiB; ZIP không được giải nén trên server.
  SV chỉ truy xuất bài của mình. Nộp lại trước hạn thay tệp cũ và xóa điểm/nhận xét cũ
  để được chấm lại. Hạn nộp do server kiểm tra; API nhận ISO 8601 có múi giờ, lưu UTC.
- **Trắc nghiệm:** tối đa 100 câu, 2–6 lựa chọn/câu, một đáp án đúng. Giao diện tạo
  câu có 4 lựa chọn. Thời lượng API 30–10800 giây (UI 1–180 phút), số lượt 1–10.
  Server sinh mã câu hỏi, ấn định hạn, lưu đáp án và tự chấm; không trả đáp án đúng cho SV.
  Bắt đầu lại khi đang làm sẽ tiếp tục lượt cũ; tải lại trang rồi bấm tiếp tục để khôi phục.
  Điểm = `10 × số câu đúng / tổng số câu`, làm tròn 2 chữ số. Câu bỏ trống tính sai.
  Hết giờ, UI tự gửi kết thúc. Nếu đóng trang, server chốt từ đáp án đã lưu khi lượt
  được truy cập tiếp qua lịch sử/kết quả/bắt đầu mới. Đáp án đến sau hạn không được tính;
  nộp lại lượt đã kết thúc không đổi điểm. Khóa dòng PostgreSQL kiểm soát giới hạn lượt
  và việc chấm khi nhiều app/process gửi đồng thời.
- **Kết quả riêng:** điểm/nhận xét bài tập, điểm trắc nghiệm cao nhất và số lượt đã dùng.
  Các điểm này lưu riêng, chưa tự quy đổi vào điểm tổng kết `enrollments` vì chưa có trọng số.
  Xem/sửa điểm môn hiện có vẫn hoạt động; chỉ giảng viên đúng môn được sửa điểm.

Hủy ghi danh thu hồi quyền truy cập của SV. Xóa khóa học xóa dữ liệu liên quan và
tệp tài liệu/bài nộp. Tất cả dữ liệu nghiệp vụ được giữ qua các lần khởi động PostgreSQL.

## Cấu hình

| Biến | Mặc định | Mô tả |
|---|---|---|
| `DATABASE_URL` | bắt buộc | Chuỗi kết nối PostgreSQL |
| `DATABASE_SCHEMA` | `public` | Schema của ứng dụng |
| `JWT_SECRET` | bắt buộc | Khóa JWT tối thiểu 32 ký tự |
| `BCRYPT_ROUNDS` | `12` | Cost factor bcrypt |
| `TOKEN_TTL_SECONDS` | `900` | Thời gian sống JWT |
| `LOGIN_MAX_FAILED_ATTEMPTS` | `5` | Ngưỡng sai trước khi khóa tạm |
| `LOGIN_LOCK_DURATION_SECONDS` | `900` | Thời gian khóa tạm |
| `RESET_TOKEN_TTL_SECONDS` | `900` | Thời gian sống reset token |
| `RESET_TOKEN_ECHO` | `0` | Trả token chỉ trong test |
| `LOCAL_EMAIL_ENABLED` | `0` | Mô phỏng email, chỉ trong debug |
| `AUDIT_LOG_PATH` | `audit.log` | Nhật ký hoạt động |
| `AVATAR_UPLOAD_DIR` | `instance/avatars` | Ảnh đại diện |
| `MATERIAL_UPLOAD_DIR` | `instance/materials` | Tài liệu |
| `SUBMISSION_UPLOAD_DIR` | `instance/submissions` | Bài nộp |

`LMS_STORE`, `SQLITE_PATH`, `RATE_LIMIT_DB_PATH` không còn được dùng.

PostgreSQL tự tạo bảng và bổ sung các cột hồ sơ khi mở schema của ứng dụng.
Các bảng `assignments`, `submissions`, `quizzes`, `quiz_attempts` lưu nội dung
nghiệp vụ trong cột JSONB `data`, kèm mã khóa học, mã bài cha/mã SV và thứ tự `sequence`.

## API chính

Các API nghiệp vụ yêu cầu `Authorization: Bearer <token>`. Các endpoint xác thực
đăng nhập/đăng ký/quên/reset là public. API giữ đường dẫn như phiên bản trước.

| Method | Endpoint | Chức năng |
|---|---|---|
| POST | `/auth/login`, `/auth/register` | Đăng nhập/đăng ký |
| POST | `/auth/forgot-password`, `/auth/reset-password` | Quên/reset mật khẩu |
| POST | `/auth/logout` | Thu hồi JWT hiện tại |
| GET | `/admin/api/audit` | ADMIN tra nhật ký với `action`, `actorId`, `page` |
| GET/POST | `/courses/<cid>/forum/topics` | Xem/tạo chủ đề; tạo với `title`, `body` |
| GET | `/courses/<cid>/forum/topics/<tid>` | Nội dung chủ đề |
| GET/POST | `/courses/<cid>/forum/topics/<tid>/comments` | Xem/bình luận; POST với `body` |
| PUT/DELETE | `/courses/<cid>/forum/posts/<pid>` | Tác giả sửa/xóa bài; chủ đề dùng `title`, `body`, bình luận dùng `body` |
| POST | `/auth/change-password` | Đổi mật khẩu với `currentPassword`, `newPassword`; yêu cầu JWT |
| GET | `/me` | Tài khoản hiện tại |
| GET/PUT | `/me/profile` | Xem/sửa `fullName`, `bio`, `contact` |
| POST/DELETE | `/me/avatar` | Multipart `avatar` / xóa ảnh |
| GET | `/users/<id>/profile`, `/users/<id>/avatar` | Hồ sơ/ảnh theo quyền |
| GET | `/me/courses`, `/courses/<cid>/members` | Khóa của tôi/thành viên |
| GET/POST | `/courses` | Tìm với `q`, `instructorId` / tạo với `title`, `instructorId` |
| GET/PUT/DELETE | `/courses/<cid>` | Chi tiết/cập nhật/xóa khóa |
| GET | `/instructors` | Giảng viên cho bộ lọc |
| POST | `/courses/join` | SV gửi `{"courseCode":"c1"}` |
| GET/POST | `/courses/<cid>/enrollments` | Xem/thêm `studentId` |
| DELETE | `/courses/<cid>/enrollments/<sid>` | Hủy ghi danh |
| GET | `/courses/<cid>/grades` | Điểm môn theo quyền |
| PUT | `/courses/<cid>/grades/<sid>` | GV gửi `{"score":8.5,"version":0}`; phiên bản cũ trả 409 |
| GET/POST | `/courses/<cid>/materials` | Danh sách/tải multipart `file`, `title` tùy chọn |
| GET/DELETE | `/courses/<cid>/materials/<mid>/download`, `/courses/<cid>/materials/<mid>` | Tải/xóa tài liệu |
| GET/POST | `/courses/<cid>/assignments` | Xem/tạo với `title`, `description`, `dueAt` |
| GET/POST | `/courses/<cid>/assignments/<aid>/submissions` | Xem theo quyền/nộp multipart `file` |
| GET | `/courses/<cid>/submissions/<sid>/download` | Tải bài nộp |
| PUT | `/courses/<cid>/submissions/<sid>/grade` | GV gửi `score`, `feedback` |
| GET/POST | `/courses/<cid>/quizzes` | Xem/tạo trắc nghiệm |
| GET | `/courses/<cid>/quizzes/<qid>` | Chi tiết, đáp án chỉ cho người quản lý |
| GET/POST | `/courses/<cid>/quizzes/<qid>/attempts` | Lịch sử/bắt đầu hoặc tiếp tục |
| GET | `/courses/<cid>/quiz-attempts/<tid>` | Xem lượt theo quyền |
| PUT/POST | `/courses/<cid>/quiz-attempts/<tid>/answers`, `/courses/<cid>/quiz-attempts/<tid>/submit` | Lưu đáp án/nộp bài |
| GET | `/courses/<cid>/results` | SV xem riêng kết quả |

Tạo quiz: `title`, `durationSeconds`, `maxAttempts`, `questions`; mỗi câu gồm
`prompt`, `choices`, `correctIndex` đánh số từ 0. Lưu/nộp gửi
`{"answers":{"<questionId>":0}}`; gửi `{"answers":{}}` để giữ các đáp án đã lưu.
Ghi danh trùng: 409 `ALREADY_ENROLLED`; hết hạn bài tập: 409 `ASSIGNMENT_CLOSED`;
hết lượt: 409 `ATTEMPT_LIMIT_REACHED`; lưu vào lượt đã đóng: 409 `ATTEMPT_CLOSED`.

## Kiểm thử và CI

Tạo database thử riêng một lần (sửa user/password/port nếu đã thay cấu hình mẫu):

```powershell
docker compose exec postgres createdb -U minilms mini_lms_test
$env:TEST_DATABASE_URL = "postgresql://minilms:minilms_local_dev_password@127.0.0.1:5432/mini_lms_test"
uv run python -m pytest --cov=app
uv run ruff check .
uv run ruff format --check .
uv run mypy app tests
```

Mỗi test dùng schema ngẫu nhiên riêng, chỉ dọn schema do nó tạo; không dùng bảng
ứng dụng/public. Các bài kiểm tra cũ đã chuyển từ memory/SQLite sang PostgreSQL.
Kiểm thử bao gồm đăng nhập, phân quyền, rollback, reset token một lần, rate limit
chia sẻ, dữ liệu qua khởi động lại, nhập dữ liệu cũ và giới hạn lượt trên nhiều app.
GitHub Actions khởi động PostgreSQL 17 rồi chạy Ruff, mypy, pytest, pip-audit;
workflow riêng chạy Semgrep.

## Bảo mật hiện có

Bcrypt, JWT HS256 có `jti`/token versioning, logout phía server, khóa tạm sau nhiều
lần sai, rate limit PostgreSQL atomic, reset token SHA-256 dùng một lần/hết hạn,
phản hồi quên mật khẩu không tiết lộ tài khoản, CSP và HTTP security headers.
Email khôi phục hỗ trợ SMTP với liên kết có thời hạn, dùng một lần. Có thể mô phỏng
email trong `instance/mailbox` bằng `LOCAL_EMAIL_ENABLED=1` và debug khi tắt SMTP.
