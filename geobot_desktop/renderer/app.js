const state = {
  projectId: null,
  activeJobId: null,
  pollTimer: null,
  shownJobMessages: new Map(),
  latestHealth: null,
  latestJobSnapshot: null,
  selectedArtifactId: null,
  isStatusPanelOpen: false,
  populationShowcase: null,
  taskMode: "lesson_ppt",
  presentationStyle: "data_analysis",
  presentationStyles: [],
};

const TASK_MODE_LABELS = {
  lesson_ppt: "教学设计 + PPT",
  qgis_only: "QGIS 操作",
};

const STAGE_LABELS = {
  analysis: "需求解析",
  design: "教学设计",
  map: "QGIS 地图",
  presentation: "PPT 生成",
};

const ARTIFACT_KEY_PRIORITY = {
  flagship_deck: 10,
  pptx: 10,
  map_export: 30,
  theme1_map: 30,
  theme2_map: 40,
  theme3_map: 50,
  chart_preview: 60,
  primary_chart: 60,
  secondary_chart: 65,
  lesson_plan: 70,
  lesson_plan_docx: 72,
  guidance: 74,
  guidance_docx: 76,
  homework: 78,
  homework_docx: 80,
  review: 82,
  review_docx: 84,
  deck_scenario: 95,
  deck_metadata: 96,
};

const ARTIFACT_GROUP_LABELS = {
  lesson_plan: "单元教学设计",
  lesson_plan_docx: "单元教学设计",
  guidance: "导学材料",
  guidance_docx: "导学材料",
  homework: "作业材料",
  homework_docx: "作业材料",
  review: "复习材料",
  review_docx: "复习材料",
  pptx: "答辩 PPT",
  flagship_deck: "答辩 PPT",
  deck_scenario: "PPT 调试文件",
  deck_metadata: "PPT 调试文件",
  map_export: "地图产物",
  theme1_map: "地图产物",
  theme2_map: "地图产物",
  theme3_map: "地图产物",
};

function $(selector) {
  return document.querySelector(selector);
}

function createElement(tag, className, text) {
  const element = document.createElement(tag);
  if (className) {
    element.className = className;
  }
  if (text !== undefined) {
    element.textContent = text;
  }
  return element;
}

function scrollChatToBottom(behavior = "auto") {
  const log = $("#chat-log");
  if (!log) {
    return;
  }

  requestAnimationFrame(() => {
    log.scrollTo({
      top: log.scrollHeight,
      behavior,
    });
  });
}

function extensionOf(path) {
  const normalized = String(path || "").toLowerCase();
  const parts = normalized.split(".");
  return parts.length > 1 ? `.${parts.pop()}` : "";
}

function isPreviewableArtifact(artifact) {
  const ext = extensionOf(artifact?.path);
  return [".png", ".jpg", ".jpeg", ".webp", ".md", ".txt", ".json"].includes(ext) || Boolean(artifact?.metadata?.preview_text);
}

function humanizeStatus(status) {
  return (
    {
      queued: "排队中",
      pending: "待处理",
      running: "执行中",
      completed: "已完成",
      success: "成功",
      failed: "失败",
      error: "异常",
      warning: "告警",
      skipped: "已跳过",
      info: "处理中",
    }[status] || status || "未知"
  );
}

function toneForStatus(status) {
  if (["success", "completed"].includes(status)) {
    return "success";
  }
  if (["failed", "error"].includes(status)) {
    return "error";
  }
  if (["warning", "skipped"].includes(status)) {
    return "warning";
  }
  if (status === "running") {
    return "running";
  }
  if (["queued", "pending"].includes(status)) {
    return "queued";
  }
  return "neutral";
}

function currentPopulationPreset() {
  if (state.taskMode === "lesson_ppt" && state.populationShowcase?.preset_message) {
    return state.populationShowcase.preset_message;
  }
  if (state.taskMode === "qgis_only") {
    return "请先检查当前 QGIS 图层；如果存在可编辑面图层，将目标图层改为黄色；如果目标不明确，请先告诉我你准备操作哪一层。";
  }
  return "请为高中地理必修二《人口》单元生成教学设计与答辩 PPT，并在教案中附上“建议 QGIS 操作”部分，说明后续可执行的图层、模板、字段和导出物。";
}

