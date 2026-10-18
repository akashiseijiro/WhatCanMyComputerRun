"use strict";

// ---------- tiny helpers (all dynamic text goes through textContent, never innerHTML) ----------
function h(tag, attrs, ...kids) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v == null || v === false) continue;
    if (k === "class") el.className = v;
    else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else if (v === true) el.setAttribute(k, "");
    else el.setAttribute(k, v);
  }
  const add = (kid) => {
    if (kid == null || kid === false) return;
    if (Array.isArray(kid)) kid.forEach(add);
    else el.append(kid instanceof Node ? kid : document.createTextNode(String(kid)));
  };
  kids.forEach(add);
  return el;
}

const app = document.getElementById("app");

// replaceChildren() would render null/false as the text "null"/"false"; skip them.
function fill(el, ...nodes) {
  el.replaceChildren(...nodes.flat().filter((n) => n != null && n !== false));
}
const state = { hw: null, report: null, tips: null, token: 0, health: null };

const FRIENDLY = {
  offline: ["Can't reach the app", "The CanIRunIt background service isn't responding. Close and reopen the app."],
  timeout: ["Taking too long", "The request timed out. Check your internet connection and try again."],
  steam_unavailable: ["Steam can't be reached", "You may be offline, or the Steam store is down. Check your connection and try again."],
  steam_rate_limited: ["Steam is rate limiting requests", "Wait a minute, then try again."],
  game_not_found: ["No store data for this game", "Steam has no store page data for it. Try another result."],
  llm_unavailable: ["AI features unavailable", "Add your ANTHROPIC_API_KEY to the .env file next to the app, then restart it."],
  llm_rate_limited: ["The AI service is busy", "It is rate limiting requests. Wait a minute and try again."],
};

class ApiError extends Error {
  constructor(code, detail) { super(detail); this.code = code; }
}

async function api(path, opts = {}, timeoutMs = 150000) {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), timeoutMs);
  let res;
  try {
    res = await fetch(path, { ...opts, signal: ctrl.signal });
  } catch (e) {
    throw e.name === "AbortError"
      ? new ApiError("timeout", "Request timed out.")
      : new ApiError("offline", "Could not reach the app.");
  } finally {
    clearTimeout(timer);
  }
  let body = null;
  try { body = await res.json(); } catch { /* non-JSON error body */ }
  if (!res.ok) {
    const detail = typeof body?.detail === "string" ? body.detail : res.statusText || "Request failed";
    throw new ApiError(body?.code || `http_${res.status}`, detail);
  }
  return body;
}

function errorBox(err, retry) {
  const [title, hint] = FRIENDLY[err.code] || ["Something went wrong", err.message];
  return h("div", { class: "alert", role: "alert" },
    h("h2", null, title),
    h("p", null, hint),
    FRIENDLY[err.code] && err.message && err.message !== hint ? h("p", { class: "muted small" }, err.message) : null,
    retry ? h("button", { class: "btn", type: "button", onclick: retry }, "Try again") : null);
}

function loading(text, sub) {
  return h("div", { class: "card row", role: "status" },
    h("div", { class: "spinner", "aria-hidden": "true" }),
    h("div", null, h("strong", null, text), sub ? h("div", { class: "muted small" }, sub) : null));
}

const VERDICT = {
  BELOW_MIN: ["❌", "Below minimum"],
  MEETS_MIN: ["⚠️", "Meets minimum"],
  MEETS_RECOMMENDED: ["✅", "Meets recommended"],
  EXCEEDS_RECOMMENDED: ["🚀", "Exceeds recommended"],
  UNKNOWN: ["❔", "Unknown"],
};
const GB = (mb) => `${(mb / 1024).toFixed(mb % 1024 ? 1 : 0)} GB`;

