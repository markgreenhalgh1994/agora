/*
 * Agora Extension — content.js
 * Fires on every page load.
 * Universal text extraction — works on any site without configuration.
 */

const BACKEND        = "http://localhost:8000";
const MIN_TEXT_LEN   = 300;

const VERDICTS = {
  CONSENSUS: { color:"#1A5C1A", bg:"#EAF7EA", border:"#1A5C1A", label:"Consensus"  },
  CONTESTED: { color:"#854F0B", bg:"#FAEEDA", border:"#BA7517", label:"Contested"   },
  HETERODOX: { color:"#0C447C", bg:"#E6F1FB", border:"#185FA5", label:"Heterodox"  },
  REJECTED:  { color:"#791F1F", bg:"#FCEBEB", border:"#A32D2D", label:"Rejected"    },
  SCORING:   { color:"#555555", bg:"#F5F5F5", border:"#AAAAAA", label:"Scoring..."  },
  ERROR:     { color:"#555555", bg:"#F5F5F5", border:"#AAAAAA", label:"?"           },
};

// ── Universal text extraction ─────────────────────────────────────
// Strategy: score every block-level text node by how "content-like"
// it is, take the top blocks, concatenate. Works on any site.

function extractText() {
  // Tags that never contain article text
  const SKIP_TAGS = new Set([
    "SCRIPT","STYLE","NOSCRIPT","NAV","FOOTER","HEADER",
    "ASIDE","FORM","IFRAME","BUTTON","SELECT","INPUT",
    "TEXTAREA","FIGURE","FIGCAPTION","MENU","DIALOG"
  ]);

  // Class/id fragments that signal non-article elements
  const NOISE_RE = new RegExp(
    "nav|footer|header|sidebar|menu|cookie|banner|" +
    "advert|popup|modal|social|share|comment|related|" +
    "recommend|newsletter|subscribe|promo|widget|" +
    "breadcrumb|pagination|toolbar|toc|tag-list",
    "i"
  );

  function isNoise(el) {
    if (SKIP_TAGS.has(el.tagName)) return true;
    const c = String(el.className || "");
    const id = String(el.id || "");
    return NOISE_RE.test(c) || NOISE_RE.test(id);
  }

  // Collect all paragraph-level text blocks with their character count
  const blocks = [];

  function walk(el) {
    if (isNoise(el)) return;
    const tag = el.tagName;
    // Grab text from block-level or semantic content elements
    if (["P","H1","H2","H3","H4","H5","H6",
         "LI","BLOCKQUOTE","TD","DD","DT",
         "FIGCAPTION","SUMMARY"].includes(tag)) {
      const text = (el.innerText || el.textContent || "").trim();
      if (text.length > 40) {
        blocks.push({ text, len: text.length, el });
      }
      return; // don't recurse into these — already grabbed their text
    }
    Array.from(el.children).forEach(walk);
  }

  // Start from the most specific content container available,
  // falling back to body. Never deletes anything.
  const root = (
    document.querySelector("article") ||
    document.querySelector("main") ||
    document.querySelector("[role='main']") ||
    document.querySelector("[itemprop='articleBody']") ||
    document.querySelector(".article-body, .post-body, .entry-content, " +
      ".story-body, .article__body, .article-text, " +
      ".content-body, .story-content, .body-copy") ||
    document.body
  );

  walk(root);

  if (blocks.length === 0) {
    // Last resort: just grab body text
    return (document.body.innerText || "").replace(/\s+/g, " ").trim().slice(0, 8000);
  }

  // Sort blocks by length — longer blocks are more likely to be
  // article prose rather than navigation or metadata
  blocks.sort((a, b) => b.len - a.len);

  // Take enough top blocks to fill the context window
  let combined = "";
  for (const b of blocks) {
    combined += b.text + " ";
    if (combined.length >= 8000) break;
  }

  return combined.replace(/\s+/g, " ").trim().slice(0, 8000);
}

// ── Badge ─────────────────────────────────────────────────────────
function createBadge() {
  const ex = document.getElementById("agora-badge");
  if (ex) ex.remove();

  const badge = document.createElement("div");
  badge.id = "agora-badge";
  badge.style.cssText = [
    "position:fixed", "bottom:20px", "right:20px",
    "z-index:2147483647",
    "font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Arial,sans-serif",
    "font-size:12px", "border-radius:8px", "padding:8px 12px",
    "cursor:pointer", "transition:opacity 0.2s",
    "box-shadow:0 2px 8px rgba(0,0,0,0.15)",
    "user-select:none", "min-width:80px", "text-align:center"
  ].join(";");

  updateBadge(badge, "SCORING", null);
  badge.addEventListener("click", () => {
    chrome.storage.local.get(["agora_last_result"], (d) => {
      if (d.agora_last_result) showPanel(d.agora_last_result);
    });
  });
  document.body.appendChild(badge);
  return badge;
}