function ensureTaskModeSwitch() {
  if (document.querySelector(".task-mode-switch")) {
    return;
  }

  const chatPanel = document.querySelector(".chat-panel");
  const showcaseCard = $("#population-showcase-card");
  if (!chatPanel || !showcaseCard) {
    return;
  }

  const switcher = createElement("div", "task-mode-switch");
  switcher.setAttribute("role", "group");
  switcher.setAttribute("aria-label", "任务模式");

  [
    { mode: "lesson_ppt", label: "教学设计 + PPT" },
    { mode: "qgis_only", label: "QGIS 操作" },
  ].forEach((item) => {
    const button = createElement("button", "task-mode-button", item.label);
    button.type = "button";
    button.dataset.taskMode = item.mode;
    button.setAttribute("aria-pressed", String(item.mode === state.taskMode));
    button.addEventListener("click", () => {
      state.taskMode = item.mode;
      renderTaskModeSelector();
      renderShowcaseCard();
    });
    switcher.appendChild(button);
  });

  chatPanel.insertBefore(switcher, showcaseCard);
}

function renderTaskModeSelector() {
  ensureTaskModeSwitch();
  const buttons = document.querySelectorAll("[data-task-mode]");
  buttons.forEach((button) => {
    const mode = button.dataset.taskMode;
    const isActive = mode === state.taskMode;
    button.classList.toggle("active", isActive);
    button.setAttribute("aria-pressed", String(isActive));
  });

  const note = $("#chat-mode-note") || document.querySelector(".chat-panel .section-note");
  if (note) {
    note.textContent =
      state.taskMode === "lesson_ppt"
        ? "当前模式只生成教学设计与 PPT，不执行 QGIS；教案会附带建议 QGIS 操作。"
        : "当前模式直接操作当前已打开的 QGIS 项目，可检查图层、修改样式、设置标注，并且只在你明确要求时导出地图。";
  }
}

function renderPresentationStyleControl() {
  const container = $("#presentation-style-control");
  const label = $("#presentation-style-label");
  const select = $("#presentation-style-select");
  if (!container || !label || !select) {
    return;
  }

  const styles = state.presentationStyles || [];
  const visible = state.taskMode === "lesson_ppt" && styles.length > 0;
  container.hidden = !visible;
  if (!visible) {
    return;
  }

  label.textContent = "PPT 风格";
  select.innerHTML = "";
  styles.forEach((item) => {
    const option = document.createElement("option");
    option.value = item.id;
    option.textContent = item.label || item.id;
    if (item.id === state.presentationStyle) {
      option.selected = true;
    }
    select.appendChild(option);
  });
}

function appendChat(role, text) {
  if (!text) {
    return;
  }

  const log = $("#chat-log");
  const last = log.lastElementChild;
  if (last && last.classList.contains(role) && last.textContent === text) {
    return;
  }

  const item = createElement("div", `chat-item ${role}`, text);
  log.appendChild(item);
  scrollChatToBottom("smooth");
}

function buildAssistantMessage(result) {
  if (!result) {
    return "";
  }
  const parts = [result.assistant_message, result.summary, result.notes].filter(Boolean);
  return [...new Set(parts)].join("\n\n");
}

function buildJobResultRevision(job) {
  if (!job?.result) {
    return "";
  }
  return [
    job.job_id || "",
    job.updated_at || "",
    job.status || "",
    job.result.request_id || "",
    job.result.assistant_message || "",
    job.result.summary || "",
    job.result.notes || "",
  ].join("|");
}

function buildResultPreviewText(job) {
  const summary = String(job?.result?.summary || "").trim();
  if (summary) {
    return `${summary}\n\n完整回复请查看聊天区。`;
  }
  return "本次任务未生成结果文件。完整回复请查看聊天区。";
}

