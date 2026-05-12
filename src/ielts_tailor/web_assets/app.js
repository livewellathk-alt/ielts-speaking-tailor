const state = {
  data: null,
  questions: [],
  index: 0,
  saveTimer: null,
  generationPoll: null,
};

const views = {
  setup: document.querySelector("#setupView"),
  test: document.querySelector("#testView"),
  results: document.querySelector("#resultsView"),
};

const viewTitles = {
  setup: ["设置", "本地备考工作台"],
  test: ["素材采集", "像正式口语考试一样逐题补充"],
  results: ["结果编辑", "测试样本与完整答案"],
};

const themeLabels = {
  city_travel: "城市/旅行",
  people_relationships: "人物/关系",
  technology_media: "科技/媒体",
  work_study: "学习/工作",
  rules_society: "规则/社会",
  lifestyle_activity: "生活/活动",
  general_experience: "通用经历",
};

const progressLabels = {
  scope_analysis: "分析题目范围",
  style_guide: "整理学生风格",
  checkpoint_samples: "生成校准样本",
  answer_batch: "生成答案批次",
  quality_review: "质量检查",
  revision: "修订答案",
  render_output: "生成文件",
};

document.querySelectorAll(".rail-item").forEach((button) => {
  button.addEventListener("click", () => setView(button.dataset.view));
});

document.querySelector("#reloadButton").addEventListener("click", loadState);
document.querySelector("#generateSampleButton").addEventListener("click", generateSampleAnswers);
document.querySelector("#generateButton").addEventListener("click", generateFullAnswers);
document.querySelector("#saveSettingsButton").addEventListener("click", saveSettings);
document.querySelector("#saveProfileButton").addEventListener("click", saveStudentProfile);
document.querySelector("#saveResultButton").addEventListener("click", saveResult);
document.querySelector("#uploadBankButton").addEventListener("click", uploadQuestionBank);
document.querySelector("#previousQuestion").addEventListener("click", () => moveQuestion(-1));
document.querySelector("#nextQuestion").addEventListener("click", () => moveQuestion(1));

loadState();

async function loadState() {
  setStatus("正在载入", false);
  const response = await fetch("/api/state");
  state.data = await response.json();
  state.questions = buildQuestionList(state.data.questionnaire);
  state.index = Math.min(state.index, Math.max(0, state.questions.length - 1));
  renderSetup();
  renderCoverage();
  renderPollProgress();
  renderQuestion();
  document.querySelector("#resultMarkdown").value = state.data.result_markdown || "";
  setStatus("已载入", true);
}

function setView(name) {
  Object.entries(views).forEach(([viewName, element]) => {
    element.classList.toggle("active", viewName === name);
  });
  document.querySelectorAll(".rail-item").forEach((button) => {
    button.classList.toggle("active", button.dataset.view === name);
  });
  document.querySelector("#viewEyebrow").textContent = viewTitles[name][0];
  document.querySelector("#viewTitle").textContent = viewTitles[name][1];
}

function renderSetup() {
  const targets = state.data.word_targets;
  document.querySelector("#part1Target").textContent = `${targets.part1.seconds}秒 / ${targets.part1.words}词`;
  document.querySelector("#part2Target").textContent =
    `${targets.part2.min_seconds}-${targets.part2.max_seconds}秒 / ${targets.part2.min_words}-${targets.part2.max_words}词`;
  document.querySelector("#part3Target").textContent = `${targets.part3.seconds}秒 / ${targets.part3.words}词`;
  const metadata = state.data.questionnaire.metadata || {};
  document.querySelector("#questionBudget").textContent = `${metadata.total_questions || state.questions.length} / ${metadata.max_questions || state.questions.length}题`;
  renderSettings();
  renderPaths();
  renderProfile();
}

function renderSettings() {
  const settings = state.data.settings;
  setInput("targetBandInput", settings.target_band);
  setInput("wpmInput", settings.speaking_speed_wpm);
  setInput("part1SecondsInput", settings.part1_seconds);
  setInput("part2MinSecondsInput", settings.part2_min_seconds);
  setInput("part2MaxSecondsInput", settings.part2_max_seconds);
  setInput("part3SecondsInput", settings.part3_seconds);
  setInput("baseUrlInput", settings.base_url);
  setInput("apiKeyEnvInput", settings.api_key_env);
  setInput("modelInput", settings.model);
  setInput("reviewerModelInput", settings.reviewer_model);
}

