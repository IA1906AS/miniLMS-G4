'use strict';

const profileRoles = {
    STUDENT: 'Sinh viên', INSTRUCTOR: 'Giảng viên', ADMIN: 'Quản trị viên'
};

// Fetch private images with Authorization; never put JWTs in image URLs.
async function displayProfileAvatar(element, url) {
    const requestId = String(Number(element.dataset.requestId || 0) + 1);
    element.dataset.requestId = requestId;
    element.hidden = true;
    element.removeAttribute('src');
    if (element.dataset.objectUrl) {
        URL.revokeObjectURL(element.dataset.objectUrl);
        delete element.dataset.objectUrl;
    }
    if (!url) return;
    try {
        const response = await fetch(url, {
            headers: { Authorization: 'Bearer ' + token() }, cache: 'no-store'
        });
        if (!response.ok) return;
        const blob = await response.blob();
        if (element.dataset.requestId !== requestId) return;
        const objectUrl = URL.createObjectURL(blob);
        element.dataset.objectUrl = objectUrl;
        element.src = objectUrl;
        element.hidden = false;
    } catch (_) {
        // Keep the profile readable if the image cannot be loaded.
    }
}

function renderOwnProfile(profile) {
    $('profile-name').value = profile.fullName || '';
    $('profile-bio').value = profile.bio || '';
    $('profile-contact').value = profile.contact || '';
    renderOwnAvatar(profile);
}

function renderOwnAvatar(profile) {
    displayProfileAvatar($('profile-avatar'), profile.avatarUrl);
    $('avatar-empty').hidden = Boolean(profile.avatarUrl);
    $('avatar-delete').hidden = !profile.avatarUrl;
}

let memberListRequest = 0;
let memberDetailRequest = 0;

async function showMemberProfile(userId) {
    const requestId = ++memberDetailRequest;
    $('member-detail').hidden = true;
    try {
        const member = await api('/users/' + encodeURIComponent(userId) + '/profile', {
            auth: true
        });
        if (requestId !== memberDetailRequest) return;
        $('member-name').textContent = member.fullName || member.id;
        $('member-role').textContent = profileRoles[member.role] || member.role;
        $('member-bio').textContent = member.bio || 'Thành viên chưa thêm giới thiệu.';
        displayProfileAvatar($('member-avatar'), member.avatarUrl);
        $('member-detail').hidden = false;
    } catch (error) {
        if (requestId === memberDetailRequest) {
            flash($('members-msg'), translate(error.message), false);
        }
    }
}

async function loadCourseMembers() {
    const requestId = ++memberListRequest;
    ++memberDetailRequest;
    $('course-members').replaceChildren();
    $('member-detail').hidden = true;
    $('members-msg').className = 'msg';
    const courseId = $('member-course').value;
    if (!courseId) return;
    try {
        const members = await api('/courses/' + encodeURIComponent(courseId) + '/members', {
            auth: true
        });
        if (requestId !== memberListRequest) return;
        for (const member of members) {
            const item = document.createElement('li');
            const button = document.createElement('button');
            button.type = 'button';
            button.textContent = (member.fullName || member.id) + ' · ' +
                (profileRoles[member.role] || member.role);
            button.addEventListener('click', () => showMemberProfile(member.id));
            item.appendChild(button);
            $('course-members').appendChild(item);
        }
    } catch (error) {
        if (requestId === memberListRequest) {
            flash($('members-msg'), translate(error.message), false);
        }
    }
}

async function initProfileFeatures() {
    if (!$('profile-form') || $('profile-form').dataset.initialized) return;
    $('profile-form').dataset.initialized = 'true';
    $('profile-form').addEventListener('submit', async (event) => {
        event.preventDefault();
        const button = event.submitter;
        if (button) button.disabled = true;
        try {
            const profile = await api('/me/profile', {
                method: 'PUT', auth: true,
                body: {
                    fullName: $('profile-name').value,
                    bio: $('profile-bio').value,
                    contact: $('profile-contact').value
                }
            });
            renderOwnProfile(profile);
            flash($('profile-msg'), 'Đã lưu hồ sơ.');
            await loadCourseMembers();
        } catch (error) {
            flash($('profile-msg'), translate(error.message), false);
        } finally {
            if (button) button.disabled = false;
        }
    });
    $('avatar-form').addEventListener('submit', async (event) => {
        event.preventDefault();
        const file = $('avatar-file').files[0];
        if (!file) return;
        if (file.size > 2 * 1024 * 1024) {
            flash($('avatar-msg'), translate('FILE_TOO_LARGE'), false);
            return;
        }
        const button = event.submitter;
        if (button) button.disabled = true;
        try {
            const body = new FormData();
            body.append('avatar', file);
            const profile = await api('/me/avatar', { method: 'POST', auth: true, body });
            renderOwnAvatar(profile);
            $('avatar-file').value = '';
            flash($('avatar-msg'), 'Đã cập nhật ảnh đại diện.');
        } catch (error) {
            flash($('avatar-msg'), translate(error.message), false);
        } finally {
            if (button) button.disabled = false;
        }
    });
    $('avatar-delete').addEventListener('click', async () => {
        $('avatar-delete').disabled = true;
        try {
            const profile = await api('/me/avatar', { method: 'DELETE', auth: true });
            renderOwnAvatar(profile);
            flash($('avatar-msg'), 'Đã xóa ảnh đại diện.');
        } catch (error) {
            flash($('avatar-msg'), translate(error.message), false);
        } finally {
            $('avatar-delete').disabled = false;
        }
    });
    $('member-course').addEventListener('change', loadCourseMembers);
    await Promise.all([
        (async () => {
            try {
                renderOwnProfile(await api('/me/profile', { auth: true }));
            } catch (error) {
                flash($('profile-msg'), translate(error.message), false);
            }
        })(),
        (async () => {
            try {
                const courses = await api('/me/courses', { auth: true });
                $('member-course').replaceChildren();
                for (const course of courses) {
                    const option = document.createElement('option');
                    option.value = course.id;
                    option.textContent = course.title;
                    $('member-course').appendChild(option);
                }
                if (!courses.length) {
                    flash($('members-msg'), 'Bạn chưa tham gia khóa học nào.');
                    return;
                }
                await loadCourseMembers();
            } catch (error) {
                flash($('members-msg'), translate(error.message), false);
            }
        })()
    ]);
}
