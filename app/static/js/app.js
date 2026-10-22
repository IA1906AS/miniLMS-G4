
const $ = (id) => document.getElementById(id);

const key = 'lms_token';

const token = () => sessionStorage.getItem(key);

function flash(el, text, ok = true) {
    if (!el) return;

    el.textContent = text;
    el.className = 'msg show ' + (ok ? 'ok' : 'err');
}

async function api(path, { method = 'GET', body, auth = false } = {}) {
    const headers = {
        'Content-Type': 'application/json',
    };

    if (auth) {
        const t = token();

        if (!t) {
            throw new Error('UNAUTHENTICATED');
        }

        headers.Authorization = 'Bearer ' + t;
    }

    const res = await fetch(path, {
        method,
        headers,
        body: body !== undefined ? JSON.stringify(body) : undefined,
    });

    let data = null;

    try {
        data = await res.json();
    } catch (_) {
        data = null;
    }

    if (!res.ok) {
        const err = new Error(
            (data && data.error) || ('HTTP ' + res.status)
        );

        err.status = res.status;
        throw err;
    }

    return data;
}

function logout() {
    sessionStorage.removeItem(key);
    window.location.href = '/';
}

async function loginForm() {
    const box = $('login-msg');

    try {
        const data = await api('/auth/login', {
            method: 'POST',
            body: {
                email: $('email')?.value,
                password: $('password')?.value,
            },
        });

        if (!data || !data.accessToken) {
            throw new Error('INVALID_RESPONSE');
        }

        sessionStorage.setItem(key, data.accessToken);

        flash(box, 'Đăng nhập thành công, đang chuyển trang…');
        window.location.href = '/account';
    } catch (err) {
        flash(box, translate(err.message), false);
    }
}

async function registerForm() {
    const box = $('register-msg');

    try {
        await api('/auth/register', {
            method: 'POST',
            body: {
                email: $('reg-email')?.value,
                password: $('reg-password')?.value,
            },
        });

        flash(box, 'Đã tạo tài khoản, mời đăng nhập.');
    } catch (err) {
        flash(box, translate(err.message), false);
    }
}

async function forgotForm() {
    const box = $('forgot-msg');

    try {
        const data = await api('/auth/forgot-password', {
            method: 'POST',
            body: {
                email: $('reset-email')?.value,
            },
        });

        if (data?.resetToken && $('reset-token')) {
            $('reset-token').value = data.resetToken;
        }

        flash(
            box,
            data?.resetToken
                ? 'Token reset (demo): ' + data.resetToken
                : 'Nếu email tồn tại, hướng dẫn đặt lại mật khẩu đã được gửi.'
        );
    } catch (err) {
        flash(box, translate(err.message), false);
    }
}

async function resetForm() {
    const box = $('confirm-msg');

    try {
        await api('/auth/reset-password', {
            method: 'POST',
            body: {
                token: $('reset-token')?.value,
                password: $('reset-new')?.value,
            },
        });

        flash(box, 'Đã đổi mật khẩu, mời đăng nhập lại.');
    } catch (err) {
        flash(box, translate(err.message), false);
    }
}

function translate(code) {
    return {
        INVALID_CREDENTIALS: 'Email hoặc mật khẩu không đúng.',
        UNAUTHENTICATED: 'Bạn cần đăng nhập trước.',
        ACCOUNT_LOCKED: 'Tài khoản tạm khoá do sai quá nhiều lần.',
        VALIDATION_ERROR: 'Dữ liệu không hợp lệ.',
        NOT_FOUND: 'Không tìm thấy dữ liệu.',
        FORBIDDEN: 'Bạn không có quyền thao tác.',
        INVALID_RESPONSE: 'Phản hồi từ máy chủ không hợp lệ.',
        'HTTP 401': 'Phiên đăng nhập hết hạn hoặc không hợp lệ.',
        'HTTP 403': 'Bạn không có quyền thực hiện thao tác này.',
    }[code] || code;
}

async function loadAccount() {
    if (!token()) {
        window.location.href = '/';
        return;
    }

    try {
        const me = await api('/me', { auth: true });

        if ($('me-id')) $('me-id').textContent = me.id ?? '';
        if ($('me-email')) $('me-email').textContent = me.email ?? '';
        if ($('me-role')) $('me-role').textContent = me.role ?? '';
        if ($('who')) $('who').textContent = me.email ?? '';

        await loadGrades();
    } catch (err) {
        if (
            err.message === 'UNAUTHENTICATED' ||
            err.status === 401
        ) {
            logout();
            return;
        }

        flash($('account-msg'), translate(err.message), false);
    }
}

async function loadGrades() {
    const courses = ['c1', 'c2'];
    const table = $('grades');

    if (!table) return;

    table.replaceChildren();

    for (const course of courses) {
        try {
            const rows = await api(
                '/courses/' + encodeURIComponent(course) + '/grades',
                { auth: true }
            );

            if (!Array.isArray(rows)) continue;

            for (const row of rows) {
                const tr = document.createElement('tr');

                for (const value of [
                    course,
                    row.studentId,
                    row.score,
                ]) {
                    const td = document.createElement('td');
                    td.textContent = value ?? '';
                    tr.appendChild(td);
                }

                table.appendChild(tr);
            }
        } catch (err) {
            if (err.message === 'FORBIDDEN' || err.status === 403) {
                continue;
            }

            throw err;
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
