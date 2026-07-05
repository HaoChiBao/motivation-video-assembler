const GROUP_LABELS = {
  hook: "Hook",
  emotional_peak: "Emotional Peak",
  wisdom: "Wisdom",
  story_climax: "Story Climax",
  call_to_action: "Call to Action",
  quotable: "Quotable",
};

const STAGE_ORDER = [
  "queued",
  "downloading_video",
  "fetching_transcript",
  "prepared",
  "analyzing",
  "extracting_clips",
  "done",
];

const STAGE_TITLES = {
  queued: "Queued",
  downloading_video: "Downloading source video",
  fetching_transcript: "Extracting transcript",
  prepared: "Ready for clipping",
  analyzing: "Analyzing moments",
  extracting_clips: "Extracting clips",
  done: "Complete",
};

const state = {
  activeView: "analyze",
  activeFilter: "all",
  activeTag: "",
  searchQuery: "",
  currentJobId: null,
  studioJobId: null,
  pollTimer: null,
  selectedClipId: null,
  library: [],
  allTags: [],
  studioSegments: [],
  rangeStart: 0,
  rangeEnd: 15,
  rangeAnchor: null,
  studioTimeline: null,
};

const analyzeForm = document.getElementById("analyze-form");
const youtubeInput = document.getElementById("youtube-url");
const autoAnalyzeInput = document.getElementById("auto-analyze");
const analyzeBtn = document.getElementById("analyze-btn");
const inlineStatus = document.getElementById("inline-status");
const healthStatus = document.getElementById("health-status");
const progressFill = document.getElementById("progress-fill");
const pipelineSteps = document.getElementById("pipeline-steps");
const pipelineCard = document.getElementById("pipeline-card");
const pipelineTitle = document.getElementById("pipeline-title");
const pipelinePercent = document.getElementById("pipeline-percent");
const pipelineActions = document.getElementById("pipeline-actions");
const openLibraryBtn = document.getElementById("open-library-btn");
const openStudioBtn = document.getElementById("open-studio-btn");
const analyzeView = document.getElementById("analyze-view");
const studioView = document.getElementById("studio-view");
const libraryView = document.getElementById("library-view");
const clipList = document.getElementById("clip-list");
const libraryEmpty = document.getElementById("library-empty");
const libraryCount = document.getElementById("library-count");
const librarySearch = document.getElementById("library-search");
const groupFilters = document.getElementById("group-filters");
const tagFilters = document.getElementById("tag-filters");
const clipDetail = document.getElementById("clip-detail");
const clipDetailEmpty = document.getElementById("clip-detail-empty");
const detailVideo = document.getElementById("detail-video");
const detailGroup = document.getElementById("detail-group");
const detailSourceType = document.getElementById("detail-source-type");
const detailTime = document.getElementById("detail-time");
const detailSaved = document.getElementById("detail-saved");
const detailTitle = document.getElementById("detail-title");
const detailQuote = document.getElementById("detail-quote");
const detailRationale = document.getElementById("detail-rationale");
const detailSource = document.getElementById("detail-source");
const detailTags = document.getElementById("detail-tags");
const downloadClipBtn = document.getElementById("download-clip-btn");
const saveLocalBtn = document.getElementById("save-local-btn");
const editTitle = document.getElementById("edit-title");
const editTags = document.getElementById("edit-tags");
const saveMetaBtn = document.getElementById("save-meta-btn");
const refreshLibraryBtn = document.getElementById("refresh-library-btn");
const studioEmpty = document.getElementById("studio-empty");
const studioWorkspace = document.getElementById("studio-workspace");
const studioJobSelect = document.getElementById("studio-job-select");
const studioVideo = document.getElementById("studio-video");
const studioClipTimelineEl = document.getElementById("studio-clip-timeline");
const transcriptList = document.getElementById("transcript-list");
const transcriptSource = document.getElementById("transcript-source");
const clipTitleInput = document.getElementById("clip-title");
const clipGroupSelect = document.getElementById("clip-group");
const clipTagsInput = document.getElementById("clip-tags");
const clipQuoteInput = document.getElementById("clip-quote");
const saveLocalCheckbox = document.getElementById("save-local");
const saveClipBtn = document.getElementById("save-clip-btn");
const runAiBtn = document.getElementById("run-ai-btn");
const studioStatus = document.getElementById("studio-status");
const pipelineLogs = document.getElementById("pipeline-logs");
const pipelineLogOutput = document.getElementById("pipeline-log-output");
const refreshPipelineLogsBtn = document.getElementById("refresh-pipeline-logs-btn");
const studioLogs = document.getElementById("studio-logs");
const studioLogOutput = document.getElementById("studio-log-output");
const refreshStudioLogsBtn = document.getElementById("refresh-studio-logs-btn");

