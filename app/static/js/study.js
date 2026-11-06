'use strict';

const studyCourseId = new URLSearchParams(window.location.search).get('course');
const studyBase = '/courses/' + encodeURIComponent(studyCourseId || '');
let studyUser;
let studyAssignments = [];
let currentAssignment = null;
let assignmentRequest = 0;
let currentQuiz = null;
let quizRequest = 0;
let activeAttempt = null;
let quizAnswers = {};
let quizSaveChain = Promise.resolve();
let quizClock = null;
let quizSubmitting = false;

function studyNode(tag, text, className) {
    const node = document.createElement(tag);
    if (text !== undefined) node.textContent = text;
    if (className) node.className = className;
    return node;
}

function studyButton(text, handler) {
    const button = studyNode('button', text);
    button.type = 'button';
    button.addEventListener('click', async () => {
        button.disabled = true;
        try { await handler(); }
        catch (error) { flash($('study-msg'), translate(error.message), false); }
        finally { button.disabled = false; }
    });
    return button;
}

function studyForm(form, message, handler) {
    form.addEventListener('submit', async (event) => {
        event.preventDefault();
        if (event.submitter) event.submitter.disabled = true;
        try { await handler(); }
        catch (error) { flash(message, translate(error.message), false); }
        finally { if (event.submitter) event.submitter.disabled = false; }
    });
}

async function studyDownload(item) {
    const response = await fetch(item.downloadUrl, {
        headers: { Authorization: 'Bearer ' + token() }, cache: 'no-store'
    });
    if (!response.ok) throw new Error((await response.json()).error);
    const url = URL.createObjectURL(await response.blob());
    const link = studyNode('a');
    link.href = url;
    link.download = item.fileName;
    document.body.appendChild(link);
    link.click();
    link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 10000);
}

async function loadStudyAssignments() {
    studyAssignments = await api(studyBase + '/assignments', { auth: true });
    $('assignment-list').replaceChildren();
    for (const item of studyAssignments) {
        const li = studyNode('li');
        li.appendChild(studyButton(item.title, () => selectAssignment(item.id)));
        $('assignment-list').appendChild(li);
    }
    if (!studyAssignments.length) $('assignment-list').appendChild(studyNode('li', 'Chưa có bài tập.'));
}

async function selectAssignment(id) {
    const requestId = ++assignmentRequest;
    const item = studyAssignments.find(value => value.id === id);
    if (!item) return;
    currentAssignment = item;
    $('assignment-detail').hidden = false;
    $('assignment-detail-title').textContent = item.title;
    $('assignment-detail-description').textContent = item.description || 'Không có mô tả.';
    $('assignment-detail-due').textContent = 'Hạn nộp: ' + new Date(item.dueAt).toLocaleString('vi-VN');
    $('submission-upload').hidden = studyUser.role !== 'STUDENT';
    $('submission-list').replaceChildren();
    const submissions = await api(studyBase + '/assignments/' + encodeURIComponent(id) + '/submissions', { auth: true });
    if (requestId !== assignmentRequest) return;
    if (!submissions.length) $('submission-list').appendChild(studyNode('p', 'Chưa có bài nộp.'));
    for (const submission of submissions) {
        const card = studyNode('section', undefined, 'assessment-submission');
        card.appendChild(studyNode('h4', 'Sinh viên: ' + submission.studentId));
        card.appendChild(studyNode('p', submission.fileName + ' · ' + new Date(submission.submittedAt).toLocaleString('vi-VN')));
        card.appendChild(studyNode('p', 'Điểm: ' + (submission.score === null ? 'Chưa chấm' : submission.score + '/10')));
        card.appendChild(studyNode('p', 'Nhận xét: ' + (submission.feedback || 'Chưa có nhận xét'), 'profile-bio'));
        card.appendChild(studyButton('Tải bài nộp', () => studyDownload(submission)));
        if (studyUser.role === 'INSTRUCTOR') {
            const form = studyNode('form');
            const scoreLabel = studyNode('label', 'Điểm (0–10)');
            const score = studyNode('input');
            score.type = 'number'; score.min = '0'; score.max = '10'; score.step = '0.01'; score.required = true;
            score.value = submission.score ?? '';
            scoreLabel.appendChild(score);
            form.appendChild(scoreLabel);
            const feedbackLabel = studyNode('label', 'Nhận xét');
            const feedback = studyNode('textarea');
            feedback.maxLength = 4000; feedback.value = submission.feedback;
            feedbackLabel.appendChild(feedback);
            form.appendChild(feedbackLabel);
            const button = studyNode('button', 'Lưu điểm và nhận xét');
            button.type = 'submit'; form.appendChild(button);
            const message = studyNode('div', undefined, 'msg');
            message.setAttribute('role', 'status');
            form.appendChild(message);
            studyForm(form, message, async () => {
                await api(studyBase + '/submissions/' + encodeURIComponent(submission.id) + '/grade', {
                    method: 'PUT', auth: true, body: { score: Number(score.value), feedback: feedback.value }
                });
                if (currentAssignment?.id === id) await selectAssignment(id);
                flash($('assignment-detail-msg'), 'Đã lưu điểm và nhận xét.');
            });
            card.appendChild(form);
        }
        $('submission-list').appendChild(card);
    }
}

