const form = document.querySelector("#uploadForm");
const input = document.querySelector("#certificateInput");
const processBox = document.querySelector("#processBox");
const statusText = document.querySelector("#statusText");
const resultsBody = document.querySelector("#resultsBody");
const exportButton = document.querySelector("#exportButton");
const fileCount = document.querySelector("#fileCount");
const verifiedCount = document.querySelector("#verifiedCount");
const reviewCount = document.querySelector("#reviewCount");
const avgConfidence = document.querySelector("#avgConfidence");
const dropZone = input.closest(".drop-zone");
const resultStatuses = new Set(["verified", "partial_match", "needs_review", "fetch_failed", "mismatch", "qr_not_found"]);

const processingLines = [
  "Parsing uploaded PDFs...",
  "Finding QR codes inside the certificate canvas...",
  "Roaming through the NPTEL verification path...",
  "Opening the official archive PDF link...",
  "Comparing uploaded marks with online marks...",
  "Scoring confidence for each student...",
];

let currentResults = [];
let processTimer = null;
let processIndex = 0;

input.addEventListener("change", handleFilesChanged);

["dragenter", "dragover"].forEach((eventName) => {
  dropZone.addEventListener(eventName, (event) => {
    event.preventDefault();
    dropZone.classList.add("is-dragging");
  });
});

["dragleave", "drop"].forEach((eventName) => {
  dropZone.addEventListener(eventName, (event) => {
    event.preventDefault();
    dropZone.classList.remove("is-dragging");
  });
});

dropZone.addEventListener("drop", (event) => {
  const droppedFiles = event.dataTransfer?.files;
  if (!droppedFiles?.length) return;
  input.files = droppedFiles;
  handleFilesChanged();
});

function handleFilesChanged() {
  const count = input.files.length;
  currentResults = [];
  renderResults(currentResults);
  statusText.textContent = count
    ? `${count} PDF${count === 1 ? "" : "s"} loaded. Ready to verify.`
    : "Waiting for PDF uploads.";
  exportButton.hidden = true;
  exportButton.disabled = true;
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (!input.files.length) {
    statusText.textContent = "Choose at least one NPTEL certificate PDF.";
    return;
  }

  const formData = new FormData();
  [...input.files].forEach((file) => formData.append("certificates", file));

  setBusy(true);
  exportButton.hidden = true;
  startProcessing();

  try {
    const response = await fetch("/api/verify", { method: "POST", body: formData });
    const payload = await response.json();
    if (!response.ok) {
      throw new Error(payload.error || "Verification failed.");
    }
    currentResults = payload.results;
    renderResults(currentResults);
    statusText.textContent = `Finished ${currentResults.length} certificate${currentResults.length === 1 ? "" : "s"}. CSV is ready.`;
    exportButton.hidden = currentResults.length === 0;
    exportButton.disabled = currentResults.length === 0;
  } catch (error) {
    statusText.textContent = error.message;
  } finally {
    stopProcessing();
    setBusy(false);
  }
});

exportButton.addEventListener("click", async () => {
  setBusy(true);
  statusText.textContent = "Preparing your CSV report...";
  try {
    const response = await fetch("/api/export", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ results: currentResults }),
    });
    if (!response.ok) {
      const payload = await response.json().catch(() => ({}));
      throw new Error(payload.error || "Could not export the CSV report.");
    }
    const blob = await response.blob();
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = "certforge-nptel-report.csv";
    link.click();
    URL.revokeObjectURL(url);
    statusText.textContent = "CSV report downloaded.";
  } catch (error) {
    statusText.textContent = error.message;
  } finally {
    setBusy(false);
  }
});

function setBusy(isBusy) {
  form.querySelector(".primary").disabled = isBusy;
  exportButton.disabled = isBusy || currentResults.length === 0;
}

function startProcessing() {
  processIndex = 0;
  processBox.classList.add("processing");
  statusText.textContent = processingLines[processIndex];
  processTimer = window.setInterval(() => {
    processIndex = (processIndex + 1) % processingLines.length;
    statusText.textContent = processingLines[processIndex];
  }, 1400);
}