document.querySelectorAll("[data-view]").forEach((button) => {
  button.addEventListener("click", () => setView(button.dataset.view));
});

analyzeForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  await startAnalysis();
});

openLibraryBtn.addEventListener("click", () => setView("library"));
openStudioBtn.addEventListener("click", () => {
  if (state.currentJobId) {
    state.studioJobId = state.currentJobId;
  }
  setView("studio");
});
refreshLibraryBtn.addEventListener("click", () => loadLibrary());
librarySearch.addEventListener("input", debounce(() => {
  state.searchQuery = librarySearch.value.trim();
  loadLibrary();
}, 250));

studioJobSelect.addEventListener("change", () => loadStudioJob(studioJobSelect.value));
studioVideo.addEventListener("click", () => {
  if (studioVideo.paused) studioVideo.play();
  else studioVideo.pause();
});
saveClipBtn.addEventListener("click", saveManualClip);
runAiBtn.addEventListener("click", runAiOnJob);
downloadClipBtn.addEventListener("click", downloadSelectedClip);
saveLocalBtn.addEventListener("click", saveSelectedToDatabase);
saveMetaBtn.addEventListener("click", updateSelectedMetadata);
refreshPipelineLogsBtn.addEventListener("click", () => {
  if (state.currentJobId) loadJobLogs(state.currentJobId, pipelineLogOutput, pipelineLogs);
});
refreshStudioLogsBtn.addEventListener("click", () => {
  if (state.studioJobId) loadJobLogs(state.studioJobId, studioLogOutput, studioLogs);
});

studioVideo.addEventListener("timeupdate", () => {
  highlightTranscriptAtTime(studioVideo.currentTime);
});

init();

async function init() {
  initStudioTimeline();
  await refreshHealth();
  await loadLibrary();
  await loadStudioJobs();
}

function initStudioTimeline() {
  if (!studioClipTimelineEl || state.studioTimeline) return;
  state.studioTimeline = new ClipTimeline(studioClipTimelineEl, {
    video: studioVideo,
    onRangeChange: (start, end) => {
      state.rangeStart = start;
      state.rangeEnd = end;
      highlightRange();
    },
    onSeek: (time) => highlightTranscriptAtTime(time),
  });
}

async function refreshHealth() {
  const label = healthStatus.querySelector(".health-label");
  try {
    const response = await fetch("/api/health");
    const data = await response.json();
    healthStatus.className = "health-status is-ready";
    label.textContent = data.openai_configured ? data.model : "Prepare-only mode";
    if (!data.openai_configured) {
      autoAnalyzeInput.checked = false;
      autoAnalyzeInput.disabled = true;
    }
  } catch (_error) {
    healthStatus.className = "health-status is-error";
    label.textContent = "Backend offline";
    showInlineStatus("Start the server with uvicorn backend.app:app --reload", "error");
  }
}

async function startAnalysis() {
  const youtubeUrl = youtubeInput.value.trim();
  if (!youtubeUrl) return;

  analyzeBtn.disabled = true;
  analyzeBtn.textContent = "Starting…";
  pipelineCard.classList.remove("hidden");
  pipelineActions.classList.add("hidden");
  showInlineStatus("Downloading video and extracting transcript…", "info");
  resetPipelineUI();

  try {
    const response = await fetch("/api/analyze", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        youtube_url: youtubeUrl,
        auto_analyze: autoAnalyzeInput.checked,
      }),
    });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.detail || "Failed to start.");

    state.currentJobId = payload.job.id;
    pipelineLogs.classList.remove("hidden");
    loadJobLogs(state.currentJobId, pipelineLogOutput, pipelineLogs);
    pollJob(state.currentJobId, "analyze");
  } catch (error) {
    showInlineStatus(error.message, "error");
    analyzeBtn.disabled = false;
    analyzeBtn.textContent = "Start import";
  }
}

