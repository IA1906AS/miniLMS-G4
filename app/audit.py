import json
from datetime import UTC, datetime
from pathlib import Path

from flask import current_app


def write_audit(
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

    log_path = Path(current_app.config["AUDIT_LOG_PATH"])

    log_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    with log_path.open("a", encoding="utf-8") as file:
        file.write(json.dumps(record, ensure_ascii=False) + "\n")