function renderCoverage() {
  const coverage = state.data.coverage || { overall_percent: 0, status: "资料不足", followups: [], theme_reports: [] };
  document.querySelector("#coverageScore").textContent = `${coverage.overall_percent}%`;
  document.querySelector("#coverageSummary").textContent = coverageSummaryText(coverage);
  document.querySelector("#coverageBar").style.width = `${Math.max(0, Math.min(100, coverage.overall_percent))}%`;
  const themeCoverage = document.querySelector("#themeCoverage");
  themeCoverage.innerHTML = "";
  coverage.theme_reports.forEach((report) => {
    const row = document.createElement("div");
    row.className = "coverage-row";
    row.innerHTML = `<strong>${escapeHtml(report.label)}</strong><span>${escapeHtml(report.status)} · ${report.score}%</span>`;
    themeCoverage.appendChild(row);
  });
  const followups = document.querySelector("#followupList");
  followups.innerHTML = "";
  const items = coverage.followups.length ? coverage.followups : ["资料足够后，可以先生成测试样本，再决定是否全量生成。"];
  items.forEach((item) => {
    const li = document.createElement("li");
    li.textContent = item;
    followups.appendChild(li);
  });
}

function renderPollProgress() {
  const progress = state.data.poll_progress || { total: state.questions.length, answered: 0, percent: 0, items: [] };
  document.querySelector("#pollProgressSummary").textContent = `${progress.answered} / ${progress.total} 已完成`;
  document.querySelector("#pollProgressPercent").textContent = `${progress.percent}%`;
  document.querySelector("#pollProgressBar").style.width = `${Math.max(0, Math.min(100, progress.percent))}%`;
  const nav = document.querySelector("#questionNav");
  nav.innerHTML = "";
  state.questions.forEach((question, index) => {
    const item = (progress.items || []).find((candidate) => candidate.key === question.key) || {};
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = `${index + 1}. ${question.title}`;
    button.classList.toggle("active", index === state.index);
    button.classList.toggle("complete", Boolean(item.answered));
    button.addEventListener("click", () => {
      state.index = index;
      renderQuestion();
      renderPollProgress();
    });
    nav.appendChild(button);
  });
}

function coverageSummaryText(coverage) {
  if (coverage.status === "资料不足") {
    return "资料不足：请补充下面建议，避免 AI 编造个人经历。";
  }
  if (coverage.status === "可以生成测试样本") {
    return "资料基本够用：建议先生成测试样本，确认风格后再全量生成。";
  }
  return "资料覆盖较完整：可以生成测试样本，也可以全量生成。";
}

function renderPaths() {
  const pathList = document.querySelector("#pathList");
  pathList.innerHTML = "";
  [
    ["题库", state.data.paths.question_bank],
    ["学生资料", state.data.paths.student_profile],
    ["输入素材", state.data.paths.profile_responses],
    ["答案结果", state.data.paths.result_markdown],
  ].forEach(([label, value]) => {
    const row = document.createElement("div");
    row.innerHTML = `<dt>${escapeHtml(label)}</dt><dd>${escapeHtml(value)}</dd>`;
    pathList.appendChild(row);
  });
}

function renderProfile() {
  const profileGrid = document.querySelector("#profileGrid");
  profileGrid.innerHTML = "";
  setInput("profileYamlInput", state.data.profile_yaml || "");
  [
    ["姓名", state.data.profile.name || "未填写"],
    ["身份", state.data.profile.current_status || "未填写"],
    ["家乡", state.data.profile.hometown || "未填写"],
  ].forEach(([label, value]) => {
    const row = document.createElement("div");
    row.innerHTML = `<span>${escapeHtml(label)}</span><strong>${escapeHtml(value)}</strong>`;
    profileGrid.appendChild(row);
  });
}

function buildQuestionList(questionnaire) {
  const questions = [];
  questionnaire.umbrella_stories.forEach((story) => {
    const scopeId = story.scope_id || story.theme;
    const scopeLabel = story.scope_label || themeLabels[story.theme] || story.theme.replaceAll("_", " ");
    questions.push({
      part: "素材题",
      key: scopeId,
      group: "umbrella_stories",
      title: scopeLabel,
      prompt: `一套素材生成 Part 2、Part 3 和 Part 1。${story.why_reusable || "这些题可以共用一个真实素材。"} 相关题目：${story.part2_prompts.join(" / ")}`,
      fields: [
        ["story", "人物、物品、地点或事件"],
        ["situation", "发生了什么或你通常怎么使用它"],
        ["details", "三个具体细节"],
        ["lesson", "感受、结果或收获"],
        ["avoid", "不要编造或不要提到的内容"],
      ],
    });
  });
  return questions;
}

