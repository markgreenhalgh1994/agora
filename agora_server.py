"""
Agora Protocol — Backend Server v0.3
MVP scope: News, Research, Government/Institutional, Substack/Blogs, Think Tank/Policy
Out-of-scope pages return a structured NOT_IN_SCOPE response — no API calls wasted.
"""

import os, json, hashlib, sqlite3, asyncio, re
from datetime import datetime
from typing import Optional
from pathlib import Path

env_file = Path(__file__).parent / ".env"
if env_file.exists():
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            os.environ.setdefault(k.strip(), v.strip())

import anthropic, uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

MODEL      = "claude-haiku-4-5-20251001"
MAX_TOKENS = 400
os.environ["ANTHROPIC_API_KEY"] = "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"
MAX_TEXT   = 6000
DB_PATH    = "agora_server_cache.db"

app = FastAPI(title="Agora Epistemic Engine", version="0.3.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"],
                   allow_methods=["*"], allow_headers=["*"])

class ScoreRequest(BaseModel):
    url:   str
    text:  str
    title: Optional[str] = ""

# ── Database ───────────────────────────────────────────────────────
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""CREATE TABLE IF NOT EXISTS score_cache (
        url_hash TEXT PRIMARY KEY, url TEXT, title TEXT,
        scored_at TEXT, verdict TEXT, overall REAL,
        result_json TEXT, expires_at INTEGER)""")
    conn.commit()
    return conn

def cache_get(url):
    h = hashlib.sha256(url.encode()).hexdigest()
    conn = get_db()
    row = conn.execute(
        "SELECT result_json, expires_at FROM score_cache WHERE url_hash=?", (h,)
    ).fetchone()
    conn.close()
    if row and row[1] > int(datetime.utcnow().timestamp()):
        return json.loads(row[0])
    return None

def cache_set(url, result, ttl_hours=24):
    h = hashlib.sha256(url.encode()).hexdigest()
    exp = int(datetime.utcnow().timestamp()) + ttl_hours * 3600
    conn = get_db()
    conn.execute("""INSERT OR REPLACE INTO score_cache
        (url_hash,url,title,scored_at,verdict,overall,result_json,expires_at)
        VALUES(?,?,?,?,?,?,?,?)""", (
        h, url,
        result.get("source_title",""),
        result.get("timestamp",""),
        result.get("classification",{}).get("verdict",""),
        result.get("classification",{}).get("overall_score",0),
        json.dumps(result), exp))
    conn.commit()
    conn.close()

# ══════════════════════════════════════════════════════════════════
# MVP SCOPE DEFINITION
# Five in-scope types. Everything else returns NOT_IN_SCOPE.
# ══════════════════════════════════════════════════════════════════

IN_SCOPE_TYPES = {
    "NEWS": {
        "label": "News article",
        "description": "Professional journalism — newspapers, wire services, broadcast news.",
        "examples": "Politico, Reuters, BBC, CNN, NYT, Washington Post, AP"
    },
    "RESEARCH": {
        "label": "Research paper",
        "description": "Peer-reviewed studies, preprints, systematic reviews, clinical trials.",
        "examples": "PubMed, NEJM, arXiv, bioRxiv, Lancet, JAMA, Nature"
    },
    "GOVERNMENT": {
        "label": "Government / institutional document",
        "description": "Official guidance, regulatory notices, policy statements from public bodies.",
        "examples": "CDC, FDA, WHO, NIH, .gov sites, EU agencies"
    },
    "BLOG": {
        "label": "Substack / blog / independent journalism",
        "description": "Individual or small-publication writing — newsletters, independent outlets.",
        "examples": "Substack, Medium, independent news sites, personal blogs with journalism"
    },
    "POLICY": {
        "label": "Think tank / policy paper",
        "description": "Policy analysis, white papers, reports from research institutions.",
        "examples": "Brookings, RAND, Heritage, CFR, CSIS, academic policy centers"
    },
}

OUT_OF_SCOPE_REASONS = {
    "SOCIAL_MEDIA":   "Social media feeds and posts are not in scope for Agora v0.3. Agora scores long-form sources where epistemic standards apply.",
    "SEARCH_ENGINE":  "Search result pages are not scored — Agora scores the articles you find, not the index.",
    "PRODUCT_PAGE":   "Commercial product and service pages are not in scope. Agora scores informational and analytical content.",
    "VIDEO_PLATFORM": "Video platforms are not in scope. Agora scores text-based sources.",
    "FORUM":          "Forum and discussion pages are not in scope. Agora scores authored sources with identifiable responsibility.",
    "PAYWALL":        "This page returned insufficient text — it may be paywalled or require login.",
    "UNKNOWN":        "This page type is not recognised as one of Agora's five in-scope source types for v0.3.",
}

# URL-based pre-screening — catches obvious out-of-scope before any API call
def url_prescreening(url: str):
    """Returns (is_out_of_scope, reason_key) or (False, None) if undetermined."""
    u = url.lower()
    if any(d in u for d in [
        "twitter.com", "x.com", "facebook.com", "instagram.com",
        "tiktok.com", "threads.net", "bsky.app", "linkedin.com/feed",
        "reddit.com/r/", "reddit.com/u/"
    ]):
        return True, "SOCIAL_MEDIA"
    if any(d in u for d in [
        "google.com/search", "bing.com/search", "duckduckgo.com",
        "yahoo.com/search", "search.yahoo"
    ]):
        return True, "SEARCH_ENGINE"
    if any(d in u for d in [
        "youtube.com/watch", "youtu.be/", "vimeo.com/",
        "twitch.tv/", "rumble.com/"
    ]):
        return True, "VIDEO_PLATFORM"
    if any(d in u for d in [
        "amazon.com/dp/", "amazon.com/gp/product",
        "ebay.com/itm/", "etsy.com/listing/"
    ]):
        return True, "PRODUCT_PAGE"
    return False, None

# ══════════════════════════════════════════════════════════════════
# STEP 0 — SOURCE CLASSIFIER (MVP scope-aware)
# ══════════════════════════════════════════════════════════════════

SOURCE_TYPE_PROMPT = """
You are a source-type classifier for an epistemic scoring system.
Your job: determine whether this text is one of five in-scope source types,
or out of scope. Be decisive — do not default to UNKNOWN unless genuinely unclear.

