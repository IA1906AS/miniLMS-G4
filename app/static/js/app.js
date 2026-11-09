
'use strict';

// ==========================================
// MINILMS - MAIN JAVASCRIPT (SEC-07)
// ==========================================

const $ = (id) => document.getElementById(id);

const TOKEN_KEY = 'lms_token';

const token = () => sessionStorage.getItem(TOKEN_KEY);


// ==========================================
// HIỂN THỊ THÔNG BÁO AN TOÀN
// ==========================================

function flash(element, message, ok = true) {
    if (!element) return;

    element.textContent = String(message ?? '');
    element.className = 'msg show ' + (ok ? 'ok' : 'err');
}


// ==========================================
// API REQUEST
// ==========================================

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

    const multipart = body instanceof FormData;
    if (body !== undefined && !multipart) {
        headers['Content-Type'] = 'application/json';
    }

    if (auth) {
        const accessToken = token();

        if (!accessToken) {
            throw new Error('UNAUTHENTICATED');
        }

        headers['Authorization'] = 'Bearer ' + accessToken;
    }

    const response = await fetch(path, {
        method,
        headers,
        body: body !== undefined
            ? (multipart ? body : JSON.stringify(body))
            : undefined
    });

    let data = null;

    try {
        data = await response.json();
    } catch (_) {
        data = null;
    }

    if (!response.ok) {
        const errorCode =
            typeof data?.error === 'string'
                ? data.error
                : typeof data?.detail === 'string'
                    ? data.detail
                    : 'HTTP ' + response.status;

        const error = new Error(errorCode);
        error.status = response.status;

        throw error;
    }

    return data;
}


// ==========================================
// CHUYỂN ĐỔI THÔNG BÁO LỖI
// ==========================================

function translate(code) {
    const messages = {
        IDEMPOTENCY_KEY_REQUIRED:
            'Yêu cầu nộp bài thiếu mã thao tác.',
        INVALID_IDEMPOTENCY_KEY:
            'Mã thao tác nộp bài không hợp lệ.',
        IDEMPOTENCY_KEY_REUSED:
            'Mã thao tác đã dùng cho dữ liệu khác. Hãy chọn lại file để nộp bản mới.',
        INVALID_CREDENTIALS:
            'Email hoặc mật khẩu không đúng.',

        UNAUTHENTICATED:
            'Bạn cần đăng nhập trước.',

        ACCOUNT_LOCKED:
            'Tài khoản tạm khóa do sai quá nhiều lần. Vui lòng thử lại sau.',

        VALIDATION_ERROR:
            'Dữ liệu không hợp lệ.',
        FILE_TOO_LARGE:
            'Tệp vượt quá dung lượng cho phép. Vui lòng chọn tệp nhỏ hơn.',
        ALREADY_ENROLLED:
            'Bạn đã ghi danh khóa học này.',
        ASSIGNMENT_CLOSED:
            'Đã hết hạn nộp bài tập.',
        ATTEMPT_LIMIT_REACHED:
            'Bạn đã dùng hết số lượt làm bài.',
        ATTEMPT_CLOSED:
            'Lượt làm bài đã kết thúc. Những đáp án đã lưu được chấm ở máy chủ.',

        NOT_FOUND:
            'Không tìm thấy dữ liệu.',

        FORBIDDEN:
            'Bạn không có quyền thực hiện thao tác này.',

        INVALID_RESPONSE:
            'Phản hồi từ máy chủ không hợp lệ.',

        RATE_LIMITED:
            'Bạn đã gửi quá nhiều yêu cầu. Vui lòng thử lại sau.',

        'HTTP 400':
            'Yêu cầu không hợp lệ.',

        'HTTP 401':
            'Phiên đăng nhập không hợp lệ hoặc đã hết hạn.',

        'HTTP 403':
            'Bạn không có quyền thực hiện thao tác này.',

        'HTTP 404':
            'Không tìm thấy API được yêu cầu.',

        'HTTP 429':
            'Bạn đã gửi quá nhiều yêu cầu.',

        'HTTP 500':
            'Máy chủ đang gặp lỗi.'
    };

    return Object.hasOwn(messages, code)
        ? messages[code]
        : code || 'Đã xảy ra lỗi.';
}