function pollJob(jobId, context = "analyze") {
  clearInterval(state.pollTimer);
  state.pollTimer = setInterval(async () => {
    try {
      const response = await fetch(`/api/jobs/${jobId}`);
      const job = (await response.json()).job;
      updatePipelineUI(job);
      loadJobLogs(jobId, context === "studio" ? studioLogOutput : pipelineLogOutput, context === "studio" ? studioLogs : pipelineLogs);

      if (job.status === "prepared" && job.stage === "prepared" && !job.auto_analyze && !job.analysis_error) {
        clearInterval(state.pollTimer);
        if (context === "analyze") finishAnalyze(job, "Transcript ready. Clip manually in Studio or run AI.");
        if (context === "studio") finishStudioPoll(job, "Transcript ready.");
      }

      if (job.status === "prepared" && job.analysis_error) {
        clearInterval(state.pollTimer);
        const message = job.analysis_error;
        if (context === "analyze") {
          finishAnalyze(job, "Import ready, but AI analysis failed. Open Studio to retry or clip manually.");
          showInlineStatus(message, "error");
        } else {
          finishStudioPoll(job, message, "error");
        }
      }

      if (job.status === "completed") {
        clearInterval(state.pollTimer);
        const count = (job.clips || []).length;
        if (context === "analyze") {
          finishAnalyze(job, `${count} clips indexed in your database.`);
        } else {
          finishStudioPoll(job, `AI analysis complete — ${count} clips indexed.`, "success");
          await loadStudioJob(jobId);
        }
        await loadLibrary();
        await loadStudioJobs();
      }

      if (job.status === "failed") {
        clearInterval(state.pollTimer);
        const message = job.error || "Job failed.";
        if (context === "analyze") {
          analyzeBtn.disabled = false;
          analyzeBtn.textContent = "Start import";
          showInlineStatus(message, "error");
        } else {
          finishStudioPoll(job, message, "error");
        }
      }
    } catch (_error) {
      clearInterval(state.pollTimer);
      if (context === "analyze") {
        analyzeBtn.disabled = false;
        analyzeBtn.textContent = "Start import";
        showInlineStatus("Lost connection while polling.", "error");
      } else {
        finishStudioPoll(null, "Lost connection while polling.", "error");
      }
    }
  }, 2000);
}

function finishStudioPoll(job, message, tone = "info") {
  runAiBtn.disabled = false;
  if (job) updateRunAiButton(job);
  showStudioStatus(message, tone === "info" ? "info" : tone);
}

function finishAnalyze(job, message) {
  analyzeBtn.disabled = false;
  analyzeBtn.textContent = "Start import";
  pipelineActions.classList.remove("hidden");
  showInlineStatus(message, job.analysis_error ? "error" : "success");
  state.studioJobId = job.id;
}

function updatePipelineUI(job) {
  progressFill.style.width = `${job.progress || 0}%`;
  pipelinePercent.textContent = `${job.progress || 0}%`;
  pipelineTitle.textContent = STAGE_TITLES[job.stage] || "Processing";

  pipelineSteps.querySelectorAll(".pipeline-step").forEach((step) => {
    step.classList.remove("is-active", "is-done");
    const stage = step.dataset.stage;
    const currentIndex = STAGE_ORDER.indexOf(job.stage);
    const stepIndex = STAGE_ORDER.indexOf(stage);

    if (stepIndex < currentIndex || job.status === "completed") {
      step.classList.add("is-done");
    } else if (stage === job.stage || (job.status === "prepared" && stage === "prepared")) {
      step.classList.add("is-active");
    }
  });
}