IN-SCOPE types (score these):
- NEWS: Professional journalism. Bylined articles. News organisations.
  Wire services. Investigative reporting. Political coverage.
- RESEARCH: Academic papers. Clinical trials. Systematic reviews. Preprints.
  Meta-analyses. Scientific studies with methods sections.
- GOVERNMENT: Official government guidance. Regulatory advisories.
  Agency policy statements. Legislation summaries. Public health directives.
- BLOG: Substack newsletters. Independent journalism. Personal blogs with
  substantive analysis. Medium posts. Opinion newsletters.
- POLICY: Think tank reports. Policy white papers. Academic policy analysis.
  Strategy documents from research institutes or advocacy organisations.

OUT-OF-SCOPE types (do not score these):
- SOCIAL_MEDIA: Tweets, Facebook posts, Instagram captions, Reddit threads.
- SEARCH_ENGINE: Google/Bing search result pages.
- PRODUCT_PAGE: E-commerce listings, product descriptions, sales pages.
- VIDEO_PLATFORM: YouTube, TikTok, Vimeo pages.
- FORUM: Discussion boards, comment sections, Q&A sites.
- PRESS_RELEASE: Corporate press releases optimised for publicity.
  (These exist in a grey zone — classify as NEWS only if substantially
  edited and published by a news outlet, otherwise OUT_OF_SCOPE.)

Additional metadata to extract:
- is_consensus_position: true if this source supports prevailing scientific
  or institutional consensus, false if it challenges or critiques it.
- funder_has_operational_control: true if the entity funding the work also
  designed it, collected data, ran the analysis, or wrote the manuscript.
  This is distinct from merely providing funding.

