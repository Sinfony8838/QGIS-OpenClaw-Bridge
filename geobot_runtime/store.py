from __future__ import annotations

import json
import threading
from dataclasses import asdict
from pathlib import Path
from typing import Any, Dict, List, Optional

from .models import ArtifactRecord, JobRecord, ProjectRecord, build_workflow_stages, utc_now


class RuntimeStore:
    def __init__(self, state_file: Path):
        self.state_file = state_file
        self._lock = threading.RLock()
        self.projects: Dict[str, ProjectRecord] = {}
        self.jobs: Dict[str, JobRecord] = {}
        self.artifacts: Dict[str, ArtifactRecord] = {}
        self._load()

    def _load(self) -> None:
        if not self.state_file.exists():
            return
        payload = json.loads(self.state_file.read_text(encoding="utf-8"))
        self.projects = {
            project_id: ProjectRecord(**data) for project_id, data in payload.get("projects", {}).items()
        }
        self.jobs = {
            job_id: JobRecord(**data) for job_id, data in payload.get("jobs", {}).items()
        }
        self.artifacts = {
            artifact_id: ArtifactRecord(**data) for artifact_id, data in payload.get("artifacts", {}).items()
        }

    def _save(self) -> None:
        payload = {
            "projects": {project_id: project.to_dict() for project_id, project in self.projects.items()},
            "jobs": {job_id: job.to_dict() for job_id, job in self.jobs.items()},
            "artifacts": {artifact_id: artifact.to_dict() for artifact_id, artifact in self.artifacts.items()},
        }
        self.state_file.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def create_project(self, name: Optional[str] = None, metadata: Optional[Dict[str, Any]] = None) -> ProjectRecord:
        with self._lock:
            project = ProjectRecord.create(name=name, metadata=metadata)
            self.projects[project.project_id] = project
            self._save()
            return project

    def get_project(self, project_id: str) -> Optional[ProjectRecord]:
        with self._lock:
            return self.projects.get(project_id)

    def create_job(
        self,
        project_id: str,
        job_type: str,
        title: str,
        request: Optional[Dict[str, Any]] = None,
        workflow_type: str = "",
        stages: Optional[Dict[str, Dict[str, str]]] = None,
    ) -> JobRecord:
        with self._lock:
            if project_id not in self.projects:
                raise KeyError(f"Unknown project: {project_id}")
            job = JobRecord.create(
                project_id=project_id,
                job_type=job_type,
                title=title,
                workflow_type=workflow_type,
                request=request,
                stages=stages or build_workflow_stages(),
            )
            self.jobs[job.job_id] = job
            project = self.projects[project_id]
            project.job_ids.append(job.job_id)
            project.updated_at = utc_now()
            self._save()
            return job

    def set_job_status(self, job_id: str, status: str, result: Optional[Dict[str, Any]] = None, error: str = "") -> JobRecord:
        with self._lock:
            job = self.jobs[job_id]
            job.status = status
            job.updated_at = utc_now()
            if result is not None:
                job.result = result
            if error:
                job.error = error
            self._save()
            return job

    def append_job_step(self, job_id: str, title: str, detail: str, status: str = "info") -> JobRecord:
        with self._lock:
            job = self.jobs[job_id]
            job.steps.append(
                {
                    "title": title,
                    "detail": detail,
                    "status": status,
                    "timestamp": utc_now(),
                }
            )
            job.updated_at = utc_now()
            self._save()
            return job

    def update_job_stage(
        self,
        job_id: str,
        stage_name: str,
        status: str,
        summary: str = "",
        detail: str = "",
    ) -> JobRecord:
        with self._lock:
            job = self.jobs[job_id]
            if stage_name not in job.stages:
                job.stages[stage_name] = {
                    "status": status,
                    "summary": summary,
                    "detail": detail,
                }
            else:
                job.stages[stage_name]["status"] = status
                job.stages[stage_name]["summary"] = summary
                job.stages[stage_name]["detail"] = detail
            job.updated_at = utc_now()
            self._save()
            return job

    def register_artifact(self, project_id: str, job_id: str, artifact_type: str, title: str, path: str, metadata: Optional[Dict[str, Any]] = None) -> ArtifactRecord:
        with self._lock:
            artifact = ArtifactRecord.create(
                project_id=project_id,
                job_id=job_id,
                artifact_type=artifact_type,
                title=title,
                path=path,
                metadata=metadata,
            )
            self.artifacts[artifact.artifact_id] = artifact
            self.jobs[job_id].artifact_ids.append(artifact.artifact_id)
            self.jobs[job_id].updated_at = utc_now()
            project = self.projects[project_id]
            project.artifact_ids.append(artifact.artifact_id)
            project.updated_at = utc_now()
            self._save()
            return artifact

    def get_job(self, job_id: str) -> Optional[JobRecord]:
        with self._lock:
            return self.jobs.get(job_id)

    def get_artifact(self, artifact_id: str) -> Optional[ArtifactRecord]:
        with self._lock:
            return self.artifacts.get(artifact_id)

    def list_outputs(self, project_id: Optional[str] = None) -> List[Dict[str, Any]]:
        with self._lock:
            artifacts = list(self.artifacts.values())
            if project_id:
                artifacts = [artifact for artifact in artifacts if artifact.project_id == project_id]
            artifacts.sort(key=lambda artifact: artifact.created_at, reverse=True)
            return [artifact.to_dict() for artifact in artifacts]
