'use strict';

const forumCourse = new URLSearchParams(window.location.search).get('course');
const forumPath = '/courses/' + encodeURIComponent(forumCourse) + '/forum';
let forumActor;
let selectedTopic;
let topicPage = 1;
let commentPage = 1;
let topicRequest = 0;
let commentRequest = 0;

function forumError(error) {
    if (error.status === 401) { window.location.replace('/login'); return; }
    if (error.status === 403) $('forum-panel').hidden = true;
    flash($('forum-msg'), translate(error.message), false);
}

function forumButton(text, action) {
    const button = document.createElement('button');
    button.type = 'button';
    button.textContent = text;
    button.addEventListener('click', async () => {
        button.disabled = true;
        try { await action(); } catch (error) { forumError(error); }
        finally { button.disabled = false; }
    });
    return button;
}

function forumPager(prefix, data) {
    $(prefix + '-page').textContent = `Trang ${data.page} · ${data.total} mục`;
    $(prefix + '-prev').disabled = data.page <= 1;
    $(prefix + '-next').disabled = data.page * data.pageSize >= data.total;
}

async function loadTopics() {
    const requestId = ++topicRequest;
    const data = await api(forumPath + '/topics?page=' + topicPage, {auth: true});
    if (requestId !== topicRequest) return;
    $('forum-topics').replaceChildren();
    if (!data.items.length) {
        const empty = document.createElement('li');
        empty.textContent = 'Chưa có chủ đề.';
        $('forum-topics').appendChild(empty);
    }
    for (const item of data.items) {
        const li = document.createElement('li');
        li.appendChild(forumButton(item.title + ` · ${item.replies} bình luận`, () => openTopic(item.id)));
        $('forum-topics').appendChild(li);
    }
    forumPager('topics', data);
}

function renderPost(item, container) {
    const article = document.createElement('article');
    const heading = document.createElement('h3');
    heading.textContent = item.topicId ? 'Bình luận' : item.title;
    const meta = document.createElement('p');
    meta.className = 'sub';
    meta.textContent = item.authorName + ' · ' + new Date(item.createdAt).toLocaleString('vi-VN') +
        (item.updatedAt !== item.createdAt ? ' · Đã chỉnh sửa' : '');
    const body = document.createElement('p');
    body.className = 'profile-bio';
    body.textContent = item.body;
    article.append(heading, meta, body);
    if (item.canEdit) {
        const editor = document.createElement('form');
        editor.hidden = true;
        const title = document.createElement('input');
        title.value = item.title;
        title.maxLength = 200;
        title.required = !item.topicId;
        title.setAttribute('aria-label', 'Tiêu đề chủ đề');
        if (!item.topicId) editor.appendChild(title);
        const content = document.createElement('textarea');
        content.value = item.body;
        content.maxLength = 10000;
        content.rows = 5;
        content.required = true;
        content.setAttribute('aria-label', 'Nội dung chỉnh sửa');
        const save = document.createElement('button');
        save.type = 'submit';
        save.textContent = 'Lưu';
        editor.append(content, save, forumButton('Hủy', async () => { editor.hidden = true; }));
        editor.addEventListener('submit', async event => {
            event.preventDefault();
            if (save.disabled) return;
            save.disabled = true;
            try {
                const data = {body: content.value.trim()};
                if (!item.topicId) data.title = title.value.trim();
                await api(forumPath + '/posts/' + encodeURIComponent(item.id), {method:'PUT',auth:true,body:data});
                await openTopic(selectedTopic, false);
                await loadTopics();
                flash($('forum-msg'), 'Đã cập nhật nội dung.');
            } catch (error) { forumError(error); }
            finally { save.disabled = false; }
        });
        article.append(forumButton('Sửa', async () => { editor.hidden = !editor.hidden; }),
            forumButton('Xóa', async () => {
                if (!window.confirm(item.topicId ? 'Xóa bình luận của bạn?' : 'Xóa chủ đề và toàn bộ bình luận trong chủ đề?')) return;
                await api(forumPath + '/posts/' + encodeURIComponent(item.id), {method:'DELETE',auth:true});
                if (!item.topicId) { selectedTopic = null; $('forum-detail').hidden = true; }
                else await openTopic(selectedTopic, false);
                await loadTopics();
                flash($('forum-msg'), 'Đã xóa nội dung.');
            }), editor);
    }
    container.appendChild(article);
}

async function openTopic(id, reset = true) {
    selectedTopic = id;
    if (reset) commentPage = 1;
    const requestId = ++commentRequest;
    const [topic, comments] = await Promise.all([
        api(forumPath + '/topics/' + encodeURIComponent(id), {auth:true}),
        api(forumPath + '/topics/' + encodeURIComponent(id) + '/comments?page=' + commentPage, {auth:true})
    ]);
    if (requestId !== commentRequest || selectedTopic !== id) return;
    $('forum-topic').replaceChildren();
    renderPost(topic, $('forum-topic'));
    $('forum-comments').replaceChildren();
    for (const comment of comments.items) {
        const li = document.createElement('li');
        renderPost(comment, li);
        $('forum-comments').appendChild(li);
    }
    forumPager('comments', comments);
    $('forum-detail').hidden = false;
}

function forumForm(id, action) {
    $(id).addEventListener('submit', async event => {
        event.preventDefault();
        const button = $(id).querySelector('button[type="submit"]');
        if (button.disabled) return;
        button.disabled = true;
        try { await action(); } catch (error) { forumError(error); }
        finally { button.disabled = false; }
    });
}

(async function initForum() {
    if (!token()) { window.location.replace('/login'); return; }
    if (!forumCourse) { flash($('forum-msg'), 'Vui lòng mở diễn đàn từ một khóa học.', false); return; }
    try {
        forumActor = await api('/me', {auth:true});
        const course = await api('/courses/' + encodeURIComponent(forumCourse), {auth:true});
        await loadTopics();
        $('forum-title').textContent = 'Diễn đàn · ' + course.title;
        $('forum-panel').hidden = false;
        $('forum-create').hidden = $('forum-reply').hidden = !['STUDENT','INSTRUCTOR'].includes(forumActor.role);
        forumForm('forum-create', async () => {
            const item = await api(forumPath + '/topics', {method:'POST',auth:true,body:{title:$('forum-new-title').value.trim(),body:$('forum-new-body').value.trim()}});
            $('forum-create').reset(); topicPage = 1;
            await loadTopics(); await openTopic(item.id);
            flash($('forum-msg'), 'Đã tạo chủ đề.');
        });
        forumForm('forum-reply', async () => {
            const id = selectedTopic;
            if (!id) return;
            await api(forumPath + '/topics/' + encodeURIComponent(id) + '/comments', {method:'POST',auth:true,body:{body:$('forum-reply-body').value.trim()}});
            if (id !== selectedTopic) return;
            $('forum-reply').reset();
            await openTopic(id); await loadTopics();
            flash($('forum-msg'), 'Đã gửi bình luận.');
        });
        for (const [prefix, delta] of [['topics-prev',-1],['topics-next',1],['comments-prev',-1],['comments-next',1]]) {
            $(prefix).addEventListener('click', () => {
                if (prefix.startsWith('topics')) { topicPage += delta; loadTopics().catch(forumError); }
                else if (selectedTopic) { commentPage += delta; openTopic(selectedTopic,false).catch(forumError); }
            });
        }
    } catch (error) { forumError(error); }
})();