TEXT TO CLASSIFY:
{text}

Respond ONLY with valid JSON:
{{
  "source_type": "<NEWS|RESEARCH|GOVERNMENT|BLOG|POLICY|SOCIAL_MEDIA|SEARCH_ENGINE|PRODUCT_PAGE|VIDEO_PLATFORM|FORUM|PRESS_RELEASE|UNKNOWN>",
  "in_scope": <true if one of the five in-scope types, false otherwise>,
  "confidence": <integer 0-100>,
  "reasoning": "<one sentence>",
  "is_consensus_position": <true|false>,
  "funder_has_operational_control": <true|false>
}}
"""

# ══════════════════════════════════════════════════════════════════
# DIMENSION PROMPTS v0.3 — succinct, source-type aware
# ══════════════════════════════════════════════════════════════════

DIMENSION_PROMPTS = {

"falsifiability": """
Evaluate FALSIFIABILITY for this {source_type} source. Score 0-100.

A claim is falsifiable if there exists at least one possible observation that
could prove it wrong. Claims consistent with every possible state of the world
carry no epistemic information. [Popper, The Logic of Scientific Discovery, 1959]

Apply source-appropriate standards:
- NEWS: Are factual claims specific enough to be verified or refuted?
  Penalise vague attribution ("sources say") without verifiable specifics.
- RESEARCH: Do hypotheses have pre-specified, testable endpoints?
  Penalise outcome-switching language and post-hoc framing.
- GOVERNMENT: Does guidance cite falsifiable evidence rather than authority alone?
- BLOG/POLICY: Are empirical claims within arguments stated with testable conditions,
  or are they rhetorical assertions dressed as facts?

Exempt from this dimension: normative claims (what SHOULD happen),
value judgements, and deliberate uncertainty disclosures.

90-100  All empirical claims specific, testable, falsification conditions clear
75-89   Most claims testable; minor hedging without conditions
55-74   Mixed: testable and unfalsifiable claims present
35-54   Primarily vague, emotional, or unfalsifiable empirical claims
0-34    No falsifiable claims; pure assertion; normative dressed as empirical

TEXT: {text}

JSON only: {{"score":<int>,"reasoning":"<2 sentences>","key_signals":["<s1>","<s2>","<s3>"]}}
""",

"evidence_trail": """
Evaluate the EVIDENCE TRAIL for this {source_type} source. Score 0-100.

Primary source: original study, official record, first-hand document, raw data.
Secondary: review or summary of the primary.
Tertiary: article citing an article citing the primary.

Apply source-appropriate standards:
- NEWS: Score on named vs anonymous sourcing, on-record attribution,
  document evidence cited, and verifiability via public records.
  Anonymous sources are permitted but penalised relative to named sources.
  Do NOT penalise for absence of academic citations — that is not the genre.
- RESEARCH: Every major claim must cite accessible primary sources.
  Penalise references that are topically related but do not support the
  specific claim made.
- GOVERNMENT: Does the guidance cite its evidence base? Is that base accessible?
- BLOG/POLICY: Are factual claims attributed? Are key statistics traceable?
  Penalise assertions presented as established facts without any attribution.

90-100  All major claims traceable to accessible primary sources
75-89   Good sourcing; minor gaps
55-74   Partial sourcing; significant anonymous or tertiary reliance
35-54   Few citations; mostly assertion
0-34    No traceable evidence

TEXT: {text}

JSON only: {{"score":<int>,"reasoning":"<2 sentences>","key_signals":["<s1>","<s2>","<s3>"]}}
""",

"conflict_of_interest": """
Evaluate CONFLICT OF INTEREST for this {source_type} source. Score 0-100.
funder_has_operational_control = {funder_has_operational_control}

Score two components together:
A) Disclosure completeness — was any conflict disclosed at all?
B) Alignment risk — does the funder/author benefit if the conclusion is accepted?

