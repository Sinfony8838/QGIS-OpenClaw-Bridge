const state = {
  projectId: null,
  activeJobId: null,
  pollTimer: null,
  shownJobMessages: new Set(),
  latestHealth: null,
  latestJobSnapshot: null,
  selectedArtifactId: null,
  templates: [],
  isStatusPanelOpen: false,
};

const STAGE_LABELS = {
  analysis: "需求解析",
  design: "教学设计",
  map: "QGIS 地图",
  presentation: "PPT 生成",
};

function $(selector) {
  return document.querySelector(selector);
}

function createElement(tag, className, text) {
  const el = document.createElement(tag);
  if (className) el.className = className;
  if (text !== undefined) el.textContent = text;
  return el;
}

function humanizeStatus(status) {
  return {
    queued: "排队中",
    pending: "待处理",
    running: "执行中",
    completed: "已完成",
    success: "成功",
    failed: "失败",
    error: "异常",
    warning: "警告",
    skipped: "已跳过",
    info: "处理中",
  }[status] || status || "未知";
}

function toneForStatus(status) {
  if (["success", "completed"].includes(status)) return "success";
  if (["failed", "error"].includes(status)) return "error";
  if (["warning", "skipped"].includes(status)) return "warning";
  if (["running"].includes(status)) return "running";
  if (["queued", "pending"].includes(status)) return "queued";
  return "neutral";
}

function appendChat(role, text) {
  if (!text) return;
  const log = $("#chat-log");
  const last = log.lastElementChild;
  if (last && last.classList.contains(role) && last.textContent === text) return;
  const item = createElement("div", `chat-item ${role}`, text);
  log.appendChild(item);
  log.scrollTop = log.scrollHeight;
}

function buildAssistantMessage(result) {
  if (!result) return "";
  const parts = [result.assistant_message, result.summary, result.notes].filter(Boolean);
  return [...new Set(parts)].join("\n\n");
}

function setStatusDrawerOpen(isOpen) {
  state.isStatusPanelOpen = isOpen;
  document.body.classList.toggle("status-drawer-open", isOpen);
  $("#status-drawer").setAttribute("aria-hidden", String(!isOpen));
  $("#toggle-status-button").setAttribute("aria-expanded", String(isOpen));
  $("#status-drawer-backdrop").hidden = !isOpen;
}

function renderStatusPills() {
  const container = $("#status-pills");
  container.innerHTML = "";
  if (!state.latestHealth) return;
  const health = state.latestHealth;
  const items = [
    { label: "Runtime", value: "Online", tone: "ok" },
    { label: "QGIS", value: health.qgis?.reachable ? "已连接" : "未连接", tone: health.qgis?.reachable ? "ok" : "warn" },
    {
      label: "引擎",
      value: health.assistant_engine?.reachable ? "已就绪" : "降级",
      tone: health.assistant_engine?.reachable ? "ok" : "neutral",
    },
  ];
  if (state.latestJobSnapshot) {
    items.push({
      label: "任务",
      value: humanizeStatus(state.latestJobSnapshot.status),
      tone: toneForStatus(state.latestJobSnapshot.status),
    });
  }
  items.forEach((item) => {
    const node = createElement("div", `status-pill ${item.tone}`);
    node.append(createElement("span", "status-pill-label", item.label), createElement("span", "status-pill-value", item.value));
    container.appendChild(node);
  });
}

function renderStatusCards() {
  const container = $("#status-cards");
  container.innerHTML = "";
  const health = state.latestHealth;
  if (!health) return;
  const cards = [
    ["Runtime 服务", health.runtime?.api || "", health.runtime?.outputs || "", "ok"],
    ["QGIS 插件", health.qgis?.reachable ? "已连接" : "未连接", health.qgis?.message || health.qgis?.error || "", health.qgis?.reachable ? "ok" : "warn"],
    ["QGIS 检测", health.qgis_installation?.detected ? "已检测" : "未检测", health.qgis_installation?.executable || "", health.qgis_installation?.detected ? "ok" : "warn"],
    ["智能引擎", health.assistant_engine?.reachable ? "已就绪" : "降级模式", health.assistant_engine?.name || "", health.assistant_engine?.reachable ? "ok" : "neutral"],
  ];
  cards.forEach(([title, value, meta, tone]) => {
    const card = createElement("article", `status-card ${tone}`);
    card.append(createElement("div", "status-card-title", title), createElement("div", "status-card-value", value), createElement("div", "status-card-meta", meta));
    container.appendChild(card);
  });
}

function renderJobSummary(job) {
  $("#status-toggle-hint").textContent = job ? `${humanizeStatus(job.status)} | ${job.title}` : "系统在线";
  $("#drawer-job-summary").textContent = job ? `${job.title} | ${humanizeStatus(job.status)}` : "系统在线，暂无执行中任务";
  $("#job-steps-meta").textContent = job ? `当前任务：${job.title}` : "暂无执行中任务";
}