// ---------- screens ----------
async function showSystem(rescan = false) {
  const my = ++state.token;
  fill(app, h("h1", { tabindex: "-1" }, "My System"), loading(rescan ? "Re-scanning your hardware…" : "Scanning your hardware…"));
  focusHeading();
  try {
    state.hw = await api(rescan ? "/api/hardware/rescan" : "/api/hardware", rescan ? { method: "POST" } : {});
  } catch (e) {
    if (my !== state.token) return;
    fill(app, h("h1", { tabindex: "-1" }, "My System"), errorBox(e, () => showSystem(true)),
      h("div", { class: "card" }, h("h2", null, "Automatic detection didn't work?"),
        h("p", null, "You can pick your CPU, GPU and other parts yourself."),
        h("a", { class: "btn", href: "#manual" }, "Choose hardware manually")));
    return;
  }
  if (my !== state.token) return;
  renderSystem();
}

function renderSystem() {
  const hw = state.hw;
  const primary = hw.gpus.reduce((best, g) => {
    const rank = (x) => [x.kind === "discrete", x.vram_mb || 0];
    if (!best) return g;
    const [a, b] = [rank(g), rank(best)];
    return a[0] !== b[0] ? (a[0] ? g : best) : (a[1] > b[1] ? g : best);
  }, null);

  const gpuCards = hw.gpus.length ? hw.gpus.map((g) => h("div", { class: "card" },
    h("h2", null, "GPU ", g === primary && hw.gpus.length > 1 ? h("span", { class: "badge" }, "used for gaming") : null),
    h("dl", { class: "kv" },
      h("dt", null, "Name"), h("dd", null, g.name),
      h("dt", null, "Type"), h("dd", null, g.kind === "integrated" ? "Integrated" : "Discrete"),
      h("dt", null, g.vram_shared ? "Memory" : "VRAM"),
      h("dd", null, g.vram_mb ? GB(g.vram_mb) + (g.vram_assumed ? ` (assumed; ${g.vram_source === "manual" ? "usually" : "detected"} ${g.vram_detected_mb ? GB(g.vram_detected_mb) : "unknown"} by default, adjustable in software)` : g.vram_shared ? " (shared with system RAM, adjustable)" : "") : "Not detected"),
      h("dt", null, "Driver"), h("dd", null, g.driver_version || "Unknown")))) :
    [h("div", { class: "card" }, h("h2", null, "GPU"), h("p", { class: "muted" }, "Not detected"))];

  const drives = hw.storage.length ? hw.storage.map((d) =>
    h("div", null, `${d.letter} ${d.free_gb ?? "?"} GB free${d.total_gb ? ` of ${d.total_gb} GB` : ""}`,
      d.media_type !== "unknown" ? ` (${d.media_type.toUpperCase()})` : "")) : [h("span", { class: "muted" }, "Not detected")];

  fill(app, 
    h("h1", { tabindex: "-1" }, "My System"),
    h("div", { class: "row", style: "margin-bottom:1rem" },
      h("span", { class: `badge ${hw.device_type}` }, deviceLabel(hw)),
      h("span", { class: "muted small" }, hw.source === "manual" ? "Manual selection" : hw.source.startsWith("mock:") ? `Demo profile: ${hw.source.slice(5)}` : "Detected on this PC"),
      h("button", { class: "btn secondary", type: "button", onclick: () => showSystem(true) }, hw.source === "manual" ? "Re-scan (use detected hardware)" : "Re-scan"),
      h("a", { class: "btn secondary", href: "#manual" }, "Choose hardware manually"),
      h("a", { class: "btn", href: "#search" }, "Check a game →")),
    hw.warnings.length ? h("div", { class: "warnbox", role: "status" },
      h("strong", null, "Some things couldn't be detected:"), h("ul", null, hw.warnings.map((w) => h("li", null, w)))) : null,
    h("div", { class: "grid" },
      h("div", { class: "card" }, h("h2", null, "CPU"), hw.cpu ? h("dl", { class: "kv" },
        h("dt", null, "Model"), h("dd", null, hw.cpu.model),
        h("dt", null, "Cores"), h("dd", null, hw.cpu.cores ? `${hw.cpu.cores} cores / ${hw.cpu.threads ?? "?"} threads` : "Unknown"),
        h("dt", null, "Clock"), h("dd", null, hw.cpu.base_clock_mhz ? `${(hw.cpu.base_clock_mhz / 1000).toFixed(2)} GHz base` : "Unknown"))
        : h("p", { class: "muted" }, "Not detected")),
      gpuCards,
      h("div", { class: "card" }, h("h2", null, "Memory & storage"), h("dl", { class: "kv" },
        h("dt", null, "RAM"), h("dd", null, hw.ram?.total_gb ? `${hw.ram.total_gb} GB${hw.ram.speed_mhz ? ` @ ${hw.ram.speed_mhz} MHz` : ""}` : "Not detected"),
        h("dt", null, "Drives"), h("dd", null, drives))),
      h("div", { class: "card" }, h("h2", null, "System"), h("dl", { class: "kv" },
        h("dt", null, "OS"), h("dd", null, hw.os?.name ? `${hw.os.name} (build ${hw.os.build ?? "?"})` : "Not detected"),
        h("dt", null, "DirectX"), h("dd", null, hw.os?.directx || "Unknown"),
        h("dt", null, "Display"), h("dd", null, hw.display?.width ? `${hw.display.width}×${hw.display.height}${hw.display.refresh_hz ? ` @ ${hw.display.refresh_hz} Hz` : ""}` : "Not detected"),
        h("dt", null, "Model"), h("dd", null, [hw.manufacturer, hw.model].filter(Boolean).join(" ") || "Unknown")))));
  focusHeading();
}