function addQuizQuestion() {
    if ($('quiz-question-editor').children.length >= 100) return;
    const field = studyNode('fieldset', undefined, 'assessment-question');
    field.appendChild(studyNode('legend', 'Câu hỏi'));
    const label = studyNode('label', 'Nội dung câu hỏi');
    const prompt = studyNode('textarea');
    prompt.className = 'question-prompt'; prompt.maxLength = 2000; prompt.required = true;
    label.appendChild(prompt); field.appendChild(label);
    for (let index = 0; index < 4; index++) {
        const optionLabel = studyNode('label', 'Lựa chọn ' + (index + 1));
        const input = studyNode('input');
        input.className = 'question-choice'; input.maxLength = 500; input.required = true;
        optionLabel.appendChild(input); field.appendChild(optionLabel);
    }
    const correctLabel = studyNode('label', 'Đáp án đúng');
    const correct = studyNode('select');
    correct.className = 'question-correct';
    for (let index = 0; index < 4; index++) {
        const option = studyNode('option', 'Lựa chọn ' + (index + 1));
        option.value = index; correct.appendChild(option);
    }
    correctLabel.appendChild(correct); field.appendChild(correctLabel);
    field.appendChild(studyButton('Bỏ câu hỏi', () => {
        if ($('quiz-question-editor').children.length > 1) field.remove();
    }));
    $('quiz-question-editor').appendChild(field);
}

async function loadStudyQuizzes() {
    const quizzes = await api(studyBase + '/quizzes', { auth: true });
    $('quiz-list').replaceChildren();
    for (const quiz of quizzes) {
        const li = studyNode('li');
        li.appendChild(studyButton(quiz.title, () => selectQuiz(quiz.id)));
        $('quiz-list').appendChild(li);
    }
    if (!quizzes.length) $('quiz-list').appendChild(studyNode('li', 'Chưa có bài trắc nghiệm.'));
}

async function loadQuizAttempts(quiz, requestId) {
    const attempts = await api(studyBase + '/quizzes/' + encodeURIComponent(quiz.id) + '/attempts', { auth: true });
    if (requestId !== quizRequest) return;
    $('quiz-attempt-list').replaceChildren();
    for (const attempt of attempts) {
        const status = { IN_PROGRESS: 'Đang làm', SUBMITTED: 'Đã nộp', EXPIRED: 'Đã hết giờ' }[attempt.status];
        $('quiz-attempt-list').appendChild(studyNode('li', attempt.studentId + ' · ' + status +
            ' · ' + (attempt.score === null ? 'Chưa có điểm' : attempt.score + '/10') +
            ' · ' + new Date(attempt.startedAt).toLocaleString('vi-VN')));
    }
    if (!attempts.length) $('quiz-attempt-list').appendChild(studyNode('li', 'Chưa có lượt làm bài.'));
    const hasActive = attempts.some(item => item.status === 'IN_PROGRESS');
    $('quiz-start').hidden = studyUser.role !== 'STUDENT' || Boolean(activeAttempt) ||
        (!hasActive && attempts.length >= quiz.maxAttempts);
}

async function selectQuiz(id) {
    const requestId = ++quizRequest;
    clearInterval(quizClock); activeAttempt = null;
    $('quiz-answer-form').hidden = true; $('quiz-timer').hidden = true;
    $('quiz-start').hidden = true; $('quiz-detail').hidden = true;
    $('quiz-save-state').textContent = '';
    $('quiz-detail-msg').className = 'msg';
    const quiz = await api(studyBase + '/quizzes/' + encodeURIComponent(id), { auth: true });
    if (requestId !== quizRequest) return;
    currentQuiz = quiz;
    $('quiz-detail-title').textContent = quiz.title;
    $('quiz-detail-info').textContent = quiz.questionCount + ' câu · ' + quiz.durationSeconds / 60 +
        ' phút · Tối đa ' + quiz.maxAttempts + ' lượt';
    $('quiz-teacher-questions').replaceChildren();
    for (const question of quiz.questions || []) {
        $('quiz-teacher-questions').appendChild(studyNode('p', question.prompt +
            '\nĐáp án: ' + question.choices[question.correctIndex], 'profile-bio'));
    }
    $('quiz-detail').hidden = false;
    await loadQuizAttempts(quiz, requestId);
}