function resetPipelineUI() {
  progressFill.style.width = "0%";
  pipelinePercent.textContent = "0%";
  pipelineTitle.textContent = "Starting…";
  pipelineSteps.querySelectorAll(".pipeline-step").forEach((step) => {
    step.classList.remove("is-active", "is-done");
  });
}

async function loadStudioJobs() {
  const response = await fetch("/api/jobs/studio");
  const data = await response.json();
  const jobs = data.jobs || [];

  studioJobSelect.innerHTML = "";
  jobs.forEach((job) => {
    const option = document.createElement("option");
    option.value = job.id;
    const statusLabel = job.analysis ? "AI analyzed" : job.analysis_error ? "AI failed" : "No AI";
    option.textContent = `${job.video_title || job.youtube_url} · ${statusLabel}`;
    studioJobSelect.appendChild(option);
  });

  const hasJobs = jobs.length > 0;
  studioEmpty.classList.toggle("hidden", hasJobs);
  studioWorkspace.classList.toggle("hidden", !hasJobs);

  if (hasJobs) {
    const target = state.studioJobId && jobs.some((j) => j.id === state.studioJobId)
      ? state.studioJobId
      : jobs[0].id;
    studioJobSelect.value = target;
    await loadStudioJob(target);
  }
}

async function loadStudioJob(jobId) {
  if (!jobId) return;
  state.studioJobId = jobId;

  const [jobRes, transcriptRes] = await Promise.all([
    fetch(`/api/jobs/${jobId}`),
    fetch(`/api/jobs/${jobId}/transcript`),
  ]);
  const job = (await jobRes.json()).job;
  const transcript = await transcriptRes.json();

  studioVideo.src = `/api/jobs/${jobId}/source`;
  state.studioSegments = transcript.segments || [];
  transcriptSource.textContent = transcript.transcript_source || "captions";

  renderTranscript();
  state.rangeStart = 0;
  state.rangeEnd = Math.min(15, segmentEnd(state.studioSegments.at(-1)) || 15);
  updateRangeUI();

  studioVideo.onloadedmetadata = () => {
    state.studioTimeline?.setDuration(studioVideo.duration);
    state.studioTimeline?.setRange(state.rangeStart, state.rangeEnd, { silent: true });
  };
  if (studioVideo.readyState >= 1) {
    state.studioTimeline?.setDuration(studioVideo.duration);
  }

  updateRunAiButton(job);
  studioLogs.classList.remove("hidden");
  loadJobLogs(jobId, studioLogOutput, studioLogs);

  if (job.analysis_error) {
    showStudioStatus(job.analysis_error, "error");
  } else {
    studioStatus.classList.add("hidden");
  }
}

function updateRunAiButton(job) {
  if (!job) return;
  const hasAnalysis = Boolean(job.analysis);
  runAiBtn.textContent = hasAnalysis ? "Re-run AI analysis" : "Run AI analysis";
  runAiBtn.classList.remove("hidden");
}

function renderTranscript() {
  transcriptList.innerHTML = "";
  state.studioSegments.forEach((segment, index) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "transcript-line";
    button.dataset.index = String(index);
    button.innerHTML = `
      <span class="transcript-line__time">${formatTime(segment.start)}</span>
      <span class="transcript-line__text">${escapeHtml(segment.text)}</span>
    `;
    button.addEventListener("click", (event) => onTranscriptClick(index, event.shiftKey));
    transcriptList.appendChild(button);
  });
  highlightRange();
}

function segmentEnd(segment) {
  return Number(segment.start) + Number(segment.duration);
}

function onTranscriptClick(index, extend) {
  const segment = state.studioSegments[index];
  if (!segment) return;

  studioVideo.currentTime = segment.start;

  if (extend && state.rangeAnchor !== null) {
    const anchor = state.studioSegments[state.rangeAnchor];
    state.rangeStart = Math.min(anchor.start, segment.start);
    state.rangeEnd = Math.max(segmentEnd(anchor), segmentEnd(segment));
  } else {
    state.rangeAnchor = index;
    state.rangeStart = segment.start;
    state.rangeEnd = segmentEnd(segment);
  }

  updateRangeUI();
  highlightRange();
}