function deviceLabel(hw) {
  const kind = { handheld: "🎮 Handheld", laptop: "💻 Laptop", desktop: "🖥️ Desktop" }[hw.device_type] || hw.device_type;
  return hw.handheld_name ? `${kind} · ${hw.handheld_name}` : kind;
}

function showSearch(prefill = "") {
  state.token++;
  const input = h("input", { type: "search", id: "q", name: "q", placeholder: "Game name, e.g. Cyberpunk 2077", "aria-label": "Game name", autocomplete: "off", value: prefill, maxlength: "100" });
  const results = h("div", { "aria-live": "polite" });
  const form = h("form", { class: "search", onsubmit: (e) => { e.preventDefault(); runSearch(input.value, results, btn); } },
    input, h("button", { class: "btn", type: "submit", id: "go" }, "Search"));
  const btn = form.querySelector("#go");
  fill(app, h("h1", { tabindex: "-1" }, "Search for a game"), form, results);
  focusHeading();
  if (prefill) runSearch(prefill, results, btn);
}

async function runSearch(term, box, btn) {
  term = term.trim();
  if (!term) { fill(box, h("p", { class: "muted" }, "Type a game name first.")); return; }
  const my = ++state.token;
  btn.disabled = true;
  fill(box, loading(`Searching Steam for “${term}”…`));
  try {
    const items = await api(`/api/search?q=${encodeURIComponent(term)}`);
    if (my !== state.token) return;
    if (!items.length) {
      fill(box, h("div", { class: "card" }, h("p", null, `No Steam results for “${term}”.`),
        h("p", { class: "muted small" }, "Check the spelling, or try a shorter name. Games not on Steam aren't supported yet.")));
    } else {
      fill(box, h("ul", { class: "results" }, items.map((g) => h("li", null,
        h("button", { class: "result", type: "button", onclick: () => { location.hash = `#report/${g.appid}`; } },
          g.image ? h("img", { src: g.image, alt: "", loading: "lazy" }) : null,
          h("span", { class: "name" }, g.name),
          g.price ? h("span", { class: "price" }, g.price) : null)))));
    }
  } catch (e) {
    if (my === state.token) fill(box, errorBox(e, () => runSearch(term, box, btn)));
  } finally {
    if (my === state.token) btn.disabled = false;
  }
}

