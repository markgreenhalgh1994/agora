/*
 * Agora Extension — popup.js
 */

const BACKEND = "http://localhost:8000";

const VERDICTS = {
  CONSENSUS: { color: "#1A5C1A", bg: "#EAF7EA", label: "Consensus",
    desc: "Methodologically strong. Rigorous process." },
  CONTESTED: { color: "#854F0B", bg: "#FAEEDA", label: "Contested",
    desc: "Mixed methodology. Verify against other sources." },
  HETERODOX: { color: "#0C447C", bg: "#E6F1FB", label: "Heterodox",
    desc: "Minority position or strong methodology in specific areas." },
  REJECTED:  { color: "#791F1F", bg: "#FCEBEB", label: "Rejected",
    desc: "Fails epistemic standard. Not presented as equivalent." },
};

const DIM_LABELS = {
  falsifiability:              "Falsifiability",
  evidence_trail:              "Evidence trail",
  conflict_of_interest:        "Conflict of interest",
  methodology:                 "Methodology",
  uncertainty_acknowledgment:  "Uncertainty",
  counterargument_engagement:  "Counterarguments",
};

function barColor(s) {
  return s >= 70 ? "#1A5C1A" : s >= 45 ? "#854F0B" : "#791F1F";
}

function renderResult(result) {
  const cls     = result.classification || {};
  const scores  = result.scores || {};
  const verdict = cls.verdict || "ERROR";
  const v       = VERDICTS[verdict] || { color: "#555", bg: "#F5F5F5", label: verdict, desc: "" };

  const dimBarsHTML = Object.entries(DIM_LABELS).map(([key, label]) => {
    const s = scores[key] || 50;
    const c = barColor(s);
    return `
      <div class="dim-row">
        <span class="dim-label">${label}</span>
        <div class="dim-bar-track">
          <div class="dim-bar-fill" style="width:${s}%;background:${c}"></div>
        </div>
        <span class="dim-score" style="color:${c}">${s}</span>
      </div>`;
  }).join("");

  const flagsHTML = [
    cls.galileo_triggered
      ? `<span class="flag" style="background:#E6F1FB;color:#0C447C">Galileo test</span>` : "",
    cls.capture_flag
      ? `<span class="flag" style="background:#FAEEDA;color:#854F0B">Capture flag</span>` : "",
  ].filter(Boolean).join("");

  const disagreements = result.disagreements || [];
  const disagreeHTML = disagreements.length > 0
    ? `<div class="disagree-box">
        <div class="disagree-title">Model disagreement</div>
        ${disagreements.map(d => `<div class="disagree-item">• ${d}</div>`).join("")}
       </div>`
    : "";

  const modelLine = result.model_agreement
    ? `<div style="font-size:10px;color:#888;margin-top:3px">${result.model_agreement}</div>`
    : "";

  document.getElementById("content").innerHTML = `
    <div class="section">
      <div class="score-display" style="background:${v.bg};border-radius:6px;padding:12px">
        <div class="score-number" style="color:${v.color}">${Math.round(cls.overall_score || 0)}</div>
        <div class="score-verdict" style="color:${v.color}">${v.label}</div>
        ${modelLine}
        ${flagsHTML ? `<div style="margin-top:6px">${flagsHTML}</div>` : ""}
      </div>
    </div>
    <div class="section">
      <div class="section-title">Dimension scores</div>
      ${dimBarsHTML}
      ${disagreeHTML}
    </div>
    <div class="section" style="font-size:10px;color:#888;padding-bottom:8px">
      <div style="margin-bottom:2px;font-weight:500;color:#555">${(result.source_title || "").slice(0, 55)}${result.source_title?.length > 55 ? "…" : ""}</div>
      <div>${new Date(result.timestamp || Date.now()).toLocaleString()}</div>
    </div>
  `;
}

function renderNoResult() {
  document.getElementById("content").innerHTML = `
    <div class="no-result">
      No score for this page yet.<br>
      The extension scores pages automatically as you browse.<br><br>
      <span style="color:#AAA">Make sure the Agora server is running:<br>python agora_server.py</span>
    </div>`;
}

async function checkServer() {
  try {
    const r = await fetch(`${BACKEND}/health`, { signal: AbortSignal.timeout(2000) });
    if (r.ok) {
      document.getElementById("server-dot").style.background   = "#1A5C1A";
      document.getElementById("server-label").textContent      = "Server running";
    } else {
      throw new Error("not ok");
    }
  } catch {
    document.getElementById("server-dot").style.background  = "#791F1F";
    document.getElementById("server-label").textContent     = "Server offline";
  }
}

// Load last result
chrome.storage.local.get(["agora_last_result"], (data) => {
  if (data.agora_last_result) {
    renderResult(data.agora_last_result);
  } else {
    renderNoResult();
  }
});

// Rescore button — clears cache for current tab and re-triggers
document.getElementById("rescore-btn").addEventListener("click", async (e) => {
  e.preventDefault();
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  if (!tab?.url) return;
  const cacheKey = "score_" + btoa(tab.url).slice(0, 40);
  chrome.storage.local.remove([cacheKey, "agora_last_result"], () => {
    chrome.tabs.reload(tab.id);
    window.close();
  });
});

checkServer();
