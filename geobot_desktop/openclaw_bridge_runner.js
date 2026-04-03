const { BrowserWindow } = require("electron");
const fs = require("fs");

function delay(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function buildError(message, extra = {}) {
  return {
    status: "error",
    message,
    ...extra,
  };
}

function extractResultBlock(text) {
  if (!text) {
    return null;
  }
  const startMarker = "GEOBOT_RESULT_START";
  const endMarker = "GEOBOT_RESULT_END";
  let cursor = 0;
  let parsed = null;
  while (cursor < text.length) {
    const startIndex = text.indexOf(startMarker, cursor);
    if (startIndex < 0) {
      break;
    }
    const jsonStart = startIndex + startMarker.length;
    const endIndex = text.indexOf(endMarker, jsonStart);
    if (endIndex < 0) {
      break;
    }
    let raw = text.slice(jsonStart, endIndex).trim();
    if (raw.startsWith("```json")) {
      raw = raw.slice("```json".length).trim();
    } else if (raw.startsWith("```")) {
      raw = raw.slice(3).trim();
    }
    if (raw.endsWith("```")) {
      raw = raw.slice(0, -3).trim();
    }
    try {
      parsed = JSON.parse(raw);
    } catch (error) {
    }
    cursor = endIndex + endMarker.length;
  }
  return parsed;
}

function isPlaceholderValue(value) {
  if (value === null || value === undefined) {
    return true;
  }
  const normalized = String(value).trim().toLowerCase();
  return !normalized || normalized === "..." || normalized === "…" || normalized === "<summary>" || normalized === "<path>" || normalized === "tbd" || normalized === "unknown";
}

function sanitizeStructuredResult(structured, exportPath) {
  const result = { ...(structured || {}) };
  if (isPlaceholderValue(result.summary)) {
    result.summary = "";
  }
  if (isPlaceholderValue(result.notes)) {
    result.notes = "";
  }
  if (isPlaceholderValue(result.template_id)) {
    result.template_id = null;
  }
  if (isPlaceholderValue(result.export_path)) {
    result.export_path = "";
  }
  return result;
}

function normalizeGatewayStorageUrl(rawUrl, fallbackUrl = "") {
  const value = (rawUrl || fallbackUrl || "").trim();
  if (!value) {
    return "";
  }
  try {
    const url = fallbackUrl ? new URL(value, fallbackUrl) : new URL(value);
    const pathname = url.pathname === "/" ? "" : (url.pathname || "").replace(/\/+$/, "");
    return `${url.protocol}//${url.host}${pathname}`;
  } catch (error) {
    return value.replace(/\/+$/, "");
  }
}

function deriveGatewayVariants(gatewayUrl, chatUrl) {
  const normalizedHttp = normalizeGatewayStorageUrl(gatewayUrl, chatUrl);
  let normalizedWs = normalizedHttp;
  try {
    const url = new URL(normalizedHttp || chatUrl);
    if (url.protocol === "http:") {
      url.protocol = "ws:";
    } else if (url.protocol === "https:") {
      url.protocol = "wss:";
    }
    normalizedWs = normalizeGatewayStorageUrl(url.toString(), chatUrl);
  } catch (error) {
  }

  const variants = [normalizedWs, normalizedHttp].filter(Boolean);
  return {
    primaryGatewayUrl: normalizedWs || normalizedHttp || "",
    alternateGatewayUrls: Array.from(new Set(variants)),
  };
}

async function waitForCondition(fn, timeoutMs, intervalMs = 600) {
  const endAt = Date.now() + timeoutMs;
  let lastValue = null;
  while (Date.now() < endAt) {
    lastValue = await fn();
    if (lastValue && lastValue.ok) {
      return lastValue;
    }
    await delay(intervalMs);
  }
  return lastValue;
}

async function pageEval(window, fnSource, ...args) {
  const payload = JSON.stringify(args);
  return window.webContents.executeJavaScript(`(${fnSource})(...${payload})`, true);
}

async function clickNewSession(window) {
  return pageEval(
    window,
    function () {
      const visible = (element) => {
        if (!element) return false;
        const style = window.getComputedStyle(element);
        return style.display !== "none" && style.visibility !== "hidden" && (element.offsetWidth > 0 || element.offsetHeight > 0 || element.getClientRects().length > 0);
      };
      const candidates = Array.from(document.querySelectorAll("button,[role='button']")).filter(visible);
      const button = candidates.find((item) => /new session|新建会话|新会话/i.test((item.innerText || item.textContent || "").trim()));
      if (!button) {
        return { ok: true, clicked: false };
      }
      button.click();
      return { ok: true, clicked: true };
    }.toString()
  );
}

async function waitForComposer(window, timeoutMs) {
  return waitForCondition(
    () =>
      pageEval(
        window,
        function () {
          const visible = (element) => {
            if (!element) return false;
            const style = window.getComputedStyle(element);
            return style.display !== "none" && style.visibility !== "hidden" && (element.offsetWidth > 0 || element.offsetHeight > 0 || element.getClientRects().length > 0);
          };
          const candidates = Array.from(
            document.querySelectorAll("textarea,input[type='text'],[contenteditable='true'],[role='textbox']")
          ).filter(visible);
          return {
            ok: candidates.length > 0,
            count: candidates.length,
          };
        }.toString()
      ),
    timeoutMs
  );
}

async function submitPrompt(window, prompt) {
  return pageEval(
    window,
    function (text) {
      const visible = (element) => {
        if (!element) return false;
        const style = window.getComputedStyle(element);
        return style.display !== "none" && style.visibility !== "hidden" && (element.offsetWidth > 0 || element.offsetHeight > 0 || element.getClientRects().length > 0);
      };

      const candidates = Array.from(
        document.querySelectorAll("textarea,input[type='text'],[contenteditable='true'],[role='textbox']")
      ).filter(visible);
      const input = candidates[0];
      if (!input) {
        return { ok: false, reason: "composer_not_found" };
      }

      const assignValue = (element, value) => {
        if (element.tagName === "TEXTAREA" || element.tagName === "INPUT") {
          const proto = element.tagName === "TEXTAREA" ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
          const descriptor = Object.getOwnPropertyDescriptor(proto, "value");
          if (descriptor && descriptor.set) {
            descriptor.set.call(element, value);
          } else {
            element.value = value;
          }
        } else {
          element.textContent = value;
        }
      };

      assignValue(input, text);
      input.dispatchEvent(new Event("input", { bubbles: true }));
      input.dispatchEvent(new Event("change", { bubbles: true }));
      input.focus();

      const down = new KeyboardEvent("keydown", { key: "Enter", code: "Enter", keyCode: 13, which: 13, bubbles: true, cancelable: true });
      const up = new KeyboardEvent("keyup", { key: "Enter", code: "Enter", keyCode: 13, which: 13, bubbles: true, cancelable: true });
      input.dispatchEvent(down);
      input.dispatchEvent(up);

      const buttons = Array.from(document.querySelectorAll("button,[role='button']")).filter(visible);
      const sendButton = buttons.find((item) => {
        const label = [item.innerText, item.textContent, item.getAttribute("aria-label"), item.getAttribute("title")]
          .filter(Boolean)
          .join(" ");
        return /send|发送|提交/i.test(label);
      });
      if (sendButton) {
        sendButton.click();
      }

      return { ok: true };
    }.toString(),
    prompt
  );
}

async function getPageText(window) {
  return pageEval(
    window,
    function () {
      return {
        ok: true,
        text: document.body ? document.body.innerText || "" : "",
      };
    }.toString()
  );
}

function shouldSendExecutionNudge(text) {
  const value = String(text || "").toLowerCase();
  if (!value) {
    return false;
  }
  return (
    value.includes("a new session was started via /new or /reset") ||
    value.includes("what would you like to do") ||
    value.includes("what should i call you") ||
    value.includes("tell me about yourself")
  );
}

async function seedOpenClawControlSettings(window, gatewayUrl, alternateGatewayUrls, gatewayToken) {
  return pageEval(
    window,
    function (primaryGatewayUrl, fallbackGatewayUrls, token) {
      try {
        const SETTINGS_KEY = "openclaw.control.settings.v1";
        const TOKEN_KEY = "openclaw.control.token.v1";
        const TOKEN_PREFIX = "openclaw.control.token.v1:";
        const sessionStore = window.sessionStorage || sessionStorage;
        const trim = (value) => (typeof value === "string" ? value.trim() : "");
        const normalize = (value) => {
          const raw = trim(value);
          if (!raw) {
            return "default";
          }
          try {
            const base = `${location.protocol}//${location.host}${location.pathname || "/"}`;
            const url = new URL(raw, base);
            const pathname = url.pathname === "/" ? "" : (url.pathname || "").replace(/\/+$/, "");
            return `${url.protocol}//${url.host}${pathname}`;
          } catch (error) {
            return raw.replace(/\/+$/, "");
          }
        };

        const existingSettings = (() => {
          try {
            const raw = localStorage.getItem(SETTINGS_KEY);
            return raw ? JSON.parse(raw) : {};
          } catch (error) {
            return {};
          }
        })();

        const normalizedGatewayUrls = Array.from(
          new Set([primaryGatewayUrl].concat(fallbackGatewayUrls || []).map(normalize).filter(Boolean))
        );

        const settings = {
          theme: "system",
          sessionKey: "main",
          lastActiveSessionKey: "main",
          chatFocusMode: false,
          chatShowThinking: true,
          splitRatio: 0.6,
          navCollapsed: false,
          navGroupsCollapsed: {},
          ...existingSettings,
          gatewayUrl: primaryGatewayUrl,
          token: trim(token),
          sessionKey: trim(existingSettings.sessionKey) || "main",
          lastActiveSessionKey: trim(existingSettings.lastActiveSessionKey) || trim(existingSettings.sessionKey) || "main",
        };

        localStorage.setItem(SETTINGS_KEY, JSON.stringify(settings));
        sessionStore.removeItem(TOKEN_KEY);
        for (const normalizedGatewayUrl of normalizedGatewayUrls) {
          if (trim(token)) {
            sessionStore.setItem(`${TOKEN_PREFIX}${normalizedGatewayUrl}`, trim(token));
          } else {
            sessionStore.removeItem(`${TOKEN_PREFIX}${normalizedGatewayUrl}`);
          }
        }

        return {
          ok: true,
          primaryGatewayUrl,
          normalizedGatewayUrls,
        };
      } catch (error) {
        return {
          ok: false,
          message: error && error.message ? error.message : String(error),
        };
      }
    }.toString(),
    gatewayUrl,
    alternateGatewayUrls,
    gatewayToken
  );
}

async function runOpenClawAutomation(request) {
  const gatewayUrl = request.gatewayUrl || "";
  const chatUrl = request.chatUrl || `${gatewayUrl.replace(/\/$/, "")}/chat`;
  const gatewayToken = request.gatewayToken || "";
  const prompt = request.prompt || "";
  const exportPath = request.exportPath || "";
  const timeoutMs = Number(request.timeoutMs || 180000);
  const forceNewSession = request.forceNewSession === true;
  const requiresExport = request.requiresExport === true;

  if (!chatUrl || !prompt) {
    return buildError("Missing chatUrl or prompt");
  }

  const window = new BrowserWindow({
    show: false,
    width: 1280,
    height: 900,
    webPreferences: {
      contextIsolation: true,
      sandbox: false,
      backgroundThrottling: false,
      partition: "persist:geobot-openclaw",
    },
  });

  try {
    const gatewayVariants = deriveGatewayVariants(gatewayUrl, chatUrl);
    const loadOptions = gatewayToken ? { extraHeaders: `Authorization: Bearer ${gatewayToken}\n` } : undefined;
    await window.loadURL(chatUrl, loadOptions);
    await delay(1500);

    if (gatewayToken) {
      const seeded = await seedOpenClawControlSettings(
        window,
        gatewayVariants.primaryGatewayUrl,
        gatewayVariants.alternateGatewayUrls,
        gatewayToken
      );
      if (!seeded || !seeded.ok) {
        return buildError("Failed to seed OpenClaw authentication state", {
          details: seeded && seeded.message ? seeded.message : "",
        });
      }
      await pageEval(
        window,
        function () {
          window.location.reload();
          return { ok: true };
        }.toString()
      );
      await delay(2000);
    }

    if (forceNewSession) {
      await clickNewSession(window);
      await delay(1000);
    }

    const composer = await waitForComposer(window, 30000);
    if (!composer || !composer.ok) {
      return buildError("OpenClaw chat composer was not found");
    }

    const submit = await submitPrompt(window, prompt);
    if (!submit || !submit.ok) {
      return buildError("Failed to submit prompt to OpenClaw");
    }

    let stableCount = 0;
    let lastText = "";
    let nudgeSent = false;
    const startAt = Date.now();
    const endAt = Date.now() + timeoutMs;
    while (Date.now() < endAt) {
      const snapshot = await getPageText(window);
      const text = (snapshot && snapshot.text) || "";
      const structured = sanitizeStructuredResult(extractResultBlock(text), exportPath);
      const resolvedExportPath = structured && structured.export_path ? structured.export_path : exportPath;
      const exportExists = resolvedExportPath ? fs.existsSync(resolvedExportPath) : false;
      const hasStructuredSuccess = !!(structured && structured.status !== "error" && (structured.summary || structured.notes || structured.export_path));
      if (structured && structured.status === "error") {
        return buildError(structured.summary || structured.message || "OpenClaw reported an execution failure", {
          export_path: structured.export_path || "",
          template_id: structured.template_id || null,
          notes: structured.notes || "",
          transcript_tail: text.slice(-4000),
        });
      }

      if (hasStructuredSuccess && (!requiresExport || exportExists)) {
        return {
          status: structured.status || "success",
          summary: structured.summary || structured.message || structured.assistant_message || "OpenClaw completed the task.",
          assistant_message: structured.assistant_message || structured.summary || "",
          export_path: exportExists ? resolvedExportPath : (structured.export_path || ""),
          template_id: structured.template_id || null,
          notes: structured.notes || "",
          workflow_type: structured.workflow_type || request.workflowMode || "",
          stages: structured.stages || {},
          artifacts: structured.artifacts || {},
          steps: [
            { title: "Analyzing teaching request", detail: "Forwarded the request to the hidden assistant engine.", status: "success" },
            { title: "Calling QGIS", detail: "OpenClaw used the QGIS bridge in the background.", status: "success" },
            { title: "Captured final result", detail: structured.summary || "Received the final result block.", status: structured.status === "error" ? "error" : "success" },
          ],
          transcript_tail: text.slice(-4000),
        };
      }

      if (text === lastText) {
        stableCount += 1;
      } else {
        stableCount = 0;
        lastText = text;
      }

      const elapsedMs = Date.now() - startAt;
      const recentText = text.slice(-12000);
      if (!nudgeSent && !hasStructuredSuccess && stableCount >= 4 && elapsedMs >= 12000 && shouldSendExecutionNudge(recentText)) {
        await submitPrompt(
          window,
          request.workflowMode === "teacher_flow"
            ? "Do not greet, do not ask questions, and do not start a fresh conversation. Execute the existing GeoBot request now through teacher_flow and return the required GEOBOT_RESULT block when finished."
            : "Do not greet, do not ask questions, and do not start a fresh conversation. Execute the existing GeoBot request now through qgis-solver and return the required GEOBOT_RESULT block when finished."
        );
        nudgeSent = true;
        stableCount = 0;
        await delay(1500);
        continue;
      }

      if (exportPath && fs.existsSync(exportPath) && stableCount >= 3) {
        return {
          status: "success",
          summary: "OpenClaw completed the task and exported a map artifact.",
          export_path: exportPath,
          template_id: null,
          notes: "No structured result block was detected, but the export file exists.",
          steps: [
            { title: "Analyzing teaching request", detail: "Forwarded the request to the hidden assistant engine.", status: "success" },
            { title: "Calling QGIS", detail: "OpenClaw used the QGIS bridge in the background.", status: "success" },
            { title: "Export detected", detail: "The expected export file was created.", status: "success" },
          ],
          transcript_tail: text.slice(-4000),
        };
      }

      await delay(1500);
    }

    return buildError("Timed out while waiting for OpenClaw to finish the task", {
      transcript_tail: lastText.slice(-4000),
      export_path: exportPath && fs.existsSync(exportPath) ? exportPath : "",
    });
  } catch (error) {
    return buildError(error.message || String(error));
  } finally {
    if (!window.isDestroyed()) {
      window.destroy();
    }
  }
}

module.exports = {
  runOpenClawAutomation,
  buildError,
};