function renderQuestion() {
  const current = state.questions[state.index];
  const fields = document.querySelector("#answerFields");
  if (!current) {
    document.querySelector("#questionPart").textContent = "准备中";
    document.querySelector("#questionCounter").textContent = "0 / 0";
    document.querySelector("#questionText").textContent = "请先导入题库";
    document.querySelector("#questionPrompt").textContent = "";
    fields.innerHTML = "";
    return;
  }
  document.querySelector("#questionPart").textContent = current.part;
  document.querySelector("#questionCounter").textContent = `${state.index + 1} / ${state.questions.length}`;
  document.querySelector("#questionText").textContent = current.title;
  document.querySelector("#questionPrompt").textContent = current.prompt;
  fields.innerHTML = "";
  const currentValues = responseBucket(current.group)[current.key] || {};
  current.fields.forEach(([name, label]) => {
    const wrapper = document.createElement("div");
    wrapper.className = "field-block";
    const textarea = document.createElement("textarea");
    textarea.value = currentValues[name] || "";
    textarea.dataset.field = name;
    textarea.addEventListener("input", () => {
      updateResponse(current, name, textarea.value);
      scheduleSave();
    });
    const fieldLabel = document.createElement("label");
    fieldLabel.textContent = label;
    wrapper.appendChild(fieldLabel);
    wrapper.appendChild(textarea);
    fields.appendChild(wrapper);
  });
}

function responseBucket(group) {
  state.data.responses[group] ||= {};
  return state.data.responses[group];
}

function updateResponse(question, field, value) {
  const bucket = responseBucket(question.group);
  bucket[question.key] ||= {};
  bucket[question.key][field] = value;
}

function moveQuestion(delta) {
  state.index = Math.max(0, Math.min(state.questions.length - 1, state.index + delta));
  renderQuestion();
  renderPollProgress();
}

function scheduleSave() {
  setStatus("正在保存", false);
  window.clearTimeout(state.saveTimer);
  state.saveTimer = window.setTimeout(saveResponses, 450);
}

async function saveResponses() {
  const response = await fetch("/api/profile-responses", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ responses: state.data.responses }),
  });
  const payload = await response.json();
  if (!payload.ok) {
    setStatus("保存失败", false);
    return;
  }
  state.data = payload.state;
  renderCoverage();
  renderPollProgress();
  setStatus("已保存", true);
}

async function saveSettings() {
  setStatus("正在保存设置", false);
  const response = await fetch("/api/settings", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ settings: collectSettings() }),
  });
  const payload = await response.json();
  if (!payload.ok) {
    setStatus("设置保存失败", false);
    return;
  }
  state.data = payload.state;
  renderSetup();
  setStatus("设置已保存", true);
}

async function saveStudentProfile() {
  setStatus("正在保存学生资料", false);
  const response = await fetch("/api/student-profile", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ profile_yaml: valueOf("profileYamlInput") }),
  });
  const payload = await response.json();
  if (!payload.ok) {
    setStatus("学生资料保存失败", false);
    return;
  }
  state.data = payload.state;
  renderSetup();
  renderCoverage();
  setStatus("学生资料已保存", true);
}

async function saveResult() {
  setStatus("正在保存结果", false);
  const response = await fetch("/api/result-markdown", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ markdown: document.querySelector("#resultMarkdown").value }),
  });
  const payload = await response.json();
  if (!payload.ok) {
    setStatus("结果保存失败", false);
    return;
  }
  state.data = payload.state;
  setStatus("结果已保存", true);
}

async function uploadQuestionBank() {
  const fileInput = document.querySelector("#questionBankFile");
  const file = fileInput.files[0];
  if (!file) {
    setStatus("请选择题库 PDF", false);
    return;
  }
  setStatus("正在导入题库", false);
  const form = new FormData();
  form.append("file", file);
  form.append("region", valueOf("bankRegionInput"));
  const response = await fetch("/api/question-bank", {
    method: "POST",
    body: form,
  });
  const payload = await response.json();
  if (!payload.ok) {
    setStatus("题库导入失败", false);
    return;
  }
  state.data = payload.state;
  state.questions = buildQuestionList(state.data.questionnaire);
  state.index = 0;
  renderSetup();
  renderCoverage();
  renderPollProgress();
  renderQuestion();
  setStatus("题库已导入", true);
}

