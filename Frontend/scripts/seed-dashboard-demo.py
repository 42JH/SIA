"""Fill the local SIA SQLite database with deterministic dashboard demo data.

Does not change Backend source. Targets the DB files the running 8080 process
actually reads (relative jdbc:sqlite:sia.db next to Backend cwd).
"""

from __future__ import annotations

import json
import math
import os
import random
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path


DEMO_PREFIX = "dashboard-demo-"
random.seed(106)

DEFAULT_DBS = [
    Path(r"C:\Users\SSAFY\Desktop\새 폴더\S15P21D106\Backend\sia.db"),
    Path(r"C:\Users\SSAFY\Desktop\프로젝트\S15P21D106\Backend\sia.db"),
    Path(os.environ.get("APPDATA", "")) / "SIA" / "sia.db",
]


def timestamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]


def seed(db_path: Path) -> tuple[int, int]:
    connection = sqlite3.connect(db_path)
    connection.execute("PRAGMA foreign_keys = ON")
    now = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)

    with connection:
        connection.execute("DELETE FROM usage_event WHERE event_uid LIKE ?", (f"{DEMO_PREFIX}%",))
        connection.execute("DELETE FROM tool_call WHERE reason = 'DASHBOARD_DEMO'")

        event_number = 0
        tool_names = {row[0] for row in connection.execute("SELECT name FROM tool")}
        app_targets = list(connection.execute("SELECT id, app_key FROM app_target WHERE enabled = 1 ORDER BY id"))

        def add_event(when: datetime, kind: str, *, action: str | None = None,
                      latency: int | None = None, accuracy: float | None = None,
                      complexity: str | None = None, payload: dict | None = None) -> None:
            nonlocal event_number
            event_number += 1
            connection.execute(
                """INSERT INTO usage_event
                   (event_uid, session_id, profile_id, received_at, kind, action, context,
                    latency_ms, accuracy, complexity, payload)
                   VALUES (?, NULL, NULL, ?, ?, ?, NULL, ?, ?, ?, ?)""",
                (
                    f"{DEMO_PREFIX}{event_number:06d}", timestamp(when), kind, action,
                    latency, accuracy, complexity,
                    json.dumps(payload or {"demo": True}, ensure_ascii=False),
                ),
            )

        for days_ago in range(400, -1, -1):
            day = now - timedelta(days=days_ago)
            seasonal = math.sin(days_ago / 21) * 0.035
            weekday_bonus = 2 if day.weekday() < 5 else 0

            for index in range(3 + weekday_bonus + random.randrange(3)):
                accuracy = min(.99, max(.72, .90 + seasonal + random.uniform(-.055, .055)))
                add_event(day.replace(hour=8 + index * 2 % 12), "voice", action="recognize", accuracy=accuracy)

            for index in range(2 + weekday_bonus + random.randrange(3)):
                accuracy = min(.99, max(.68, .86 - seasonal / 2 + random.uniform(-.07, .06)))
                add_event(day.replace(hour=9 + index * 2 % 11), "gesture", action="recognize", accuracy=accuracy)

            add_event(day.replace(hour=11), "gaze", action="track", accuracy=min(.99, .88 + random.uniform(-.05, .05)))

            for complexity, base_latency, count in (("SIMPLE", 420, 2), ("COMPLEX", 1280, 1)):
                for index in range(count + random.randrange(2)):
                    age = 1 + days_ago / 260
                    weekend = 1.38 if day.weekday() >= 5 else (1.16 if day.weekday() == 4 else 1.0)
                    month_wave = 1 + 0.32 * math.sin((day.month - 1) / 12 * 2 * math.pi)
                    latency = max(90, int(base_latency * age * weekend * month_wave + random.gauss(0, 70)))
                    add_event(day.replace(hour=13 + index), "command", action="execute", latency=latency, complexity=complexity)

            if app_targets and "app.launch" in tool_names:
                launches = 1 + weekday_bonus + random.randrange(3)
                for index in range(launches):
                    target_id, app_key = app_targets[(days_ago + index) % len(app_targets)]
                    connection.execute(
                        """INSERT INTO tool_call
                           (session_id, app_target_id, tool_name, ts, args_json, caller, outcome, reason, latency_ms)
                           VALUES (NULL, ?, 'app.launch', ?, ?, ?, 'EXECUTED', 'DASHBOARD_DEMO', ?)""",
                        (
                            target_id,
                            timestamp(day.replace(hour=10 + index * 2)),
                            json.dumps({"appRef": f"app:{app_key}"}),
                            "GESTURE" if index % 2 else "LLM",
                            random.randint(180, 620),
                        ),
                    )

    usage_count = connection.execute("SELECT COUNT(*) FROM usage_event WHERE event_uid LIKE ?", (f"{DEMO_PREFIX}%",)).fetchone()[0]
    launch_count = connection.execute("SELECT COUNT(*) FROM tool_call WHERE reason = 'DASHBOARD_DEMO'").fetchone()[0]
    connection.close()
    return usage_count, launch_count


def main() -> None:
    requested = [Path(item) for item in sys.argv[1:]] or DEFAULT_DBS
    seeded = 0
    for db_path in requested:
        if not db_path or not db_path.exists():
            print(f"SKIP missing {db_path}")
            continue
        usage_count, launch_count = seed(db_path)
        seeded += 1
        print(f"Seeded {usage_count} usage events and {launch_count} app launches into {db_path}")
    if not seeded:
        raise SystemExit("No sia.db files were found to seed.")


if __name__ == "__main__":
    main()
