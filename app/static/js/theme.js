'use strict';

// Run before styles load so the selected palette is applied without a flash.
(function () {
    let theme = 'dark';
    try {
        const saved = localStorage.getItem('lms_theme');
        if (saved === 'light' || saved === 'dark') theme = saved;
    } catch (_) { /* Storage can be disabled by the browser. */ }
    document.documentElement.dataset.theme = theme;
    document.addEventListener('DOMContentLoaded', () => {
        const button = document.getElementById('theme-toggle');
        if (!button) return;
        function update() {
            const dark = document.documentElement.dataset.theme === 'dark';
            button.textContent = dark ? '☀ Sáng' : '☾ Tối';
            button.setAttribute('aria-label', dark ? 'Chuyển sang giao diện sáng' : 'Chuyển sang giao diện tối');
            button.title = dark ? 'Đang dùng chế độ tối' : 'Đang dùng chế độ sáng';
        }
        button.addEventListener('click', () => {
            const next = document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark';
            document.documentElement.dataset.theme = next;
            try { localStorage.setItem('lms_theme', next); } catch (_) { /* Keep working without storage. */ }
            update();
        });
        update();
    });
})();