Three severity levels — apply the correct one:
1. FUNDING ONLY: Money provided; funder had no role in design, analysis, or writing.
   Moderate conflict. Disclosure substantially addresses it. Score: 55-75.
2. FUNDING + INVOLVEMENT: Funder contributed to design, interpretation, or writing.
   Significant conflict even with disclosure. Score: 35-55.
3. FULL OPERATIONAL CONTROL (funder_has_operational_control=true): Funder designed,
   collected data, analysed, AND wrote. Maximum conflict. Score: 0-35 regardless
   of disclosure quality. This is the profile of industry-sponsored research.

Also penalise:
- Undisclosed conflicts discovered by cross-reference: severe penalty
- Author institutional affiliations with direct financial stake in conclusion
- Revolving door between regulatory body and regulated industry

90-100  Independent funding; no financial alignment; full disclosure
75-89   Minor disclosed conflict; low funder-conclusion alignment
55-74   Moderate conflict disclosed; or partial disclosure with low alignment
35-54   Significant undisclosed conflict OR high funder-conclusion alignment
0-34    Full operational control by interested party; OR active concealment

IMPORTANT: A high-methodology source with COI below 45 should trigger the
capture flag — strong method + captured funding is exactly what bias looks like.

TEXT: {text}

JSON only: {{"score":<int>,"reasoning":"<2 sentences>","key_signals":["<s1>","<s2>","<s3>"],"conflict_level":"<NONE|FUNDING_ONLY|FUNDING_PLUS_INVOLVEMENT|FULL_OPERATIONAL_CONTROL>"}}
""",

"methodology": """
Evaluate METHODOLOGY TRANSPARENCY for this {source_type} source. Score 0-100.

Core question: Could an independent party reproduce or verify the process
by which conclusions were reached?

Apply source-appropriate standards:
- RESEARCH: Full scientific standards. Score: pre-registration, randomisation
  and blinding, sample size adequacy vs claimed effect size, statistical
  method appropriateness, independent oversight (DSMB, IRB), protocol availability.
  Bonus for pre-registered studies. Significant penalty for underpowered
  studies making strong population-level claims.
- NEWS: Reporting process standards. Score: source corroboration
  (single vs multiple independent sources), quantitative claim methodology,
  editorial standards disclosed. A well-sourced news investigation with
  named sources and document evidence scores 70-80.
- GOVERNMENT: Was the guidance development process described? Was the
  evidence review documented? Were dissenting expert views considered?
- BLOG/POLICY: Is the argument's logical structure clear? Are factual premises
  distinguished from value claims? Are analytical methods disclosed
  for any quantitative claims?

90-100  Fully described, reproducible, independently reviewed/overseen
75-89   Clear method; peer reviewed or editorially rigorous; minor gaps
55-74   Partial description; not independently reviewed; significant gaps
35-54   Method vaguely gestured at; major verifiability gaps
0-34    No method; no way to verify conclusions follow from process

TEXT: {text}

JSON only: {{"score":<int>,"reasoning":"<2 sentences>","key_signals":["<s1>","<s2>","<s3>"]}}
""",

"uncertainty_acknowledgment": """
Evaluate UNCERTAINTY ACKNOWLEDGMENT for this {source_type} source. Score 0-100.

Two failure modes — both penalised equally:
1. OVERCLAIMING: "Proves" when evidence "suggests." Definitive language on
   contested findings. Generalising from narrow samples to broad populations.
   Omitting confidence intervals or effect size context.
2. FALSE UNCERTAINTY: Strategic hedging to imply a conclusion while avoiding
   accountability. "Cannot rule out X" used to insinuate X without evidence.

Apply source-appropriate standards:
- RESEARCH: Confidence intervals present. Limitations section is specific, not
  generic. Scope of conclusions matches study design. Generalisability limits stated.
  Statistical significance distinguished from clinical/practical significance.
- NEWS: Developing vs settled facts distinguished. Single-source claims flagged.
  Speculation labelled as such. Quantitative claims contextualised.
