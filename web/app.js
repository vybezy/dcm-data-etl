// ---------- sidebar ----------

const sidebar = document.getElementById("sidebar");

// collapse / expand when the round button is clicked, and remember the choice
document.getElementById("sidebar-toggle").addEventListener("click", () => {
  sidebar.classList.toggle("collapsed");
  try {
    localStorage.setItem("sidebarCollapsed", sidebar.classList.contains("collapsed"));
  } catch (err) {
    // the browser can block storage; the button still works, it just won't be remembered
  }
});

try {
  if (localStorage.getItem("sidebarCollapsed") === "true") {
    sidebar.classList.add("collapsed");
  }
} catch (err) {
  // same as above
}

// ---------- pages ----------

// which function fills each page with data (more pages get added in the next steps)
const loaders = {
  dashboard: loadDashboard,
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

// ---------- talking to the api ----------

// sends a GET request and returns the json answer; an error status becomes an exception
async function getJson(url) {
  const response = await fetch(url);
  if (!response.ok) {
    throw new Error(`${response.status} ${response.statusText}`);
  }
  return response.json();
}

// 40894464 -> "39.0 MB" (the api sends raw bytes, the page decides how to show them)
function formatBytes(bytes) {
  return (bytes / 1024 / 1024).toFixed(1) + " MB";
}

// ---------- dashboard ----------

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

// ---------- start ----------

window.addEventListener("hashchange", showPage);   // sidebar click / back button
showPage();                                         // first load
