from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import uuid4


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


WORKFLOW_STAGE_KEYS = ("analysis", "design", "map", "presentation")


def build_workflow_stages(default_status: str = "pending") -> Dict[str, Dict[str, str]]:
    return {
        stage: {
            "status": default_status,
            "summary": "",
            "detail": "",
        }
        for stage in WORKFLOW_STAGE_KEYS
    }


@dataclass
class ArtifactRecord:
    artifact_id: str
    project_id: str
    job_id: str
    artifact_type: str
    title: str
    path: str
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=utc_now)

    @classmethod
    def create(
        cls,
        project_id: str,
        job_id: str,
        artifact_type: str,
        title: str,
        path: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> "ArtifactRecord":
        return cls(
            artifact_id=f"artifact_{uuid4().hex}",
            project_id=project_id,
            job_id=job_id,
            artifact_type=artifact_type,
            title=title,
            path=path,
            metadata=metadata or {},
        )

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class JobRecord:
    job_id: str
    project_id: str
    job_type: str
    title: str
    workflow_type: str = ""
    status: str = "queued"
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)
    request: Dict[str, Any] = field(default_factory=dict)
    result: Dict[str, Any] = field(default_factory=dict)
    error: str = ""
    steps: List[Dict[str, Any]] = field(default_factory=list)
    artifact_ids: List[str] = field(default_factory=list)
    stages: Dict[str, Dict[str, str]] = field(default_factory=build_workflow_stages)

    @classmethod
    def create(
        cls,
        project_id: str,
        job_type: str,
        title: str,
        workflow_type: str = "",
        request: Optional[Dict[str, Any]] = None,
        stages: Optional[Dict[str, Dict[str, str]]] = None,
    ) -> "JobRecord":
        return cls(
            job_id=f"job_{uuid4().hex}",
            project_id=project_id,
            job_type=job_type,
            title=title,
            workflow_type=workflow_type,
            request=request or {},
            stages=stages or build_workflow_stages(),
        )

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ProjectRecord:
    project_id: str
    name: str
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)
    metadata: Dict[str, Any] = field(default_factory=dict)
    job_ids: List[str] = field(default_factory=list)
    artifact_ids: List[str] = field(default_factory=list)

    @classmethod
    def create(cls, name: Optional[str] = None, metadata: Optional[Dict[str, Any]] = None) -> "ProjectRecord":
        project_id = f"project_{uuid4().hex}"
        return cls(
            project_id=project_id,
            name=name or "GeoBot Project",
            metadata=metadata or {},
        )

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
