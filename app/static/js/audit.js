'use strict';
let auditPage = 1;
let auditRequest = 0;
let auditAction = '';
let auditActor = '';

function auditError(error) {
    if (error.status === 401) { window.location.replace('/login'); return; }
    if (error.status === 403) $('audit-panel').hidden = true;
    flash($('audit-msg'), translate(error.message), false);
}

async function loadAudit() {
    const requestId = ++auditRequest;
    const data = await api('/admin/api/audit?' + new URLSearchParams({page:auditPage,action:auditAction,actorId:auditActor}), {auth:true});
    if (requestId !== auditRequest) return;
    $('audit-list').replaceChildren();
    if (!data.items.length) {
        const empty = document.createElement('li'); empty.textContent = 'Không có sự kiện phù hợp.';
        $('audit-list').appendChild(empty);
    }
    for (const item of data.items) {
        const li = document.createElement('li');
        const summary = document.createElement('p');
        summary.textContent = `${new Date(item.createdAt).toLocaleString('vi-VN')} · ${item.actorId || 'Chưa xác thực'} · ${item.action} · ${item.result}`;
        const detail = document.createElement('p'); detail.className = 'profile-bio';
        detail.textContent = item.resource + (Object.keys(item.details).length ? '\n' + JSON.stringify(item.details) : '');
        li.append(summary, detail); $('audit-list').appendChild(li);
    }
    $('audit-page').textContent = `Trang ${data.page} · ${data.total} sự kiện`;
    $('audit-prev').disabled = data.page <= 1;
    $('audit-next').disabled = data.page * data.pageSize >= data.total;
}

(async function initAudit() {
    if (!token()) { window.location.replace('/login'); return; }
    try {
        const me = await api('/me', {auth:true});
        if (me.role !== 'ADMIN') { flash($('audit-msg'), 'Chỉ quản trị viên được xem nhật ký.', false); return; }
        $('audit-panel').hidden = false;
        $('audit-filter').addEventListener('submit', event => {
            event.preventDefault(); auditPage = 1;
            auditAction = $('audit-action').value.trim(); auditActor = $('audit-actor').value.trim();
            loadAudit().catch(auditError);
        });
        for (const [id,delta] of [['audit-prev',-1],['audit-next',1]]) $(id).addEventListener('click', () => { auditPage += delta; loadAudit().catch(auditError); });
        await loadAudit();
    } catch (error) { auditError(error); }
})();