function buildExecutionPreviewText(job) {
  const activeStage = Object.entries(job?.stages || {}).find(([, stage]) => stage?.status === "running");
  const queuedStage = Object.entries(job?.stages || {}).find(([, stage]) => stage?.status === "queued");
  const stageInfo = activeStage || queuedStage;
  const summary = stageInfo?.[1]?.summary || "";

  if (job?.status === "running") {
    return summary ? `正在执行当前任务。\n\n${summary}` : "正在执行当前任务。";
  }
  if (job?.status === "failed") {
    return String(job?.error || job?.result?.notes || "当前任务执行失败。");
  }
  return summary ? `任务已提交，正在等待执行。\n\n${summary}` : "任务已提交，正在等待执行。";
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

  if (!state.latestHealth) {
    return;
  }

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
    node.append(
      createElement("span", "status-pill-label", item.label),
      createElement("span", "status-pill-value", item.value)
    );
    container.appendChild(node);
  });
}

function renderStatusCards() {
  const container = $("#status-cards");
  container.innerHTML = "";

  const health = state.latestHealth;
  if (!health) {
    return;
  }

  const cards = [
    ["Runtime 服务", health.runtime?.api || "", health.runtime?.outputs || "", "ok"],
    [
      "QGIS 插件",
      health.qgis?.reachable ? "已连接" : "未连接",
      health.qgis?.message || health.qgis?.error || "",
      health.qgis?.reachable ? "ok" : "warn",
    ],
    [
      "QGIS 环境",
      health.qgis_installation?.detected ? "已检测" : "未检测",
      health.qgis_installation?.executable || "",
      health.qgis_installation?.detected ? "ok" : "warn",
    ],
    [
      "智能引擎",
      health.assistant_engine?.reachable ? "已就绪" : "降级模式",
      health.assistant_engine?.name || "",
      health.assistant_engine?.reachable ? "ok" : "neutral",
    ],
  ];

  cards.forEach(([title, value, meta, tone]) => {
    const card = createElement("article", `status-card ${tone}`);
    card.append(
      createElement("div", "status-card-title", title),
      createElement("div", "status-card-value", value),
      createElement("div", "status-card-meta", meta)
    );
    container.appendChild(card);
  });
}


function renderShowcaseCard() {
  const showcase = state.populationShowcase;
  const card = $("#population-showcase-card");
  if (!showcase) {
    card.hidden = true;
    return;
  }

  card.hidden = false;
  const title = $("#population-showcase-title") || document.querySelector("#population-showcase-card .showcase-title");
  if (title) {
    title.textContent = state.taskMode === "lesson_ppt" ? "人口单元教学设计模式" : "通用 QGIS 控制模式";
  }
  $("#population-showcase-headline").textContent =
    state.taskMode === "lesson_ppt"
      ? "当前模式面向教学设计与 PPT 生成，不执行人口单元数据预检。"
      : "当前模式面向当前已打开的 QGIS 项目，可直接执行样式修改、图层检查、标注设置与按需导出。";
  $("#population-showcase-headline").className = "showcase-meta";
  $("#population-showcase-path").textContent =
    state.taskMode === "lesson_ppt" ? (showcase.knowledge_root || "") : "当前项目中的现有图层";
  $("#population-preset-button").textContent = state.taskMode === "lesson_ppt" ? "载入教案需求" : "载入示例命令";
  renderPresentationStyleControl();

  const chipContainer = $("#population-theme-status");
  chipContainer.innerHTML = "";
  chipContainer.hidden = true;
}

function renderJobSummary(job) {
  $("#status-toggle-hint").textContent = job ? `${humanizeStatus(job.status)} · ${job.title}` : "系统在线";
  $("#drawer-job-summary").textContent = job ? `${job.title} · ${humanizeStatus(job.status)}` : "系统在线，暂无执行中任务";
  $("#job-steps-meta").textContent = job ? `当前任务：${job.title}` : "暂无执行中任务";
}