function updateBadge(badge, verdict, score) {
  const v = VERDICTS[verdict] || VERDICTS.ERROR;
  badge.style.background = v.bg;
  badge.style.border     = "1.5px solid " + v.border;
  badge.style.color      = v.color;
  const num = (score !== null && score !== undefined)
    ? "<span style='font-size:16px;font-weight:600;display:block;margin-bottom:2px'>" + Math.round(score) + "</span>"
    : "";
  badge.innerHTML = num +
    "<span style='font-weight:500;font-size:11px'>" + v.label + "</span>" +
    "<span style='font-size:9px;opacity:0.7;display:block;margin-top:1px'>Agora</span>";
}

// ── Panel ─────────────────────────────────────────────────────────
function showPanel(result) {
  const ex = document.getElementById("agora-panel");
  if (ex) { ex.remove(); return; }

  const cls     = result.classification || {};
  const scores  = result.scores || {};
  const verdict = cls.verdict || "ERROR";
  const v       = VERDICTS[verdict] || VERDICTS.ERROR;

  const DIMS = {
    falsifiability:             "Falsifiability",
    evidence_trail:             "Evidence trail",
    conflict_of_interest:       "Conflict of interest",
    methodology:                "Methodology",
    uncertainty_acknowledgment: "Uncertainty",
    counterargument_engagement: "Counterarguments",
  };

  const bars = Object.entries(DIMS).map(([k, label]) => {
    const s = scores[k] || 50;
    const c = s >= 70 ? "#1A5C1A" : s >= 45 ? "#854F0B" : "#791F1F";
    return "<div style='display:flex;align-items:center;gap:8px;margin-bottom:6px'>" +
      "<span style='min-width:110px;color:#555;font-size:10px'>" + label + "</span>" +
      "<div style='flex:1;height:4px;background:#EEE;border-radius:2px;overflow:hidden'>" +
        "<div style='width:" + s + "%;height:100%;background:" + c + ";border-radius:2px'></div>" +
      "</div>" +
      "<span style='min-width:24px;text-align:right;font-weight:500;color:" + c + ";font-size:10px'>" + s + "</span>" +
    "</div>";
  }).join("");

  const flags = [
    cls.galileo_triggered ? "<span style='background:#E6F1FB;color:#0C447C;padding:2px 7px;border-radius:8px;font-size:10px;font-weight:500'>Galileo test</span>" : "",
    cls.capture_flag      ? "<span style='background:#FAEEDA;color:#854F0B;padding:2px 7px;border-radius:8px;font-size:10px;font-weight:500'>Capture flag</span>" : "",
  ].filter(Boolean).join(" ");

  const disagree = (result.disagreements || []).length > 0
    ? "<div style='background:#FDF8EC;border-left:3px solid #B8860B;padding:8px 10px;margin-top:10px;border-radius:0 4px 4px 0'>" +
        "<div style='font-weight:600;color:#854F0B;margin-bottom:4px;font-size:11px'>Model disagreement</div>" +
        result.disagreements.map(d => "<div style='font-size:10px;color:#555;margin-bottom:2px'>• " + d + "</div>").join("") +
      "</div>"
    : "";

  const panel = document.createElement("div");
  panel.id = "agora-panel";
  panel.style.cssText = [
    "position:fixed", "bottom:80px", "right:20px",
    "z-index:2147483647",
    "font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Arial,sans-serif",
    "font-size:12px", "width:320px", "max-height:480px",
    "overflow-y:auto", "background:#FFF",
    "border:1px solid #DDD", "border-radius:10px",
    "box-shadow:0 4px 20px rgba(0,0,0,0.18)"
  ].join(";");

  panel.innerHTML =
    "<div style='background:" + v.bg + ";border-radius:10px 10px 0 0;padding:12px 14px;border-bottom:1px solid " + v.border + "44'>" +
      "<div style='display:flex;justify-content:space-between;align-items:flex-start'>" +
        "<div>" +
          "<div style='font-size:22px;font-weight:700;color:" + v.color + "'>" + Math.round(cls.overall_score || 0) + "</div>" +
          "<div style='font-weight:600;color:" + v.color + ";font-size:13px'>" + v.label + "</div>" +
          (result.model_agreement ? "<div style='font-size:10px;color:#888;margin-top:3px'>" + result.model_agreement + "</div>" : "") +
        "</div>" +
        "<button onclick=\"document.getElementById('agora-panel').remove()\" " +
          "style='background:none;border:none;cursor:pointer;color:#999;font-size:18px;padding:0;line-height:1'>×</button>" +
      "</div>" +
      (flags ? "<div style='margin-top:8px;display:flex;gap:4px;flex-wrap:wrap'>" + flags + "</div>" : "") +
    "</div>" +
    "<div style='padding:12px 14px'>" +
      "<div style='font-size:10px;font-weight:600;color:#888;letter-spacing:0.05em;margin-bottom:8px;text-transform:uppercase'>Dimension scores</div>" +
      bars + disagree +
      "<div style='margin-top:10px;font-size:10px;color:#AAA;border-top:1px solid #EEE;padding-top:8px'>" +
        (result.source_title || "").slice(0, 60) + (result.source_title && result.source_title.length > 60 ? "…" : "") +
      "</div>" +
      "<div style='font-size:10px;color:#CCC;margin-top:2px'>" + (result.source_url || "").slice(0, 60) + "</div>" +
    "</div>";

  document.body.appendChild(panel);

  setTimeout(() => {
    document.addEventListener("click", function close(e) {
      if (!panel.contains(e.target) && e.target.id !== "agora-badge") {
        panel.remove();
        document.removeEventListener("click", close);
      }
    });
  }, 100);
}

