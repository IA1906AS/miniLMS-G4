'use strict';

let usersPage = 1;
let usersQuery = '';
let adminActor;
let usersRequest = 0;

async function loadAdminUsers() {
    const requestId = ++usersRequest;
    const data = await api('/admin/api/users?' + new URLSearchParams({q: usersQuery, page: usersPage}), {auth: true});
    if (requestId !== usersRequest) return;
    const list = $('admin-user-list');
    list.replaceChildren();
    if (!data.items.length) {
        const empty = document.createElement('li');
        empty.textContent = 'Không tìm thấy người dùng.';
        list.appendChild(empty);
    }
    for (const user of data.items) {
        const li = document.createElement('li');
        const title = document.createElement('p');
        title.textContent = `${user.fullName || user.email} · ${user.email} · ${user.id} · ${user.isLocked ? 'Đã khóa' : 'Hoạt động'}`;
        const role = document.createElement('select');
        role.setAttribute('aria-label', 'Vai trò của ' + user.email);
        for (const name of ['STUDENT', 'INSTRUCTOR', 'ADMIN']) {
            const option = document.createElement('option');
            option.value = name;
            option.textContent = name;
            role.appendChild(option);
        }
        role.value = user.role;
        const save = document.createElement('button');
        save.type = 'button';
        save.textContent = 'Lưu vai trò';
        const lock = document.createElement('button');
        lock.type = 'button';
        lock.textContent = user.isLocked ? 'Mở khóa' : 'Khóa tài khoản';
        role.disabled = save.disabled = lock.disabled = user.id === adminActor.id;
        async function update(changes, prompt) {
            if (!window.confirm(prompt)) return;
            save.disabled = lock.disabled = true;
            try {
                await api('/admin/api/users/' + encodeURIComponent(user.id), {method: 'PUT', auth: true, body: changes});
                await loadAdminUsers();
                flash($('admin-msg'), 'Đã cập nhật người dùng.');
            } catch (error) {
                showAdminError(error);
                save.disabled = lock.disabled = false;
            }
        }
        save.addEventListener('click', () => update({role: role.value}, 'Đổi vai trò của ' + user.email + '?'));
        lock.addEventListener('click', () => update({isLocked: !user.isLocked}, (user.isLocked ? 'Mở khóa ' : 'Khóa tài khoản ') + user.email + '?'));
        li.append(title, role, save, lock);
        list.appendChild(li);
    }
    $('users-page').textContent = `Trang ${data.page} · ${data.total} người dùng`;
    $('users-prev').disabled = data.page <= 1;
    $('users-next').disabled = data.page * data.pageSize >= data.total;
}

function showAdminError(error) {
    if (error.status === 401) {
        sessionStorage.removeItem(TOKEN_KEY);
        window.location.replace('/login');
        return;
    }
    if (error.status === 403) $('admin-panel').hidden = true;
    const messages = {
        SELF_ADMIN_CHANGE: 'Bạn không thể tự khóa hoặc hạ quyền tài khoản quản trị đang dùng.',
        INSTRUCTOR_HAS_COURSES: 'Giảng viên đang phụ trách khóa học. Hãy chuyển khóa học trước khi đổi vai trò.'
    };
    flash($('admin-msg'), messages[error.message] || translate(error.message), false);
}

(async function initAdminUsers() {
    if (!token()) {
        window.location.replace('/login');
        return;
    }
    try {
        adminActor = await api('/me', {auth: true});
        if (adminActor.role !== 'ADMIN') {
            flash($('admin-msg'), 'Chỉ quản trị viên được truy cập trang này.', false);
            return;
        }
        $('admin-panel').hidden = false;
        $('user-search').addEventListener('submit', event => {
            event.preventDefault();
            usersQuery = $('user-query').value.trim();
            usersPage = 1;
            loadAdminUsers().catch(showAdminError);
        });
        for (const [id, delta] of [['users-prev', -1], ['users-next', 1]]) {
            $(id).addEventListener('click', () => {
                usersPage += delta;
                loadAdminUsers().catch(showAdminError);
            });
        }
        await loadAdminUsers();
    } catch (error) {
        showAdminError(error);
    }
})();