function renderJobSteps(job) {
  const container = $("#job-steps");
  container.innerHTML = "";
  const steps = job?.steps || [];
  if (!steps.length) {
    const empty = createElement("div", "empty-state");
    empty.append(createElement("div", "empty-state-title", "暂无执行步骤"), createElement("div", "empty-state-detail", "提交任务后，这里会显示运行时间线。"));
    container.appendChild(empty);
    return;
  }
  steps.forEach((step, index) => {
    const tone = toneForStatus(step.status);
    const node = createElement("div", `job-step ${tone}`);
    const marker = createElement("div", "job-step-marker", String(index + 1).padStart(2, "0"));
    const content = createElement("div", "job-step-content");
    const top = createElement("div", "job-step-top");
    top.append(createElement("div", "job-step-title", step.title || "执行步骤"), createElement("div", "job-step-badge", humanizeStatus(step.status)));
    content.append(top, createElement("div", "job-step-detail", step.detail || ""));
    node.append(marker, content);
    container.appendChild(node);
  });
}

function renderWorkflowStages(job) {
  const container = $("#workflow-stages");
  container.innerHTML = "";
  const stages = job?.result?.stages || job?.stages || {};
  Object.entries(STAGE_LABELS).forEach(([key, label]) => {
    const payload = stages[key] || { status: "pending", summary: "", detail: "" };
    const card = createElement("article", `stage-card ${toneForStatus(payload.status)}`);
    card.append(
      createElement("div", "stage-card-title", label),
      createElement("div", "stage-card-status", humanizeStatus(payload.status)),
      createElement("div", "stage-card-summary", payload.summary || "等待处理"),
    );
    if (payload.detail) {
      card.append(createElement("div", "stage-card-detail", payload.detail));
    }
    container.appendChild(card);
  });
}

function renderResultSummary(job) {
  if (!job) {
    $("#result-summary").textContent = "系统在线，等待新任务";
    return;
  }
  const workflow = job.result?.workflow_type || job.workflow_type || "workflow";
  $("#result-summary").textContent = `${job.title} | 状态: ${job.status} | ${workflow}`;
}

function renderTextPreview(title, text, meta = "") {
  const preview = $("#artifact-preview");
  preview.className = "artifact-preview text-result";
  preview.innerHTML = "";
  const card = createElement("div", "result-text-card");
  card.append(createElement("div", "result-text-title", title));
  if (meta) card.append(createElement("div", "result-text-meta", meta));
  card.append(createElement("pre", "result-text-body", text));
  preview.appendChild(card);
}

function renderImageArtifact(artifact) {
  const preview = $("#artifact-preview");
  preview.className = "artifact-preview";
  preview.innerHTML = "";
  const image = createElement("img");
  image.src = `file:///${artifact.path.replace(/\\/g, "/")}`;
  image.alt = artifact.title;
  preview.appendChild(image);
}

function renderFileArtifact(artifact) {
  const preview = $("#artifact-preview");
  preview.className = "artifact-preview text-result";
  preview.innerHTML = "";
  const card = createElement("div", "result-text-card");
  card.append(createElement("div", "result-text-title", artifact.title));
  card.append(createElement("div", "result-text-meta", artifact.path));
  const actions = createElement("div", "artifact-actions");
  const openButton = createElement("button", "secondary-button", "打开文件");
  openButton.addEventListener("click", () => window.geobotApi.openPath(artifact.path));
  const locateButton = createElement("button", "ghost-button", "打开目录");
  locateButton.addEventListener("click", () => window.geobotApi.showInFolder(artifact.path));
  actions.append(openButton, locateButton);
  card.append(actions);
  preview.appendChild(card);
}

function renderArtifactPreview(artifact) {
  if (!artifact) {
    $("#artifact-preview").className = "artifact-preview empty";
    $("#artifact-preview").textContent = "暂无导出结果";
    return;
  }
  const lowerPath = (artifact.path || "").toLowerCase();
  if (lowerPath.endsWith(".png") || lowerPath.endsWith(".jpg") || lowerPath.endsWith(".jpeg")) {
    renderImageArtifact(artifact);
    return;
  }
  const previewText = artifact.metadata?.preview_text;
  if (previewText) {
    renderTextPreview(artifact.title, previewText, artifact.path);
    return;
  }
  renderFileArtifact(artifact);
}

function updateArtifactSelection(artifactId) {
  document.querySelectorAll(".artifact-row").forEach((node) => {
    node.classList.toggle("active", node.dataset.artifactId === artifactId);
  });
}

