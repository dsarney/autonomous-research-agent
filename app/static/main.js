const PIPELINE = [
  { id: "planning", title: "Plan", hint: "Break the question into searches" },
  { id: "searching", title: "Search", hint: "Find and filter sources" },
  { id: "evaluating", title: "Evaluate", hint: "Spot gaps and follow up" },
  { id: "writing", title: "Write", hint: "Draft the cited report" },
];

document.addEventListener("DOMContentLoaded", () => {
  const form = document.getElementById("research-form");
  const statusEl = document.getElementById("status");
  const progressEl = document.getElementById("progress");
  const output = document.getElementById("output");
  const submit = document.getElementById("submit");
  const stop = document.getElementById("stop");
  const queryEl = document.getElementById("query");
  const fileInput = document.getElementById("documents");
  const fileList = document.getElementById("file-list");
  let activeRunId = null;
  let selectedFiles = [];

  fileInput.addEventListener("change", () => {
    for (const file of fileInput.files) {
      const exists = selectedFiles.some(
        (item) =>
          item.name === file.name &&
          item.size === file.size &&
          item.lastModified === file.lastModified,
      );
      if (!exists) selectedFiles.push(file);
    }
    fileInput.value = "";
    renderFileChips();
    syncQueryRequired();
  });

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    output.innerHTML = "";
    progressEl.innerHTML = "";
    const query = queryEl.value.trim();
    if (query.length < 3 && selectedFiles.length === 0) {
      statusEl.innerHTML =
        '<span class="error">Enter a research question or upload at least one document.</span>';
      return;
    }
    submit.disabled = true;
    stop.disabled = false;
    statusEl.textContent = "Starting research…";
    try {
      const body = new FormData();
      body.append("query", queryEl.value);
      body.append("wait", "false");
      for (const file of selectedFiles) {
        body.append("documents", file);
      }
      const created = await fetch("/research/run", {
        method: "POST",
        body,
      });
      if (!created.ok) {
        const err = await created
          .json()
          .catch(() => ({ detail: created.statusText }));
        throw new Error(formatDetail(err.detail) || "Failed to start research");
      }
      const run = await created.json();
      activeRunId = run.id;
      renderProgress(run);
      await poll(run.id);
    } catch (error) {
      statusEl.innerHTML = `<span class="error">${escapeHtml(error.message)}</span>`;
    } finally {
      submit.disabled = false;
      stop.disabled = true;
      activeRunId = null;
    }
  });

  stop.addEventListener("click", async () => {
    if (!activeRunId) return;
    stop.disabled = true;
    statusEl.textContent = "Stopping…";
    try {
      await fetch(`/research/${activeRunId}/stop`, { method: "POST" });
    } catch (error) {
      statusEl.innerHTML = `<span class="error">${escapeHtml(error.message)}</span>`;
    }
  });

  async function poll(id) {
    while (true) {
      const response = await fetch(`/research/${id}`);
      if (!response.ok) throw new Error("Could not load research run");
      const run = await response.json();
      statusEl.textContent = run.stage_label || `Status: ${run.status}`;
      renderProgress(run);
      if (["complete", "failed", "cancelled"].includes(run.status)) {
        render(run);
        return;
      }
      await new Promise((resolve) => setTimeout(resolve, 1200));
    }
  }

  function pipelineState(run, stepId) {
    const order = [
      "queued",
      "planning",
      "searching",
      "evaluating",
      "writing",
      "complete",
    ];
    let current = run.current_stage || "queued";
    let failedHere = false;
    // Failed/cancelled: current_stage is the terminal stage, so infer the step
    // that was running from the last non-terminal progress event.
    if (current === "failed" || run.status === "failed") {
      const prior = (run.progress || [])
        .filter((event) => event.stage !== "failed")
        .at(-1);
      current = prior?.stage || "planning";
      failedHere = current === stepId;
    }
    if (current === "cancelled" || run.status === "cancelled") {
      const prior = (run.progress || [])
        .filter((event) => event.stage !== "cancelled")
        .at(-1);
      current = prior?.stage || "planning";
      if (current === stepId) return "cancelled";
    }
    if (current === "complete" || run.status === "complete") return "done";
    const currentIndex = Math.max(order.indexOf(current), 0);
    const stepIndex = order.indexOf(stepId);
    if (stepIndex < 0) return "";
    if (stepIndex < currentIndex) return "done";
    if (stepIndex === currentIndex) return failedHere ? "failed" : "active";
    return "";
  }

  function renderProgress(run) {
    const steps = PIPELINE.map((step) => {
      const state = pipelineState(run, step.id);
      return `<div class="step ${state}"><strong>${step.title}</strong><span class="step-hint">${step.hint}</span></div>`;
    }).join("");
    const events = (run.progress || [])
      .map((event) => {
        const detail = event.detail
          ? `<span class="detail">${escapeHtml(event.detail)}</span>`
          : "";
        return `<li><strong>${escapeHtml(event.label)}</strong>${detail}</li>`;
      })
      .join("");
    let planHtml = "";
    if (run.plan) {
      const questions = (run.plan.sub_questions || [])
        .map((q) => `<li>${escapeHtml(q)}</li>`)
        .join("");
      planHtml = `<section class="panel"><h2>Research plan</h2><p>${escapeHtml(run.plan.objective)}</p><ul class="plan-preview">${questions}</ul></section>`;
    }
    const docs = (run.documents || [])
      .map(
        (doc) => `<li>${escapeHtml(doc.id)} ${escapeHtml(doc.filename)}</li>`,
      )
      .join("");
    const docsHtml = docs
      ? `<section class="panel"><h2>Uploaded documents</h2><ul>${docs}</ul></section>`
      : "";
    progressEl.innerHTML = `
      <div class="pipeline">${steps}</div>
      <div class="progress-grid">
        <section class="panel">
          <h2>Activity</h2>
          <ul class="activity">${events || "<li>Waiting to start…</li>"}</ul>
        </section>
        ${planHtml || `<section class="panel"><h2>Research plan</h2><p>The plan will appear here once planning finishes.</p></section>`}
      </div>
      ${docsHtml}
    `;
  }

  function render(run) {
    if (run.status === "cancelled") {
      output.innerHTML = `<div class="panel"><p>Research stopped. Edit your question and run it again.</p></div>`;
      return;
    }
    if (run.status === "failed") {
      output.innerHTML = `<div class="panel error"><p>${run.error || "Research failed."}</p></div>`;
      return;
    }
    const report = run.report;
    const findings = (report.findings || [])
      .map(
        (finding) => `
        <article class="panel">
          <h3>${escapeHtml(finding.claim)} <span class="badge ${finding.confidence}">${finding.confidence}</span></h3>
          <p>${escapeHtml(finding.evidence)}</p>
          <p><small>${escapeHtml(finding.confidence_rationale)}</small></p>
          <p><small>Sources: ${(finding.source_ids || []).join(", ") || "none"}</small></p>
        </article>
      `,
      )
      .join("");
    const risks =
      (report.gaps_and_risks || [])
        .map((item) => `<li>${escapeHtml(item)}</li>`)
        .join("") || "<li>None recorded</li>";
    const bib =
      (report.bibliography || [])
        .map((source) => bibliographyItem(source))
        .join("") || "<li>None</li>";
    const log = (run.iterations || [])
      .map((item) => {
        const queries =
          (item.searches || []).map((s) => s.query).join("; ") || "none";
        const gaps = (item.assessment.gaps || []).join(", ") || "none";
        return `<li>Iteration ${item.iteration}: searched ${escapeHtml(queries)}. Gaps: ${escapeHtml(gaps)}. Sufficient: ${item.assessment.sufficient}</li>`;
      })
      .join("");
    const docs = (run.documents || [])
      .map(
        (doc) => `<li>${escapeHtml(doc.id)} ${escapeHtml(doc.filename)}</li>`,
      )
      .join("");
    output.innerHTML = `
      <div class="report-toolbar">
        <h2 class="section-title">Report</h2>
        <p class="downloads">
          <a href="/research/${run.id}/export.docx">Download Word</a>
          <a href="/research/${run.id}/export.pdf">Download PDF</a>
        </p>
      </div>
      ${docs ? `<section class="panel"><h2>Uploaded documents</h2><ul>${docs}</ul></section>` : ""}
      <section class="panel">
        <h2>Executive summary</h2>
        <p>${escapeHtml(report.executive_summary)}</p>
      </section>
      <h2 class="section-title">Findings</h2>
      <div class="findings-grid">${findings}</div>
      <div class="split-grid">
        <section class="panel">
          <h2>Gaps and risks</h2>
          <ul>${risks}</ul>
        </section>
        <section class="panel">
          <h2>Bibliography</h2>
          <ul>${bib}</ul>
        </section>
      </div>
      <section class="panel">
        <h2>Investigation log</h2>
        <ul>${log || "<li>No iterations recorded</li>"}</ul>
      </section>
    `;
  }

  function renderFileChips() {
    fileList.innerHTML = selectedFiles
      .map((file, index) => {
        return `<li class="file-chip"><span>${escapeHtml(file.name)}</span><button type="button" data-index="${index}" aria-label="Remove ${escapeAttr(file.name)}">&times;</button></li>`;
      })
      .join("");
    fileList.querySelectorAll("button").forEach((button) => {
      button.addEventListener("click", () => {
        selectedFiles.splice(Number(button.dataset.index), 1);
        renderFileChips();
        syncQueryRequired();
      });
    });
  }

  function syncQueryRequired() {
    if (selectedFiles.length) {
      queryEl.removeAttribute("required");
      queryEl.removeAttribute("minlength");
    } else {
      queryEl.setAttribute("minlength", "3");
    }
  }
});

function bibliographyItem(source) {
  const snippet = escapeHtml(source.snippet);
  if (source.kind === "upload" || !isWebUrl(source.url)) {
    return `<li>[${escapeHtml(source.id)}] ${escapeHtml(source.title)} — ${snippet}</li>`;
  }
  return `<li>[${escapeHtml(source.id)}] <a href="${escapeAttr(source.url)}" target="_blank" rel="noopener">${escapeHtml(source.title)}</a> — ${snippet}</li>`;
}

function isWebUrl(value) {
  try {
    const parsed = new URL(String(value || ""));
    return parsed.protocol === "http:" || parsed.protocol === "https:";
  } catch {
    return false;
  }
}

function formatDetail(detail) {
  if (!detail) return "";
  if (typeof detail === "string") return detail;
  return JSON.stringify(detail);
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;");
}

function escapeAttr(value) {
  return escapeHtml(value).replaceAll('"', "&quot;");
}
