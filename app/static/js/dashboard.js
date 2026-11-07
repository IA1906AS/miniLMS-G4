'use strict';

const dashboardRoles = {
    ADMIN: {
        eyebrow:'ĐIỀU HÀNH HỆ THỐNG', title:'Mọi thứ trong tầm quản lý.', description:'Theo dõi người dùng, quản lý khóa học và nắm bắt hoạt động trên toàn hệ thống.',
        primary:['Quản lý người dùng','/admin/users'], courseTitle:'Khóa học trong hệ thống',
        stats:[['users','Người dùng','Toàn hệ thống'],['courses','Khóa học','Đang được quản lý'],['instructors','Giảng viên','Tài khoản giảng viên'],['locked','Tài khoản khóa','Cần kiểm tra khi cần']],
        actions:[['◎','Quản lý người dùng','Phân quyền và trạng thái tài khoản','/admin/users'],['▦','Quản lý khóa học','Giảng viên, ghi danh và tài liệu','/catalog'],['≡','Nhật ký hoạt động','Kiểm tra các sự kiện hệ thống','/admin/audit']],
        tip:['Giữ hệ thống vận hành tốt','Kiểm tra nhật ký định kỳ và chuyển khóa học trước khi thay đổi vai trò giảng viên.']
    },
    INSTRUCTOR: {
        eyebrow:'KHÔNG GIAN GIẢNG DẠY', title:'Một ngày giảng dạy hiệu quả.', description:'Quản lý lớp học, chuẩn bị bài giảng và đồng hành cùng sinh viên của bạn.',
        primary:['Vào lớp giảng dạy','/catalog'], courseTitle:'Lớp bạn phụ trách',
        stats:[['courses','Lớp giảng dạy','Do bạn phụ trách'],['students','Sinh viên','Không tính trùng giữa các lớp'],['grading','Bài cần chấm','Bài nộp chưa có điểm'],['assignments','Bài tập','Trong các lớp của bạn']],
        actions:[['▦','Quản lý lớp học','Tài liệu, bài tập và thông báo','/catalog'],['↗','Cập nhật điểm','Điểm tổng kết theo môn','/grades'],['◉','Hồ sơ giảng viên','Giới thiệu và thông tin cá nhân','/account#profile-section']],
        tip:['Đồng hành cùng lớp học','Đăng thông báo tại chi tiết khóa học để sinh viên nắm được lịch học và yêu cầu mới.']
    },
    STUDENT: {
        eyebrow:'HÀNH TRÌNH HỌC TẬP', title:'Sẵn sàng cho một bước tiến mới?', description:'Tiếp tục khóa học, hoàn thành bài tập và theo dõi những điều mới từ lớp của bạn.',
        primary:['Khám phá khóa học','/catalog'], courseTitle:'Khóa học bạn tham gia',
        stats:[['courses','Khóa đang học','Đã ghi danh'],['pending','Bài chưa nộp','Còn trong hạn nộp'],['submissions','Bài đã nộp','Trong các khóa đang học'],['announcements','Thông báo lớp','Trong các khóa đang học']],
        actions:[['▦','Vào khóa học','Tài liệu, bài tập và diễn đàn','/catalog'],['↗','Kết quả học tập','Xem điểm các môn của bạn','/grades'],['◉','Hồ sơ của tôi','Cập nhật thông tin và ảnh đại diện','/account#profile-section']],
        tip:['Một chút mỗi ngày','Ưu tiên bài có hạn nộp gần nhất. Mở khóa học để làm bài kiểm tra và xem nhận xét của giảng viên.']
    }
};

function dashElement(tag, className, text) {
    const element = document.createElement(tag);
    if (className) element.className = className;
    if (text !== undefined) element.textContent = text;
    return element;
}

function dashboardEmpty(container, title, text, link) {
    const empty = dashElement('div','empty-state');
    empty.append(dashElement('span','empty-icon','◫'),dashElement('h3','',title),dashElement('p','',text));
    if (link) { const a = dashElement('a','text-link','Đến khóa học →'); a.href=link; empty.appendChild(a); }
    container.appendChild(empty);
}

