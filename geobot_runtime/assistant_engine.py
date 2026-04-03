from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, Optional


class AssistantEngine(ABC):
    name = "assistant"
    mode = "unconfigured"

    @abstractmethod
    def health(self) -> Dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def chat(self, project_id: str, message: str, context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        raise NotImplementedError

    def cancel(self, job_id: str) -> Dict[str, Any]:
        return {
            "status": "error",
            "message": f"{self.name} does not support cancellation yet",
            "job_id": job_id,
        }