// ── Scoring flow ──────────────────────────────────────────────────
async function scoreCurrentPage() {
  const url  = window.location.href;
  const text = extractText();

  if (text.length < MIN_TEXT_LEN) return;

  // Skip search engines and non-article pages
  if (/^https?:\/\/(www\.)?(google|bing|duckduckgo|yahoo)\.(com|co)/.test(url)) return;
  if (/\/(search|login|signup|register|cart|checkout|account|settings)\b/i.test(url)) return;

  const badge    = createBadge();
  const cacheKey = "score_" + btoa(encodeURIComponent(url)).slice(0, 40);

  try {
    const cached = await new Promise(r =>
      chrome.storage.local.get([cacheKey], d => r(d[cacheKey]))
    );

    if (cached && cached._expiry > Date.now()) {
      updateBadge(badge, cached.classification?.verdict, cached.classification?.overall_score);
      chrome.storage.local.set({ agora_last_result: cached });
      return;
    }

    const resp = await fetch(BACKEND + "/score", {
      method:  "POST",
      headers: { "Content-Type": "application/json" },
      body:    JSON.stringify({ url, text, title: document.title }),
    });

    if (!resp.ok) throw new Error("Backend " + resp.status);

    const result = await resp.json();
    const expiry = Date.now() + 24 * 60 * 60 * 1000;

    chrome.storage.local.set({
      [cacheKey]:        { ...result, _expiry: expiry },
      agora_last_result: result,
    });

    // Handle out-of-scope response
    if (result.in_scope === false) {
      const oosBadge = document.getElementById("agora-badge");
      if (oosBadge) {
        oosBadge.style.background    = "#F5F5F5";
        oosBadge.style.border        = "1.5px solid #AAAAAA";
        oosBadge.style.color         = "#888888";
        oosBadge.innerHTML =
          "<span style='font-size:10px;font-weight:500;display:block;margin-bottom:1px'>Not scored</span>" +
          "<span style='font-size:9px;opacity:0.7;display:block'>Agora</span>";
        oosBadge.title = result.out_of_scope_message || "This page type is not in Agora\'s scope.";
      }
      chrome.storage.local.set({ agora_last_result: result });
      return;
    }

    updateBadge(badge, result.classification?.verdict, result.classification?.overall_score);

  } catch (err) {
    const ex = document.getElementById("agora-badge");
    if (ex) { ex.style.opacity = "0.3"; ex.title = "Agora: server offline"; }
    console.debug("Agora:", err.message);
  }
}

// ── Entry point — wait for content, then score ────────────────────
// Retries with increasing delays to handle JS-rendered pages.

async function waitAndScore() {
  const delays = [1500, 3000, 5000];
  for (let i = 0; i < delays.length; i++) {
    await new Promise(r => setTimeout(r, delays[i]));
    if (extractText().length >= MIN_TEXT_LEN) {
      scoreCurrentPage();
      return;
    }
  }
  // Final attempt regardless of text length
  scoreCurrentPage();
}

if (document.readyState === "complete") {
  waitAndScore();
} else {
  window.addEventListener("load", waitAndScore);
}