function renderJobSteps(job) {
  const container = $("#job-steps");
  container.innerHTML = "";

  const steps = job?.steps || [];
  if (!steps.length) {
    const empty = createElement("div", "empty-state");
    empty.append(
      createElement("div", "empty-state-title", "暂无执行步骤"),
      createElement("div", "empty-state-detail", "提交任务后，这里会显示实时执行进度。")
    );
    container.appendChild(empty);
    return;
  }

  steps.forEach((step, index) => {
    const node = createElement("div", `job-step ${toneForStatus(step.status)}`);
    const marker = createElement("div", "job-step-marker", String(index + 1).padStart(2, "0"));
    const content = createElement("div", "job-step-content");
    const top = createElement("div", "job-step-top");

    top.append(
      createElement("div", "job-step-title", step.title || "执行步骤"),
      createElement("div", "job-step-badge", humanizeStatus(step.status))
    );
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
    const payload = stages[key] || {};
    const status = payload.status || "pending";
    const card = createElement("article", `stage-card ${toneForStatus(status)}`);

    const header = createElement("div", "stage-card-header");
    header.append(
      createElement("div", "stage-card-title", label),
      createElement("div", "stage-card-status", humanizeStatus(status))
    );

    const summary = createElement(
      "div",
      "stage-card-summary",
      payload.summary || payload.detail || (status === "pending" ? "等待处理" : "处理中")
    );

    card.append(header, summary);
    container.appendChild(card);
  });
}

function renderResultSummary(job) {
  $("#result-summary").textContent = job ? `${job.title} · ${humanizeStatus(job.status)}` : "系统在线，等待新任务";
}

function parseSummaryEntry(item) {
  const raw = String(item || "").trim();
  if (!raw) {
    return { label: "", value: "" };
  }

  const match = raw.match(/^([^:：]{1,32})\s*[：:]\s*(.+)$/);
  if (!match) {
    return { label: "", value: raw };
  }

  return {
    label: match[1].trim(),
    value: match[2].trim(),
  };
}

function renderShowcaseHighlights(job) {
  const section = $("#showcase-highlights-section");
  const container = $("#showcase-highlights");
  if (!section || !container) {
    return;
  }

  const items = (job?.result?.showcase_highlights || []).filter(Boolean);
  container.innerHTML = "";
  section.hidden = !items.length;
  if (!items.length) {
    return;
  }

  items.forEach((item) => {
    const card = createElement("article", "showcase-highlight-card");
    card.appendChild(createElement("div", "showcase-highlight-text", item));
    container.appendChild(card);
  });
}

function renderPackageContractSummary(job) {
  const section = $("#package-contract-section");
  const container = $("#package-contract-summary");
  if (!section || !container) {
    return;
  }

  const items = (job?.result?.package_contract_summary || []).filter(Boolean);
  container.innerHTML = "";
  section.hidden = !items.length;
  if (!items.length) {
    return;
  }

  items.forEach((item) => {
    const entry = parseSummaryEntry(item);
    const card = createElement("article", "contract-summary-item");

    if (entry.label) {
      card.append(
        createElement("div", "contract-summary-label", entry.label),
        createElement("div", "contract-summary-value", entry.value)
      );
    } else {
      card.appendChild(createElement("div", "contract-summary-value", entry.value));
    }

    container.appendChild(card);
  });
}

function renderTextPreview(title, text, meta = "") {
  const preview = $("#artifact-preview");
  preview.className = "artifact-preview text-result";
  preview.innerHTML = "";

  const card = createElement("div", "result-text-card");
  card.append(createElement("div", "result-text-title", title));
  if (meta) {
    card.append(createElement("div", "result-text-meta", meta));
  }
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
  const actions = createElement("div", "artifact-actions");
  const openButton = createElement("button", "secondary-button", "打开文件");
  const locateButton = createElement("button", "ghost-button", "打开目录");

  openButton.addEventListener("click", () => window.geobotApi.openPath(artifact.path));
  locateButton.addEventListener("click", () => window.geobotApi.showInFolder(artifact.path));

  actions.append(openButton, locateButton);
  card.append(
    createElement("div", "result-text-title", artifact.title),
    createElement("div", "result-text-meta", artifact.path),
    actions
  );
  preview.appendChild(card);
}