// ==========================================
// CẬP NHẬT HEADER
// ==========================================

function updateNavigation() {
    const isLoggedIn = Boolean(token());

    document.querySelectorAll('.guest-only').forEach((element) => {
        element.hidden = isLoggedIn;
    });

    document.querySelectorAll('.auth-only').forEach((element) => {
        element.hidden = !isLoggedIn;
    });

    const logoutLink = $('logout-link');

    if (
        logoutLink &&
        logoutLink.dataset.initialized !== 'true'
    ) {
        logoutLink.dataset.initialized = 'true';

        logoutLink.addEventListener('click', function (event) {
            event.preventDefault();
            logout();
        });
    }
}


// ==========================================
// ĐĂNG XUẤT
// ==========================================

let logoutInProgress = false;

async function logout() {
    if (logoutInProgress) return;

    logoutInProgress = true;
    const accessToken = token();

    try {
        if (accessToken) {
            await api('/auth/logout', {
                method: 'POST',
                auth: true
            });
        }
    } catch (error) {
        // Không ghi JWT vào console.
        console.warn(
            'Server-side logout could not be confirmed:',
            error.message
        );
    } finally {
        if (token() === accessToken) {
            sessionStorage.removeItem(TOKEN_KEY);
        }

        updateNavigation();
        window.location.assign('/');
    }
}


// ==========================================
// ĐĂNG NHẬP
// ==========================================

async function loginForm(event) {
    if (event) {
        event.preventDefault();
    }

    const emailInput = $('email');
    const passwordInput = $('password');
    const loginButton = $('login-button');
    const messageBox = $('login-msg');

    if (!emailInput || !passwordInput) {
        flash(
            messageBox,
            'Không tìm thấy biểu mẫu đăng nhập.',
            false
        );
        return;
    }

    if (loginButton) {
        loginButton.disabled = true;
    }

    try {
        const data = await api('/auth/login', {
            method: 'POST',
            body: {
                email: emailInput.value.trim(),
                password: passwordInput.value
            }
        });

        const accessToken =
            data?.accessToken ??
            data?.access_token;

        if (
            typeof accessToken !== 'string' ||
            !accessToken
        ) {
            throw new Error('INVALID_RESPONSE');
        }

        sessionStorage.setItem(TOKEN_KEY, accessToken);

        // Không giữ mật khẩu trong input sau khi đăng nhập.
        passwordInput.value = '';

        updateNavigation();

        flash(
            messageBox,
            'Đăng nhập thành công, đang chuyển trang.'
        );

        window.location.assign('/dashboard');

    } catch (error) {
        console.error('Login failed:', error.message);

        flash(
            messageBox,
            translate(error.message),
            false
        );

        if (loginButton) {
            loginButton.disabled = false;
        }
    }
}


// ==========================================
// ĐĂNG KÝ
// ==========================================

async function registerForm(event) {
    if (event) {
        event.preventDefault();
    }

    const messageBox = $('register-msg');

    try {
        await api('/auth/register', {
            method: 'POST',
            body: {
                email: $('reg-email')?.value.trim(),
                password: $('reg-password')?.value
            }
        });

        const passwordInput = $('reg-password');

        if (passwordInput) {
            passwordInput.value = '';
        }

        flash(
            messageBox,
            'Đã tạo tài khoản thành công. Mời đăng nhập.'
        );

    } catch (error) {
        flash(
            messageBox,
            translate(error.message),
            false
        );
    }
}


// ==========================================
// QUÊN MẬT KHẨU
// ==========================================

