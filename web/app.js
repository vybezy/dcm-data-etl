// sidebar

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

// pages

// which function fills each page with data
const loaders = {
  dashboard: loadDashboard,
  browse: showPatients,
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

// connection w/ api

// sends a GET request and returns the json answer: an error status -> exception
async function getJson(url) {
  const response = await fetch(url);
  if (!response.ok) {
    throw new Error(`${response.status} ${response.statusText}`);
  }
  return response.json();
}


function formatBytes(bytes) {
  return (bytes / 1024 / 1024).toFixed(1) + " MB";
}

// dashboard

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

// builds table where every row is clickable. values are put in with textContent, never
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
    tr.addEventListener("click", () => onRowClick(row));
  });

  return table;
}

// browse

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

// start

window.addEventListener("hashchange", showPage);   // sidebar click / back button
showPage();                                         // first load
