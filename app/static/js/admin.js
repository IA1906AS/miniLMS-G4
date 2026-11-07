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
        const empty = document.createElement('tr');
        const cell = document.createElement('td');
        cell.colSpan = 6;
        cell.className = 'admin-users-empty';
        cell.textContent = 'Không tìm thấy người dùng phù hợp.';
        empty.appendChild(cell);
        list.appendChild(empty);
    }
    for (const [index, user] of data.items.entries()) {
        const row = document.createElement('tr');
        const numberCell = document.createElement('td');
        numberCell.textContent = (data.page - 1) * data.pageSize + index + 1;
        const nameCell = document.createElement('td');
        const name = document.createElement('strong');
        name.textContent = user.fullName || 'Chưa cập nhật họ tên';
        nameCell.appendChild(name);
        if (user.id === adminActor.id) {
            const own = document.createElement('span');
            own.className = 'pill';
            own.textContent = 'Bạn';
            nameCell.appendChild(own);
        }
        const details = document.createElement('details');
        details.className = 'admin-user-id';
        const summary = document.createElement('summary');
        summary.textContent = 'Mã tài khoản';
        const code = document.createElement('code');
        code.textContent = user.id;
        details.append(summary, code);
        nameCell.appendChild(details);
        const emailCell = document.createElement('td');
        emailCell.className = 'admin-user-email';
        emailCell.textContent = user.email;
        const roleCell = document.createElement('td');
        const role = document.createElement('select');
        role.setAttribute('aria-label', 'Vai trò của ' + user.email);
        for (const name of ['STUDENT', 'INSTRUCTOR', 'ADMIN']) {
            const option = document.createElement('option');
            option.value = name;
            option.textContent = ({STUDENT:'Sinh viên',INSTRUCTOR:'Giảng viên',ADMIN:'Quản trị viên'})[name];
            role.appendChild(option);
        }
        role.value = user.role;
        roleCell.appendChild(role);
        const statusCell = document.createElement('td');
        const status = document.createElement('span');
        status.className = 'user-status ' + (user.isLocked ? 'is-locked' : 'is-active');
        status.textContent = user.isLocked ? 'Đã khóa' : 'Hoạt động';
        statusCell.appendChild(status);
        const actionsCell = document.createElement('td');
        const actions = document.createElement('div');
        actions.className = 'admin-row-actions';
        const save = document.createElement('button');
        save.type = 'button';
        save.textContent = 'Lưu vai trò';
        const lock = document.createElement('button');
        lock.type = 'button';
        lock.textContent = user.isLocked ? 'Mở khóa' : 'Khóa tài khoản';
        lock.className = user.isLocked ? 'user-unlock' : 'user-lock';
        const isSelf = user.id === adminActor.id;
        role.disabled = lock.disabled = isSelf;
        save.disabled = true;
        role.addEventListener('change', () => { save.disabled = isSelf || role.value === user.role; });
        if (isSelf) {
            role.title = lock.title = save.title = 'Không thể tự khóa hoặc đổi vai trò tài khoản quản trị đang dùng.';
        }
        async function update(changes, prompt) {
            if (!window.confirm(prompt)) return;
            role.disabled = save.disabled = lock.disabled = true;
            try {
                await api('/admin/api/users/' + encodeURIComponent(user.id), {method: 'PUT', auth: true, body: changes});
                await loadAdminUsers();
                flash($('admin-msg'), 'Đã cập nhật người dùng.');
            } catch (error) {
                showAdminError(error);
                role.disabled = lock.disabled = isSelf;
                save.disabled = isSelf || role.value === user.role;
            }
        }
        save.addEventListener('click', () => update({role: role.value}, 'Đổi vai trò của ' + user.email + '?'));
        lock.addEventListener('click', () => update({isLocked: !user.isLocked}, (user.isLocked ? 'Mở khóa ' : 'Khóa tài khoản ') + user.email + '?'));
        actions.append(save, lock);
        actionsCell.appendChild(actions);
        row.append(numberCell, nameCell, emailCell, roleCell, statusCell, actionsCell);
        list.appendChild(row);
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
