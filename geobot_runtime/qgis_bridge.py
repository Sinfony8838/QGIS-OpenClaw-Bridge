from __future__ import annotations

import json
import socket
import subprocess
from typing import Any, Dict


class QgisBridgeClient:
    def __init__(self, host: str = "127.0.0.1", port: int = 5555, timeout: int = 30):
        self.host = host
        self.port = port
        self.timeout = timeout

    def _recv_exact(self, sock: socket.socket, size: int) -> bytes:
        buffer = b""
        while len(buffer) < size:
            chunk = sock.recv(size - len(buffer))
            if not chunk:
                raise ConnectionError("Socket closed before full response was received")
            buffer += chunk
        return buffer

    def call(self, tool_name: str, **tool_params: Any) -> Dict[str, Any]:
        payload = json.dumps({"tool_name": tool_name, "tool_params": tool_params}).encode("utf-8")
        with socket.create_connection((self.host, self.port), timeout=self.timeout) as sock:
            sock.sendall(len(payload).to_bytes(4, "big") + payload)
            message_length = int.from_bytes(self._recv_exact(sock, 4), "big")
            return json.loads(self._recv_exact(sock, message_length).decode("utf-8"))

    def health(self) -> Dict[str, Any]:
        try:
            response = self.call("ping")
            if response.get("status") == "success":
                return {
                    "reachable": True,
                    "response": response,
                    "health_mode": "ping",
                }

            message = str(response.get("message", ""))
            if "Unknown tool: ping" in message:
                fallback = self.call("get_layers")
                return {
                    "reachable": isinstance(fallback, dict),
                    "response": fallback,
                    "health_mode": "fallback:get_layers",
                    "warning": "Plugin does not expose ping yet; reachability verified via get_layers.",
                }

            return {
                "reachable": False,
                "response": response,
                "health_mode": "ping",
            }
        except Exception as exc:
            return {
                "reachable": False,
                "error": str(exc),
            }

    def focus_window(self) -> Dict[str, Any]:
        try:
            command = """
Add-Type @'
using System;
using System.Runtime.InteropServices;
public static class WinApi {
  [DllImport("user32.dll")]
  public static extern bool ShowWindowAsync(IntPtr hWnd, int nCmdShow);
  [DllImport("user32.dll")]
  public static extern bool SetForegroundWindow(IntPtr hWnd);
}
'@;
$process = Get-Process | Where-Object {
  $_.MainWindowHandle -ne 0 -and ($_.ProcessName -like 'qgis*' -or $_.MainWindowTitle -like '*QGIS*')
} | Select-Object -First 1;
if (-not $process) {
  throw 'QGIS window not found';
}
[WinApi]::ShowWindowAsync([IntPtr]$process.MainWindowHandle, 9) | Out-Null;
Start-Sleep -Milliseconds 120;
if (-not [WinApi]::SetForegroundWindow([IntPtr]$process.MainWindowHandle)) {
  throw 'Failed to bring QGIS window to foreground';
}
Write-Output 'OK'
""".strip()

            completed = subprocess.run(
                ["powershell", "-NoProfile", "-Command", command],
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )

            if completed.returncode != 0:
                raw_message = completed.stderr.strip() or completed.stdout.strip() or ""
                lowered = raw_message.lower()
                if "qgis window not found" in lowered:
                    return {
                        "ok": False,
                        "message": "未找到正在运行的 QGIS 窗口，请先打开 QGIS。",
                        "raw_message": raw_message,
                    }
                return {
                    "ok": False,
                    "message": raw_message or "Failed to focus QGIS",
                }

            return {"ok": True, "message": "已切换到 QGIS 窗口。"}
        except Exception as exc:
            return {"ok": False, "message": str(exc)}