async function forgotForm(event) {
    if (event) {
        event.preventDefault();
    }

    const messageBox = $('forgot-msg');
    const button = $('forgot-form').querySelector('button[type="submit"]');
    if (button.disabled) return;
    button.disabled = true;

    try {
        const data = await api('/auth/forgot-password', {
            method: 'POST',
            body: {
                email: $('reset-email')?.value.trim()
            }
        });

        // Chỉ hỗ trợ token demo khi backend test trả về.
        if (
            typeof data?.resetToken === 'string' &&
            $('reset-token')
        ) {
            $('reset-token').value = data.resetToken;
        }

        // Không hiển thị token reset trong thông báo.
        flash(
            messageBox,
            $('forgot-form').dataset.successMessage ||
                'Đã tiếp nhận yêu cầu. Nếu email đã đăng ký, vui lòng kiểm tra thư hướng dẫn đặt lại mật khẩu.'
        );

    } catch (error) {
        flash(
            messageBox,
            translate(error.message),
            false
        );
    } finally {
        button.disabled = false;
    }
}


// ==========================================
// ĐẶT LẠI MẬT KHẨU
// ==========================================

async function resetForm(event) {
    if (event) {
        event.preventDefault();
    }

    const messageBox = $('confirm-msg');
    const password = $('reset-new').value;
    if (password !== $('reset-confirm').value) {
        flash(messageBox, 'Mật khẩu xác nhận không khớp.', false);
        return;
    }
    const passwordLength = new TextEncoder().encode(password).length;
    if (passwordLength < 8 || passwordLength > 72) {
        flash(messageBox, 'Mật khẩu mới phải dài từ 8 đến 72 byte.', false);
        return;
    }
    const button = $('reset-form').querySelector('button[type="submit"]');
    if (button.disabled) return;
    button.disabled = true;

    try {
        await api('/auth/reset-password', {
            method: 'POST',
            body: {
                token: $('reset-token')?.value.trim(),
                password: $('reset-new')?.value
            }
        });

        const passwordInput = $('reset-new');
        const tokenInput = $('reset-token');

        if (passwordInput) {
            passwordInput.value = '';
        }

        if (tokenInput) {
            tokenInput.value = '';
        }
        $('reset-confirm').value = '';
        $('reset-form').hidden = true;

        sessionStorage.removeItem(TOKEN_KEY);
        updateNavigation();
        $('reset-login').hidden = false;

        flash(
            messageBox,
            'Đổi mật khẩu thành công. Mời đăng nhập lại.'
        );

    } catch (error) {
        flash(
            messageBox,
            error.message === 'VALIDATION_ERROR'
                ? 'Liên kết không hợp lệ, đã hết hạn hoặc đã sử dụng; hoặc mật khẩu chưa hợp lệ. Vui lòng kiểm tra mật khẩu hoặc yêu cầu liên kết mới.'
                : translate(error.message),
            false
        );
    } finally {
        button.disabled = false;
    }
}


// ==========================================
// THÔNG TIN TÀI KHOẢN
// ==========================================

async function loadAccount() {
    if (!token()) {
        window.location.replace('/login');
        return;
    }

    try {
        const me = await api('/me', {
            auth: true
        });

        if ($('me-id')) {
            $('me-id').textContent = me.id ?? '–';
        }

        if ($('me-email')) {
            $('me-email').textContent = me.email ?? '–';
        }

        if ($('me-role')) {
            $('me-role').textContent = ({ADMIN:'Quản trị viên',INSTRUCTOR:'Giảng viên',STUDENT:'Sinh viên'})[me.role] ?? '–';
        }
        if ($('members-section')) $('members-section').hidden = me.role === 'ADMIN';

        if ($('who')) {
            $('who').textContent = me.email ?? 'Người dùng';
        }

        if ($('admin-users-link')) $('admin-users-link').hidden = me.role !== 'ADMIN';
        initProfileFeatures();

    } catch (error) {
        console.error('Load account failed:', error.message);

        if (
            error.message === 'UNAUTHENTICATED' ||
            error.status === 401
        ) {
            sessionStorage.removeItem(TOKEN_KEY);
            updateNavigation();

            window.location.replace('/login');
            return;
        }

        flash(
            $('account-msg'),
            translate(error.message),
            false
        );

        return;
    }

}

