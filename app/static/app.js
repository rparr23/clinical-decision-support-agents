// ClearPath CDS front end: plain JavaScript, no build step.
const $ = (sel) => document.querySelector(sel);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

const EXAMPLES = [
  ["Imaging", "Is a chest x-ray appropriate on hospital admission for a patient with no cardiopulmonary symptoms?"],
  ["Order check", "Check a chest x-ray order for P-0002 before her knee replacement"],
  ["Billing", "What is the billing code and fee for sterile water used in nebulizer treatments?"],
  ["Multi-agent", "I was diagnosed with COPD. What supplies will I need and what will they cost?"],
  ["Similar patients", "Find patients similar to a 65-year-old male with diabetes and hypertension"],
  ["Limits", "We need 150 units of A4216 this month. Is that within the coverage limit?"],
];
const ORDERS = ["Chest x-ray PA and lateral", "CT chest without contrast", "CT chest with IV contrast", "CTA chest", "MRI chest", "FDG-PET/CT"];
const REPORTS = {
  "Complete report": `EXAM: Chest radiograph, PA and lateral views.
INDICATION: Preoperative evaluation, history of COPD.
COMPARISON: Prior chest radiograph from last year.
TECHNIQUE: Standard PA and lateral projections.
FINDINGS: Hyperinflated lungs with flattened diaphragms. No focal consolidation, effusion or pneumothorax. Heart size normal.
IMPRESSION: Changes of COPD. No acute cardiopulmonary process.
RECOMMENDATION: No follow-up imaging needed.`,
  "Missing comparison": `EXAM: Chest PA and lateral.
INDICATION: Cough for two weeks.
FINDINGS: Lungs are clear. No pleural effusion.
IMPRESSION: Normal chest.`,
  "Critical finding not communicated": `EXAM: Portable chest radiograph, AP view.
INDICATION: Shortness of breath after central line placement.
COMPARISON: None available.
FINDINGS: Large right pneumothorax with mediastinal shift.
IMPRESSION: Large right pneumothorax.`,
};

let lastCitations = [];

function inline(text, cites) {
  let s = esc(text);
  s = s.replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>").replace(/`([^`]+)`/g, "<code>$1</code>");
  s = s.replace(/\[(S\d+)\]/g, (m, id) => {
    const c = cites.find((x) => x.id === id);
    const title = c ? `${c.source}, ${c.locator}` : id;
    return `<span class="cite" title="${esc(title)}">${id}</span>`;
  });
  return s;
}

function renderMarkdown(md, cites = []) {
  const lines = String(md || "").split("\n");
  let html = "", i = 0;
  while (i < lines.length) {
    const line = lines[i];
    if (/^#{1,4}\s/.test(line)) {
      html += `<h4>${inline(line.replace(/^#+\s/, ""), cites)}</h4>`; i++;
    } else if (/^\|/.test(line)) {
      const rows = [];
      while (i < lines.length && /^\|/.test(lines[i])) { rows.push(lines[i]); i++; }
      const cells = (r) => r.replace(/^\||\|$/g, "").split("|").map((c) => c.trim());
      const head = cells(rows[0]);
      const body = rows.slice(2).map(cells);
      html += `<table><thead><tr>${head.map((h) => `<th>${inline(h, cites)}</th>`).join("")}</tr></thead><tbody>` +
        body.map((r) => `<tr>${r.map((c) => `<td>${inline(c, cites)}</td>`).join("")}</tr>`).join("") + "</tbody></table>";
    } else if (/^\s*-\s/.test(line)) {
      html += "<ul>";
      while (i < lines.length && /^\s*-\s/.test(lines[i])) { html += `<li>${inline(lines[i].replace(/^\s*-\s/, ""), cites)}</li>`; i++; }
      html += "</ul>";
    } else if (line.trim() === "") { i++; }
    else { html += `<p>${inline(line, cites)}</p>`; i++; }
  }
  return html;
}

