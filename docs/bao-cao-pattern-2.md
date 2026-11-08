# Báo cáo Pattern 2 — Idempotency key cho chức năng nộp bài

## 1. Phạm vi và hai bản source

- Bản trước: commit `c7ae285`, đã có các chức năng mới của nhóm nhưng chưa áp dụng Idempotency key.
- Bản sau: code hiện tại bổ sung pattern 2 cho đúng API POST nộp bài tập.
- Thêm một module nghiệp vụ `app/api/idempotency.py` và một bảng `submission_idempotency`. Không sử dụng thư viện thực hiện sẵn toàn bộ pattern; UUID, SHA-256 và JSONB chỉ hỗ trợ các thao tác cơ bản.
- Source ZIP và kết quả kiểm chứng được lưu tại `instance/pattern2-delivery/`. Đây là thư mục giao bài local, được Git bỏ qua theo cấu hình instance hiện có. Các ZIP source không chứa `.env`, `.venv`, database hay file bài nộp.

## 2. Tình huống lỗi nhân tạo

Sinh viên gửi bài; server lưu thành công nhưng phản hồi bị mất ở phía trình duyệt. Sinh viên chưa biết kết quả nên gửi lại cùng yêu cầu. Demo Console bỏ phản hồi HTTP 201 để tái hiện trường hợp này mà không làm hỏng database.

Để thể hiện hậu quả rõ hơn: sau lần nộp đầu, giảng viên chấm 8.5 và thêm nhận xét; sinh viên sau đó gửi lại yêu cầu cũ.

Code cũ chỉ giữ một dòng submissions cho mỗi bài tập/sinh viên, nhưng vẫn ghi file mới, xóa file cũ, thay thời gian nộp và đặt điểm về null, nhận xét rỗng. Vì vậy không mô tả lỗi là tạo hai dòng bài nộp. Lỗi là thực hiện lại tác dụng phụ của một thao tác đã thành công.

## 3. Thiết kế và cách xử lý

1. Trình duyệt tạo UUID cho mỗi thao tác nộp mới và gửi bằng header Idempotency-Key.
2. Nếu mất mạng hoặc nhận lỗi 5xx, trình duyệt giữ key cùng file để gửi lại. Khi thành công thì kết thúc thao tác; file khác hoặc thao tác mới dùng key mới.
3. Server xác thực và kiểm tra quyền trước, sau đó kiểm tra key và file.
4. SHA-256 của metadata (khóa học, bài tập, tên file) và nội dung xác định dữ liệu của yêu cầu. Không hash multipart boundary hoặc token đăng nhập.
5. Trong transaction đã khóa dòng khóa học, server tìm key theo scope sinh viên/khóa học/bài tập/key.
6. Key cũ và hash trùng: trả status/body đã lưu, header Idempotency-Replayed: true; không sửa file, bài, thời gian hoặc điểm.
7. Key cũ và hash khác: trả HTTP 409 IDEMPOTENCY_KEY_REUSED.
8. Key mới: kiểm tra hạn, lưu file, lưu bài và bản ghi key bằng cùng connection/transaction PostgreSQL. Sau commit mới dọn file cũ và ghi audit như luồng hiện có.

Khóa dòng courses đã có trong assessment_store ngăn hai request đồng thời cùng khóa học cùng vượt bước tìm key. Request sau chờ commit rồi đọc được kết quả. Khóa chính bảng key là bảo vệ bổ sung. Đây là khóa transaction hiện có, không phải Optimistic locking cho điểm.

## 4. File đã thay đổi và mục đích

| File | Thay đổi |
|---|---|
| app/database/db.py | Tạo bảng key; xóa key liên quan trong transaction xóa khóa học |
| app/api/idempotency.py | Kiểm tra UUID; tính hash; đọc/ghi kết quả idempotency |
| app/api/assessments.py | Kiểm tra replay trước ghi file, lưu bài và key trong cùng transaction |
| app/static/js/app.js | Hỗ trợ header bổ sung và thông báo lỗi tiếng Việt |
| app/static/js/study.js | Tạo key, giữ key qua lỗi mạng/5xx, kết thúc thao tác khi thành công |
| tests/test_assessments.py | Gửi key trong test cũ; bổ sung test cho dữ liệu, quyền, concurrency, rollback và audit |
| tests/test_dashboard.py | Bổ sung key cho request nộp bài trong test thống kê; giữ nguyên kỳ vọng nghiệp vụ |

## 5. Kết quả trước và sau

| Tiêu chí | Bản trước | Bản sau |
|---|---|---|
| Gửi lại cùng thao tác sau khi đã chấm | Điểm trở về null | Giữ điểm 8.5 |
| Nhận xét | Bị xóa | Giữ nguyên |
| File lưu và submittedAt | Bị thay | Giữ nguyên |
| Số dòng bài nộp cho SV/bài tập | Một | Một |
| Audit SUBMIT_ASSIGNMENT khi retry thành công | Ghi thêm event | Không ghi thêm event |
| Dashboard GV sau retry bài đã chấm | Bài quay về chờ chấm | Số chờ chấm giữ nguyên |
| Cùng key nhưng dữ liệu khác | Xử lý như nộp lại | HTTP 409 |
| Chủ động nộp bản khác với key mới, còn hạn | Thay bài | Vẫn thay bài hợp lệ |