- GOVERNMENT: Evidence quality graded. Gaps in evidence acknowledged.
  Distinction between strong evidence and precautionary recommendations.
- BLOG/POLICY: Author distinguishes personal interpretation from established fact.
  Confidence expressed matches evidence cited.

90-100  Explicit specific limitations; calibrated confidence throughout
75-89   Good calibration; most limitations acknowledged; minor overclaiming
55-74   Some overclaiming or false uncertainty; key limitations omitted
35-54   Significant overclaiming; definitive language on uncertain findings
0-34    No acknowledgment of limits; or systematic false uncertainty

TEXT: {text}

JSON only: {{"score":<int>,"reasoning":"<2 sentences>","key_signals":["<s1>","<s2>","<s3>"]}}
""",

"counterargument_engagement": """
Evaluate COUNTERARGUMENT ENGAGEMENT for this {source_type} source. Score 0-100.

Two failure modes:
1. OMISSION: Major contrary evidence or interpretations ignored entirely.
2. STRAWMANNING: Opposing views misrepresented in weakest form to dismiss them.

Apply source-appropriate standards:
- RESEARCH: An extensive, specific limitations section IS counterargument
  engagement — do not penalise research papers for not debating frameworks.
  Score on: contrary findings in literature cited, alternative data
  interpretations considered, limitations that could reverse the conclusion
  explicitly acknowledged.
- NEWS: Both/all material perspectives represented with named on-record sources.
  Strongest version of each side presented, not just talking points.
  Penalise single-party framing of contested events.
- GOVERNMENT: Dissenting expert opinion acknowledged. Evidence of risks or
  limitations of the recommended approach addressed.
- BLOG/POLICY: Strongest counterarguments engaged directly. Penalise
  exclusive engagement with weak versions of opposing positions.
  Exception: clearly labelled opinion/advocacy is exempt from this standard.

90-100  Substantively engages strongest counterarguments; steel-mans; cites contrary evidence
75-89   Acknowledges counterarguments with partial substantive engagement
55-74   Mentions opposition without engaging; or engages only weak versions
35-54   Ignores significant counterarguments; major contrary evidence omitted
0-34    Active strawmanning; or misrepresentation of contrary evidence

TEXT: {text}

