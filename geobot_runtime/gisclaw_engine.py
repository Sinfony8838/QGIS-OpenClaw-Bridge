from __future__ import annotations

from typing import Any, Dict, Optional

from .assistant_engine import AssistantEngine
from .config import RuntimeConfig


class GISclawEngine(AssistantEngine):
    name = "gisclaw"
    mode = "planned"

    def __init__(self, config: RuntimeConfig):
        self.config = config

    def health(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "mode": self.mode,
            "configured": True,
            "reachable": False,
            "capabilities": ["planned-replacement"],
            "message": "GISclaw is the planned long-term engine but is not implemented in this build",
        }

    def chat(self, project_id: str, message: str, context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        raise NotImplementedError("GISclaw is not implemented in this build yet")