function highlightTranscriptAtTime(time) {
  transcriptList.querySelectorAll(".transcript-line").forEach((line, index) => {
    const segment = state.studioSegments[index];
    line.classList.toggle("is-active", segment && time >= segment.start && time < segmentEnd(segment));
  });
}

function highlightRange() {
  transcriptList.querySelectorAll(".transcript-line").forEach((line, index) => {
    const segment = state.studioSegments[index];
    const inRange = segment && segmentEnd(segment) >= state.rangeStart && segment.start <= state.rangeEnd;
    line.classList.toggle("is-in-range", inRange);
  });
  clipQuoteInput.value = quoteForRange(state.rangeStart, state.rangeEnd);
}

function quoteForRange(start, end) {
  return state.studioSegments
    .filter((segment) => segmentEnd(segment) >= start && segment.start <= end)
    .map((segment) => segment.text)
    .join(" ")
    .trim();
}

function setRangeFromPlayhead(edge) {
  const time = studioVideo.currentTime || 0;
  if (edge === "start") state.rangeStart = time;
  if (edge === "end") state.rangeEnd = Math.max(time, state.rangeStart + 1);
  updateRangeUI();
}

function syncRangeFromInputs() {
  state.rangeStart = ClipTimeline.parseTime(
    studioClipTimelineEl?.querySelector("[data-tl-start-input]")?.value || "0"
  );
  state.rangeEnd = Math.max(
    ClipTimeline.parseTime(studioClipTimelineEl?.querySelector("[data-tl-end-input]")?.value || "0"),
    state.rangeStart + 1
  );
  state.studioTimeline?.setRange(state.rangeStart, state.rangeEnd, { silent: true });
  highlightRange();
}

function updateRangeUI() {
  state.studioTimeline?.setRange(state.rangeStart, state.rangeEnd, { silent: true });
  highlightRange();
}

function previewRange() {
  state.studioTimeline?._previewRange();
}

async function saveManualClip() {
  if (!state.studioJobId) return;
  syncRangeFromInputs();
  saveClipBtn.disabled = true;
  showStudioStatus("Saving clip…", "info");

  try {
    const response = await fetch(`/api/jobs/${state.studioJobId}/clips`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        start_seconds: state.rangeStart,
        end_seconds: state.rangeEnd,
        title: clipTitleInput.value.trim(),
        group: clipGroupSelect.value,
        tags: parseTags(clipTagsInput.value),
        quote: clipQuoteInput.value.trim(),
        save_local: saveLocalCheckbox.checked,
      }),
    });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.detail || "Failed to save clip.");

    showStudioStatus("Clip saved to your database.", "success");
    clipTitleInput.value = "";
    await loadLibrary();
  } catch (error) {
    showStudioStatus(error.message, "error");
  } finally {
    saveClipBtn.disabled = false;
  }
}

async function runAiOnJob() {
  if (!state.studioJobId) return;
  runAiBtn.disabled = true;
  showStudioStatus("Running AI analysis…", "info");
  studioLogs.classList.remove("hidden");
  try {
    const response = await fetch(`/api/jobs/${state.studioJobId}/analyze-ai`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ replace_existing: true }),
    });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.detail || "AI analysis failed.");
    pollJob(state.studioJobId, "studio");
  } catch (error) {
    showStudioStatus(error.message, "error");
    runAiBtn.disabled = false;
  }
}

async function loadJobLogs(jobId, outputEl, containerEl) {
  if (!jobId || !outputEl) return;
  try {
    const response = await fetch(`/api/jobs/${jobId}/logs?limit=200`);
    const data = await response.json();
    const logs = data.logs || [];
    if (containerEl) containerEl.classList.toggle("hidden", logs.length === 0);
    outputEl.textContent = formatLogs(logs);
    outputEl.scrollTop = outputEl.scrollHeight;
  } catch (_error) {
    outputEl.textContent = "Unable to load logs.";
  }
}

