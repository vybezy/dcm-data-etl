// ------------------------- sidebar -------------------------
const sidebar = document.getElementById("sidebar");

// collapse / expand when the round button is clicked, and remember choice
document.getElementById("sidebar-toggle").addEventListener("click", () => {
  sidebar.classList.toggle("collapsed");
  try {
    localStorage.setItem("sidebarCollapsed", sidebar.classList.contains("collapsed"));
  } catch (err) {
    // the browser can block storage. the button still works, it just won't be remembered
  }
});

try {
  if (localStorage.getItem("sidebarCollapsed") === "true") {
    sidebar.classList.add("collapsed");
  }
} catch (err) {
  // same as above
}

// ------------------------- pages -------------------------

// which function fills each page with data
const loaders = {
  dashboard: loadDashboard,
  browse: showPatients,
  import: openImportPage,
  history: loadHistory,
  settings: loadSettings,
  reset: openResetPage,
};

// shows the page named after the "#" in the address, e.g. /#settings
function showPage() {
  let name = location.hash.slice(1) || "dashboard";
  if (!document.getElementById(name)) {
    name = "dashboard";   // unknown name in the address: fall back to the dashboard
  }

  document.querySelectorAll(".page").forEach((page) => {
    page.classList.toggle("active", page.id === name);
  });
  document.querySelectorAll(".menu a").forEach((link) => {
    link.classList.toggle("active", link.getAttribute("href") === "#" + name);
  });

  if (loaders[name]) {
    loaders[name]();
  }
}

// ------------------------- connection w/ api -------------------------

// sends a request and returns the json answer. an error status becomes an exception
// that carries the api's own message, e.g. "an import is already running"
async function request(url, options = {}) {
  const response = await fetch(url, options);
  if (!response.ok) {
    throw new Error(await errorMessage(response));
  }
  return response.json();
}

// error answers look like {"detail": ...}: a sentence from our services,
// or a list of problems when pydantic rejected the input (422)
async function errorMessage(response) {
  try {
    const body = await response.json();
    if (typeof body.detail === "string") {
      return body.detail;
    }
    if (Array.isArray(body.detail)) {
      // each problem says where (e.g. ["body", "workers"]) and what: "workers: must be ≥ 0"
      return body.detail
        .map((problem) => (problem.loc ? problem.loc.at(-1) + ": " : "") + problem.msg)
        .join("; ");
    }
  } catch (err) {
    // the body wasn't json (e.g. a plain "Internal Server Error")
  }
  return `${response.status} ${response.statusText}`;
}

function getJson(url) {
  return request(url);
}