function renderArtifactPreview(artifact) {
  if (!artifact) {
    const preview = $("#artifact-preview");
    preview.className = "artifact-preview empty";
    preview.textContent = "暂无导出结果";
    return;
  }

  const ext = extensionOf(artifact.path);
  if ([".png", ".jpg", ".jpeg", ".webp"].includes(ext)) {
    renderImageArtifact(artifact);
    return;
  }

  if (artifact.metadata?.preview_text) {
    renderTextPreview(artifact.title, artifact.metadata.preview_text, artifact.path);
    return;
  }

  renderFileArtifact(artifact);
}

function updateArtifactSelection(artifactId) {
  document.querySelectorAll(".artifact-row").forEach((node) => {
    node.classList.toggle("active", node.dataset.artifactId === artifactId);
  });
}

function renderArtifactListEmpty(text = "暂无结果文件") {
  const list = $("#artifact-list");
  list.innerHTML = "";
  list.appendChild(createElement("div", "artifact-list-empty", text));
}

function renderRunningOutputs(job) {
  state.selectedArtifactId = null;
  renderArtifactListEmpty("当前任务尚未生成结果文件");
  renderTextPreview("执行状态", buildExecutionPreviewText(job));
}

function artifactPriority(item) {
  const metadataPriority = item?.metadata?.showcase_priority;
  if (typeof metadataPriority === "number") {
    return metadataPriority;
  }
  return ARTIFACT_KEY_PRIORITY[item?.metadata?.artifact_key] ?? 999;
}

function artifactPreviewPriority(item) {
  const ext = extensionOf(item?.path);
  if ([".png", ".jpg", ".jpeg", ".webp"].includes(ext)) {
    return 0;
  }
  if (item?.metadata?.preview_text) {
    return 1;
  }
  if (ext === ".pdf") {
    return 2;
  }
  if (ext === ".pptx") {
    return 3;
  }
  return 4;
}

function sortArtifacts(items) {
  return [...items].sort((left, right) => {
    const priorityDiff = artifactPriority(left) - artifactPriority(right);
    if (priorityDiff !== 0) {
      return priorityDiff;
    }
    const previewDiff = artifactPreviewPriority(left) - artifactPreviewPriority(right);
    if (previewDiff !== 0) {
      return previewDiff;
    }
    return String(left.title || "").localeCompare(String(right.title || ""), "zh-CN");
  });
}

function artifactGroupLabel(item) {
  return ARTIFACT_GROUP_LABELS[item?.metadata?.artifact_key] || "其他成果";
}

