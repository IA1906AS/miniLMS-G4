'use strict';

let catalogUser;
let selectedCourse = null;
let detailRequest = 0;
let catalogRequest = 0;
const instructorNames = new Map();

function coursePath(id) {
    return '/courses/' + encodeURIComponent(id);
}

function actionButton(label, handler) {
    const button = document.createElement('button');
    button.type = 'button';
    button.textContent = label;
    button.addEventListener('click', async () => {
        button.disabled = true;
        try { await handler(); }
        catch (error) { flash($('course-detail-msg'), translate(error.message), false); }
        finally { button.disabled = false; }
    });
    return button;
}

async function loadCatalog() {
    const requestId = ++catalogRequest;
    const params = new URLSearchParams({
        q: $('course-query').value.trim(),
        instructorId: $('course-instructor').value
    });
    const courses = await api('/courses?' + params, { auth: true });
    if (requestId !== catalogRequest) return;
    $('course-list').replaceChildren();
    $('course-empty').hidden = courses.length > 0;
    for (const course of courses) {
        const li = document.createElement('li');
        li.appendChild(actionButton(
            course.title + ' · ' + (instructorNames.get(course.instructorId) || course.instructorId),
            () => selectCourse(course.id)
        ));
        $('course-list').appendChild(li);
    }
}

async function selectCourse(id) {
    const requestId = ++detailRequest;
    selectedCourse = null;
    $('course-study-link').hidden = true;
    $('course-detail').hidden = true;
    $('course-detail-msg').className = 'msg';
    const course = await api(coursePath(id), { auth: true });
    if (requestId !== detailRequest) return;
    selectedCourse = course;
    $('course-study-link').hidden = !course.canAccessMaterials;
    $('course-study-link').href = '/study?course=' + encodeURIComponent(id);
    $('course-detail-title').textContent = course.title;
    $('course-detail-code').textContent = 'Mã khóa học: ' + course.courseCode;
    $('course-detail-owner').textContent = 'Giảng viên: ' +
        (instructorNames.get(course.instructorId) || course.instructorId);
    $('course-detail-state').textContent = course.enrolled ? 'Bạn đã ghi danh.' :
        course.canManage ? 'Bạn có quyền quản lý khóa học này.' : 'Bạn chưa tham gia khóa học này.';
    if (catalogUser.role === 'STUDENT') $('course-code').value = course.courseCode;
    $('course-manager').hidden = !course.canManage;
    $('course-edit-title').value = course.title;
    $('material-upload').hidden = !course.canManage;
    $('course-enrollments').replaceChildren();
    $('course-materials').replaceChildren();
    $('material-access').textContent = course.canAccessMaterials ? 'Đang tải tài liệu…' :
        'Bạn cần ghi danh khóa học để xem và tải tài liệu.';
    $('course-detail').hidden = false;
    await Promise.all([
        (async () => {
            if (!course.canManage) return;
            const rows = await api(coursePath(id) + '/enrollments', { auth: true });
            if (requestId !== detailRequest) return;
            if (!rows.length) {
                const li = document.createElement('li');
                li.textContent = 'Chưa có sinh viên ghi danh.';
                $('course-enrollments').appendChild(li);
            }
            for (const row of rows) {
                const li = document.createElement('li');
                li.appendChild(document.createTextNode(row.studentId + ' '));
                li.appendChild(actionButton('Hủy ghi danh', async () => {
                    if (!window.confirm('Hủy ghi danh của ' + row.studentId + '?')) return;
                    await api(coursePath(id) + '/enrollments/' + encodeURIComponent(row.studentId), {
                        method: 'DELETE', auth: true
                    });
                    if (selectedCourse?.id === id) await selectCourse(id);
                }));
                $('course-enrollments').appendChild(li);
            }
        })(),
        (async () => {
            if (!course.canAccessMaterials) return;
            const materials = await api(coursePath(id) + '/materials', { auth: true });
            if (requestId !== detailRequest) return;
            $('material-access').textContent = materials.length ? '' : 'Chưa có tài liệu.';
            for (const material of materials) {
                const li = document.createElement('li');
                const label = document.createElement('p');
                label.textContent = material.title + ' · ' + material.fileName + ' · ' +
                    Math.ceil(material.size / 1024) + ' KB';
                li.appendChild(label);
                li.appendChild(actionButton('Tải xuống', () => downloadMaterial(material)));
                if (course.canManage) {
                    li.appendChild(actionButton('Xóa tài liệu', async () => {
                        if (!window.confirm('Xóa tài liệu ' + material.title + '?')) return;
                        await api(coursePath(id) + '/materials/' + encodeURIComponent(material.id), {
                            method: 'DELETE', auth: true
                        });
                        if (selectedCourse?.id === id) await selectCourse(id);
                    }));
                }
                $('course-materials').appendChild(li);
            }
        })()
    ]);
}