async function generateSampleAnswers() {
  await generateAnswers("sample", "正在生成测试样本", "测试样本已生成");
}

async function generateFullAnswers() {
  await generateAnswers("full", "正在全量生成", "完整答案已生成");
}

async function generateAnswers(mode, loadingText, successText) {
  setView("results");
  setStatus(loadingText, false);
  setGenerateDisabled(true);
  renderGenerationProgress({ status: "running", events: [] });
  const response = await fetch("/api/generation-jobs", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ mode }),
  });
  const payload = await response.json();
  if (!payload.ok) {
    setGenerateDisabled(false);
    setStatus("资料不足", false);
    document.querySelector("#resultMarkdown").value = `资料不足，暂时不能生成。\n\n请补充：\n${payload.error}`;
    return;
  }
  pollGenerationJob(payload.job_id, successText);
}

function pollGenerationJob(jobId, successText) {
  window.clearInterval(state.generationPoll);
  state.generationPoll = window.setInterval(async () => {
    const response = await fetch(`/api/generation-jobs/${jobId}`);
    const payload = await response.json();
    renderGenerationProgress(payload);
    if (payload.status === "running") {
      return;
    }
    window.clearInterval(state.generationPoll);
    setGenerateDisabled(false);
    if (payload.status === "failed") {
      setStatus("生成失败", false);
      document.querySelector("#resultMarkdown").value = `生成失败。\n\n${payload.error}`;
      return;
    }
    state.data = payload.state;
    document.querySelector("#resultMarkdown").value = state.data.result_markdown || "";
    renderCoverage();
    renderPollProgress();
    setStatus(successText, true);
  }, 700);
}

function renderGenerationProgress(job) {
  const summary = document.querySelector("#generationProgressSummary");
  const percent = Math.max(0, Math.min(100, Number(job.percent) || 0));
  document.querySelector("#generationProgressPercent").textContent = `${percent}%`;
  document.querySelector("#generationProgressBar").style.width = `${percent}%`;
  const list = document.querySelector("#generationSteps");
  const events = job.events || [];
  summary.textContent =
    job.status === "completed"
      ? "生成完成，答案文件已经写入本地输出文件夹。"
      : job.status === "failed"
        ? `生成失败：${job.error || "请检查设置和输入素材。"}`
        : "正在按阶段生成，完成前不会展示未校验的半成品答案。";
  list.innerHTML = "";
  if (!events.length) {
    const item = document.createElement("li");
    item.textContent = "等待后端开始处理";
    list.appendChild(item);
    return;
  }
  events.forEach((event) => {
    const item = document.createElement("li");
    const label = progressLabels[event.stage] || event.stage;
    item.innerHTML = `<strong>${escapeHtml(label)}</strong><span>${escapeHtml(event.message || "")}</span>`;
    list.appendChild(item);
  });
}

function collectSettings() {
  return {
    target_band: numberValue("targetBandInput"),
    speaking_speed_wpm: numberValue("wpmInput"),
    part1_seconds: numberValue("part1SecondsInput"),
    part2_min_seconds: numberValue("part2MinSecondsInput"),
    part2_max_seconds: numberValue("part2MaxSecondsInput"),
    part3_seconds: numberValue("part3SecondsInput"),
    base_url: valueOf("baseUrlInput"),
    api_key_env: valueOf("apiKeyEnvInput"),
    model: valueOf("modelInput"),
    reviewer_model: valueOf("reviewerModelInput"),
  };
}

function setGenerateDisabled(disabled) {
  document.querySelector("#generateSampleButton").disabled = disabled;
  document.querySelector("#generateButton").disabled = disabled;
}

function setStatus(message, saved) {
  document.querySelector("#saveStatus").textContent = message;
  document.querySelector("#statusDot").classList.toggle("saved", Boolean(saved));
}

function setInput(id, value) {
  document.querySelector(`#${id}`).value = value ?? "";
}

function valueOf(id) {
  return document.querySelector(`#${id}`).value.trim();
}

function numberValue(id) {
  return Number(document.querySelector(`#${id}`).value);
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}