function queueQuizAnswers(attemptId, answers) {
    quizSaveChain = quizSaveChain.then(async () => {
        try {
            await api(studyBase + '/quiz-attempts/' + encodeURIComponent(attemptId) + '/answers', {
                method: 'PUT', auth: true, body: { answers }
            });
            if (activeAttempt?.id === attemptId) $('quiz-save-state').textContent = 'Đã lưu đáp án.';
        } catch (error) {
            if (activeAttempt?.id === attemptId) {
                $('quiz-save-state').textContent = 'Chưa lưu được đáp án: ' + translate(error.message);
            }
        }
    });
}

function renderQuizAttempt(attempt) {
    activeAttempt = attempt; quizAnswers = { ...attempt.answers };
    $('quiz-answer-questions').replaceChildren();
    $('quiz-start').hidden = true; $('quiz-answer-form').hidden = false;
    $('quiz-timer').hidden = false;
    for (const [number, question] of attempt.questions.entries()) {
        const field = studyNode('fieldset', undefined, 'assessment-question assessment-options');
        field.appendChild(studyNode('legend', (number + 1) + '. ' + question.prompt));
        question.choices.forEach((choice, index) => {
            const label = studyNode('label');
            const radio = studyNode('input');
            radio.type = 'radio'; radio.name = question.id; radio.value = index;
            radio.checked = quizAnswers[question.id] === index;
            radio.addEventListener('change', () => {
                if (activeAttempt?.id !== attempt.id) return;
                quizAnswers[question.id] = index;
                $('quiz-save-state').textContent = 'Đang lưu đáp án…';
                queueQuizAnswers(attempt.id, { ...quizAnswers });
            });
            label.append(radio, document.createTextNode(choice)); field.appendChild(label);
        });
        $('quiz-answer-questions').appendChild(field);
    }
    clearInterval(quizClock);
    const offset = attempt.serverNow * 1000 - Date.now();
    const tick = () => {
        if (activeAttempt?.id !== attempt.id) return;
        const remaining = Math.max(0, Math.ceil((Date.parse(attempt.expiresAt) - Date.now() - offset) / 1000));
        $('quiz-timer').textContent = 'Còn lại: ' + Math.floor(remaining / 60) + ':' + String(remaining % 60).padStart(2, '0');
        if (!remaining) {
            $('quiz-answer-questions').querySelectorAll('input').forEach(input => { input.disabled = true; });
            if (!quizSubmitting) finishQuizAttempt(false).catch(error => {
                flash($('quiz-detail-msg'), translate(error.message), false);
            });
        }
    };
    quizClock = setInterval(tick, 1000); tick();
}

async function finishQuizAttempt(manual) {
    if (!activeAttempt || quizSubmitting) return;
    quizSubmitting = true;
    const attemptId = activeAttempt.id;
    const answers = { ...quizAnswers };
    try {
        await quizSaveChain;
        const result = await api(studyBase + '/quiz-attempts/' + encodeURIComponent(attemptId) + '/submit', {
            method: 'POST', auth: true, body: { answers: manual ? answers : {} }
        });
        if (activeAttempt?.id === attemptId) {
            clearInterval(quizClock); activeAttempt = null;
            $('quiz-answer-form').hidden = true; $('quiz-timer').hidden = true;
            flash($('quiz-detail-msg'), (result.status === 'EXPIRED' ? 'Đã hết giờ. ' : 'Đã nộp bài. ') +
                'Điểm: ' + result.score + '/10.');
            await loadQuizAttempts(currentQuiz, quizRequest);
        }
        await loadAssessmentResults();
    } finally {
        quizSubmitting = false;
        // The server retains the attempt if a network error prevents submission.
    }
}

async function loadAssessmentResults() {
    if (studyUser.role !== 'STUDENT') return;
    const results = await api(studyBase + '/results', { auth: true });
    $('assessment-results').replaceChildren();
    for (const item of results.assignments) {
        const submission = item.submission;
        $('assessment-results').appendChild(studyNode('p', 'Bài tập: ' + item.title + ' · ' +
            (!submission ? 'Chưa nộp' : submission.score === null ? 'Chờ chấm' : submission.score + '/10') +
            (submission?.feedback ? '\nNhận xét: ' + submission.feedback : ''), 'profile-bio'));
    }
    for (const item of results.quizzes) {
        $('assessment-results').appendChild(studyNode('p', 'Trắc nghiệm: ' + item.title +
            ' · Điểm cao nhất: ' + (item.bestScore === null ? 'Chưa có' : item.bestScore + '/10') +
            ' · Lượt: ' + item.attemptsUsed + '/' + item.maxAttempts));
    }
    if (!results.assignments.length && !results.quizzes.length) {
        $('assessment-results').appendChild(studyNode('p', 'Chưa có bài tập hoặc bài trắc nghiệm.'));
    }
}