async function refreshOutputs(job = null) {
  if (!state.projectId) {
    return;
  }

  const payload = await window.geobotApi.listOutputs(state.projectId);
  const allItems = payload.items || [];
  const artifactIds = new Set(job?.artifact_ids || []);
  const filtered = artifactIds.size ? allItems.filter((item) => artifactIds.has(item.artifact_id)) : allItems;
  const items = sortArtifacts(filtered);

  if (!items.length) {
    state.selectedArtifactId = null;
    renderArtifactListEmpty();

    if (job?.result) {
      renderTextPreview("执行结果摘要", buildResultPreviewText(job), job?.result?.export_path || "");
    } else {
      renderArtifactPreview(null);
    }
    return;
  }

  const list = $("#artifact-list");
  list.innerHTML = "";

  const selected =
    items.find((item) => item.artifact_id === state.selectedArtifactId) ||
    items.find((item) => isPreviewableArtifact(item)) ||
    items[0];
  state.selectedArtifactId = selected.artifact_id;

  let currentGroupLabel = "";
  items.forEach((artifact) => {
    const groupLabel = artifactGroupLabel(artifact);
    if (currentGroupLabel !== groupLabel) {
      const header = createElement("div", "artifact-group-label", groupLabel);
      header.dataset.groupLabel = groupLabel;
      list.appendChild(header);
      currentGroupLabel = groupLabel;
    }
    const row = createElement("button", "artifact-row");
    row.type = "button";
    row.dataset.artifactId = artifact.artifact_id;
    row.append(
      createElement("div", "artifact-row-title", artifact.title),
      createElement("div", "artifact-row-meta", artifact.path)
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

async function refreshPopulationShowcase() {
  state.populationShowcase = await window.geobotApi.getPopulationShowcase();
  state.presentationStyles = state.populationShowcase?.presentation_styles || [];
  state.presentationStyle =
    state.populationShowcase?.default_presentation_style ||
    state.presentationStyle ||
    "data_analysis";
  renderShowcaseCard();
}

async function watchJob(jobId) {
  state.activeJobId = jobId;
  if (state.pollTimer) {
    clearInterval(state.pollTimer);
  }

  const poll = async () => {
    const job = await window.geobotApi.getJob(jobId);
    state.latestJobSnapshot = job;

    renderStatusPills();
    renderJobSummary(job);
    renderJobSteps(job);
    renderWorkflowStages(job);
    renderResultSummary(job);
    renderShowcaseHighlights(job);
    renderPackageContractSummary(job);

    if (job.result) {
      const message = buildAssistantMessage(job.result);
      const revision = buildJobResultRevision(job);
      if (message && state.shownJobMessages.get(jobId) !== revision) {
        appendChat("assistant", message);
        state.shownJobMessages.set(jobId, revision);
      }
    }

    if (["queued", "pending", "running"].includes(job.status)) {
      renderRunningOutputs(job);
    }

    if (["completed", "failed"].includes(job.status)) {
      clearInterval(state.pollTimer);
      state.pollTimer = null;
      if (job.error) {
        appendChat("assistant", job.error);
      }
      await refreshOutputs(job);
    }
  };

  await poll();
  state.pollTimer = setInterval(poll, 1500);
}

async function initializeProject() {
  const project = await window.geobotApi.createProject({
    name: "GeoBot Workspace",
    metadata: { source: "desktop-shell" },
  });
  state.projectId = project.project_id;
}

async function submitChatMessage() {
  const input = $("#chat-input");
  const message = input.value.trim();
  if (!message || !state.projectId) {
    return;
  }

  appendChat("user", message);
  input.value = "";
  const job = await window.geobotApi.submitChat({
    project_id: state.projectId,
    message,
    task_mode: state.taskMode,
    presentation_style: state.taskMode === "lesson_ppt" ? state.presentationStyle : "",
  });
  state.selectedArtifactId = null;
  state.latestJobSnapshot = job;
  renderStatusPills();
  renderJobSummary(job);
  renderJobSteps(job);
  renderWorkflowStages(job);
  renderResultSummary(job);
  renderShowcaseHighlights(job);
  renderPackageContractSummary(job);
  renderRunningOutputs(job);
  await watchJob(job.job_id);
}

function injectPopulationPreset() {
  const preset = currentPopulationPreset();
  if (!preset) {
    return;
  }
  $("#chat-input").value = preset;
  $("#chat-input").focus();
}

async function initialize() {
  renderJobSummary(null);
  renderJobSteps(null);
  renderWorkflowStages(null);
  renderResultSummary(null);
  renderShowcaseHighlights(null);
  renderPackageContractSummary(null);
  renderTaskModeSelector();
  await refreshHealth();
  await refreshPopulationShowcase();
  await initializeProject();
  await refreshOutputs();
  appendChat("assistant", "GeoBot 已就绪。可在“教学设计 + PPT”和“QGIS 操作”之间切换；QGIS 模式会直接操作当前已打开的项目。");
}

document.querySelectorAll("[data-task-mode]").forEach((button) => {
  button.addEventListener("click", () => {
    state.taskMode = button.dataset.taskMode || "lesson_ppt";
    renderTaskModeSelector();
    renderShowcaseCard();
  });
});

$("#chat-send-button").addEventListener("click", () => {
  submitChatMessage().catch((error) => appendChat("assistant", error.message || String(error)));
});

$("#population-preset-button").addEventListener("click", () => injectPopulationPreset());

$("#presentation-style-select").addEventListener("change", (event) => {
  state.presentationStyle = event.target.value || state.presentationStyle;
  renderPresentationStyleControl();
});

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
  if (event.key === "Escape" && state.isStatusPanelOpen) {
    setStatusDrawerOpen(false);
  }
});

initialize().catch((error) => {
  appendChat("assistant", `初始化失败：${error.message || String(error)}`);
  $("#result-summary").textContent = `初始化失败 · ${error.message || String(error)}`;
});
