from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime
from typing import Any

from app.missions.plans import compatibility, compile_mission_item_int, mission_runtime_id
from app.models import Mission, MissionRevision


def build_deployment_package(
    mission: Mission,
    revision: MissionRevision,
    *,
    deployment_id: uuid.UUID,
    created_at: datetime,
    preflight: dict[str, Any],
) -> dict[str, Any]:
    """Freeze the persisted revision and current safety evidence into one handoff artifact."""

    compat = compatibility(revision.plan_json or {})
    wire = (
        compile_mission_item_int(revision.plan_json or {})
        if compat.get("wire_ready")
        else None
    )
    if wire is not None:
        wire["mission_id"] = mission_runtime_id(wire)
    return {
        "schema_version": 1,
        "kind": "M3_CLOUD_MISSION_HANDOFF",
        "deployment_id": str(deployment_id),
        "created_at": created_at.isoformat(),
        "mission": {
            "id": str(mission.id),
            "survey_id": str(mission.survey_id) if mission.survey_id else None,
            "name": mission.name,
            "kind": mission.kind,
            "source": mission.source,
            "status": mission.status,
        },
        "revision": {
            "version": revision.version,
            "plan_sha256": revision.plan_sha256,
            "item_count": revision.item_count,
            "plan": revision.plan_json,
        },
        "target": {
            "aircraft_sn": mission.aircraft_sn,
            "preferred_executor": mission.preferred_executor,
        },
        "compatibility": compat,
        "preflight": preflight,
        "wire": wire,
        "handoff": {
            "protocol": "MAVLINK_MISSION",
            "wire_ready": bool(compat.get("wire_ready")),
            "upload_enabled": False,
            "execution_enabled": False,
            "frame_policy": (
                "EXPLICIT_PER_ITEM"
                if compat.get("wire_ready")
                else "UNRESOLVED"
            ),
            "note": (
                "This is an immutable handoff/audit package, not a flight command. "
                "Wire-ready includes logical MISSION_ITEM_INT fields with runtime target IDs. "
                "Null float params must be encoded as IEEE NaN. M3-Cloud still does not "
                "upload or execute this plan."
            ),
        },
    }


def deployment_sha256(package: dict[str, Any]) -> str:
    encoded = json.dumps(
        package,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