async function loadGradesPage() {
    if (!token()) { window.location.replace('/login'); return; }
    try {
        const me = await api('/me', {auth:true});
        const teacher = me.role === 'INSTRUCTOR';
        $('grades-page-title').textContent = teacher ? 'Quản lý điểm' : 'Kết quả học tập';
        $('grades-page-description').textContent = teacher
            ? 'Xem và cập nhật điểm tổng kết cho sinh viên trong các lớp bạn phụ trách.'
            : 'Theo dõi điểm tổng kết các môn. Điểm bài tập và trắc nghiệm nằm trong từng khóa học.';
        $('grades-heading').textContent = teacher ? 'Điểm các lớp phụ trách' : 'Điểm các môn';
        $('workspace-page-title').textContent = teacher ? 'Quản lý điểm' : 'Kết quả học tập';
        await Promise.all([loadGrades(), initGradeEditor(me.role, me.id)]);
        $('grades-content').hidden = false;
    } catch (error) {
        if (error.status === 401) { sessionStorage.removeItem(TOKEN_KEY); window.location.replace('/login'); return; }
        flash($('grades-page-msg'), translate(error.message), false);
    }
}


// ==========================================
// DANH SÁCH ĐIỂM
// ==========================================

async function loadGrades() {
    const table = $('grades');

    if (!table) return;

    table.replaceChildren();

    let courses;

    try {
        courses = await api('/me/courses', { auth: true });
    } catch (error) {
        if (error.status === 403 || error.status === 404) {
            courses = [];
        } else {
            throw error;
        }
    }

    if (!Array.isArray(courses)) {
        courses = [];
    }

    for (const course of courses) {
        try {
            const rows = await api(
                '/courses/' +
                encodeURIComponent(course.id) +
                '/grades',
                { auth: true }
            );

            if (!Array.isArray(rows)) {
                continue;
            }

            for (const row of rows) {
                const tr = document.createElement('tr');

                for (const value of [
                    course.title || course.id,
                    row.studentId,
                    row.score
                ]) {
                    const td = document.createElement('td');

                    // Không diễn giải dữ liệu API thành HTML.
                    td.textContent = value ?? '';
                    tr.appendChild(td);
                }

                table.appendChild(tr);
            }

        } catch (error) {
            if (
                error.status === 403 ||
                error.status === 404
            ) {
                continue;
            }

            throw error;
        }
    }

    if (!table.children.length) {
        const tr = document.createElement('tr');
        const td = document.createElement('td');

        td.colSpan = 3;
        td.textContent = 'Không có dữ liệu điểm.';

        tr.appendChild(td);
        table.appendChild(tr);
    }
}


// ==========================================
// QUẢN LÝ ĐIỂM (GIẢNG VIÊN)
// ==========================================

let gradeEditorRequest = 0;

async function loadEnrollmentsIntoEditor(courseId) {
    const requestId = ++gradeEditorRequest;
    const studentSelect = $('edit-student');

    if (!studentSelect) return;

    studentSelect.replaceChildren();

    if (!courseId) return;

    try {
        const enrollments = await api(
            '/courses/' +
            encodeURIComponent(courseId) +
            '/enrollments',
            { auth: true }
        );

        if (requestId !== gradeEditorRequest || $('edit-course').value !== courseId) return;

        if (!Array.isArray(enrollments)) {
            return;
        }

        const placeholder = document.createElement('option');
        placeholder.value = '';
        placeholder.textContent = 'Chọn sinh viên';
        studentSelect.appendChild(placeholder);

        for (const item of enrollments) {
            const option = document.createElement('option');
            option.value = item.studentId;
            option.dataset.version = String(item.version);
            option.textContent = item.studentId + ' — điểm ' + item.score;
            studentSelect.appendChild(option);
        }

    } catch (error) {
        flash(
            $('edit-grade-msg'),
            translate(error.message),
            false
        );
    }
}