Đã chạy tự động test `test_idempotency_replay_preserves_graded_submission` trên source cũ trong bản sao tạm; thất bại đúng tại `assert rows[0]["score"] == 8.5` với giá trị thực tế None. Cùng test nằm trong bộ test bản sau đã đạt. Log bản trước là lỗi dự kiến để chứng minh bài tập, không phải một test lỗi để đưa vào main CI.

Các kiểm tra bổ sung của bản sau:

- Thiếu/sai key bị từ chối, không có bài/file/key mới.
- Cùng key nhưng đổi tên hoặc nội dung file bị từ chối.
- Hai request cùng key chạy đồng thời chỉ lưu một kết quả.
- Retry sau hạn hoặc qua app instance mới vẫn nhận xác nhận cũ; key mới sau hạn bị từ chối.
- Cùng chuỗi key ở sinh viên hoặc bài tập khác không làm lộ kết quả người trước.
- Hủy ghi danh hoặc khóa tài khoản vẫn thu hồi quyền replay.
- Lỗi lưu key rollback thay đổi bài và dọn file mới; có thể retry lại.
- Lỗi audit sau commit trả 500 lần đầu, nhưng retry nhận kết quả cũ và không thay bài.
- Xóa khóa học xóa các key liên quan.

Kết quả cuối cùng: **181 test đạt**, coverage toàn ứng dụng **91%**, riêng module idempotency **100% coverage dòng**. Bộ bài tập/trắc nghiệm có **21 test đạt**. Ruff check, Ruff format, mypy (app và tests), git diff --check đều đạt. pip-audit không phát hiện lỗ hổng đã biết trong các dependency được kiểm tra; package local my-project không có trên PyPI nên bị bỏ qua theo thông báo công cụ. Coverage dòng không có nghĩa đã chứng minh mọi tình huống có thể xảy ra.

Log đầy đủ được đặt trong thư mục giao bài local; xem file `KET-QUA.md` ở đó để biết hash source và tên từng file bằng chứng.

## 6. Cách trình bày demo

1. Cho xem source ZIP trước/sau và giới thiệu tình huống mất phản hồi.
2. Cho xem ảnh/video bản trước: đã chấm 8.5, gửi lại rồi mất điểm.
3. Mở code và chỉ ba điểm: tạo/giữ key ở study.js; tìm kết quả cũ trước ghi file; lưu bài và key cùng transaction.
4. Demo bản sau cùng tình huống: lần đầu mất phản hồi, giảng viên chấm, sinh viên gửi lại cùng file/key; điểm, nhận xét, thời gian giữ nguyên.
5. Tab Network cho thấy hai request cùng key và response lần hai có Idempotency-Replayed: true.
6. Nếu cần, dùng ADMIN xem log SUBMIT_ASSIGNMENT và dashboard GV làm bằng chứng bổ sung. Điểm demo phải chấm trong /study; /grades là điểm tổng kết môn, lưu ở enrollments.

Ảnh/video demo thủ công do thành viên tự lưu, không được tạo hoặc giả mạo bởi test tự động. Người dùng đã xác nhận demo trước/sau đạt theo kịch bản.

## 7. Giới hạn cần nói rõ

- Key đang chờ chỉ được giữ trong bộ nhớ của trang. Tải lại/đóng trang sẽ mất key pending; phiên bản này chưa hỗ trợ phục hồi thao tác qua reload.
- Bản ghi key giữ đến khi xóa khóa học; chưa có TTL/cleanup theo thời gian.
- Phản hồi replay là ảnh chụp lúc nộp, có thể có score null dù hiện tại đã chấm. Dùng API tra cứu hiện tại để xem điểm, không dùng response lịch sử để kết luận mất điểm.
- Khóa cả dòng khóa học khá rộng; thao tác khác cùng khóa học có thể phải chờ. Không tuyên bố đây là tối ưu cho hệ thống tải cao.
- Database và filesystem không có transaction chung. Ngoại lệ thông thường được dọn file; tiến trình tắt đột ngột có thể để lại file không được tham chiếu.
- Audit vẫn thực hiện sau commit bằng connection khác. Idempotency ngăn ghi lại bài khi retry sau lỗi audit, nhưng không phục hồi sự kiện audit đã thiếu. Không tuyên bố đảm bảo exactly-once cho mọi tác dụng phụ.
- JWT và quyền vẫn phải hợp lệ. Idempotency không thay thế xác thực, kiểm tra ghi danh hoặc thời hạn cho thao tác mới.

## 8. Nội dung giải thích ngắn

“Em áp dụng Idempotency key cho nộp bài. Khi server đã lưu nhưng phản hồi bị mất, client gửi lại cùng key. Server so hash và trả kết quả đã lưu, không thay file, thời gian và điểm. Cùng key nhưng khác dữ liệu trả 409. Bài và key nằm trong cùng transaction PostgreSQL. Sinh viên chủ động nộp bản mới thì dùng key mới và vẫn phải còn hạn.”

“Pattern 2 nhận diện một thao tác bị gửi lặp. Pattern 3 của bạn cùng nhóm xử lý hai thao tác sửa điểm độc lập cùng dựa trên dữ liệu cũ. token_version trong đăng nhập không phải phiên bản điểm.”