async function initStudy() {
    if (!token()) { window.location.replace('/login'); return; }
    if (!studyCourseId) { flash($('study-msg'), 'Hãy chọn khóa học từ trang Khóa học.', false); return; }
    try {
        studyUser = await api('/me', { auth: true });
        const course = await api(studyBase, { auth: true });
        if (!course.canAccessMaterials) throw new Error('FORBIDDEN');
        $('study-title').textContent = course.title + ' · Bài tập và trắc nghiệm';
        $('assignment-list-panel').hidden = false; $('quiz-list-panel').hidden = false;
        const teacher = studyUser.role === 'INSTRUCTOR' && course.canManage;
        $('assignment-create-panel').hidden = !teacher;
        $('quiz-create-panel').hidden = !teacher;
        $('assessment-results-panel').hidden = studyUser.role !== 'STUDENT';
        if (teacher) { addQuizQuestion(); $('quiz-add-question').addEventListener('click', addQuizQuestion); }
        studyForm($('assignment-create'), $('assignment-create-msg'), async () => {
            const due = new Date($('assignment-due').value);
            if (!Number.isFinite(due.getTime())) throw new Error('VALIDATION_ERROR');
            const item = await api(studyBase + '/assignments', {
                method: 'POST', auth: true, body: { title: $('assignment-title').value,
                    description: $('assignment-description').value, dueAt: due.toISOString() }
            });
            $('assignment-create').reset(); await loadStudyAssignments(); await selectAssignment(item.id);
            flash($('assignment-create-msg'), 'Đã tạo bài tập.');
        });
        studyForm($('submission-upload'), $('assignment-detail-msg'), async () => {
            if (!currentAssignment) return;
            const id = currentAssignment.id;
            const file = $('submission-file').files[0];
            if (!file) return;
            if (file.size > 10 * 1024 * 1024) throw new Error('Bài nộp vượt quá 10 MB.');
            const body = new FormData(); body.append('file', file);
            await api(studyBase + '/assignments/' + encodeURIComponent(id) + '/submissions', {
                method: 'POST', auth: true, body
            });
            $('submission-file').value = '';
            if (currentAssignment?.id === id) await selectAssignment(id);
            await loadAssessmentResults(); flash($('assignment-detail-msg'), 'Đã nộp bài.');
        });
        studyForm($('quiz-create'), $('quiz-create-msg'), async () => {
            const questions = [...$('quiz-question-editor').children].map(field => ({
                prompt: field.querySelector('.question-prompt').value,
                choices: [...field.querySelectorAll('.question-choice')].map(input => input.value),
                correctIndex: Number(field.querySelector('.question-correct').value)
            }));
            const quiz = await api(studyBase + '/quizzes', { method: 'POST', auth: true, body: {
                title: $('quiz-title').value, durationSeconds: Number($('quiz-duration').value) * 60,
                maxAttempts: Number($('quiz-limit').value), questions
            }});
            $('quiz-create').reset(); $('quiz-question-editor').replaceChildren(); addQuizQuestion();
            await loadStudyQuizzes(); await selectQuiz(quiz.id); flash($('quiz-create-msg'), 'Đã tạo bài trắc nghiệm.');
        });
        $('quiz-start').addEventListener('click', async () => {
            if (!currentQuiz) return;
            const id = currentQuiz.id;
            $('quiz-start').disabled = true;
            try {
                const attempt = await api(studyBase + '/quizzes/' + encodeURIComponent(id) + '/attempts', {
                    method: 'POST', auth: true
                });
                if (currentQuiz?.id === id) renderQuizAttempt(attempt);
            } catch (error) { flash($('quiz-detail-msg'), translate(error.message), false); }
            finally { $('quiz-start').disabled = false; }
        });
        studyForm($('quiz-answer-form'), $('quiz-detail-msg'), () => finishQuizAttempt(true));
        await Promise.all([loadStudyAssignments(), loadStudyQuizzes(), loadAssessmentResults()]);
    } catch (error) {
        flash($('study-msg'), translate(error.message), false);
    }
}

document.addEventListener('DOMContentLoaded', initStudy);