async function showReport(appid) {
  const my = ++state.token;
  state.report = null; state.tips = null;
  const nav = document.getElementById("nav-report");
  nav.hidden = false; nav.href = `#report/${appid}`;
  fill(app, h("h1", { tabindex: "-1" }, "Report"),
    loading("Checking your system against this game…", "Fetching requirements and comparing hardware. The first check of a game can take up to a minute."));
  focusHeading();
  try {
    const rep = await api(`/api/report/${appid}`);
    if (my !== state.token) return;
    state.report = rep;
    renderReport(rep, appid);
  } catch (e) {
    if (my !== state.token) return;
    fill(app, h("h1", { tabindex: "-1" }, "Report"), errorBox(e, () => showReport(appid)),
      h("a", { class: "btn secondary", href: "#search" }, "← Back to search"));
    focusHeading();
  }
}

function renderReport(rep, appid) {
  const g = rep.game;
  const price = g.is_free ? "Free" : g.price ? g.price.formatted || `${(g.price.final_cents / 100).toFixed(2)} ${g.price.currency}` : "No price listed";
  const discount = g.price && g.price.discount_percent > 0 ? ` (${g.price.discount_percent}% off)` : "";
  const hw = state.hw;

  fill(app, 
    h("div", { class: "row", style: "margin-bottom:1rem" },
      h("a", { class: "btn secondary", href: "#search" }, "← Search"),
      h("button", { class: "btn secondary", type: "button", id: "copy", onclick: copyReport }, "Copy report"),
      h("span", { id: "copied", class: "muted", role: "status" })),
    h("div", { class: "card hero" },
      g.header_image ? h("img", { src: g.header_image, alt: "" }) : null,
      h("div", null,
        h("h1", { tabindex: "-1" }, g.name),
        h("div", null, `${price}${discount}`),
        h("div", { class: "muted" }, g.release_date ? `${g.coming_soon ? "Releases" : "Released"}: ${g.release_date}` : null),
        h("a", { href: g.store_url, target: "_blank", rel: "noopener noreferrer" }, "Steam store page"))),
    h("div", { class: `verdictbar ${rep.recommendation}` },
      h("p", { class: "headline" }, rep.headline),
      h("div", { class: "muted" }, `Confidence: ${rep.confidence}` + (rep.bottleneck && rep.recommendation !== "INSUFFICIENT_DATA" ? ` · limited by ${rep.bottleneck.toUpperCase()}` : "") +
        (hw ? ` · for your ${hw.handheld_name || hw.device_type}` : "")),
      rep.reasons.length ? h("ul", null, rep.reasons.map((r) => h("li", null, r))) : null),
    rep.warnings.length ? h("div", { class: "warnbox", role: "status" }, h("ul", null, rep.warnings.map((w) => h("li", null, w)))) : null,
    comparisonTable(rep),
    settingsCard(rep.settings),
    tipsCard(appid),
    sourcesCard(rep));
  focusHeading();
}

function comparisonTable(rep) {
  if (!rep.rows.length) return h("div", { class: "card" }, h("h2", null, "Requirements"), h("p", null, "No system requirements could be found for this game."));
  const rows = rep.rows.map((r) => {
    const [icon, label] = VERDICT[r.verdict];
    return h("tr", { class: r.specified ? "" : "dim" },
      h("td", { "data-label": "Component" }, h("strong", null, r.label)),
      h("td", { "data-label": "Your PC" }, r.yours,
        r.specified ? h("div", { class: `vtag ${r.verdict}` }, h("span", { "aria-hidden": "true" }, icon), label,
          r.verdict !== "UNKNOWN" && r.confidence !== "high" ? ` · ${r.confidence} confidence` : "") : null,
        r.note ? h("span", { class: "note" }, r.note) : null),
      h("td", { "data-label": "Minimum" }, r.minimum || "—"),
      h("td", { "data-label": "Recommended" }, r.recommended || "—"));
  });
  return h("div", { class: "card" }, h("h2", null, "Your PC vs. requirements"),
    h("table", { class: "cmp" },
      h("thead", null, h("tr", null, ["Component", "Your PC", "Minimum", "Recommended"].map((t) => h("th", { scope: "col" }, t)))),
      h("tbody", null, rows)));
}

