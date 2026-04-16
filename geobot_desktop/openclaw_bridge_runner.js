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

function extractTextDelta(currentText, baselineText) {
  const current = String(currentText || "");
  const baseline = String(baselineText || "");
  if (!baseline) {
    return current;
  }
  if (!current || current === baseline) {
    return "";
  }
  if (current.startsWith(baseline)) {
    return current.slice(baseline.length);
  }
  const baselineIndex = current.lastIndexOf(baseline);
  if (baselineIndex >= 0) {
    return current.slice(baselineIndex + baseline.length);
  }
  const maxPrefix = Math.min(current.length, baseline.length);
  let prefixLength = 0;
  while (prefixLength < maxPrefix && current[prefixLength] === baseline[prefixLength]) {
    prefixLength += 1;
  }
  return current.slice(prefixLength);
}

function isPlaceholderValue(value) {
  if (value === null || value === undefined) {
    return true;
  }
  const normalized = String(value).trim().toLowerCase();
  return !normalized || normalized === "..." || normalized === "…" || normalized === "<summary>" || normalized === "<path>" || normalized === "tbd" || normalized === "unknown";
}

function sanitizeStructuredResult(structured, exportPath) {
  if (!structured || typeof structured !== "object") {
    return null;
  }
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
  if (isPlaceholderValue(result.request_id)) {
    result.request_id = "";
  }
  const verification = result.verification && typeof result.verification === "object" ? { ...result.verification } : {};
  result.verification = {
    status: isPlaceholderValue(verification.status) ? "" : String(verification.status).trim(),
    checked_layers: Array.isArray(verification.checked_layers) ? verification.checked_layers : [],
    expected_style: verification.expected_style && typeof verification.expected_style === "object" ? verification.expected_style : {},
    observed_style: verification.observed_style && typeof verification.observed_style === "object" ? verification.observed_style : {},
    mismatches: Array.isArray(verification.mismatches) ? verification.mismatches : [],
  };
  return result;
}

function matchesStructuredRequest(structured, requestId) {
  if (!structured) {
    return false;
  }
  const expected = String(requestId || "").trim();
  if (!expected) {
    return true;
  }
  return String(structured.request_id || "").trim() === expected;
}

function isVerifiedStructuredResult(structured, workflowMode) {
  const mode = String(structured?.workflow_type || workflowMode || "").trim().toLowerCase();
  if (mode !== "qgis_only") {
    return true;
  }
  return String(structured?.verification?.status || "").trim().toLowerCase() === "verified";
}

