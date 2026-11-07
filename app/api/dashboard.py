"""Role-scoped overview; aggregate only data the current actor can access."""

import time

from flask import Blueprint, current_app, g, jsonify

bp = Blueprint("dashboard", __name__)


@bp.get("/api/dashboard")
def overview():
    store = current_app.extensions["lms_store"]
    user = store.get_user(g.actor["id"])
    role = user.role
    with store._connect() as conn:
        courses = conn.execute(
            "SELECT c.*, u.full_name AS instructor_name, "
            "(SELECT count(*) FROM enrollments e WHERE e.course_id=c.id) AS student_count, "
            "(SELECT count(*) FROM materials m WHERE m.course_id=c.id) AS material_count "
            "FROM courses c LEFT JOIN users u ON u.id=c.instructor_id "
            "WHERE %s='ADMIN' OR (%s='INSTRUCTOR' AND c.instructor_id=%s) OR "
            "(%s='STUDENT' AND EXISTS(SELECT 1 FROM enrollments e WHERE e.course_id=c.id AND e.student_id=%s)) "
            "ORDER BY c.title, c.id",
            (role, role, user.id, role, user.id),
        ).fetchall()
        ids = [item["id"] for item in courses]
        counts = {"courses": len(courses)}
        activity = []
        deadlines = []
        announcements = []
        if role == "ADMIN":
            counts.update(
                conn.execute(
                    "SELECT count(*) AS users, count(*) FILTER(WHERE is_locked) AS locked, "
                    "count(*) FILTER(WHERE role='INSTRUCTOR') AS instructors FROM users"
                ).fetchone()
            )
            activity = [
                {
                    "action": row["action"],
                    "actorId": row["actor_id"],
                    "result": row["result"],
                    "createdAt": row["created_at"].isoformat(),
                }
                for row in conn.execute(
                    "SELECT * FROM audit_events ORDER BY created_at DESC,id DESC LIMIT 6"
                ).fetchall()
            ]
        else:
            counts["announcements"] = conn.execute(
                "SELECT count(*) AS n FROM course_announcements WHERE course_id=ANY(%s)",
                (ids,),
            ).fetchone()["n"]
            announcements = [
                {
                    "id": row["id"],
                    "title": row["title"],
                    "courseTitle": row["course_title"],
                    "courseId": row["course_id"],
                    "createdAt": row["created_at"].isoformat(),
                }
                for row in conn.execute(
                    "SELECT a.*,c.title AS course_title FROM course_announcements a JOIN courses c ON c.id=a.course_id "
                    "WHERE a.course_id=ANY(%s) ORDER BY a.created_at DESC,a.id DESC LIMIT 4",
                    (ids,),
                ).fetchall()
            ]
            params = (ids, user.id, time.time())
            assignments = conn.execute(
                "SELECT a.id,a.course_id,a.data,c.title AS course_title, "
                "EXISTS(SELECT 1 FROM submissions s WHERE s.parent_id=a.id AND s.student_id=%s) AS submitted "
                "FROM assignments a JOIN courses c ON c.id=a.course_id WHERE a.course_id=ANY(%s) "
                "AND (a.data->>'deadline')::double precision > %s ORDER BY (a.data->>'deadline')::double precision,a.id",
                (params[1], params[0], params[2]),
            ).fetchall()
            pending = [
                item
                for item in assignments
                if role == "INSTRUCTOR" or not item["submitted"]
            ]
            deadlines = [
                {
                    "id": item["id"],
                    "title": item["data"]["title"],
                    "courseId": item["course_id"],
                    "courseTitle": item["course_title"],
                    "dueAt": item["data"]["dueAt"],
                }
                for item in pending[:5]
            ]
            if role == "INSTRUCTOR":
                counts["students"] = conn.execute(
                    "SELECT count(DISTINCT student_id) AS n FROM enrollments WHERE course_id=ANY(%s)",
                    (ids,),
                ).fetchone()["n"]
                counts["grading"] = conn.execute(
                    "SELECT count(*) AS n FROM submissions WHERE course_id=ANY(%s) AND (data->>'score') IS NULL",
                    (ids,),
                ).fetchone()["n"]
                counts["assignments"] = conn.execute(
                    "SELECT count(*) AS n FROM assignments WHERE course_id=ANY(%s)",
                    (ids,),
                ).fetchone()["n"]
            else:
                counts["pending"] = len(pending)
                counts["submissions"] = conn.execute(
                    "SELECT count(*) AS n FROM submissions WHERE course_id=ANY(%s) AND student_id=%s",
                    (ids, user.id),
                ).fetchone()["n"]
    result = {
        "user": {
            "id": user.id,
            "email": user.email,
            "fullName": user.full_name,
            "role": role,
        },
        "counts": counts,
        "courses": [
            {
                "id": item["id"],
                "title": item["title"],
                "instructorName": item["instructor_name"] or item["instructor_id"],
                "students": item["student_count"],
                "materials": item["material_count"],
            }
            for item in courses[:6]
        ],
        "deadlines": deadlines,
        "announcements": announcements,
        "activity": activity,
    }
    response = jsonify(result)
    response.headers["Cache-Control"] = "private, no-store"
    return response