function formatLogs(logs) {
  if (!logs.length) return "No log entries yet.";
  return logs
    .map((entry) => {
      const details = entry.details && Object.keys(entry.details).length
        ? `\n  ${JSON.stringify(entry.details, null, 2).replaceAll("\n", "\n  ")}`
        : "";
      return `[${entry.level?.toUpperCase() || "INFO"}] ${entry.ts} · ${entry.event}\n${entry.message}${details}`;
    })
    .join("\n\n");
}

async function loadLibrary() {
  const params = new URLSearchParams();
  if (state.searchQuery) params.set("q", state.searchQuery);
  if (state.activeFilter !== "all") params.set("group", state.activeFilter);
  if (state.activeTag) params.set("tag", state.activeTag);

  const response = await fetch(`/api/library?${params.toString()}`);
  const data = await response.json();
  state.library = data.clips || [];
  state.allTags = data.tags || [];

  libraryCount.textContent = String(state.library.length);
  libraryCount.classList.toggle("hidden", state.library.length === 0);

  renderFilters();
  renderLibrary();
}

function renderFilters() {
  const groups = ["all", ...new Set(state.library.map((clip) => clip.group))];
  groupFilters.innerHTML = "";
  groups.forEach((group) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = `filter-pill${group === state.activeFilter ? " is-active" : ""}`;
    button.textContent = group === "all" ? "All" : GROUP_LABELS[group] || group;
    button.addEventListener("click", () => {
      state.activeFilter = group;
      loadLibrary();
    });
    groupFilters.appendChild(button);
  });

  tagFilters.innerHTML = "";
  if (state.allTags.length) {
    const allTagBtn = document.createElement("button");
    allTagBtn.type = "button";
    allTagBtn.className = `filter-pill${!state.activeTag ? " is-active" : ""}`;
    allTagBtn.textContent = "All tags";
    allTagBtn.addEventListener("click", () => {
      state.activeTag = "";
      loadLibrary();
    });
    tagFilters.appendChild(allTagBtn);

    state.allTags.forEach((tag) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = `filter-pill${state.activeTag === tag ? " is-active" : ""}`;
      button.textContent = tag;
      button.addEventListener("click", () => {
        state.activeTag = tag;
        loadLibrary();
      });
      tagFilters.appendChild(button);
    });
  }
}

function renderLibrary() {
  const clips = state.library;
  clipList.innerHTML = "";
  const hasClips = clips.length > 0;
  libraryEmpty.classList.toggle("hidden", hasClips);
  clipList.classList.toggle("hidden", !hasClips);

  clips.forEach((clip) => {
    const row = document.createElement("button");
    row.type = "button";
    row.className = `clip-row${state.selectedClipId === clip.id ? " is-selected" : ""}`;
    row.dataset.clipId = clip.id;
    row.innerHTML = `
      <div class="clip-row__thumb">${formatDuration(clip.start_seconds, clip.end_seconds)}</div>
      <div>
        <p class="clip-row__title">${escapeHtml(clip.title)}</p>
        <div class="clip-row__meta">
          <span class="badge badge-teal">${escapeHtml(GROUP_LABELS[clip.group] || clip.group)}</span>
          <span class="badge badge-neutral">${clip.source_type === "manual" ? "Manual" : "AI"}</span>
        </div>
      </div>
    `;
    row.addEventListener("click", () => selectClip(clip, true));
    clipList.appendChild(row);
  });

  if (!hasClips) {
    clipDetail.classList.add("hidden");
    clipDetailEmpty.classList.remove("hidden");
    return;
  }

  const selected = clips.find((clip) => clip.id === state.selectedClipId) || clips[0];
  selectClip(selected, false);
}