// POST / PUT with a json body
function sendJson(method, url, data) {
  return request(url, {
    method: method,
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
}


function formatBytes(bytes) {
  return (bytes / 1024 / 1024).toFixed(1) + " MB";
}

// ------------------------- dashboard -------------------------

async function loadDashboard() {
  const error = document.getElementById("dashboard-error");
  error.textContent = "";

  try {
    const stats = await getJson("/api/stats");
    document.getElementById("stat-patients").textContent = stats.patients;
    document.getElementById("stat-studies").textContent = stats.studies;
    document.getElementById("stat-series").textContent = stats.series;
    document.getElementById("stat-instances").textContent = stats.instances;
    document.getElementById("stat-pixels").textContent = formatBytes(stats.total_pixel_bytes);
  } catch (err) {
    error.textContent = "Couldn't load stats (is the database running?): " + err.message;
  }
}

// builds a table; rows are clickable when onRowClick is given.
// values go in with textContent (never innerHTML), so they can't run as html
function renderTable(columns, rows, onRowClick) {
  const table = document.createElement("table");

  const head = table.createTHead().insertRow();
  columns.forEach((column) => {
    const th = document.createElement("th");
    th.textContent = column.title;
    head.appendChild(th);
  });

  const body = table.createTBody();
  rows.forEach((row) => {
    const tr = body.insertRow();
    columns.forEach((column) => {
      const value = column.value(row);
      // no value -> "–" (written out instead of value || "–", so a real 0 still shows as 0)
      const empty = value === null || value === undefined || value === "";
      tr.insertCell().textContent = empty ? "–" : value;
    });
    if (onRowClick) {
      tr.classList.add("clickable");
      tr.addEventListener("click", () => onRowClick(row));
    }
  });

  return table;
}

// ------------------------- browse -------------------------

// where the user is: patient -> study -> series -> slices
const browse = {
  patient: null,
  study: null,
  series: null,
  slices: [],
  index: 0,
  window: "auto",
};

const browseList = document.getElementById("browse-list");
const browseError = document.getElementById("browse-error");
const breadcrumb = document.getElementById("breadcrumb");
const viewer = document.getElementById("viewer");
const sliceImage = document.getElementById("slice-image");
const sliceInfo = document.getElementById("slice-info");
const sliceSlider = document.getElementById("slice-slider");
const imageError = document.getElementById("image-error");

// asks the api then shows a table
async function loadBrowseLevel(url, columns, emptyText, onRowClick) {
  browseError.textContent = "";
  viewer.hidden = true;
  browseList.replaceChildren();   // removes old table
  renderBreadcrumb();

  try {
    const rows = await getJson(url);
    if (rows.length === 0) {
      browseList.textContent = emptyText;
    } else {
      browseList.appendChild(renderTable(columns, rows, onRowClick));
    }
  } catch (err) {
    browseError.textContent = "Couldn't load: " + err.message;
  }
}


function showPatients() {
  Object.assign(browse, { patient: null, study: null, series: null });
  loadBrowseLevel("/api/patients", [
    { title: "ID", value: (p) => p.patient_id },
    { title: "Name", value: (p) => p.patient_name },
    { title: "Sex", value: (p) => p.sex },
    { title: "Studies", value: (p) => p.study_count },
  ], "No patients yet. Import some files first.", showStudies);
}


function showStudies(patient) {
  Object.assign(browse, { patient, study: null, series: null });
  loadBrowseLevel(`/api/patients/${patient.patient_id}/studies`, [
    { title: "Date", value: (s) => s.study_date },
    { title: "Description", value: (s) => s.study_description },
    { title: "Series", value: (s) => s.series_count },
  ], "This patient has no studies.", showSeries);
}


function showSeries(study) {
  Object.assign(browse, { study, series: null });
  loadBrowseLevel(`/api/studies/${study.study_id}/series`, [
    { title: "#", value: (s) => s.series_number },
    { title: "Modality", value: (s) => s.modality },
    { title: "Body part", value: (s) => s.body_part_examined },
    { title: "Description", value: (s) => s.series_description },
    {
      title: "Slice thickness",
      value: (s) => (s.slice_thickness_mm == null ? null : s.slice_thickness_mm + " mm"),
    },
    { title: "Slices", value: (s) => s.instance_count },
  ], "This study has no series.", openViewer);
}

// load the list of slices once then show one picture at a time
async function openViewer(series) {
  browse.series = series;
  browseError.textContent = "";
  renderBreadcrumb();

  try {
    browse.slices = await getJson(`/api/series/${series.series_id}/instances`);
  } catch (err) {
    browseError.textContent = "Couldn't load slices: " + err.message;
    return;
  }
  if (browse.slices.length === 0) {
    browseError.textContent = "This series has no slices.";
    return;
  }

  browseList.replaceChildren();
  viewer.hidden = false;
  browse.index = 0;
  sliceSlider.max = browse.slices.length - 1;
  showSlice();
}


function showSlice() {
  const slice = browse.slices[browse.index];
  imageError.textContent = "";
  sliceImage.src = `/api/instances/${slice.file_id}/image?window=${browse.window}`;
  sliceInfo.textContent = `Slice ${browse.index + 1} / ${browse.slices.length}`;
  sliceSlider.value = browse.index;

  document.querySelectorAll(".window-buttons button").forEach((button) => {
    button.classList.toggle("active", button.dataset.window === browse.window);
  });
}

function moveSlice(step) {
  const next = browse.index + step;
  if (next >= 0 && next < browse.slices.length) {
    browse.index = next;
    showSlice();
  }
}

// "Patients > D** J*** > 2025-03-14 > Series 1"; earlier parts are buttons that go back
function renderBreadcrumb() {
  const parts = [["Patients", showPatients]];
  if (browse.patient) {
    parts.push([browse.patient.patient_name, () => showStudies(browse.patient)]);
  }
  if (browse.study) {
    const studyName = browse.study.study_date || "Study " + browse.study.study_id;
    parts.push([studyName, () => showSeries(browse.study)]);
  }
  if (browse.series) {
    parts.push(["Series " + (browse.series.series_number ?? browse.series.series_id), null]);
  }

  breadcrumb.replaceChildren();
  parts.forEach(([text, onClick], i) => {
    if (i > 0) {
      breadcrumb.append(" › ");
    }
    const part = document.createElement(onClick ? "button" : "span");
    part.textContent = text;
    if (onClick) {
      part.addEventListener("click", onClick);
    }
    breadcrumb.appendChild(part);
  });
}

document.getElementById("slice-prev").addEventListener("click", () => moveSlice(-1));
document.getElementById("slice-next").addEventListener("click", () => moveSlice(1));

sliceSlider.addEventListener("input", () => {
  browse.index = Number(sliceSlider.value);
  showSlice();
});

document.querySelectorAll(".window-buttons button").forEach((button) => {
  button.addEventListener("click", () => {
    browse.window = button.dataset.window;
    showSlice();
  });
});

// left / right arrow keys scroll through the slices while the viewer is open
document.addEventListener("keydown", (event) => {
  // the slider moves with arrow keys
  if (viewer.hidden || location.hash !== "#browse" || event.target === sliceSlider) {
    return;
  }
  if (event.key === "ArrowLeft") {
    moveSlice(-1);
  }
  if (event.key === "ArrowRight") {
    moveSlice(1);
  }
});

// the api answers with error (404 no pixel data, 422 compressed) instead of a picture
sliceImage.addEventListener("error", () => {
  imageError.textContent = "This slice can't be shown (no pixel data stored, or compressed).";
});

// ------------------------- import -------------------------

const importForm = document.getElementById("import-form");
const importStart = document.getElementById("import-start");
const importError = document.getElementById("import-error");
const importProgress = document.getElementById("import-progress");
let pollTimer = null;   // the running setInterval, so it can be stopped later

importForm.addEventListener("submit", async (event) => {
  event.preventDefault();   // a form normally reloads the page; we send json ourselves instead
  importError.textContent = "";

  try {
    const job = await sendJson("POST", "/api/imports", {
      folder: document.getElementById("import-folder").value,
      dry_run: document.getElementById("import-dry-run").checked,
    });
    startPolling(job.id);   // 202: it started, now watch it
  } catch (err) {
    importError.textContent = err.message;   // e.g. 409 "an import is already running"
  }
});

// asks the api about this import every second until it stops running
function startPolling(importId) {
  stopPolling();
  importStart.disabled = true;
  importProgress.hidden = false;
  checkProgress(importId);
  pollTimer = setInterval(() => checkProgress(importId), 1000);
}

function stopPolling() {
  clearInterval(pollTimer);
  pollTimer = null;
  importStart.disabled = false;
}

async function checkProgress(importId) {
  let job;
  try {
    // our import is one of the newest ones (a cli run could have started meanwhile)
    const imports = await getJson("/api/imports?limit=5");
    job = imports.find((item) => item.id === importId);
  } catch (err) {
    importError.textContent = "Couldn't read the progress: " + err.message;
    stopPolling();
    return;
  }

  if (!job) {
    importError.textContent = "Import #" + importId + " is no longer in the history.";
    stopPolling();
    return;
  }

  showProgress(job);
  if (job.status !== "running") {
    stopPolling();
  }
}

function showProgress(job) {
  const total = job.total_files ?? job.processed;
  const bar = document.getElementById("import-bar");
  bar.max = Math.max(total, 1);   // a max of 0 isn't allowed (empty folder)
  bar.value = job.processed;

  document.getElementById("import-title").textContent = `Import #${job.id}: ${job.status}`;
  document.getElementById("import-counts").textContent =
    `${job.processed} / ${total} files · inserted ${job.inserted} · ` +
    `duplicates ${job.duplicates} · skipped ${job.skipped} · ` +
    `dry run ${job.dry_run} · errors ${job.errors}`;
}

function openImportPage() {
  loadFolders();
  resumeImport();
}

// fills the dropdown with the folders inside data/ (keeps the current choice if it still exists)
async function loadFolders() {
  const select = document.getElementById("import-folder");
  const chosen = select.value;

  try {
    const folders = await getJson("/api/folders");
    const options = [new Option("All of data/", "")];
    folders.forEach((folder) => options.push(new Option(folder, folder)));
    select.replaceChildren(...options);
    if (folders.includes(chosen)) {
      select.value = chosen;
    }
  } catch (err) {
    importError.textContent = "Couldn't load the folders: " + err.message;
  }
}

document.getElementById("refresh-folders").addEventListener("click", loadFolders);

// opening the page while an import runs (e.g. after a refresh) shows its progress again
async function resumeImport() {
  if (pollTimer) {
    return;
  }
  try {
    const [latest] = await getJson("/api/imports?limit=1");
    if (latest && latest.status === "running") {
      startPolling(latest.id);
    }
  } catch (err) {
    importError.textContent = "Couldn't check for a running import: " + err.message;
  }
}

// ------------------------- import history -------------------------

async function loadHistory() {
  const error = document.getElementById("history-error");
  const list = document.getElementById("history-list");
  error.textContent = "";
  list.replaceChildren();

  try {
    const imports = await getJson("/api/imports?limit=50");
    if (imports.length === 0) {
      list.textContent = "No imports yet.";
      return;
    }
    list.appendChild(renderTable([
      { title: "#", value: (i) => i.id },
      // the api sends "2026-10-22T14:05:31+00:00"; show it in local time
      { title: "Started", value: (i) => new Date(i.started_at).toLocaleString() },
      { title: "Status", value: (i) => i.status },
      {
        title: "Files",
        value: (i) => (i.total_files == null ? i.processed : `${i.processed} / ${i.total_files}`),
      },
      { title: "Inserted", value: (i) => i.inserted },
      { title: "Duplicates", value: (i) => i.duplicates },
      { title: "Skipped", value: (i) => i.skipped },
      { title: "Dry run", value: (i) => i.dry_run },
      { title: "Errors", value: (i) => i.errors },
    ], imports, null));   // null: history rows aren't clickable
  } catch (err) {
    error.textContent = "Couldn't load the history: " + err.message;
  }
}

// ------------------------- settings -------------------------

const settingsSaved = document.getElementById("settings-saved");
const settingsError = document.getElementById("settings-error");

// the api works in bytes; the page shows MB because they're easier to read
const MB = 1024 * 1024;
let loadedSettings = null;

function toUnit(bytes, unit) {
  return Number((bytes / unit).toFixed(2));   // 103809024 bytes -> 99 (MB)
}

function fromUnit(input, unit, savedBytes) {
  if (input.valueAsNumber === toUnit(savedBytes, unit)) {
    return savedBytes;
  }
  // valueAsNumber is NaN for an empty box; JSON turns NaN into null, so the api answers 422
  return Math.round(input.valueAsNumber * unit);
}

async function loadSettings() {
  settingsSaved.textContent = "";
  settingsError.textContent = "";
  try {
    showSettings(await getJson("/api/settings"));
  } catch (err) {
    settingsError.textContent = "Couldn't load the settings: " + err.message;
  }
}

function showSettings(settings) {
  loadedSettings = settings;
  document.getElementById("set-min-size").value = toUnit(settings.min_file_size, MB);
  document.getElementById("set-max-size").value = toUnit(settings.max_file_size, MB);
  document.getElementById("set-max-age").value = settings.max_file_age_months;
  document.getElementById("set-workers").value = settings.workers;
}

document.getElementById("settings-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  settingsSaved.textContent = "";
  settingsError.textContent = "";

  // PUT replaces all settings, so every field is sent
  const settings = {
    min_file_size: fromUnit(document.getElementById("set-min-size"), MB,
                            loadedSettings.min_file_size),
    max_file_size: fromUnit(document.getElementById("set-max-size"), MB,
                            loadedSettings.max_file_size),
    max_file_age_months: document.getElementById("set-max-age").valueAsNumber,
    workers: document.getElementById("set-workers").valueAsNumber,
  };

  try {
    showSettings(await sendJson("PUT", "/api/settings", settings));
    settingsSaved.textContent = "Settings saved.";
  } catch (err) {
    settingsError.textContent = err.message;   // e.g. "max_file_size must be bigger than min_file_size"
  }
});

// ------------------------- reset -------------------------

const resetConfirm = document.getElementById("reset-confirm");
const resetButton = document.getElementById("reset-button");
const resetDone = document.getElementById("reset-done");
const resetError = document.getElementById("reset-error");
const resetDialog = document.getElementById("reset-dialog");

// every visit starts locked: the box is emptied and the button disabled
function openResetPage() {
  resetConfirm.value = "";
  resetButton.disabled = true;
  resetDone.textContent = "";
  resetError.textContent = "";
}

// the button only unlocks when exactly RESET is typed (the api checks the same word)
resetConfirm.addEventListener("input", () => {
  resetButton.disabled = resetConfirm.value !== "RESET";
});

document.getElementById("reset-form").addEventListener("submit", (event) => {
  event.preventDefault();
  resetDialog.returnValue = "";
  resetDialog.showModal();
});

resetDialog.addEventListener("close", () => {
  if (resetDialog.returnValue === "confirm") {
    runReset();
  }
});

async function runReset() {
  resetDone.textContent = "";
  resetError.textContent = "";
  resetButton.disabled = true;   // no double clicks while it runs

  try {
    await sendJson("POST", "/api/admin/reset", { confirm: resetConfirm.value });
    resetConfirm.value = "";
    resetDone.textContent = "Database reset. Import your files again to see them.";
  } catch (err) {
    resetError.textContent = err.message;   // e.g. 409 "cannot reset while an import is running"
    resetButton.disabled = resetConfirm.value !== "RESET";
  }
}

// ------------------------- start site -------------------------

window.addEventListener("hashchange", showPage);   // sidebar click / back button
showPage();                                         // first load