JSON only: {{"score":<int>,"reasoning":"<2 sentences>","key_signals":["<s1>","<s2>","<s3>"]}}
"""
}

# ══════════════════════════════════════════════════════════════════
# SCORING ENGINE
# ══════════════════════════════════════════════════════════════════

async def classify_source(client, text):
    try:
        resp = client.messages.create(
            model=MODEL, max_tokens=300,
            messages=[{"role":"user","content":
                SOURCE_TYPE_PROMPT.format(text=text[:MAX_TEXT])}])
        raw = resp.content[0].text.strip()
        raw = re.sub(r"^```[\w]*\n?","",raw)
        raw = re.sub(r"```$","",raw).strip()
        m = re.search(r"\{.*\}", raw, re.DOTALL)
        if m: raw = m.group(0)
        return json.loads(raw)
    except Exception as e:
        return {"source_type":"UNKNOWN","in_scope":False,
                "confidence":0,"reasoning":str(e),
                "is_consensus_position":True,
                "funder_has_operational_control":False}

async def score_dimension(client, dim, prompt_template,
                          source_type, funder_ctrl, text):
    prompt = prompt_template.format(
        text=text[:MAX_TEXT],
        source_type=source_type,
        funder_has_operational_control=str(funder_ctrl))
    try:
        resp = client.messages.create(
            model=MODEL, max_tokens=MAX_TOKENS,
            messages=[{"role":"user","content":prompt}])
        raw = resp.content[0].text.strip()
        raw = re.sub(r"^```[\w]*\n?","",raw)
        raw = re.sub(r"```$","",raw).strip()
        m = re.search(r"\{.*\}", raw, re.DOTALL)
        if m: raw = m.group(0)
        data = json.loads(raw)
        data["score"] = max(0, min(100, int(data.get("score",50))))
        return dim, data
    except Exception as e:
        return dim, {"score":50,"reasoning":f"Error: {e}","key_signals":[],"error":str(e)}

async def score_with_claude(text):
    key = os.environ.get("ANTHROPIC_API_KEY","")
    if not key:
        raise HTTPException(500, "ANTHROPIC_API_KEY not set")
    client = anthropic.Anthropic(api_key=key)
    source_meta = await classify_source(client, text)
    source_type = source_meta.get("source_type","UNKNOWN")
    funder_ctrl = source_meta.get("funder_has_operational_control",False)
    tasks = [
        score_dimension(client, dim, prompt, source_type, funder_ctrl, text)
        for dim, prompt in DIMENSION_PROMPTS.items()
    ]
    results = await asyncio.gather(*tasks)
    dim_results = {dim: data for dim, data in results}
    return dim_results, source_meta

def classify(scores, source_meta):
    overall  = sum(scores.values()) / len(scores)
    coi      = scores.get("conflict_of_interest",50)
    method   = scores.get("methodology",50)
    false_   = scores.get("falsifiability",50)
    uncert   = scores.get("uncertainty_acknowledgment",50)
    is_cons  = source_meta.get("is_consensus_position",True)

    if overall >= 75:
        verdict,desc = "CONSENSUS","Methodologically strong. Surfaced as reliable."
    elif overall >= 55:
        verdict,desc = "CONTESTED","Mixed methodology. Verify against other sources."
    elif overall >= 35:
        verdict,desc = "HETERODOX","Methodology concerns or minority position."
    else:
        verdict,desc = "REJECTED","Fails epistemic standard."

    galileo = (
        not is_cons and
        method >= 70 and false_ >= 70 and uncert >= 55 and coi >= 55 and
        overall >= 45
    )
    if galileo and verdict in ("REJECTED","HETERODOX"):
        verdict = "HETERODOX"
        desc = "Galileo test: strong methodology challenging prevailing consensus."

    capture_flag = (overall >= 65 and coi < 45)

    return {
        "verdict":           verdict,
        "description":       desc,
        "overall_score":     round(overall,1),
        "galileo_triggered": galileo,
        "capture_flag":      capture_flag,
        "capture_warning":   (
            "Strong methodology but significant conflict of interest. "
            "Verify against independently funded sources."
            if capture_flag else None),
        "source_type":       source_meta.get("source_type","UNKNOWN"),
        "source_label":      IN_SCOPE_TYPES.get(
                                source_meta.get("source_type",""),{}
                             ).get("label",""),
    }

# ══════════════════════════════════════════════════════════════════
# ROUTES
# ══════════════════════════════════════════════════════════════════

@app.get("/health")
async def health():
    key = os.environ.get("ANTHROPIC_API_KEY","")
    return {"status":"ok","model":MODEL,"version":"0.3.0",
            "api_key":"set" if key.startswith("sk-ant") else "NOT SET",
            "key_preview":key[:20] if key else "(empty)",
            "in_scope_types": list(IN_SCOPE_TYPES.keys())}

@app.get("/test-key")
async def test_key():
    key = os.environ.get("ANTHROPIC_API_KEY","")
    if not key: return {"status":"error","message":"Key not set"}
    if not key.startswith("sk-ant"):
        return {"status":"error","message":f"Key looks wrong: {key[:8]}"}
    try:
        client = anthropic.Anthropic(api_key=key)
        resp = client.messages.create(
            model=MODEL, max_tokens=10,
            messages=[{"role":"user","content":"Reply OK only."}])
        return {"status":"success","message":resp.content[0].text.strip(),
                "key_preview":key[:16]+"..."}
    except Exception as e:
        return {"status":"error","message":str(e)}

@app.get("/clear-cache")
async def clear_cache():
    conn = get_db()
    count = conn.execute("SELECT COUNT(*) FROM score_cache").fetchone()[0]
    conn.execute("DELETE FROM score_cache")
    conn.commit(); conn.close()
    return {"status":"ok","cleared":count}

@app.post("/score")
async def score(req: ScoreRequest):
    cached = cache_get(req.url)
    if cached: return cached

    text = req.text[:MAX_TEXT]
    if len(text) < 150:
        # Return structured out-of-scope for empty/minimal pages
        return {
            "agora_version":"0.3-server",
            "timestamp":datetime.utcnow().isoformat()+"Z",
            "source_url":req.url,
            "source_title":req.title or "",
            "in_scope":False,
            "out_of_scope_reason":"PAYWALL",
            "out_of_scope_message":OUT_OF_SCOPE_REASONS["PAYWALL"],
            "scores":{},
            "classification":{"verdict":"NOT_IN_SCOPE","overall_score":None},
        }

    # URL pre-screening — no API call needed for obvious out-of-scope
    oos, reason = url_prescreening(req.url)
    if oos:
        result = {
            "agora_version":"0.3-server",
            "timestamp":datetime.utcnow().isoformat()+"Z",
            "source_url":req.url,
            "source_title":req.title or "",
            "in_scope":False,
            "out_of_scope_reason":reason,
            "out_of_scope_message":OUT_OF_SCOPE_REASONS.get(reason,"Not in scope."),
            "scores":{},
            "classification":{"verdict":"NOT_IN_SCOPE","overall_score":None},
        }
        cache_set(req.url, result, ttl_hours=6)
        return result

    # Full scoring
    dim_results, source_meta = await score_with_claude(text)

    # Check if classifier determined out-of-scope
    if not source_meta.get("in_scope", True):
        st = source_meta.get("source_type","UNKNOWN")
        result = {
            "agora_version":"0.3-server",
            "timestamp":datetime.utcnow().isoformat()+"Z",
            "source_url":req.url,
            "source_title":req.title or "",
            "in_scope":False,
            "out_of_scope_reason":st,
            "out_of_scope_message":OUT_OF_SCOPE_REASONS.get(st, OUT_OF_SCOPE_REASONS["UNKNOWN"]),
            "source_meta":source_meta,
            "scores":{},
            "classification":{"verdict":"NOT_IN_SCOPE","overall_score":None},
        }
        cache_set(req.url, result, ttl_hours=6)
        return result

    scores = {d:r["score"] for d,r in dim_results.items()}
    classification = classify(scores, source_meta)
    st = source_meta.get("source_type","UNKNOWN")

    result = {
        "agora_version":   "0.3-server",
        "timestamp":       datetime.utcnow().isoformat()+"Z",
        "source_url":      req.url,
        "source_title":    req.title or "",
        "in_scope":        True,
        "scores":          scores,
        "dimensions":      dim_results,
        "classification":  classification,
        "source_meta":     source_meta,
        "model_agreement": f"Scored as {IN_SCOPE_TYPES.get(st,{}).get('label',st)} "
                           f"(single model — ensemble in Phase 2)",
        "disagreements":   [],
    }
    cache_set(req.url, result)
    return result

@app.get("/history")
async def history(limit: int = 20):
    conn = get_db()
    rows = conn.execute("""SELECT url,title,scored_at,verdict,overall
        FROM score_cache WHERE expires_at > ?
        ORDER BY scored_at DESC LIMIT ?""",
        (int(datetime.utcnow().timestamp()), limit)).fetchall()
    conn.close()
    return [{"url":r[0],"title":r[1],"scored_at":r[2],
             "verdict":r[3],"overall":r[4]} for r in rows]

if __name__ == "__main__":
    print("\n  Agora Server v0.3")
    print(f"  In-scope types: {', '.join(IN_SCOPE_TYPES.keys())}")
    key = os.environ.get("ANTHROPIC_API_KEY","")
    print(f"  API key: {key[:20] if key else 'NOT SET'}")
    print(f"\n  http://localhost:8000\n")
    uvicorn.run(app, host="127.0.0.1", port=8000, log_level="warning")