async function loadDashboard() {
    $('dashboard-retry').hidden = true;
    if (!token()) { window.location.replace('/login'); return; }
    try {
        const data = await api('/api/dashboard',{auth:true});
        const config = dashboardRoles[data.user.role];
        showWorkspace(data.user);
        $('dashboard-eyebrow').textContent = config.eyebrow;
        $('dashboard-heading').textContent = config.title;
        $('dashboard-description').textContent = config.description;
        $('workspace-page-title').textContent = 'Tổng quan';
        $('dashboard-primary').textContent = config.primary[0] + ' →';
        $('dashboard-primary').href = config.primary[1];
        $('dashboard-courses-title').textContent = config.courseTitle;
        $('dashboard-tip-title').textContent = config.tip[0];
        $('dashboard-tip-body').textContent = config.tip[1];
        $('dashboard-stats').replaceChildren();
        config.stats.forEach(([key,label,hint],index) => {
            const card = dashElement('a','stat-card');
            const statLinks = {users:'/admin/users',locked:'/admin/users',instructors:'/admin/users',pending:'#dashboard-deadlines-section',announcements:'#dashboard-announcements-section'};
            card.href = statLinks[key] || '/catalog';
            card.setAttribute('aria-label',label + ': ' + String(data.counts[key] ?? 0));
            card.append(dashElement('span','stat-mark mark-' + index,['◫','◎','↗','≡'][index]),
                dashElement('p','stat-label',label),dashElement('strong','stat-value',String(data.counts[key] ?? 0)),dashElement('p','stat-hint',hint));
            $('dashboard-stats').appendChild(card);
        });
        $('dashboard-actions').replaceChildren();
        for (const [icon,title,description,href] of config.actions) {
            const a = dashElement('a','quick-action'); a.href=href;
            const detail = dashElement('span',''); detail.append(dashElement('strong','',title),dashElement('small','',description));
            a.append(dashElement('span','action-icon',icon),detail,dashElement('span','action-arrow','↗'));
            $('dashboard-actions').appendChild(a);
        }
        $('dashboard-courses').replaceChildren();
        if (!data.courses.length) dashboardEmpty($('dashboard-courses'),'Chưa có khóa học',data.user.role === 'STUDENT' ? 'Ghi danh bằng mã khóa học để bắt đầu hành trình.' : 'Tạo khóa học để bắt đầu tổ chức lớp và tài liệu.','/catalog');
        for (const [index,course] of data.courses.entries()) {
            const card = dashElement('article','dashboard-course');
            const banner = dashElement('div','course-cover cover-' + index%3);
            banner.append(dashElement('span','', ['◫','◈','▦'][index%3]), dashElement('small','',data.user.role === 'STUDENT' ? 'ĐÃ GHI DANH' : 'KHÓA HỌC'));
            const detail = dashElement('div','course-content');
            detail.append(dashElement('p','course-owner',course.instructorName),dashElement('h3','',course.title));
            detail.append(dashElement('p','course-meta',`${course.students} sinh viên · ${course.materials} tài liệu`));
            const a = dashElement('a','course-open','Mở khóa học →'); a.href='/catalog?course='+encodeURIComponent(course.id);
            detail.appendChild(a); card.append(banner,detail); $('dashboard-courses').appendChild(card);
        }
        const isAdmin = data.user.role === 'ADMIN';
        $('dashboard-activity-section').hidden = !isAdmin;
        $('dashboard-deadlines-section').hidden = isAdmin;
        $('dashboard-announcements-section').hidden = isAdmin;
        $('dashboard-deadlines-title').textContent = data.user.role === 'STUDENT' ? 'Bài chưa nộp · Hạn gần nhất' : 'Hạn nộp sắp tới của lớp';
        $('dashboard-deadlines').replaceChildren();
        if (!isAdmin && !data.deadlines.length) dashboardEmpty($('dashboard-deadlines'),'Bạn đã cập nhật mọi việc','Chưa có bài tập còn trong hạn cần hiển thị.');
        for (const item of data.deadlines) {
            const li = dashElement('li','deadline-item'); const a=dashElement('a','',item.title);
            a.href='/study?course='+encodeURIComponent(item.courseId);
            const text=dashElement('div',''); text.append(a,dashElement('small','',item.courseTitle));
            const date=new Date(item.dueAt); li.append(text,dashElement('time','due-label',date.toLocaleString('vi-VN',{day:'2-digit',month:'2-digit',hour:'2-digit',minute:'2-digit'})));
            $('dashboard-deadlines').appendChild(li);
        }
        $('dashboard-announcements').replaceChildren();
        if (!isAdmin && !data.announcements.length) dashboardEmpty($('dashboard-announcements'),'Chưa có thông báo','Thông báo từ các lớp của bạn sẽ xuất hiện tại đây.');
        for (const item of data.announcements) {
            const li=dashElement('li','announcement-preview');
            const a=dashElement('a','',item.title); a.href='/catalog?course='+encodeURIComponent(item.courseId);
            li.append(dashElement('span','announcement-dot'),a,dashElement('small','',item.courseTitle+' · '+new Date(item.createdAt).toLocaleDateString('vi-VN')));
            $('dashboard-announcements').appendChild(li);
        }
        $('dashboard-activity').replaceChildren();
        const actions={LOGIN:'Đăng nhập',UPDATE_GRADE:'Cập nhật điểm',ADMIN_UPDATE_USER:'Cập nhật người dùng',CREATE_COURSE:'Tạo khóa học',CREATE_ANNOUNCEMENT:'Đăng thông báo',FORUM_CREATE:'Đăng thảo luận'};
        if (isAdmin && !data.activity.length) dashboardEmpty($('dashboard-activity'),'Chưa có hoạt động','Các sự kiện hệ thống sẽ được hiển thị tại đây.');
        for (const item of data.activity) {
            const li=dashElement('li','activity-item');
            const text=dashElement('div',''); text.append(dashElement('strong','',actions[item.action]||item.action),dashElement('small','',(item.actorId||'Chưa xác thực')+' · '+new Date(item.createdAt).toLocaleString('vi-VN')));
            li.append(dashElement('span','activity-dot'),text,dashElement('span','pill '+(item.result==='SUCCESS'?'success':'warning'),item.result==='SUCCESS'?'Thành công':'Cần chú ý'));
            $('dashboard-activity').appendChild(li);
        }
        $('dashboard-status').hidden = true;
        $('dashboard-content').hidden = false;
    } catch (error) {
        if(error.status===401) {sessionStorage.removeItem(TOKEN_KEY);window.location.replace('/login');return;}
        flash($('dashboard-status'),'Chưa thể tải tổng quan. '+translate(error.message),false);
        $('dashboard-retry').hidden = false;
    }
}
$('dashboard-retry').addEventListener('click',loadDashboard);
loadDashboard();
