
// ==========================================
// MINILMS - MAIN JAVASCRIPT
// ==========================================

const $ = (id) => document.getElementById(id);

const TOKEN_KEY = 'lms_token';

const token = () => sessionStorage.getItem(TOKEN_KEY);


// ==========================================
// HIỂN THỊ THÔNG BÁO
// ==========================================

function flash(element, message, ok = true) {
    if (!element) return;

    element.textContent = message;
    element.className = 'msg show ' + (ok ? 'ok' : 'err');
}


// ==========================================
// API REQUEST
// ==========================================

async function api(path, {
    method = 'GET',
    body,
    auth = false
} = {}) {
    const headers = {
        'Accept': 'application/json'
    };

    if (body !== undefined) {
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
            ? JSON.stringify(body)
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
        INVALID_CREDENTIALS:
            'Email hoặc mật khẩu không đúng.',

        UNAUTHENTICATED:
            'Bạn cần đăng nhập trước.',

        ACCOUNT_LOCKED:
            'Tài khoản tạm khóa do sai quá nhiều lần.',

        VALIDATION_ERROR:
            'Dữ liệu không hợp lệ.',

        NOT_FOUND:
            'Không tìm thấy dữ liệu.',

        FORBIDDEN:
            'Bạn không có quyền thực hiện thao tác này.',

        INVALID_RESPONSE:
            'Phản hồi từ máy chủ không hợp lệ.',

        'HTTP 400':
            'Yêu cầu không hợp lệ.',

        'HTTP 401':
            'Phiên đăng nhập không hợp lệ hoặc đã hết hạn.',

        'HTTP 403':
            'Bạn không có quyền thực hiện thao tác này.',

        'HTTP 404':
            'Không tìm thấy API được yêu cầu.',

        'HTTP 500':
            'Máy chủ đang gặp lỗi.'
    };

    return messages[code] || code || 'Đã xảy ra lỗi.';
}


// ==========================================
// CẬP NHẬT HEADER
// ==========================================

function updateNavigation() {
    const isLoggedIn = Boolean(token());

    // Menu dành cho khách
    document.querySelectorAll('.guest-only').forEach((element) => {
        element.hidden = isLoggedIn;
    });

    // Menu dành cho người đã đăng nhập
    document.querySelectorAll('.auth-only').forEach((element) => {
        element.hidden = !isLoggedIn;
    });

    // Nút đăng xuất
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

function logout() {
    sessionStorage.removeItem(TOKEN_KEY);

    updateNavigation();

    window.location.assign('/');
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

        // Lưu JWT
        sessionStorage.setItem(TOKEN_KEY, accessToken);

        // Cập nhật header
        updateNavigation();

        flash(
            messageBox,
            'Đăng nhập thành công, đang chuyển trang.'
        );

        // Chuyển đến trang tài khoản
        window.location.assign('/account');

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

    try {
        const data = await api('/auth/forgot-password', {
            method: 'POST',
            body: {
                email: $('reset-email')?.value.trim()
            }
        });

        if (data?.resetToken && $('reset-token')) {
            $('reset-token').value = data.resetToken;
        }

        flash(
            messageBox,
            data?.resetToken
                ? 'Token reset (demo): ' + data.resetToken
                : 'Nếu email tồn tại, hướng dẫn đặt lại mật khẩu đã được gửi.'
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
// ĐẶT LẠI MẬT KHẨU
// ==========================================

async function resetForm(event) {
    if (event) {
        event.preventDefault();
    }

    const messageBox = $('confirm-msg');

    try {
        await api('/auth/reset-password', {
            method: 'POST',
            body: {
                token: $('reset-token')?.value.trim(),
                password: $('reset-new')?.value
            }
        });

        flash(
            messageBox,
            'Đổi mật khẩu thành công. Mời đăng nhập lại.'
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
            $('me-role').textContent = me.role ?? '–';
        }

        if ($('who')) {
            $('who').textContent = me.email ?? 'Người dùng';
        }

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

    // Tải điểm riêng để không ảnh hưởng thông tin tài khoản
    try {
        await loadGrades();
    } catch (error) {
        console.error('Load grades failed:', error.message);

        flash(
            $('account-msg'),
            'Đã tải tài khoản nhưng chưa thể tải điểm.',
            false
        );
    }
}


// ==========================================
// DANH SÁCH ĐIỂM
// ==========================================

async function loadGrades() {
    const table = $('grades');
    const courses = ['c1', 'c2'];

    if (!table) return;

    table.replaceChildren();

    for (const course of courses) {
        try {
            const rows = await api(
                '/courses/' +
                encodeURIComponent(course) +
                '/grades',
                { auth: true }
            );

            if (!Array.isArray(rows)) {
                continue;
            }

            for (const row of rows) {
                const tr = document.createElement('tr');

                for (const value of [
                    course,
                    row.studentId,
                    row.score
                ]) {
                    const td = document.createElement('td');

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
// HIỆN / ẨN MẬT KHẨU
// ==========================================

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

    // Con mắt không gạch
    const eyeOpen = `
        <path d="M2 12s3.6-7 10-7 10 7 10 7-3.6 7-10 7-10-7-10-7z"/>
        <circle cx="12" cy="12" r="3"/>
    `;

    // Con mắt có gạch chéo
    const eyeClosed = `
        <path d="M3 3l18 18"/>
        <path d="M10.6 10.6a2 2 0 0 0 2.8 2.8"/>
        <path d="M9.9 5.2A10.9 10.9 0 0 1 12 5c5 0 9 4 10 7a13.7 13.7 0 0 1-3 4.2"/>
        <path d="M6.3 6.3C4.3 7.6 2.8 9.5 2 12c1 3 5 7 10 7 1.5 0 2.9-.3 4.2-.9"/>
    `;

    // Mặc định: mật khẩu ẩn, mắt không gạch
    eyeIcon.innerHTML =
        passwordInput.type === 'password'
            ? eyeOpen
            : eyeClosed;

    toggleButton.addEventListener('click', function () {
        const showPassword =
            passwordInput.type === 'password';

        passwordInput.type = showPassword
            ? 'text'
            : 'password';

        // Theo yêu cầu:
        // Ẩn mật khẩu -> mắt không gạch
        // Hiện mật khẩu -> mắt có gạch
        eyeIcon.innerHTML = showPassword
            ? eyeClosed
            : eyeOpen;

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

function initApp() {
    updateNavigation();
    initPasswordToggle();
}

if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initApp);
} else {
    initApp();
}
