
-- BANG NGUOI DUNG
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    full_name TEXT NOT NULL,
    email TEXT NOT NULL COLLATE NOCASE UNIQUE,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'STUDENT'
        CHECK (role IN ('ADMIN', 'INSTRUCTOR', 'STUDENT')),
    created_at TEXT NOT NULL DEFAULT (
        strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
    )
);

-- BANG TOKEN DAT LAI MAT KHAU
CREATE TABLE IF NOT EXISTS password_reset_tokens (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    token_hash TEXT NOT NULL UNIQUE,
    expires_at INTEGER NOT NULL,
    used_at INTEGER,
    FOREIGN KEY (user_id)
        REFERENCES users(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_password_reset_user
ON password_reset_tokens(user_id);


-- BANG MON HOC
CREATE TABLE IF NOT EXISTS courses (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    instructor_id INTEGER NOT NULL,

    FOREIGN KEY (instructor_id)
        REFERENCES users(id)
);


-- BANG GHI DANH VA DIEM
CREATE TABLE IF NOT EXISTS enrollments (
    course_id TEXT NOT NULL,
    student_id INTEGER NOT NULL,
    score REAL NOT NULL
        CHECK (score >= 0 AND score <= 10),

    PRIMARY KEY (course_id, student_id),

    FOREIGN KEY (course_id)
        REFERENCES courses(id),

    FOREIGN KEY (student_id)
        REFERENCES users(id)
);
