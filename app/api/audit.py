import json
from datetime import UTC, datetime
from pathlib import Path

from flask import current_app, has_app_context


def make_audit_record(
    actor_id,
    action,
    resource,
    result,
    old_score=None,
    new_score=None,
):
    record = {
        "ts": datetime.now(UTC).isoformat(),
        "actorId": actor_id,
        "action": action,
        "resource": resource,
        "result": result,
    }

    if old_score is not None:
        record["oldScore"] = old_score

    if new_score is not None:
        record["newScore"] = new_score

    return record


def write_audit_file(record):
    """The file is a best-effort mirror of the durable database audit."""
    if not has_app_context():
        return
    try:
        log_path = Path(current_app.config["AUDIT_LOG_PATH"])
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("a", encoding="utf-8") as file:
            file.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError:
        current_app.logger.warning(
            "Unable to write audit file; database audit retained."
        )


def write_audit(actor_id, action, resource, result, old_score=None, new_score=None):
    record = make_audit_record(actor_id, action, resource, result, old_score, new_score)
    current_app.extensions["lms_store"].record_audit(record)
    write_audit_file(record)