async function initGradeEditor(role, userId) {
    const editor = $('grade-editor');

    if (!editor) return;

    if (role !== 'INSTRUCTOR') {
        editor.hidden = true;
        return;
    }

    editor.hidden = false;

    const courseSelect = $('edit-course');
    const studentSelect = $('edit-student');
    const scoreInput = $('edit-score');
    const button = $('edit-grade-button');

    try {
        const courses = await api('/me/courses', { auth: true });

        courseSelect.replaceChildren();

        const placeholder = document.createElement('option');
        placeholder.value = '';
        placeholder.textContent = 'Chọn môn học';
        courseSelect.appendChild(placeholder);

        for (const course of courses) {
            if (course.instructorId !== userId) continue;
            const option = document.createElement('option');
            option.value = course.id;
            option.textContent = course.title + ' (' + course.id + ')';
            courseSelect.appendChild(option);
        }
    } catch (error) {
        flash(
            $('edit-grade-msg'),
            translate(error.message),
            false
        );
        return;
    }

    if (courseSelect.dataset.initialized === 'true') {
        return;
    }

    courseSelect.dataset.initialized = 'true';

    courseSelect.addEventListener('change', function () {
        scoreInput.value = '';
        flash($('edit-grade-msg'), '');
        loadEnrollmentsIntoEditor(courseSelect.value);
    });

    button.addEventListener('click', async function () {
        const courseId = courseSelect.value;
        const studentId = studentSelect.value;
        const raw = scoreInput.value;
        const version = Number(studentSelect.selectedOptions[0]?.dataset.version);

        if (!courseId || !studentId || raw === '' || !Number.isInteger(version)) {
            flash(
                $('edit-grade-msg'),
                'Vui lòng chọn môn, sinh viên và nhập điểm.',
                false
            );
            return;
        }

        const score = Number(raw);

        if (!Number.isFinite(score) || score < 0 || score > 10) {
            flash(
                $('edit-grade-msg'),
                'Điểm phải nằm trong khoảng 0 đến 10.',
                false
            );
            return;
        }

        button.disabled = true;
        courseSelect.disabled = true;
        studentSelect.disabled = true;
        scoreInput.disabled = true;

        try {
            await api(
                '/courses/' +
                encodeURIComponent(courseId) +
                '/grades/' +
                encodeURIComponent(studentId),
                {
                    method: 'PUT',
                    auth: true,
                    body: { score: score, version: version }
                }
            );

            flash($('edit-grade-msg'), 'Đã cập nhật điểm.', true);
            scoreInput.value = '';

            await loadGrades();
            await loadEnrollmentsIntoEditor(courseId);
        } catch (error) {
            if (error.message === 'GRADE_CONFLICT') {
                studentSelect.replaceChildren();
                scoreInput.value = '';
                try {
                    await loadGrades();
                    await loadEnrollmentsIntoEditor(courseId);
                } catch (_) {
                    // The conflict message below remains visible even if refresh fails.
                }
                flash(
                    $('edit-grade-msg'),
                    'Điểm đã được cập nhật ở phiên khác. Điểm bạn nhập chưa được lưu. Vui lòng chọn lại sinh viên, kiểm tra điểm mới rồi nhập lại.',
                    false
                );
                return;
            }
            flash(
                $('edit-grade-msg'),
                translate(error.message),
                false
            );
        } finally {
            button.disabled = false;
            courseSelect.disabled = false;
            studentSelect.disabled = false;
            scoreInput.disabled = false;
        }
    });
}


// ==========================================
// HIỆN / ẨN MẬT KHẨU - KHÔNG DÙNG innerHTML
// ==========================================

const SVG_NS = 'http://www.w3.org/2000/svg';

function createSvgElement(tag, attributes = {}) {
    const element = document.createElementNS(SVG_NS, tag);

    for (const [name, value] of Object.entries(attributes)) {
        element.setAttribute(name, String(value));
    }

    return element;
}