function stopProcessing() {
  window.clearInterval(processTimer);
  processTimer = null;
  processBox.classList.remove("processing");
}

function renderResults(results) {
  fileCount.textContent = `${results.length} file${results.length === 1 ? "" : "s"} processed`;
  const verified = results.filter((result) => result.status === "verified").length;
  const review = results.length - verified;
  verifiedCount.textContent = verified;
  reviewCount.textContent = review;
  const average = results.length
    ? Math.round(results.reduce((sum, result) => sum + confidenceValue(result.confidence), 0) / results.length)
    : 0;
  avgConfidence.textContent = `${average}%`;

  if (!results.length) {
    resultsBody.innerHTML = '<tr class="empty-row"><td colspan="8">Upload certificates to start verification.</td></tr>';
    return;
  }

  resultsBody.innerHTML = results.map(renderRow).join("");

  // Set meter widths via DOM (CSP-safe — property assignment, not inline attribute)
  resultsBody.querySelectorAll(".meter-fill[data-pct]").forEach((el) => {
    el.style.width = `${el.dataset.pct}%`;
  });
}

function renderRow(result) {
  const uploaded = result.uploaded || {};
  const online = result.online || {};
  const mismatches = Object.entries(result.field_matches || {})
    .filter(([, matched]) => matched === false)
    .map(([field]) => field.replaceAll("_", " "))
    .join(", ");
  const confidence = confidenceValue(result.confidence);
  const status = safeStatus(result.status);
  const qr = result.qr_url && isSafeUrl(result.qr_url)
    ? `<a class="evidence-link" href="${escapeAttribute(result.qr_url)}" target="_blank" rel="noreferrer noopener">QR link</a>`
    : `<span class="subtle">No QR</span>`;

  return `
    <tr>
      <td>
        <span class="student-name">${escapeHtml(uploaded.name || "Unknown student")}</span>
        ${online.name && normalizeText(uploaded.name) !== normalizeText(online.name) ? `<span class="subtle">Online: ${escapeHtml(online.name)}</span>` : ""}
      </td>
      <td>${pair(uploaded.course, online.course)}</td>
      <td>${pair(uploaded.course_code, online.course_code)}</td>
      <td>${pair(uploaded.assignment_score, online.assignment_score)}</td>
      <td>${pair(uploaded.exam_score, online.exam_score)}</td>
      <td>${pair(uploaded.total_score, online.total_score)}</td>
      <td class="confidence">
        <span class="status ${status}">${escapeHtml(status.replaceAll("_", " "))}</span>
        <strong class="subtle">${confidence}% confidence</strong>
        <div class="meter"><span class="meter-fill" data-pct="${confidence}"></span></div>
        ${mismatches ? `<span class="subtle">Mismatch: ${escapeHtml(mismatches)}</span>` : ""}
      </td>
      <td>${qr}<span class="subtle">${result.same_file ? "Exact PDF match" : "Field comparison"}</span></td>
    </tr>
  `;
}

function confidenceValue(value) {
  const confidence = Number(value);
  return Number.isFinite(confidence) ? Math.max(0, Math.min(100, Math.round(confidence))) : 0;
}

function safeStatus(value) {
  return resultStatuses.has(value) ? value : "needs_review";
}

function pair(uploadedValue, onlineValue) {
  return `
    <div class="pair">
      <span>Uploaded: ${escapeHtml(uploadedValue || "not parsed")}</span>
      <span>Online: ${escapeHtml(onlineValue || "not parsed")}</span>
    </div>
  `;
}

function isSafeUrl(value) {
  try {
    const url = new URL(value);
    return url.protocol === "https:" &&
      (url.hostname === "nptel.ac.in" || url.hostname.endsWith(".nptel.ac.in"));
  } catch {
    return false;
  }
}

function normalizeText(value) {
  return String(value || "").trim().toLowerCase().replace(/\s+/g, " ");
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function escapeAttribute(value) {
  return escapeHtml(value).replaceAll("`", "&#096;");
}
