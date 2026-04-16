const { app, BrowserWindow, ipcMain, shell } = require("electron");
const { spawn } = require("child_process");
const http = require("http");
const path = require("path");
const { runOpenClawAutomation } = require("./openclaw_bridge_runner");

const runtimeHost = process.env.GEOBOT_RUNTIME_HOST || "127.0.0.1";
const runtimePort = process.env.GEOBOT_RUNTIME_PORT || "18999";
const runtimeUrl = process.env.GEOBOT_RUNTIME_URL || `http://${runtimeHost}:${runtimePort}`;
const automationBridgePort = Number(process.env.GEOBOT_AUTOMATION_PORT || "19091");
const repoRoot = path.resolve(__dirname, "..");

let mainWindow = null;
let runtimeProcess = null;
let automationServer = null;

function focusQgisWindow() {
  return new Promise((resolve) => {
    const command = `
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
`.trim();

    const child = spawn("powershell", ["-NoProfile", "-Command", command], {
      windowsHide: true,
    });

    let stdout = "";
    let stderr = "";

    child.stdout.on("data", (chunk) => {
      stdout += chunk.toString("utf8");
    });

    child.stderr.on("data", (chunk) => {
      stderr += chunk.toString("utf8");
    });

    child.on("error", (error) => {
      resolve({
        status: "error",
        message: error.message || "切换到 QGIS 窗口失败。",
      });
    });

    child.on("close", (code) => {
      if (code === 0) {
        resolve({
          status: "success",
          message: "已切换到 QGIS 窗口。",
        });
        return;
      }

      const rawMessage = (stderr || stdout || "").trim();
      const lowered = rawMessage.toLowerCase();
      if (lowered.includes("qgis window not found")) {
        resolve({
          status: "error",
          message: "未找到正在运行的 QGIS 窗口，请先打开 QGIS。",
        });
        return;
      }

      resolve({
        status: "error",
        message: rawMessage || "切换到 QGIS 窗口失败。",
      });
    });
  });
}

function getPythonCommand() {
  const explicit = process.env.GEOBOT_PYTHON;
  if (explicit) {
    return { command: explicit, args: [] };
  }
  if (process.platform === "win32") {
    return { command: "py", args: ["-3"] };
  }
  return { command: "python3", args: [] };
}

function startRuntime() {
  const python = getPythonCommand();
  const args = python.args.concat([
    "-m",
    "geobot_runtime.main",
    "--host",
    runtimeHost,
    "--port",
    String(runtimePort),
  ]);

  runtimeProcess = spawn(python.command, args, {
    cwd: repoRoot,
    env: {
      ...process.env,
      PYTHONPATH: repoRoot,
      GEOBOT_AUTOMATION_BRIDGE_URL: `http://127.0.0.1:${automationBridgePort}`,
    },
    stdio: "inherit",
  });

  runtimeProcess.on("exit", () => {
    runtimeProcess = null;
  });
}

async function waitForRuntime() {
  const timeoutAt = Date.now() + 15000;
  while (Date.now() < timeoutAt) {
    try {
      const response = await fetch(`${runtimeUrl}/health`);
      if (response.ok) {
        return true;
      }
    } catch (error) {
    }
    await new Promise((resolve) => setTimeout(resolve, 500));
  }
  return false;
}

async function isRuntimeUp() {
  try {
    const response = await fetch(`${runtimeUrl}/health`);
    return response.ok;
  } catch (error) {
    return false;
  }
}

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1440,
    height: 920,
    minWidth: 980,
    minHeight: 720,
    backgroundColor: "#eef3f8",
    title: "GeoBot Desktop",
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
    },
  });

  mainWindow.loadFile(path.join(__dirname, "renderer", "index.html"));
}

function startAutomationBridge() {
  automationServer = http.createServer(async (request, response) => {
    if (request.method === "GET" && request.url === "/health") {
      const payload = JSON.stringify({ status: "ok", product: "GeoBot Automation Bridge" });
      response.writeHead(200, { "Content-Type": "application/json; charset=utf-8" });
      response.end(payload);
      return;
    }

    if (request.method === "POST" && request.url === "/openclaw/chat") {
      let raw = "";
      request.on("data", (chunk) => {
        raw += chunk.toString("utf8");
      });
      request.on("end", async () => {
        try {
          const payload = raw ? JSON.parse(raw) : {};
          const result = await runOpenClawAutomation(payload);
          response.writeHead(result.status === "success" ? 200 : 500, {
            "Content-Type": "application/json; charset=utf-8",
          });
          response.end(JSON.stringify(result));
        } catch (error) {
          response.writeHead(500, { "Content-Type": "application/json; charset=utf-8" });
          response.end(JSON.stringify({ status: "error", message: error.message || String(error) }));
        }
      });
      return;
    }

    response.writeHead(404, { "Content-Type": "application/json; charset=utf-8" });
    response.end(JSON.stringify({ status: "error", message: "Not found" }));
  });

  automationServer.listen(automationBridgePort, "127.0.0.1");
}

async function apiFetch(method, route, body) {
  const response = await fetch(`${runtimeUrl}${route}`, {
    method,
    headers: {
      "Content-Type": "application/json",
    },
    body: body ? JSON.stringify(body) : undefined,
  });

  const payload = await response.json();
  if (!response.ok) {
    throw new Error(payload.error || payload.message || `Request failed: ${response.status}`);
  }
  return payload;
}

ipcMain.handle("geobot:health", async () => apiFetch("GET", "/health"));
ipcMain.handle("geobot:get-population-showcase", async () => apiFetch("GET", "/showcases/population"));
ipcMain.handle("geobot:create-project", async (_event, payload) => apiFetch("POST", "/projects", payload || {}));
ipcMain.handle("geobot:get-project", async (_event, projectId) => apiFetch("GET", `/projects/${projectId}`));
ipcMain.handle("geobot:list-templates", async () => apiFetch("GET", "/templates"));
ipcMain.handle("geobot:submit-template", async (_event, templateId, payload) =>
  apiFetch("POST", `/templates/${templateId}`, payload)
);
ipcMain.handle("geobot:submit-chat", async (_event, payload) => apiFetch("POST", "/chat", payload));
ipcMain.handle("geobot:get-job", async (_event, jobId) => apiFetch("GET", `/jobs/${jobId}`));
ipcMain.handle("geobot:get-artifact", async (_event, artifactId) => apiFetch("GET", `/artifacts/${artifactId}`));
ipcMain.handle("geobot:list-outputs", async (_event, projectId) => {
  const route = projectId ? `/outputs?project_id=${encodeURIComponent(projectId)}` : "/outputs";
  return apiFetch("GET", route);
});
ipcMain.handle("geobot:focus-qgis", async () => focusQgisWindow());
ipcMain.handle("geobot:get-runtime-url", async () => runtimeUrl);
ipcMain.handle("geobot:open-path", async (_event, targetPath) => shell.openPath(targetPath));
ipcMain.handle("geobot:show-in-folder", async (_event, targetPath) => {
  shell.showItemInFolder(targetPath);
  return { status: "success" };
});

app.whenReady().then(async () => {
  startAutomationBridge();
  const runtimeAlreadyUp = await isRuntimeUp();
  if (!runtimeAlreadyUp && process.env.GEOBOT_SKIP_RUNTIME_SPAWN !== "1") {
    startRuntime();
  }
  await waitForRuntime();
  createWindow();
});

app.on("window-all-closed", () => {
  if (automationServer) {
    automationServer.close();
    automationServer = null;
  }
  if (runtimeProcess) {
    runtimeProcess.kill();
  }
  if (process.platform !== "darwin") {
    app.quit();
  }
});