function updateEyeIcon(eyeIcon, showPassword) {
    const elements = [];

    if (!showPassword) {
        // Biểu tượng mắt mở.
        elements.push(
            createSvgElement('path', {
                d: 'M2 12s3.6-7 10-7 10 7 10 7-3.6 7-10 7-10-7-10-7z'
            }),
            createSvgElement('circle', {
                cx: '12',
                cy: '12',
                r: '3'
            })
        );
    } else {
        // Biểu tượng mắt có gạch chéo.
        elements.push(
            createSvgElement('path', {
                d: 'M3 3l18 18'
            }),
            createSvgElement('path', {
                d: 'M10.6 10.6a2 2 0 0 0 2.8 2.8'
            }),
            createSvgElement('path', {
                d: 'M9.9 5.2A10.9 10.9 0 0 1 12 5c5 0 9 4 10 7a13.7 13.7 0 0 1-3 4.2'
            }),
            createSvgElement('path', {
                d: 'M6.3 6.3C4.3 7.6 2.8 9.5 2 12c1 3 5 7 10 7 1.5 0 2.9-.3 4.2-.9'
            })
        );
    }

    eyeIcon.replaceChildren(...elements);
}

function initPasswordToggle() {
    const passwordInput = $('password');
    const toggleButton = $('toggle-password');
    const eyeIcon = $('eye-icon');

    if (!passwordInput || !toggleButton || !eyeIcon) {
        return;
    }

    if (toggleButton.dataset.initialized === 'true') {
        return;
    }

    toggleButton.dataset.initialized = 'true';

    // Giữ nguyên quy ước biểu tượng của giao diện cũ.
    updateEyeIcon(
        eyeIcon,
        passwordInput.type === 'text'
    );

    toggleButton.addEventListener('click', function () {
        const showPassword =
            passwordInput.type === 'password';

        passwordInput.type = showPassword
            ? 'text'
            : 'password';

        updateEyeIcon(eyeIcon, showPassword);

        const label = showPassword
            ? 'Ẩn mật khẩu'
            : 'Hiện mật khẩu';

        toggleButton.setAttribute('aria-label', label);
        toggleButton.setAttribute('title', label);
        toggleButton.setAttribute(
            'aria-pressed',
            String(showPassword)
        );
    });
}


// ==========================================
// KHỞI TẠO
// ==========================================

async function initChangePasswordPage(form) {
    if (!token()) {
        window.location.replace('/login');
        return;
    }
    try {
        await api('/me', { auth: true });
        form.hidden = false;
    } catch (error) {
        if (error.status === 401) {
            sessionStorage.removeItem(TOKEN_KEY);
            window.location.replace('/login');
            return;
        }
        flash($('change-password-msg'), translate(error.message), false);
    }
}

async function changePasswordForm(event) {
    event.preventDefault();
    const form = event.currentTarget;
    const button = $('change-password-button');
    const message = $('change-password-msg');
    const current = $('current-password').value;
    const next = $('new-password').value;
    if (next !== $('confirm-password').value) {
        flash(message, 'Mật khẩu xác nhận không khớp.', false);
        return;
    }
    const length = new TextEncoder().encode(next).length;
    if (length < 8 || length > 72 || current === next) {
        flash(message, 'Mật khẩu mới phải khác mật khẩu hiện tại và dài từ 8 đến 72 byte.', false);
        return;
    }
    button.disabled = true;
    try {
        await api('/auth/change-password', {
            method: 'POST', auth: true,
            body: { currentPassword: current, newPassword: next }
        });
        form.reset();
        sessionStorage.removeItem(TOKEN_KEY);
        updateNavigation();
        form.hidden = true;
        $('change-password-login').hidden = false;
        flash(message, 'Đổi mật khẩu thành công. Vui lòng đăng nhập lại.');
    } catch (error) {
        flash(message, error.message === 'INVALID_CREDENTIALS'
            ? 'Mật khẩu hiện tại không đúng. Vui lòng thử lại.'
            : translate(error.message), false);
    } finally {
        button.disabled = false;
    }
}

async function initHome() {
    if (!token()) return;
    window.location.replace('/dashboard');
}

function closeWorkspaceNav() {
    const wasOpen = document.body.classList.contains('nav-open');
    document.body.classList.remove('nav-open');
    $('sidebar-toggle').setAttribute('aria-expanded', 'false');
    $('sidebar-overlay').hidden = true;
    if (wasOpen) $('sidebar-toggle').focus();
}