function settingsCard(s) {
  if (!s) return null;
  if (!s.available) return h("div", { class: "card" }, h("h2", null, "Recommended settings"), h("p", { class: "muted" }, s.unavailable_reason));
  const fg = s.frame_generation, up = s.upscaler, hd = s.handheld;
  return h("div", { class: "card" },
    h("h2", null, "Recommended settings"),
    !s.playable ? h("div", { class: "alert" }, h("strong", null, "Likely not playable "), "even at the lowest settings.") : null,
    h("dl", { class: "kv" },
      h("dt", null, "Graphics preset"), h("dd", null, h("strong", null, s.preset)),
      h("dt", null, "Resolution"), h("dd", null, s.render_resolution === s.output_resolution ? s.output_resolution : `${s.render_resolution} rendered → ${s.output_resolution} shown`),
      h("dt", null, "Upscaling"), h("dd", null, up.needed ? `${up.technology} ${up.mode}` : `Not needed (${up.technology} optional)`, h("span", { class: "note muted small", style: "display:block" }, up.note)),
      h("dt", null, "Frame generation"), h("dd", null, fg.suggested ? "Optional" : "Not recommended",
        h("span", { class: "muted small", style: "display:block" }, `${fg.technology ? fg.technology + ". " : ""}${fg.note} ${fg.latency_caveat}`)),
      h("dt", null, "Expected FPS"), h("dd", null, h("strong", null, `~${s.fps.low}–${s.fps.high} FPS`),
        h("span", { class: "muted small", style: "display:block" }, `Estimate only, limited by your ${s.fps.limited_by}. ${s.fps.label} Target: ${s.target_fps} FPS.`))),
    hd ? h("div", { class: "card", style: "background:var(--panel-2);margin-top:1rem" },
      h("h3", null, `Handheld tips · ${hd.device}`),
      h("dl", { class: "kv" },
        h("dt", null, "Power mode"), h("dd", null, `${hd.power_mode} (${hd.watts} W)`, hd.power_note ? h("span", { class: "muted small", style: "display:block" }, hd.power_note) : null),
        h("dt", null, "FPS cap"), h("dd", null, `${hd.fps_cap} FPS plugged in, ${hd.battery_fps_cap} FPS on battery`),
        h("dt", null, "Battery"), h("dd", null, hd.battery_note))) : null,
    s.vram_tip ? h("div", { class: "warnbox" }, s.vram_tip) : null,
    s.notes.length || s.warnings.length ? h("ul", null, [...s.warnings, ...s.notes].map((n) => h("li", null, n))) : null);
}

function tipsCard(appid) {
  const body = h("div", { "aria-live": "polite" });
  const btn = h("button", { class: "btn secondary", type: "button", onclick: async () => {
    btn.disabled = true;
    fill(body, loading("Asking the AI for game-specific tips…"));
    try {
      const t = await api(`/api/tips/${appid}`);
      state.tips = t.tips;
      fill(body, 
        t.warning ? h("p", { class: "muted" }, t.warning) : null,
        t.tips.length ? h("ul", null, t.tips.map((x) => h("li", null, h("strong", null, `${x.setting}: `), x.advice))) :
          (t.warning ? null : h("p", { class: "muted" }, "The AI had no confident tips for this game.")),
        t.tips.length ? h("p", { class: "muted small" }, "AI-generated and unverified. Treat as hints, and check them against the in-game menus.") : null);
      if (t.tips.length) btn.hidden = true;
    } catch (e) {
      fill(body, errorBox(e));
    }
    btn.disabled = false;
  } }, "Get game-specific tips (AI)");
  return h("div", { class: "card" }, h("h2", null, "Game-specific tips"), h("p", { class: "muted small" }, "Optional. Uses the Anthropic API."), btn, body);
}

