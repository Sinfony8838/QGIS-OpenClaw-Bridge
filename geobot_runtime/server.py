from __future__ import annotations

import json
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict
from urllib.parse import parse_qs, urlparse

from .runtime import GeoBotRuntime


def create_handler(runtime: GeoBotRuntime):
    class RuntimeRequestHandler(BaseHTTPRequestHandler):
        server_version = "GeoBotRuntime/0.1"

        def do_OPTIONS(self) -> None:
            self.send_response(HTTPStatus.NO_CONTENT)
            self._send_cors_headers()
            self.end_headers()

        def do_GET(self) -> None:
            parsed = urlparse(self.path)
            path = parsed.path
            try:
                if path == "/health":
                    self._write_json(runtime.health())
                elif path == "/showcases/population":
                    self._write_json(runtime.get_population_showcase())
                elif path == "/templates":
                    self._write_json(runtime.list_templates())
                elif path.startswith("/projects/"):
                    project_id = path.split("/", 2)[2]
                    self._write_json(runtime.get_project(project_id))
                elif path.startswith("/jobs/") and path.endswith("/stream"):
                    job_id = path.split("/")[2]
                    self._stream_job(job_id)
                elif path.startswith("/jobs/"):
                    job_id = path.split("/", 2)[2]
                    self._write_json(runtime.get_job(job_id))
                elif path.startswith("/artifacts/"):
                    artifact_id = path.split("/", 2)[2]
                    self._write_json(runtime.get_artifact(artifact_id))
                elif path == "/outputs":
                    query = parse_qs(parsed.query)
                    project_id = query.get("project_id", [None])[0]
                    self._write_json(runtime.list_outputs(project_id=project_id))
                else:
                    self._write_json({"status": "error", "message": "Not found"}, status=HTTPStatus.NOT_FOUND)
            except KeyError as exc:
                self._write_json({"status": "error", "message": str(exc)}, status=HTTPStatus.NOT_FOUND)
            except Exception as exc:
                self._write_json({"status": "error", "message": str(exc)}, status=HTTPStatus.INTERNAL_SERVER_ERROR)

        def do_POST(self) -> None:
            parsed = urlparse(self.path)
            path = parsed.path
            payload = self._read_json_body()
            try:
                if path == "/projects":
                    self._write_json(runtime.create_project(name=payload.get("name"), metadata=payload.get("metadata")))
                elif path == "/chat":
                    self._write_json(
                        runtime.submit_chat(
                            project_id=payload["project_id"],
                            message=payload["message"],
                            task_mode=payload.get("task_mode", ""),
                            presentation_style=payload.get("presentation_style", ""),
                        ),
                        status=HTTPStatus.ACCEPTED,
                    )
                elif path.startswith("/templates/"):
                    template_id = path.split("/", 2)[2]
                    self._write_json(
                        runtime.submit_template(
                            project_id=payload["project_id"],
                            template_id=template_id,
                            payload=payload.get("payload", {}),
                        ),
                        status=HTTPStatus.ACCEPTED,
                    )
                elif path == "/qgis/focus":
                    self._write_json(runtime.focus_qgis())
                else:
                    self._write_json({"status": "error", "message": "Not found"}, status=HTTPStatus.NOT_FOUND)
            except KeyError as exc:
                self._write_json({"status": "error", "message": f"Missing required field: {exc}"}, status=HTTPStatus.BAD_REQUEST)
            except ValueError as exc:
                self._write_json({"status": "error", "message": str(exc)}, status=HTTPStatus.BAD_REQUEST)
            except Exception as exc:
                self._write_json({"status": "error", "message": str(exc)}, status=HTTPStatus.INTERNAL_SERVER_ERROR)

        def log_message(self, format: str, *args: Any) -> None:
            return

        def _read_json_body(self) -> Dict[str, Any]:
            length = int(self.headers.get("Content-Length", "0"))
            if length == 0:
                return {}
            return json.loads(self.rfile.read(length).decode("utf-8"))

        def _write_json(self, payload: Dict[str, Any], status: HTTPStatus = HTTPStatus.OK) -> None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self._send_cors_headers()
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _send_cors_headers(self) -> None:
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")

        def _stream_job(self, job_id: str) -> None:
            self.send_response(HTTPStatus.OK)
            self._send_cors_headers()
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "keep-alive")
            self.end_headers()

            last_version = None
            started = time.time()
            while time.time() - started < 180:
                job = runtime.get_job(job_id)
                version = job["updated_at"]
                if version != last_version:
                    self.wfile.write(b"event: job\n")
                    self.wfile.write(f"data: {json.dumps(job, ensure_ascii=False)}\n\n".encode("utf-8"))
                    self.wfile.flush()
                    last_version = version
                if job["status"] in {"completed", "failed"}:
                    break
                time.sleep(1)

    return RuntimeRequestHandler


def run_server(runtime: GeoBotRuntime) -> ThreadingHTTPServer:
    handler = create_handler(runtime)
    server = ThreadingHTTPServer((runtime.config.host, runtime.config.port), handler)
    return server
