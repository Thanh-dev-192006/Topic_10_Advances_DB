from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import sqlite3
import time
import re
import os
from datasets import load_dataset
from sentence_transformers import SentenceTransformer
from pymilvus import connections, Collection

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

conn = None
cur = None
model = None
cv_col = None
cv_count = 0
milvus_connected = False

def clean_text(text):
    if not text or not isinstance(text, str): return ""
    return re.sub(r'\s+', ' ', text).strip()

def truncate_text(text, max_length=500):
    if len(text) <= max_length: return text
    truncated = text[:max_length]
    last_space = truncated.rfind(" ")
    return truncated[:last_space] if last_space > 0 else truncated

def extract_keywords(query: str) -> list[str]:
    STOP_WORDS = {"with", "and", "the", "for", "in", "of", "to", "a", "an", "is", "are",
                  "that", "this", "have", "has", "been", "will", "can", "from", "or", "on",
                  "at", "by", "who", "our"}
    words = re.findall(r'[a-zA-Z0-9]+', query.lower())
    return [w for w in words if len(w) >= 2 and w not in STOP_WORDS]

@app.on_event("startup")
def startup_event():
    global conn, cur, model, cv_col, cv_count, milvus_connected
    print("Loading datasets...")
    # Match the 1000-CV count already indexed in Milvus (see datasets_v2.ipynb)
    cv_data = load_dataset("lang-uk/recruitment-dataset-candidate-profiles-english", split="train[:1000]")

    cleaned_cv = []
    for i, item in enumerate(cv_data):
        cv_text = clean_text(item.get("CV"))
        if len(cv_text) >= 20:
            cleaned_cv.append({
                "id": i + 1,
                "position": clean_text(item.get("Position")) or "Unknown",
                "cv_text": truncate_text(cv_text, 2000),
                "highlights": clean_text(item.get("Highlights")) or "",
                "keyword": clean_text(item.get("Primary Keyword")) or "",
                "exp_years": clean_text(str(item.get("Experience Years") or "")),
                "looking_for": clean_text(item.get("Looking For")) or "",
            })

    print("Initializing SQLite...")
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE cvs (
            id INTEGER PRIMARY KEY, position TEXT, cv_text TEXT,
            highlights TEXT, keyword TEXT, exp_years TEXT, looking_for TEXT
        )
    """)
    cur.executemany(
        "INSERT INTO cvs VALUES (:id, :position, :cv_text, :highlights, :keyword, :exp_years, :looking_for)",
        cleaned_cv
    )
    conn.commit()
    cv_count = len(cleaned_cv)
    print(f"SQLite ready: {cv_count} CVs")

    print("Loading SentenceTransformer model...")
    model = SentenceTransformer("paraphrase-multilingual-MiniLM-L12-v2")

    print("Connecting to Milvus...")
    try:
        connections.connect(host="localhost", port="19530")
        cv_col = Collection("cvs")
        cv_col.load()
        milvus_connected = True
        print("Milvus connected.")
    except Exception as e:
        print(f"Milvus connection error: {e}")
        milvus_connected = False


# ── Status endpoint ─────────────────────────────────────────────────────────

@app.get("/api/status")
def status():
    return {
        "cv_count": cv_count,
        "milvus_connected": milvus_connected,
        "sql_engine": "SQLite (in-memory)",
        "embedding_model": "paraphrase-multilingual-MiniLM-L12-v2",
        "vector_dim": 384,
    }


# ── Search endpoint ──────────────────────────────────────────────────────────

class SearchResponse(BaseModel):
    query: str
    keywords: list[str]
    sql_strategy: str
    sql_time_ms: float
    vector_time_ms: float
    sql_results: list[dict]
    vector_results: list[dict]

@app.get("/api/search", response_model=SearchResponse)
def search(query: str = Query(...), limit: int = 5):
    keywords = extract_keywords(query)

    # --- SQL LIKE SEARCH ---
    sql_start = time.perf_counter()
    sql_results = []
    sql_strategy = "N/A"
    raw_results = []

    if keywords:
        score_check = (
            "(CASE WHEN position LIKE ? THEN 2 ELSE 0 END"
            " + CASE WHEN keyword LIKE ? THEN 2 ELSE 0 END"
            " + CASE WHEN cv_text LIKE ? THEN 1 ELSE 0 END"
            " + CASE WHEN highlights LIKE ? THEN 1 ELSE 0 END)"
        )
        count_check = (
            "(CASE WHEN cv_text LIKE ? OR position LIKE ? OR highlights LIKE ? OR keyword LIKE ?"
            " THEN 1 ELSE 0 END)"
        )

        match_score_expr = " + ".join(score_check for _ in keywords)
        keyword_count_expr = " + ".join(count_check for _ in keywords)
        kw_params = [f'%{kw}%' for kw in keywords for _ in range(4)]

        subquery = (
            f"SELECT id, position, keyword, cv_text, highlights, exp_years,"
            f" ({match_score_expr}) AS match_score,"
            f" ({keyword_count_expr}) AS keyword_count"
            f" FROM cvs"
        )
        outer_sql = (
            f"SELECT id, position, keyword, cv_text, highlights, exp_years, match_score, keyword_count"
            f" FROM ({subquery})"
            f" WHERE keyword_count >= ?"
            f" ORDER BY match_score DESC LIMIT ?"
        )

        n_all = len(keywords)
        n_partial = min(n_all, max(2, n_all * 2 // 3))
        seen: set[int] = set()
        thresholds = []
        for n, name in [(n_all, "AND"), (n_partial, "PARTIAL"), (1, "OR")]:
            if n not in seen:
                seen.add(n)
                thresholds.append((n, name))

        seen_ids = set()
        sql_strategies = []
        for n_required, strategy_name in thresholds:
            if len(raw_results) >= limit:
                break
            cur.execute(outer_sql, kw_params + kw_params + [n_required, limit])
            added_this_round = False
            for row in cur.fetchall():
                if row["id"] not in seen_ids:
                    seen_ids.add(row["id"])
                    raw_results.append(dict(row))
                    added_this_round = True
                    if len(raw_results) >= limit:
                        break
            if added_this_round:
                sql_strategies.append(strategy_name)

        if sql_strategies:
            sql_strategy = " + ".join(sql_strategies)

        for i, row in enumerate(raw_results):
            # Base score: up to 70% based on how many keywords were found anywhere
            base_pct = (row["keyword_count"] / len(keywords)) * 70 if len(keywords) > 0 else 0
            
            # Bonus score: up to 30% if keywords appear in high-weight fields (position, highlights)
            extra_points = row["match_score"] - row["keyword_count"]
            max_extra = 5 * len(keywords) # 6 max possible - 1 for cv_text
            bonus_pct = (extra_points / max_extra) * 30 if max_extra > 0 else 0
            
            score_pct = min(100, round(base_pct + bonus_pct))
            
            sql_results.append({
                "rank": i + 1,
                "title": row["position"],
                "score": str(score_pct),
                "raw_score": f"{row['keyword_count']}/{len(keywords)} kw",
                "text": row["cv_text"][:150] + "...",
                "full_text": row["cv_text"],
                "highlights": row["highlights"],
                "exp_years": row["exp_years"],
                "kws": row["keyword"]
            })

    sql_time_ms = (time.perf_counter() - sql_start) * 1000

    # --- MILVUS VECTOR SEARCH ---
    vector_start = time.perf_counter()
    vector_results = []
    if cv_col is not None:
        query_vector = model.encode([query])
        # Fetch more candidates for re-ranking (Hybrid approach)
        fetch_limit = limit * 4
        v_res = cv_col.search(
            data=query_vector.tolist(),
            anns_field="vector",
            param={"metric_type": "COSINE"},
            limit=fetch_limit,
            output_fields=["position", "keyword", "cv_text"],
        )

        hits = v_res[0]
        if hits:
            # Fetch extra metadata from SQLite
            hit_ids = [hit.id for hit in hits]
            cur.execute(f"SELECT id, highlights, exp_years FROM cvs WHERE id IN ({','.join(['?']*len(hit_ids))})", hit_ids)
            extra_data = {r["id"]: dict(r) for r in cur.fetchall()}

            scored_hits = []
            for hit in hits:
                pos = (hit.entity.get("position") or "").lower()
                kw = (hit.entity.get("keyword") or "").lower()
                text = (hit.entity.get("cv_text") or "").lower()
                
                # Apply lexical bonus to vector score
                bonus = 0.0
                if keywords:
                    for k in keywords:
                        # Exact word matching or substring matching
                        if k in pos: bonus += 0.15
                        elif k in kw: bonus += 0.10
                        elif k in text: bonus += 0.05
                
                final_score = hit.score + bonus
                scored_hits.append((final_score, hit))
            
            # Sort descending by the new hybrid score
            scored_hits.sort(key=lambda x: x[0], reverse=True)
            
            for i, (final_score, hit) in enumerate(scored_hits[:limit]):
                # Cap the percentage at 100% just in case
                score_pct = min(100, round(max(0.0, final_score) * 100))
                
                # Show hybrid components in raw_score
                bonus_str = f" + {(final_score - hit.score):.2f} kw" if final_score > hit.score else ""
                
                extra = extra_data.get(hit.id, {})
                vector_results.append({
                    "rank": i + 1,
                    "title": hit.entity.get("position"),
                    "score": str(score_pct),
                    "raw_score": f"cos {hit.score:.3f}{bonus_str}",
                    "text": hit.entity.get("cv_text")[:150] + "...",
                    "full_text": hit.entity.get("cv_text"),
                    "highlights": extra.get("highlights", ""),
                    "exp_years": extra.get("exp_years", ""),
                    "kws": hit.entity.get("keyword")
                })
    vector_time_ms = (time.perf_counter() - vector_start) * 1000

    return {
        "query": query,
        "keywords": keywords,
        "sql_strategy": sql_strategy,
        "sql_time_ms": sql_time_ms,
        "vector_time_ms": vector_time_ms,
        "sql_results": sql_results,
        "vector_results": vector_results,
    }

# ── Auto-suggest endpoint ───────────────────────────────────────────────────

@app.get("/api/suggest")
def suggest(q: str = Query("")):
    if len(q) < 2: return {"suggestions": []}
    # Search for matching positions or keywords
    cur.execute(
        "SELECT DISTINCT position FROM cvs WHERE position LIKE ? LIMIT 50",
        (f"%{q}%",)
    )
    
    suggestions = set()
    q_lower = q.lower()
    for row in cur.fetchall():
        pos_raw = row["position"]
        if not pos_raw: continue
        
        # Split by comma, pipe, or forward slash
        parts = re.split(r'[,|/]+', pos_raw)
        for part in parts:
            part = part.strip()
            if q_lower in part.lower():
                # Avoid insanely long suggestions
                if len(part) <= 40:
                    # Capitalize nicely
                    suggestions.add(part.title() if part.islower() else part)
        
        if len(suggestions) >= 5:
            break
            
    return {"suggestions": list(suggestions)[:5]}

# ── Stats endpoint ──────────────────────────────────────────────────────────

@app.get("/api/stats")
def stats():
    # Experience distribution
    cur.execute("""
        SELECT 
            SUM(CASE WHEN exp_years LIKE '%1%' OR exp_years LIKE '%2%' THEN 1 ELSE 0 END) as junior,
            SUM(CASE WHEN exp_years LIKE '%3%' OR exp_years LIKE '%4%' OR exp_years LIKE '%5%' THEN 1 ELSE 0 END) as mid,
            SUM(CASE WHEN exp_years LIKE '%6%' OR exp_years LIKE '%7%' OR exp_years LIKE '%8%' OR exp_years LIKE '%9%' OR exp_years LIKE '%10%' THEN 1 ELSE 0 END) as senior
        FROM cvs
    """)
    exp = dict(cur.fetchone())
    
    # Top positions
    cur.execute("SELECT position, COUNT(*) as count FROM cvs GROUP BY position ORDER BY count DESC LIMIT 5")
    positions = [dict(row) for row in cur.fetchall()]
    
    return {
        "experience": {"Junior (1-2y)": exp["junior"] or 0, "Mid (3-5y)": exp["mid"] or 0, "Senior (6y+)": exp["senior"] or 0},
        "top_positions": positions
    }

# ── Serve frontend as static files (fixes file:// CORS issue) ───────────────
# Open http://localhost:8001 instead of opening index.html directly

_ui_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "semantic-matcher-ui"))

if os.path.isdir(_ui_dir):
    app.mount("/", StaticFiles(directory=_ui_dir, html=True), name="frontend")