async function downloadMaterial(material) {
    const response = await fetch(material.downloadUrl, {
        headers: { Authorization: 'Bearer ' + token() }, cache: 'no-store'
    });
    if (!response.ok) {
        const data = await response.json();
        throw new Error(data.error || 'Không tải được tài liệu.');
    }
    const url = URL.createObjectURL(await response.blob());
    const anchor = document.createElement('a');
    anchor.href = url;
    anchor.download = material.fileName;
    document.body.appendChild(anchor);
    anchor.click();
    anchor.remove();
    setTimeout(() => URL.revokeObjectURL(url), 10000);
}

function courseForm(id, messageId, handler) {
    $(id).addEventListener('submit', async (event) => {
        event.preventDefault();
        const button = event.submitter;
        if (button) button.disabled = true;
        try { await handler(); }
        catch (error) { flash($(messageId), translate(error.message), false); }
        finally { if (button) button.disabled = false; }
    });
}

async function initCatalog() {
    if (!token()) { window.location.replace('/login'); return; }
    try {
        catalogUser = await api('/me', { auth: true });
        const instructors = await api('/instructors', { auth: true });
        for (const instructor of instructors) {
            const name = instructor.fullName || instructor.id;
            instructorNames.set(instructor.id, name);
            for (const id of ['course-instructor', 'course-new-owner']) {
                const option = document.createElement('option');
                option.value = instructor.id;
                option.textContent = name + ' (' + instructor.id + ')';
                $(id).appendChild(option);
            }
        }
        $('course-create-panel').hidden = !['ADMIN', 'INSTRUCTOR'].includes(catalogUser.role);
        $('course-owner-field').hidden = catalogUser.role !== 'ADMIN';
        $('course-join-panel').hidden = catalogUser.role !== 'STUDENT';
        courseForm('course-search', 'catalog-msg', loadCatalog);
        courseForm('course-create', 'create-course-msg', async () => {
            const body = { title: $('course-new-title').value.trim() };
            if (catalogUser.role === 'ADMIN') body.instructorId = $('course-new-owner').value;
            const course = await api('/courses', { method: 'POST', auth: true, body });
            $('course-new-title').value = '';
            flash($('create-course-msg'), 'Đã tạo khóa học. Mã: ' + course.id);
            await loadCatalog();
            await selectCourse(course.id);
        });
        courseForm('course-join', 'join-course-msg', async () => {
            const result = await api('/courses/join', {
                method: 'POST', auth: true, body: { courseCode: $('course-code').value.trim() }
            });
            flash($('join-course-msg'), 'Đã ghi danh khóa học.');
            await selectCourse(result.courseId);
        });
        courseForm('course-edit', 'course-detail-msg', async () => {
            if (!selectedCourse) return;
            const id = selectedCourse.id;
            await api(coursePath(id), {
                method: 'PUT', auth: true, body: { title: $('course-edit-title').value.trim() }
            });
            await loadCatalog();
            if (selectedCourse?.id === id) await selectCourse(id);
            flash($('course-detail-msg'), 'Đã cập nhật khóa học.');
        });
        courseForm('enrollment-add', 'course-detail-msg', async () => {
            if (!selectedCourse) return;
            const id = selectedCourse.id;
            await api(coursePath(id) + '/enrollments', {
                method: 'POST', auth: true, body: { studentId: $('enrollment-student').value.trim() }
            });
            $('enrollment-student').value = '';
            if (selectedCourse?.id === id) await selectCourse(id);
            flash($('course-detail-msg'), 'Đã thêm sinh viên.');
        });
        courseForm('material-upload', 'course-detail-msg', async () => {
            if (!selectedCourse) return;
            const id = selectedCourse.id;
            const file = $('material-file').files[0];
            if (!file) return;
            if (file.size > 10 * 1024 * 1024) throw new Error('Tài liệu vượt quá 10 MB.');
            const body = new FormData();
            body.append('file', file);
            body.append('title', $('material-title').value.trim());
            await api(coursePath(id) + '/materials', { method: 'POST', auth: true, body });
            $('material-file').value = '';
            $('material-title').value = '';
            if (selectedCourse?.id === id) await selectCourse(id);
            flash($('course-detail-msg'), 'Đã tải tài liệu lên.');
        });
        await loadCatalog();
    } catch (error) {
        if (error.status === 401) { window.location.replace('/login'); return; }
        flash($('catalog-msg'), translate(error.message), false);
    }
}

document.addEventListener('DOMContentLoaded', initCatalog);