function showWorkspace(me) {
    if (!$('workspace-sidebar')) return;
    const labels = {ADMIN:'Quản trị viên',INSTRUCTOR:'Giảng viên',STUDENT:'Sinh viên'};
    document.body.classList.add('workspace-auth');
    document.body.dataset.role = me.role;
    $('workspace-sidebar').hidden = false;
    $('workspace-topbar').hidden = false;
    $('workspace-role').textContent = labels[me.role];
    $('workspace-user-role').textContent = labels[me.role];
    $('workspace-user-name').textContent = me.fullName || me.email;
    $('workspace-user-initial').textContent = (me.fullName || me.email).slice(0,1).toUpperCase();
    $('workspace-page-title').textContent = document.title.split('·')[0].trim();
    $('workspace-courses-label').textContent = me.role === 'ADMIN' ? 'Quản lý khóa học' : me.role === 'INSTRUCTOR' ? 'Lớp giảng dạy' : 'Khóa học của tôi';
    $('workspace-grades-label').textContent = me.role === 'INSTRUCTOR' ? 'Quản lý điểm' : 'Kết quả học tập';
    $('workspace-grades-link').href = '/grades';
    $('workspace-grades-link').dataset.nav = '/grades';
    document.querySelectorAll('[data-workspace-roles]').forEach(element => {
        element.hidden = !element.dataset.workspaceRoles.split(' ').includes(me.role);
    });
    document.querySelectorAll('[data-nav]').forEach(element => {
        const profilePage = element.dataset.nav === '/account' && window.location.pathname === '/account';
        const exact = element.dataset.nav === window.location.pathname + window.location.hash || profilePage;
        const coursePage = element.dataset.nav === '/catalog' && ['/study','/forum'].includes(window.location.pathname);
        const active = exact || coursePage;
        element.classList.toggle('active',active);
        if (active) element.setAttribute('aria-current','page'); else element.removeAttribute('aria-current');
    });
}

async function initWorkspace() {
    if (!token()) return;
    try { showWorkspace(await api('/me', {auth:true})); }
    catch (error) {
        if (error.status === 401) { sessionStorage.removeItem(TOKEN_KEY); updateNavigation(); }
    }
}

function initApp() {
    updateNavigation();
    initPasswordToggle();
    initWorkspace();
    if ($('workspace-logout')) {
        $('workspace-logout').addEventListener('click', logout);
        $('sidebar-toggle').addEventListener('click', () => {
            const open = document.body.classList.toggle('nav-open');
            $('sidebar-toggle').setAttribute('aria-expanded', String(open));
            $('sidebar-overlay').hidden = !open;
        });
        $('sidebar-overlay').addEventListener('click', closeWorkspaceNav);
        document.addEventListener('keydown', event => { if (event.key === 'Escape') closeWorkspaceNav(); });
        window.addEventListener('hashchange', () => { initWorkspace(); closeWorkspaceNav(); });
    }
    if ($('home-title')) initHome();

    const changeForm = $('change-password-form');
    if (changeForm) {
        initChangePasswordPage(changeForm);
        changeForm.addEventListener('submit', changePasswordForm);
    }

    const loginFormElement = $('login-form');
    if (loginFormElement) {
        loginFormElement.addEventListener('submit', loginForm);
    }

    const registerFormElement = $('register-form');
    if (registerFormElement) {
        registerFormElement.addEventListener('submit', registerForm);
    }

    const forgotFormElement = $('forgot-form');
    if (forgotFormElement) {
        forgotFormElement.addEventListener('submit', forgotForm);
    }

    const resetFormElement = $('reset-form');
    if (resetFormElement) {
        const resetToken = new URLSearchParams(window.location.hash.slice(1)).get('token');
        if (resetToken) {
            $('reset-token').value = resetToken;
            $('reset-section').hidden = false;
            $('forgot-section').hidden = true;
            history.replaceState(null, '', window.location.pathname);
            $('reset-new').focus();
        }
        resetFormElement.addEventListener('submit', resetForm);
    }

    if ($('me-id')) {
        loadAccount();
    }
    if ($('grades-page-title')) loadGradesPage();
}

if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initApp);
} else {
    initApp();
}