async function api(path, body) {
  const res = await fetch(path, body === undefined ? {} : { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || res.statusText);
  return res.json();
}

function showTrace(answer) {
  const t = answer.trace || [];
  $("#trace-hint").textContent = t.length ? `${answer.mode} mode · ${answer.latency_ms} ms total` : "No agent calls for this answer.";
  $("#trace").innerHTML = t.map((s) => `<li><span class="k-${s.kind}">${esc(s.kind === "agent" ? s.name + " agent" : s.name)}</span>` +
    `${s.kind === "tool" ? ` <span class="muted">(${esc(s.agent)})</span>` : ""} <span class="ms">${s.ms} ms</span></li>`).join("");
  lastCitations = answer.citations || [];
  $("#sources").innerHTML = lastCitations.length ? lastCitations.map((c) =>
    `<li><b>${esc(c.id)}</b> <span>${esc(c.source)}</span>, ${esc(c.locator)}${c.url ? ` · <a href="${esc(c.url)}" target="_blank" rel="noopener" style="color:var(--accent)">link</a>` : ""}</li>`).join("")
    : `<li class="muted">No sources.</li>`;
}

const AGENT_LABELS = { guidelines: "ACR Guidelines Agent", patients: "Patient Similarity Agent", billing: "Medical Billing Agent" };

function botMessage(a) {
  const el = document.createElement("div");
  el.className = "msg bot" + (a.refused ? " refused" : "");
  el.dataset.testid = "answer";
  const badges = a.refused ? `<span class="badge amber">No answer: ${esc(a.refusal_reason.replace("_", " "))}</span>`
    : (a.agents || []).map((x) => `<span class="badge">${esc(AGENT_LABELS[x] || x)}</span>`).join("");
  el.innerHTML = `<div class="msg-head">${badges}<span class="badge time">${a.latency_ms} ms</span></div>
    <div class="md">${renderMarkdown(a.answer, a.citations || [])}</div>
    <div class="disclaimer">${esc(a.disclaimer)}</div>
    <div class="feedback">Was this useful?
      <button data-r="1" aria-label="Useful">👍</button><button data-r="-1" aria-label="Not useful">👎</button>
      <span class="fb-status"></span></div>`;
  el.querySelectorAll(".feedback button").forEach((b) => b.addEventListener("click", async () => {
    el.querySelectorAll(".feedback button").forEach((x) => x.classList.remove("on"));
    b.classList.add("on");
    await api("/api/feedback", { answer_id: a.id, rating: Number(b.dataset.r), question: a.question });
    el.querySelector(".fb-status").textContent = "Saved, thanks.";
  }));
  return el;
}

async function ask(question) {
  if (!question.trim()) return;
  $("#empty-state")?.remove();
  const conv = $("#conversation");
  const u = document.createElement("div");
  u.className = "msg user"; u.textContent = question; conv.appendChild(u);
  const pending = document.createElement("div");
  pending.className = "msg bot"; pending.innerHTML = `<span class="spinner"></span> Routing to specialist agents…`;
  conv.appendChild(pending); conv.scrollTop = conv.scrollHeight;
  $("#ask-btn").disabled = true;
  try {
    const a = await api("/api/ask", { question });
    pending.replaceWith(botMessage(a));
    showTrace(a);
  } catch (e) {
    pending.textContent = "Something went wrong: " + e.message;
  } finally {
    $("#ask-btn").disabled = false; conv.scrollTop = conv.scrollHeight;
  }
}

// ---------- order check
let patientCache = {};
async function loadPatient(id) {
  const p = patientCache[id] || (patientCache[id] = await api(`/api/patients/${id}`));
  $("#chart-card").innerHTML = `<h4>${esc(p.id)} · ${esc(p.name)} <span class="badge amber">synthetic</span></h4>
    <div class="row">Age and sex: <b>${p.age}, ${esc(p.sex)}</b></div>
    <div class="row">Problems: <b>${esc(p.conditions.map((c) => `${c.display} (${c.icd10})`).join(", ") || "none")}</b></div>
    <div class="row">Symptoms: <b>${esc(p.symptoms.map((c) => c.display).join(", ") || "none")}</b></div>
    <div class="row">SpO2: <b>${p.spo2 ?? "n/a"}%</b> · Smoking: <b>${esc(p.smoking)}</b></div>
    <div class="row">Encounter: <b>${esc(p.setting_label)}</b></div>
    <div class="row">${esc(p.encounter_note)}</div>`;
}

async function checkOrder(ev) {
  ev?.preventDefault();
  const btn = $("#order-btn"); btn.disabled = true;
  try {
    const a = await api("/api/ask", { question: `Check ${$("#order-input").value}`, patient_id: $("#patient-select").value,
      order: $("#order-input").value, setting: $("#setting-select").value || null });
    const sec = (a.sections || [])[0];
    const v = sec?.data?.verdict || (a.refused ? "not assessable" : "");
    const titles = { "consistent": "Consistent with ACR criteria", "review": "Review needed", "not supported": "Not supported by ACR criteria",
      "outside routine imaging": "Outside the routine imaging criteria", "not assessable": "Not assessable" };
    $("#order-result").innerHTML = `<div class="verdict v-${v.replace(/ /g, "-")}" data-testid="verdict">
      <div class="verdict-title"><span class="dot"></span>${esc(titles[v] || "Result")}</div>
      <div class="md">${renderMarkdown(a.answer.replace(/^\*\*[^*]+\*\*\s*/, ""), a.citations || [])}</div></div>`;
    showTrace(a);
  } finally { btn.disabled = false; }
}

// ---------- report validation
async function validateReport() {
  const btn = $("#report-btn"); btn.disabled = true;
  try {
    const a = await api("/api/ask", { question: "Validate this radiology report", report_text: $("#report-text").value });
    const res = a.sections?.[0]?.data;
    if (!res || !res.items) { $("#report-result").innerHTML = `<div class="verdict"><div class="md">${renderMarkdown(a.answer)}</div></div>`; return; }
    const label = { pass: "Present", gap: "Missing", suggestion: "Consider", na: "Not needed" };
    $("#report-result").innerHTML = `<div class="verdict v-${res.verdict === "complete" ? "consistent" : res.verdict === "critical gap" ? "not-supported" : "review"}" data-testid="report-verdict">
      <div class="verdict-title"><span class="dot"></span>Report ${esc(res.verdict)} · ${res.passed} of ${res.total} items</div>
      <ul class="checklist">${res.items.map((it) => `<li><span class="status s-${it.status}">${label[it.status]}</span>
        <div><b>${esc(it.label)}</b>${it.note && it.status !== "pass" ? `<div class="muted small">${esc(it.note)}</div>` : ""}</div></li>`).join("")}</ul></div>`;
    showTrace(a);
  } finally { btn.disabled = false; }
}

// ---------- evaluation
async function runEval() {
  const btn = $("#eval-btn"); btn.disabled = true;
  $("#eval-result").innerHTML = `<p><span class="spinner"></span> Running 50 questions…</p>`;
  try {
    const r = await api("/api/eval", {});
    $("#eval-result").innerHTML = `<table class="metrics" data-testid="metrics"><thead><tr><th>Metric</th><th>Result</th><th>Target</th><th></th></tr></thead><tbody>` +
      r.metrics.map((m) => `<tr><td>${esc(m.name)}</td><td>${esc(m.display)}</td><td>${esc(m.target_display)}</td><td class="${m.passed ? "ok" : "no"}">${m.passed ? "Pass" : "Miss"}</td></tr>`).join("") +
      `</tbody></table><p class="muted small">${r.total} questions · ${r.failures.length} failed checks · ${esc(r.mode)} mode</p>`;
  } catch (e) { $("#eval-result").textContent = e.message; }
  finally { btn.disabled = false; }
}

// ---------- boot
function setTab(name) {
  document.querySelectorAll(".tab").forEach((t) => { const on = t.dataset.tab === name; t.classList.toggle("active", on); t.setAttribute("aria-selected", on); });
  document.querySelectorAll(".tab-body").forEach((b) => b.classList.toggle("hidden", b.id !== `tab-${name}`));
}

async function boot() {
  document.querySelectorAll(".tab").forEach((t) => t.addEventListener("click", () => setTab(t.dataset.tab)));
  $("#examples").innerHTML = EXAMPLES.map(([k, q]) => `<button class="example" type="button"><small>${esc(k)}</small>${esc(q)}</button>`).join("");
  document.querySelectorAll(".example").forEach((b, i) => b.addEventListener("click", () => ask(EXAMPLES[i][1])));
  $("#ask-form").addEventListener("submit", (e) => { e.preventDefault(); const q = $("#question").value; $("#question").value = ""; ask(q); });
  $("#question").addEventListener("keydown", (e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); $("#ask-form").requestSubmit(); } });
  $("#order-chips").innerHTML = ORDERS.map((o) => `<button type="button" class="chip">${esc(o)}</button>`).join("");
  document.querySelectorAll("#order-chips .chip").forEach((c) => c.addEventListener("click", () => { $("#order-input").value = c.textContent; }));
  $("#order-form").addEventListener("submit", checkOrder);
  $("#report-samples").innerHTML = Object.keys(REPORTS).map((k) => `<button type="button" class="chip">${esc(k)}</button>`).join("");
  document.querySelectorAll("#report-samples .chip").forEach((c) => c.addEventListener("click", () => { $("#report-text").value = REPORTS[c.textContent]; }));
  $("#report-text").value = REPORTS["Missing comparison"];
  $("#report-btn").addEventListener("click", validateReport);
  $("#eval-btn").addEventListener("click", runEval);

  const cfg = await api("/api/config");
  document.title = cfg.brand;
  $("#brand-name").textContent = cfg.brand;
  $("#mode-pill").textContent = { offline: "Offline demo", bedrock: "Bedrock · Claude", agentcore: "AgentCore Runtime" }[cfg.mode] || cfg.mode;
  $("#stat-patients").textContent = cfg.patients;
  $("#stat-codes").textContent = cfg.billing_items;
  $("#disclaimer").textContent = cfg.disclaimer;

  const pts = await api("/api/patients");
  $("#patient-select").innerHTML = pts.map((p) => `<option value="${esc(p.id)}">${esc(p.label)}</option>`).join("");
  $("#patient-select").value = "P-0002";
  $("#patient-select").addEventListener("change", (e) => loadPatient(e.target.value));
  loadPatient("P-0002");
}

boot();