function sourcesCard(rep) {
  const g = rep.game, req = g.requirements;
  const bench = rep.rows.find((r) => r.benchmark)?.benchmark;
  return h("div", { class: "card" }, h("h2", null, "Data sources"),
    h("ul", null,
      h("li", null, "Requirements: ", h("a", { href: g.store_url, target: "_blank", rel: "noopener noreferrer" }, "Steam store page"),
        req ? ` (read ${req.parse_method === "deterministic" ? "directly" : "with AI assistance"})` : ""),
      ...(req?.source_urls || []).map((u) => h("li", null, h("a", { href: u, target: "_blank", rel: "noopener noreferrer" }, u))),
      bench ? h("li", null, `CPU/GPU comparison: AI-estimated relative scores on the ${bench} scale (approximate).`) : null,
      h("li", null, "Settings and FPS: rule-based estimate from those scores, not a measured benchmark.")));
}


// ---------- manual hardware selection ----------
const MANUAL_KEY = "canirunit.manual";
const DEVICE_LABELS = { desktop: "🖥️ Desktop PC", laptop: "💻 Laptop", handheld: "🎮 Handheld" };

function partPicker(label, items, visible, optionLabel) {
  const filter = h("input", { type: "search", placeholder: `Filter ${label}…`, "aria-label": `Filter ${label}`, autocomplete: "off" });
  const select = h("select", { "aria-label": label, required: true });
  const refresh = () => {
    const q = filter.value.trim().toLowerCase(), cur = select.value;
    const groups = new Map();
    for (const it of items) {
      if (!visible(it) || (q && !optionLabel(it).toLowerCase().includes(q))) continue;
      if (!groups.has(it.family)) groups.set(it.family, []);
      groups.get(it.family).push(it);
    }
    fill(select, groups.size ? [...groups].map(([fam, list]) =>
      h("optgroup", { label: fam }, list.map((it) => h("option", { value: it.id }, optionLabel(it))))) :
      h("option", { value: "", disabled: true }, "No matching parts"));
    if (cur && [...select.options].some((o) => o.value === cur)) select.value = cur;
  };
  filter.addEventListener("input", refresh);
  refresh();
  return { filter, select, refresh,
    el: h("div", { class: "field" }, h("label", null, label), filter, select) };
}

function simpleSelect(label, options, value) {
  const select = h("select", { "aria-label": label },
    options.map(([v, text]) => h("option", { value: String(v) }, text)));
  if (value != null) select.value = String(value);
  return { select, el: h("div", { class: "field" }, h("label", null, label), select) };
}

