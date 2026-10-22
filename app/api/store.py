import json
from dataclasses import dataclass
from pathlib import Path

import bcrypt

BASE_DIR = Path(__file__).resolve().parent.parent.parent
SEED_PATH = BASE_DIR / "seed.json"


@dataclass
class User:
    id: str
    email: str
    role: str
    password_hash: str


@dataclass
class Course:
    id: str
    title: str
    instructor_id: str


@dataclass
class Enrollment:
    course_id: str
    student_id: str
    score: float


@dataclass
class LoginAttempt:
    failures: int = 0
    locked_until: float = 0


@dataclass
class ResetToken:
    token: str
    user_id: str
    expires_at: float


def load_seed():
    with open(SEED_PATH, encoding="utf-8") as file:
        data = json.load(file)

    users = {}
    users_by_email = {}

    for record in data["users"]:
        user = {key: value for key, value in record.items() if key != "password"}

        password_hash = bcrypt.hashpw(
            record["password"].encode("utf-8"), bcrypt.gensalt(rounds=12)
        )

        user["password_hash"] = password_hash.decode("utf-8")

        users[user["id"]] = user
        users_by_email[user["email"].lower()] = user["id"]

    courses = {course["id"]: dict(course) for course in data["courses"]}

    enrollments = [dict(enrollment) for enrollment in data["enrollments"]]

    return {
        "users": users,
        "users_by_email": users_by_email,
        "courses": courses,
        "enrollments": enrollments,
        "failed_logins": {},
    }