function selectClip(clip, scrollIntoView) {
  state.selectedClipId = clip.id;
  clipDetail.classList.remove("hidden");
  clipDetailEmpty.classList.add("hidden");

  detailVideo.src = clip.clip_url;
  detailGroup.textContent = GROUP_LABELS[clip.group] || clip.group;
  detailSourceType.textContent = clip.source_type === "manual" ? "Manual clip" : "AI clip";
  detailTime.textContent = `${formatTime(clip.start_seconds)} – ${formatTime(clip.end_seconds)}`;
  detailSaved.classList.toggle("hidden", !clip.saved_at);
  detailTitle.textContent = clip.title;
  detailQuote.textContent = clip.quote ? `“${clip.quote}”` : "";
  detailRationale.textContent = clip.rationale || "";
  detailSource.textContent = clip.video_title ? `Source: ${clip.video_title}` : "";
  editTitle.value = clip.title;
  editTags.value = (clip.tags || []).join(", ");

  detailTags.innerHTML = "";
  (clip.tags || []).forEach((tag) => {
    const span = document.createElement("span");
    span.className = "badge badge-neutral";
    span.textContent = tag;
    detailTags.appendChild(span);
  });

  clipList.querySelectorAll(".clip-row").forEach((row) => {
    row.classList.toggle("is-selected", row.dataset.clipId === clip.id);
    if (row.dataset.clipId === clip.id && scrollIntoView) {
      row.scrollIntoView({ block: "nearest", behavior: "smooth" });
    }
  });
}

async function downloadSelectedClip() {
  const clip = state.library.find((item) => item.id === state.selectedClipId);
  if (!clip) return;
  window.open(`/api/database/clips/${clip.id}/download`, "_blank");
}

async function saveSelectedToDatabase() {
  const clip = state.library.find((item) => item.id === state.selectedClipId);
  if (!clip) return;
  saveLocalBtn.disabled = true;
  try {
    const response = await fetch(`/api/database/clips/${clip.id}/save`, { method: "POST" });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.detail || "Save failed.");
    await loadLibrary();
  } catch (error) {
    alert(error.message);
  } finally {
    saveLocalBtn.disabled = false;
  }
}

async function updateSelectedMetadata() {
  const clip = state.library.find((item) => item.id === state.selectedClipId);
  if (!clip) return;
  try {
    const response = await fetch(`/api/database/clips/${clip.id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        title: editTitle.value.trim(),
        tags: parseTags(editTags.value),
      }),
    });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.detail || "Update failed.");
    await loadLibrary();
  } catch (error) {
    alert(error.message);
  }
}

function setView(view) {
  state.activeView = view;
  analyzeView.classList.toggle("hidden", view !== "analyze");
  studioView.classList.toggle("hidden", view !== "studio");
  libraryView.classList.toggle("hidden", view !== "library");

  document.querySelectorAll(".nav-tab[data-view]").forEach((button) => {
    button.classList.toggle("is-active", button.dataset.view === view);
  });

  if (view === "library") loadLibrary();
  if (view === "studio") loadStudioJobs();
}

function showInlineStatus(message, tone) {
  inlineStatus.textContent = message;
  inlineStatus.className = `inline-status is-${tone}`;
  inlineStatus.classList.remove("hidden");
}

function showStudioStatus(message, tone) {
  studioStatus.textContent = message;
  studioStatus.className = `inline-status is-${tone}`;
  studioStatus.classList.remove("hidden");
}

function parseTags(value) {
  return value.split(",").map((tag) => tag.trim()).filter(Boolean);
}

function parseTimeInput(value) {
  const parts = value.split(":").map(Number);
  if (parts.length === 3) return parts[0] * 3600 + parts[1] * 60 + parts[2];
  if (parts.length === 2) return parts[0] * 60 + parts[1];
  return Number(value) || 0;
}

function formatTime(seconds) {
  const total = Math.max(0, Math.floor(Number(seconds) || 0));
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const secs = total % 60;
  if (hours) return `${hours}:${String(minutes).padStart(2, "0")}:${String(secs).padStart(2, "0")}`;
  return `${minutes}:${String(secs).padStart(2, "0")}`;
}

function formatDuration(start, end) {
  return `${Math.max(1, Math.round(Number(end) - Number(start)))}s`;
}

function escapeHtml(value) {
  return String(value || "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function debounce(fn, ms) {
  let timer;
  return (...args) => {
    clearTimeout(timer);
    timer = setTimeout(() => fn(...args), ms);
  };
}