async function showManual() {
  const my = ++state.token;
  fill(app, h("h1", { tabindex: "-1" }, "Choose your hardware"), loading("Loading parts list…"));
  focusHeading();
  let cat;
  try { cat = await api("/api/hardware/catalog"); } catch (e) {
    if (my === state.token) fill(app, h("h1", { tabindex: "-1" }, "Choose your hardware"), errorBox(e, showManual));
    return;
  }
  if (my !== state.token) return;
  let saved = {};
  try { saved = JSON.parse(localStorage.getItem(MANUAL_KEY) || "{}"); } catch { /* ignore */ }

  const device = simpleSelect("Device type", Object.entries(DEVICE_LABELS), saved.device_type || "desktop");
  const handheld = simpleSelect("Handheld model", [["", "Other / choose parts myself"], ...cat.handhelds.map((x) => [x.id, x.name])], saved.handheld_id || "");
  const showAll = h("input", { type: "checkbox", id: "showall" });
  const kind = () => device.select.value;
  const cpuVisible = (c) => showAll.checked || (kind() === "handheld" ? ["handheld", "laptop"].includes(c.segment) : c.segment === kind());
  const gpuVisible = (g) => showAll.checked || (kind() === "desktop" ? ["desktop", "integrated"].includes(g.segment) : ["laptop", "integrated"].includes(g.segment));
  const gpuLabel = (g) => `${g.name.replace(/ Laptop GPU$/, " (laptop)")} · ${g.kind === "integrated" ? "integrated" : g.vram_gb + " GB"} · ${g.year}`;
  const cpu = partPicker("CPU", cat.cpus, cpuVisible, (c) => `${c.name} · ${c.cores}C/${c.threads}T · ${c.year}`);
  const gpu = partPicker("GPU", cat.gpus, gpuVisible, gpuLabel);
  const ram = simpleSelect("RAM", cat.ram_options_gb.map((n) => [n, `${n} GB`]), saved.ram_gb ?? 16);
  const res = simpleSelect("Screen resolution", cat.resolutions.map(([w, hh]) => [`${w}x${hh}`, `${w} × ${hh}`]), saved.width ? `${saved.width}x${saved.height}` : "1920x1080");
  const refresh = simpleSelect("Refresh rate", cat.refresh_options_hz.map((n) => [n, `${n} Hz`]), saved.refresh_hz ?? 60);
  const storType = simpleSelect("Game drive type", [["ssd", "SSD"], ["hdd", "Hard drive (HDD)"]], saved.storage_type || "ssd");
  const free = h("input", { type: "number", min: "1", max: "100000", step: "1", required: true, value: String(saved.storage_free_gb ?? 200), "aria-label": "Free space on the game drive in GB" });
  const win = simpleSelect("Windows", [["11", "Windows 11"], ["10", "Windows 10"]], saved.windows || "11");

  const restoreParts = () => {
    cpu.refresh(); gpu.refresh();
    if (saved.cpu_id && [...cpu.select.options].some((o) => o.value === saved.cpu_id)) cpu.select.value = saved.cpu_id;
    if (saved.gpu_id && [...gpu.select.options].some((o) => o.value === saved.gpu_id)) gpu.select.value = saved.gpu_id;
  };
  const applyPreset = () => {
    const p = cat.handhelds.find((x) => x.id === handheld.select.value);
    if (!p) return;
    showAll.checked = true; cpu.refresh(); gpu.refresh();
    cpu.select.value = p.cpu; gpu.select.value = p.gpu;
    ram.select.value = String(p.ram_gb); res.select.value = `${p.width}x${p.height}`; refresh.select.value = String(p.refresh_hz);
  };
  const syncVisibility = () => { handheldField.hidden = kind() !== "handheld"; };
  const handheldField = handheld.el;
  device.select.addEventListener("change", () => { syncVisibility(); if (kind() !== "handheld") handheld.select.value = ""; cpu.refresh(); gpu.refresh(); });
  handheld.select.addEventListener("change", applyPreset);
  showAll.addEventListener("change", () => { cpu.refresh(); gpu.refresh(); });
  syncVisibility(); restoreParts();

  const status = h("div", { role: "status", "aria-live": "polite" });
  const form = h("form", { class: "manual", onsubmit: async (e) => {
    e.preventDefault();
    if (!cpu.select.value || !gpu.select.value) { fill(status, h("p", { class: "warnbox" }, "Pick a CPU and a GPU first.")); return; }
    const [w, hh] = res.select.value.split("x").map(Number);
    const body = {
      device_type: kind(), handheld_id: kind() === "handheld" && handheld.select.value ? handheld.select.value : null,
      cpu_id: cpu.select.value, gpu_id: gpu.select.value, ram_gb: Number(ram.select.value),
      storage_free_gb: Number(free.value), storage_type: storType.select.value,
      width: w, height: hh, refresh_hz: Number(refresh.select.value), windows: win.select.value,
    };
    submit.disabled = true; fill(status, loading("Applying…"));
    try {
      state.hw = await api("/api/hardware/manual", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
      try { localStorage.setItem(MANUAL_KEY, JSON.stringify(body)); } catch { /* private mode etc. */ }
      if (location.hash === "#system") route(); else location.hash = "#system";
    } catch (err) {
      fill(status, errorBox(err)); submit.disabled = false;
    }
  } });
  const submit = h("button", { class: "btn", type: "submit" }, "Use this hardware");
  fill(form,
    h("p", { class: "muted" }, "Pick the parts in your machine (2019 and newer). This replaces automatic detection until you press Re-scan."),
    h("div", { class: "formgrid" }, device.el, handheldField, cpu.el, gpu.el, ram.el, res.el, refresh.el,
      h("div", { class: "field" }, h("label", null, "Free space on game drive (GB)"), free), storType.el, win.el),
    h("label", { class: "check" }, showAll, " Show all parts (ignore device type)"),
    h("div", { class: "row", style: "margin-top:1rem" }, submit, h("a", { class: "btn secondary", href: "#system" }, "Cancel")),
    status);
  fill(app, h("h1", { tabindex: "-1" }, "Choose your hardware"), h("div", { class: "card" }, form));
  focusHeading();
}

// ---------- copy report ----------
function reportText() {
  const r = state.report;
  if (!r) return "";
  const lines = [`CanIRunIt: ${r.game.name}`, `Verdict: ${r.headline} (confidence: ${r.confidence})`];
  if (state.hw) lines.push(`System: ${deviceLabel(state.hw)}`);
  r.reasons.forEach((x) => lines.push(`- ${x}`));
  lines.push("", "Component | Your PC | Minimum | Recommended | Result");
  r.rows.forEach((x) => lines.push(`${x.label} | ${x.yours} | ${x.minimum || "-"} | ${x.recommended || "-"} | ${VERDICT[x.verdict][1]}`));
  const s = r.settings;
  if (s && s.available) {
    lines.push("", `Settings: ${s.preset}, ${s.render_resolution}${s.upscaler.needed ? ` (${s.upscaler.technology} ${s.upscaler.mode})` : ""}, ~${s.fps.low}-${s.fps.high} FPS (estimate)`);
    if (s.handheld) lines.push(`Handheld: ${s.handheld.power_mode} ${s.handheld.watts} W, cap ${s.handheld.fps_cap}/${s.handheld.battery_fps_cap} FPS (plugged/battery)`);
  }
  if (state.tips?.length) { lines.push("", "AI tips (unverified):"); state.tips.forEach((t) => lines.push(`- ${t.setting}: ${t.advice}`)); }
  lines.push("", `Steam: ${r.game.store_url}`);
  return lines.join("\n");
}

async function copyReport() {
  const out = document.getElementById("copied"), text = reportText();
  try {
    await navigator.clipboard.writeText(text);
  } catch {
    const ta = h("textarea", { style: "position:fixed;opacity:0", "aria-hidden": "true" });
    ta.value = text; document.body.append(ta); ta.select();
    let ok = false;
    try { ok = document.execCommand("copy"); } catch { /* ignore */ }
    ta.remove();
    if (!ok) { out.textContent = "Couldn't copy automatically."; return; }
  }
  out.textContent = "Copied!";
  setTimeout(() => { out.textContent = ""; }, 2500);
}

// ---------- routing ----------
function focusHeading() {
  const el = app.querySelector("h1");
  if (el) el.focus({ preventScroll: true });
  window.scrollTo(0, 0);
}

function route() {
  const [page, arg] = (location.hash || "#system").slice(1).split("/");
  const navId = page === "manual" ? "system" : page;
  document.querySelectorAll(".tab").forEach((a) => {
    if (a.id === `nav-${navId}`) a.setAttribute("aria-current", "page"); else a.removeAttribute("aria-current");
  });
  if (page === "search") showSearch();
  else if (page === "manual") showManual();
  else if (page === "report" && /^\d+$/.test(arg || "")) showReport(Number(arg));
  else if (page === "report") location.hash = "#search";
  else showSystem();
}

async function init() {
  try {
    state.health = await api("/api/health", {}, 8000);
    if (!state.health.has_api_key) {
      fill(document.getElementById("notice"), h("div", { class: "notice" }, h("div", { class: "box" },
        "No ANTHROPIC_API_KEY found. Hardware and Steam requirements work, but CPU/GPU comparisons and tips need the key in your .env file.")));
    }
  } catch { /* the first screen will show the real error */ }
  window.addEventListener("hashchange", route);
  route();
}
init();