async function refreshOutputs(job = null) {
  if (!state.projectId) return;
  const payload = await window.geobotApi.listOutputs(state.projectId);
  const allItems = payload.items || [];
  const list = $("#artifact-list");
  list.innerHTML = "";

  const artifactIds = new Set(job?.artifact_ids || []);
  const items = artifactIds.size ? allItems.filter((item) => artifactIds.has(item.artifact_id)) : allItems;

  if (!items.length) {
    state.selectedArtifactId = null;
    const text = buildAssistantMessage(job?.result || {});
    if (text) {
      renderTextPreview(job.result.summary || "文本结果", text);
    } else {
      renderArtifactPreview(null);
    }
    return;
  }

  const selected = items.find((item) => item.artifact_id === state.selectedArtifactId) || items[0];
  state.selectedArtifactId = selected.artifact_id;
  items.forEach((artifact) => {
    const row = createElement("button", "artifact-row");
    row.type = "button";
    row.dataset.artifactId = artifact.artifact_id;
    row.append(
      createElement("div", "artifact-row-title", `${artifact.title} (${artifact.artifact_type})`),
      createElement("div", "artifact-row-meta", artifact.path),
    );
    row.addEventListener("click", () => {
      state.selectedArtifactId = artifact.artifact_id;
      updateArtifactSelection(artifact.artifact_id);
      renderArtifactPreview(artifact);
    });
    list.appendChild(row);
  });
  updateArtifactSelection(selected.artifact_id);
  renderArtifactPreview(selected);
}

async function refreshHealth() {
  state.latestHealth = await window.geobotApi.getHealth();
  renderStatusPills();
  renderStatusCards();
  renderJobSummary(state.latestJobSnapshot);
}

async function watchJob(jobId) {
  state.activeJobId = jobId;
  if (state.pollTimer) clearInterval(state.pollTimer);
  const poll = async () => {
    const job = await window.geobotApi.getJob(jobId);
    state.latestJobSnapshot = job;
    renderStatusPills();
    renderJobSummary(job);
    renderJobSteps(job);
    renderWorkflowStages(job);
    renderResultSummary(job);

    if (job.result && !state.shownJobMessages.has(jobId)) {
      const message = buildAssistantMessage(job.result);
      if (message) appendChat("assistant", message);
      state.shownJobMessages.add(jobId);
    }

    if (["completed", "failed"].includes(job.status)) {
      clearInterval(state.pollTimer);
      state.pollTimer = null;
      await refreshOutputs(job);
    }
  };
  await poll();
  state.pollTimer = setInterval(poll, 1500);
}

async function loadTemplates() {
  const payload = await window.geobotApi.listTemplates();
  state.templates = payload.items || [];
  const container = $("#template-list");
  container.innerHTML = "";
  state.templates.forEach((template) => {
    const card = createElement("article", "template-card");
    const editor = createElement("textarea", "template-editor");
    editor.value = JSON.stringify(template.sample_payload || {}, null, 2);
    const button = createElement("button", "primary-button", "执行模板");
    button.addEventListener("click", async () => {
      try {
        const payload = editor.value.trim() ? JSON.parse(editor.value) : {};
        appendChat("user", `执行模板：${template.title}`);
        const job = await window.geobotApi.submitTemplate(template.template_id, { project_id: state.projectId, payload });
        await watchJob(job.job_id);
      } catch (error) {
        appendChat("assistant", `模板执行失败：${error.message || String(error)}`);
      }
    });
    card.append(
      createElement("div", "template-title", template.title),
      createElement("div", "template-description", template.description || ""),
      editor,
      button,
    );
    container.appendChild(card);
  });
}

async function initializeProject() {
  const project = await window.geobotApi.createProject({ name: "GeoBot Teaching Project", metadata: { source: "desktop-shell" } });
  state.projectId = project.project_id;
}

async function submitChatMessage() {
  const input = $("#chat-input");
  const message = input.value.trim();
  if (!message || !state.projectId) return;
  appendChat("user", message);
  input.value = "";
  const job = await window.geobotApi.submitChat({ project_id: state.projectId, message });
  await watchJob(job.job_id);
}

async function initialize() {
  renderJobSummary(null);
  renderJobSteps(null);
  renderWorkflowStages(null);
  renderResultSummary(null);
  await refreshHealth();
  await initializeProject();
  await loadTemplates();
  await refreshOutputs();
  appendChat("assistant", "GeoBot 已就绪。你可以输入完整教学需求，系统会按教学设计、QGIS 地图和课件生成流程执行。");
}

$("#chat-send-button").addEventListener("click", () => submitChatMessage().catch((error) => appendChat("assistant", error.message || String(error))));
$("#chat-input").addEventListener("keydown", (event) => {
  if ((event.ctrlKey || event.metaKey) && event.key === "Enter") {
    submitChatMessage().catch((error) => appendChat("assistant", error.message || String(error)));
  }
});
$("#focus-qgis-button").addEventListener("click", async () => {
  const result = await window.geobotApi.focusQgis();
  appendChat("assistant", result.message || (result.status === "success" ? "已切换到 QGIS。" : "切换到 QGIS 失败。"));
});
$("#toggle-status-button").addEventListener("click", () => setStatusDrawerOpen(!state.isStatusPanelOpen));
$("#close-status-button").addEventListener("click", () => setStatusDrawerOpen(false));
$("#status-drawer-backdrop").addEventListener("click", () => setStatusDrawerOpen(false));
window.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && state.isStatusPanelOpen) setStatusDrawerOpen(false);
});

initialize().catch((error) => {
  appendChat("assistant", `初始化失败：${error.message || String(error)}`);
  $("#result-summary").textContent = `初始化失败 | ${error.message || String(error)}`;
});
