# miniLMS

Mini Learning Management System (LMS) viết bằng **Flask**, tập trung vào xác thực, phân quyền và quản lý điểm.

## Tính năng

- Đăng nhập / đăng ký / quên & đặt lại mật khẩu.
- Phân quyền 3 vai trò: `ADMIN`, `INSTRUCTOR`, `STUDENT`.
- Xem điểm (`GET /courses/<id>/grades`) và cập nhật điểm (`PUT /courses/<id>/grades/<student_id>`).
- Quản lý khóa học (CRUD) cho ADMIN và quản lý ghi danh (thêm/xóa sinh viên).
- Giao diện sửa điểm cho giảng viên.
- Hai backend lưu trữ: `memory` (mặc định) và `sqlite`.

## Bảo mật

- Mật khẩu băm bằng **bcrypt** (cost mặc định 12).
- JWT ký **HS256** với `jti` và **token versioning** (JWT cũ bị vô hiệu khi đổi mật khẩu).
- Đăng xuất phía server (revoke JWT).
- **Rate limiting** dùng chung (SQLite) chống brute-force.
- **Soft account lockout**: khóa tạm thời sau nhiều lần sai mật khẩu, tự mở khóa sau thời gian quy định (kèm header `Retry-After`).
- Chống liệt kê tài khoản (phản hồi forgot-password giống nhau cho mọi email).
- Reset token lưu dạng **SHA-256**, dùng một lần, có thời hạn.
- HTTP security headers (CSP, X-Frame-Options, X-Content-Type-Options, ...).

## Yêu cầu

- Python >= 3.12
- `uv` (khuyến nghị) hoặc `pip`

## Cài đặt & chạy

### 1. Cài dependencies

```bash
uv sync --dev
# hoặc
python -m venv .venv && .venv/Scripts/activate && pip install -r requirements.txt
```

### 2. Thiết lập biến môi trường

Ứng dụng **bắt buộc** có `JWT_SECRET` (tối thiểu 32 ký tự):

```powershell
# Windows (PowerShell)
$env:JWT_SECRET = "dev-only-secret-at-least-32-characters-long!!"
$env:LMS_STORE  = "memory"   # "memory" hoặc "sqlite"
```

Các biến cấu hình khác (đều có giá trị mặc định):

| Biến | Mặc định | Mô tả |
|---|---|---|
| `JWT_SECRET` | *(bắt buộc)* | Khóa ký JWT, tối thiểu 32 ký tự |
| `TOKEN_TTL_SECONDS` | `900` | Thời gian sống JWT (giây) |
| `LMS_STORE` | `memory` | `memory` hoặc `sqlite` |
| `SQLITE_PATH` | `instance/mini_lms.sqlite3` | Đường dẫn DB khi dùng `sqlite` |
| `BCRYPT_ROUNDS` | `12` | Cost factor bcrypt |
| `RATE_LIMIT_DB_PATH` | `instance/rate_limits.sqlite3` | DB rate-limit |
| `LOGIN_MAX_FAILED_ATTEMPTS` | `5` | Số lần sai tối đa trước khi khóa tài khoản |
| `LOGIN_LOCK_DURATION_SECONDS` | `900` | Thời gian khóa tài khoản (giây) |
| `AUDIT_LOG_PATH` | `audit.log` | File audit log |
| `RESET_TOKEN_TTL_SECONDS` | `900` | TTL reset token |
| `RESET_TOKEN_ECHO` | `0` | Echo reset token (chỉ test) |
| `LOCAL_EMAIL_ENABLED` | `0` | Bật mô phỏng email (chỉ dev) |
| `ENABLE_EXTENSIONS` | `0` | Điểm mở rộng |

### 3. Chạy ứng dụng

```bash
flask --app app run
# hoặc
uv run flask --app app run
```

## Chạy test

```bash
uv run python -m pytest --cov=app
```

## Tài khoản seed (mật khẩu chung `Lms@2026`)

| Email | Vai trò |
|---|---|
| `admin@lms.test` | ADMIN |
| `an.gv@lms.test` | INSTRUCTOR |
| `binh.gv@lms.test` | INSTRUCTOR |
| `chi.sv@lms.test` | STUDENT |
| `dung.sv@lms.test` | STUDENT |
| `em.sv@lms.test` | STUDENT |

## API chính

| Method | Endpoint | Mô tả | Quyền |
|---|---|---|---|
| POST | `/auth/login` | Đăng nhập | public |
| POST | `/auth/register` | Đăng ký (STUDENT) | public |
| POST | `/auth/forgot-password` | Yêu cầu reset | public |
| POST | `/auth/reset-password` | Đặt lại mật khẩu | public |
| POST | `/auth/logout` | Đăng xuất | auth |
| GET | `/me` | Thông tin tài khoản | auth |
| GET | `/courses` | Danh sách khóa học | auth |
| POST | `/courses` | Tạo khóa học | ADMIN |
| PUT | `/courses/<id>` | Sửa khóa học | ADMIN |
| DELETE | `/courses/<id>` | Xóa khóa học | ADMIN |
| GET | `/courses/<id>/grades` | Xem điểm | auth |
| PUT | `/courses/<id>/grades/<sid>` | Sửa điểm | INSTRUCTOR (đúng môn) |
| GET | `/courses/<id>/enrollments` | Danh sách ghi danh | ADMIN / giảng viên môn |
| POST | `/courses/<id>/enrollments` | Ghi danh sinh viên | ADMIN / giảng viên môn |
| DELETE | `/courses/<id>/enrollments/<sid>` | Hủy ghi danh | ADMIN / giảng viên môn |

## Cấu trúc dự án

```
app/
  api/          # auth, guards, services, store, reset, rate_limit, ...
  database/     # SQLite backend
  templates/    # Jinja2
  static/       # CSS/JS
tests/          # pytest
seed.json       # Dữ liệu mẫu
```

## CI/CD

GitHub Actions chạy ruff, mypy (app + tests), pytest (coverage `app`), pip-audit và Semgrep.
