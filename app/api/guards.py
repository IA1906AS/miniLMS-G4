from functools import wraps

from flask import current_app, g

from app.api.errors import (
    Forbidden,
    NotFound,
    Unauthenticated,
)


def require_role(*roles):
    def decorator(func):

        @wraps(func)
        def wrapper(*args, **kwargs):

            actor = getattr(g, "actor", None)

            if actor is None:
                raise Unauthenticated()

            store = current_app.extensions["lms_store"]

            # Kiem tra mon hoc ton tai truoc
            course_id = kwargs.get("course_id")

            if course_id is not None:
                course_exists = (
                    course_id in store["courses"]
                    if isinstance(store, dict)
                    else store.get_course(course_id) is not None
                )
                if not course_exists:
                    raise NotFound()

            # Kiem tra vai tro nguoi dung
            if actor["role"] not in roles:
                raise Forbidden()

            return func(*args, **kwargs)

        return wrapper

    return decorator