function successStepsForWorkflow(isLessonWorkflow, summary) {
  if (isLessonWorkflow) {
    return [
      { title: "解析教学请求", detail: "已将请求转发到隐藏的教学引擎。", status: "success" },
      { title: "已获取结构化教学蓝图", detail: summary || "已收到最终 GEOBOT_RESULT 结果块。", status: "success" },
    ];
  }
  return [
    { title: "解析 QGIS 请求", detail: "已将请求转发到隐藏的 QGIS 执行引擎。", status: "success" },
    { title: "调用 QGIS", detail: "OpenClaw 已通过 qgis-solver 操作当前 QGIS 项目。", status: "success" },
    { title: "已获取最终结果", detail: summary || "已收到最终结果块。", status: "success" },
  ];
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
      const button = candidates.find((item) => /new session/i.test((item.innerText || item.textContent || "").trim()));
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
        return /send|submit/i.test(label);
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
  const lessonPlanPath = request.lessonPlanPath || "";
  const pptxPath = request.pptxPath || "";
  const timeoutMs = Number(request.timeoutMs || 180000);
  const forceNewSession = request.forceNewSession === true;
  const requiresExport = request.requiresExport === true;
  const requestId = String(request.requestId || "").trim();
  const isLessonWorkflow = ["lesson_ppt", "teacher_flow", "full_flow"].includes(String(request.workflowMode || "").toLowerCase());
  const isQgisOnlyWorkflow = String(request.workflowMode || "").toLowerCase() === "qgis_only";
  const sessionPartition = forceNewSession
    ? `geobot-openclaw-${Date.now()}-${Math.random().toString(16).slice(2)}`
    : "persist:geobot-openclaw";

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
      partition: sessionPartition,
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
        return buildError("写入 OpenClaw 鉴权状态失败", {
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
      return buildError("未找到 OpenClaw 输入框");
    }

    const submit = await submitPrompt(window, prompt);
    if (!submit || !submit.ok) {
      return buildError("向 OpenClaw 提交请求失败");
    }

    await delay(1200);
    const submittedSnapshot = await getPageText(window);
    const submittedBaselineText = (submittedSnapshot && submittedSnapshot.text) || "";

    let stableCount = 0;
    let lastText = "";
    let nudgeSent = false;
    const startAt = Date.now();
    const endAt = Date.now() + timeoutMs;
    while (Date.now() < endAt) {
      const snapshot = await getPageText(window);
      const text = (snapshot && snapshot.text) || "";
      const responseText = extractTextDelta(text, submittedBaselineText);
      const structured = sanitizeStructuredResult(extractResultBlock(responseText), exportPath);
      const matchesRequest = matchesStructuredRequest(structured, requestId);
      const verificationSatisfied = isVerifiedStructuredResult(structured, request.workflowMode);
      const resolvedExportPath = structured && structured.export_path ? structured.export_path : exportPath;
      const exportExists = resolvedExportPath ? fs.existsSync(resolvedExportPath) : false;
      const hasStructuredSuccess = !!(
        structured &&
        matchesRequest &&
        structured.status !== "error" &&
        verificationSatisfied &&
        (structured.summary || structured.notes || structured.export_path)
      );
      if (structured && matchesRequest && structured.status === "error") {
        return buildError(structured.summary || structured.message || "OpenClaw 执行失败", {
          request_id: structured.request_id || requestId,
          export_path: structured.export_path || "",
          template_id: structured.template_id || null,
          notes: structured.notes || "",
          transcript_tail: text.slice(-4000),
        });
      }

      if (hasStructuredSuccess && (!requiresExport || exportExists)) {
        return {
          status: structured.status || "success",
          request_id: structured.request_id || requestId,
          summary: structured.summary || structured.message || structured.assistant_message || "OpenClaw 已完成任务。",
          assistant_message: structured.assistant_message || structured.summary || "",
          export_path: exportExists ? resolvedExportPath : (structured.export_path || ""),
          template_id: structured.template_id || null,
          notes: structured.notes || "",
          workflow_type: structured.workflow_type || request.workflowMode || "",
          stages: structured.stages || {},
          artifacts: structured.artifacts || {},
          verification: structured.verification || {},
          package_contract: structured.package_contract || null,
          lesson_payload: structured.lesson_payload || null,
          slide_contract: structured.slide_contract || [],
          steps: successStepsForWorkflow(isLessonWorkflow, structured.summary || "已收到最终结果块。"),
          transcript_tail: responseText.slice(-4000),
        };
      }

      if (text === lastText) {
        stableCount += 1;
      } else {
        stableCount = 0;
        lastText = text;
      }

      const elapsedMs = Date.now() - startAt;
      const recentText = (responseText || text).slice(-12000);
      if (!nudgeSent && !hasStructuredSuccess && stableCount >= 4 && elapsedMs >= 12000 && shouldSendExecutionNudge(recentText)) {
        await submitPrompt(
          window,
          isLessonWorkflow
            ? "Do not greet, do not ask questions, and do not start a fresh conversation. Execute the existing GeoBot request now through lesson_ppt and return the required GEOBOT_RESULT block when finished."
            : "Do not greet, do not ask questions, and do not start a fresh conversation. Execute the existing GeoBot request now through qgis-solver and return the required GEOBOT_RESULT block when finished."
        );
        nudgeSent = true;
        stableCount = 0;
        await delay(1500);
        continue;
      }

      if (!isQgisOnlyWorkflow && exportPath && fs.existsSync(exportPath) && stableCount >= 3) {
        return {
          status: "success",
          summary: "OpenClaw 已完成任务并生成地图导出结果。",
          export_path: exportPath,
          template_id: null,
          notes: "未检测到结构化结果块，但预期导出文件已生成。",
          steps: [
            { title: "解析 QGIS 请求", detail: "已将请求转发到隐藏的 QGIS 执行引擎。", status: "success" },
            { title: "调用 QGIS", detail: "OpenClaw 已通过 qgis-solver 操作当前 QGIS 项目。", status: "success" },
            { title: "检测到导出结果", detail: "已生成预期的导出文件。", status: "success" },
          ],
          transcript_tail: text.slice(-4000),
        };
      }

      await delay(1500);
    }

    const lessonPlanExists = lessonPlanPath && fs.existsSync(lessonPlanPath);
    const pptxExists = pptxPath && fs.existsSync(pptxPath);
    if (isLessonWorkflow && (lessonPlanExists || pptxExists)) {
      const artifacts = {};
      if (lessonPlanExists) {
        artifacts.lesson_plan = {
          artifact_type: "lesson_plan",
          title: "Lesson Plan",
          path: lessonPlanPath,
        };
      }
      if (pptxExists) {
        artifacts.pptx = {
          artifact_type: "pptx",
          title: "Teaching Slides",
          path: pptxPath,
        };
      }
      return {
        status: "success",
        summary: lessonPlanExists && pptxExists
          ? "Lesson plan and PPT files were created, but OpenClaw timed out before returning the final result block."
          : lessonPlanExists
          ? "Lesson plan was created, but OpenClaw timed out before the PPT workflow completed."
          : "PPT file was created, but OpenClaw timed out before the lesson workflow returned the final result block.",
        assistant_message: lessonPlanExists && pptxExists
          ? "Lesson plan and PPT were generated, but OpenClaw timed out before returning the final result block."
          : lessonPlanExists
          ? "Lesson plan was generated, but the PPT workflow timed out before returning the final result block."
          : "PPT was generated, but the lesson workflow timed out before returning the final result block.",
        export_path: "",
        template_id: null,
        notes: "Recovered from OpenClaw timeout by detecting generated lesson artifacts.",
        workflow_type: request.workflowMode || "",
        stages: {
          analysis: { status: "success", summary: "Parsed the teaching request.", detail: "" },
          design: { status: lessonPlanExists ? "success" : "warning", summary: lessonPlanExists ? "Lesson plan file was generated." : "Lesson plan file was not generated before timeout.", detail: "" },
          map: { status: "skipped", summary: "QGIS execution is disabled in lesson_ppt mode.", detail: "" },
          presentation: { status: pptxExists ? "success" : "warning", summary: pptxExists ? "PPT file was generated." : "PPT generation did not finish before timeout.", detail: "" },
        },
        artifacts,
        lesson_payload: null,
        slide_contract: [],
        steps: [
          { title: "Analyzing teaching request", detail: "Forwarded the request to the hidden assistant engine.", status: "success" },
          { title: "Recovered lesson artifacts", detail: lessonPlanExists && pptxExists ? "Detected generated lesson plan and PPT files after timeout." : lessonPlanExists ? "Detected generated lesson plan after timeout." : "Detected generated PPT after timeout.", status: "warning" },
        ],
        transcript_tail: (lastText || "").slice(-4000),
      };
    }

    return buildError("Timed out while waiting for OpenClaw to finish the task", {
      request_id: requestId,
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
