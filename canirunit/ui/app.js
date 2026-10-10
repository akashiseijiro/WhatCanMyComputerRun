// Milestone 1 placeholder: proves the UI -> API wiring. Real screens arrive in milestone 6.
async function load(method, path) {
  const status = document.getElementById("status");
  status.textContent = "Scanning…";
  try {
    const res = await fetch(path, { method });
    if (!res.ok) throw new Error((await res.json()).detail || res.statusText);
    document.getElementById("hw").textContent = JSON.stringify(await res.json(), null, 2);
    status.textContent = "Hardware detected.";
  } catch (e) {
    status.textContent = "Error: " + e.message;
  }
}
document.getElementById("rescan").addEventListener("click", () => load("POST", "/api/hardware/rescan"));
load("GET", "/api/hardware");
