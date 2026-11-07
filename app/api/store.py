from dataclasses import dataclass
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent.parent
SEED_PATH = BASE_DIR / "seed.json"


@dataclass
class User:
    id: str
    email: str
    role: str
    password_hash: str
    token_version: int = 0
    full_name: str = ""
    bio: str = ""
    contact: str = ""
    avatar_filename: str = ""
    is_locked: bool = False


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
