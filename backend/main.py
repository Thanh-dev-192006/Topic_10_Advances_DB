from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import psycopg2
import psycopg2.extras
import configparser
import time
import re
import os
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
jd_count = 0
milvus_connected = False

def clean_text(text):
    if not text or not isinstance(text, str): return ""
    return re.sub(r'\s+', ' ', text).strip()

def extract_keywords(query: str) -> list[str]:
    STOP_WORDS = {"with", "and", "the", "for", "in", "of", "to", "a", "an", "is", "are",
                  "that", "this", "have", "has", "been", "will", "can", "from", "or", "on",
                  "at", "by", "who", "our"}
    words = re.findall(r'[a-zA-Z0-9]+', query.lower())
    return [w for w in words if len(w) >= 2 and w not in STOP_WORDS]

def load_db_config(config_file: str = "config.properties") -> dict:
    config_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "Postgre-setup", config_file))
    default_config = {
        "host": os.getenv("PG_HOST", "localhost"),
        "port": int(os.getenv("PG_PORT", "5432")),
        "dbname": os.getenv("PG_DB", "recruitment_db"),
        "user": os.getenv("PG_USER", "postgres"),
        "password": os.getenv("PG_PASSWORD", ""),
    }

    if not os.path.exists(config_path):
        return default_config

    config = configparser.ConfigParser()
    try:
        config.read(config_path, encoding="utf-8")
    except configparser.MissingSectionHeaderError:
        with open(config_path, "r", encoding="utf-8") as f:
            raw_config = f.read()
        config.read_string("[postgresql]\n" + raw_config)

    if "postgresql" not in config:
        return default_config

    pg = config["postgresql"]
    return {
        "host": pg.get("host", default_config["host"]),
        "port": int(pg.get("port", str(default_config["port"]))),
        "dbname": pg.get("dbname", default_config["dbname"]),
        "user": pg.get("user", default_config["user"]),
        "password": pg.get("password", default_config["password"]),
    }

@app.on_event("startup")
def startup_event():
    global conn, cur, model, cv_col, cv_count, jd_count, milvus_connected
    
    print("Connecting to PostgreSQL...")
    db_config = load_db_config()
    try:
        conn = psycopg2.connect(**db_config)
        conn.autocommit = True
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        
        cur.execute("SELECT COUNT(*) FROM cvs")
        cv_count = cur.fetchone()["count"]
        
        cur.execute("SELECT COUNT(*) FROM job_descriptions")
        jd_count = cur.fetchone()["count"]
        print(f"PostgreSQL ready: {cv_count} CVs, {jd_count} JDs")
    except Exception as e:
        print(f"PostgreSQL connection error: {e}")

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
        "jd_count": jd_count,
        "milvus_connected": milvus_connected,
        "sql_engine": "PostgreSQL",
        "embedding_model": "paraphrase-multilingual-MiniLM-L12-v2",
        "vector_dim": 384,
    }


# ── CV / JD Management endpoints ─────────────────────────────────────────────

@app.get("/api/cvs")
def list_cvs(query: str = Query(""), limit: int = 100):
    q = f"%{query}%"
    cur.execute(
        "SELECT id, position, keyword, exp_years, cv_text, highlights, looking_for"
        " FROM cvs"
        " WHERE position ILIKE %s OR keyword ILIKE %s OR cv_text ILIKE %s OR highlights ILIKE %s"
        " ORDER BY id LIMIT %s",
        (q, q, q, q, limit)
    )
    rows = [dict(row) for row in cur.fetchall()]
    return {"cvs": rows}


@app.get("/api/jds")
def list_jds(query: str = Query(""), limit: int = 100):
    q = f"%{query}%"
    cur.execute(
        "SELECT id, position, company, keyword, exp_years, description"
        " FROM job_descriptions"
        " WHERE position ILIKE %s OR company ILIKE %s OR keyword ILIKE %s OR description ILIKE %s"
        " ORDER BY id LIMIT %s",
        (q, q, q, q, limit)
    )
    rows = [dict(row) for row in cur.fetchall()]
    return {"jds": rows}


# ── Search endpoint ──────────────────────────────────────────────────────────

class SearchResponse(BaseModel):
    query: str
    keywords: list[str]
    sql_strategy: str
    sql_time_ms: float
    vector_time_ms: float
    sql_results: list[dict]
    vector_results: list[dict]
    sql_filtered_reason: str = ""
    vector_filtered_reason: str = ""

@app.get("/api/search", response_model=SearchResponse)
def search(
    query: str = Query(...),
    limit: int = 5,
    min_score: int = Query(0, ge=0, le=100),
    vector_threshold: int = Query(0, ge=0, le=100),
):
    keywords = extract_keywords(query)
    min_score = max(0, min(100, min_score))
    vector_threshold = max(0, min(100, vector_threshold))

    # --- SQL LIKE SEARCH ---
    sql_start = time.perf_counter()
    sql_results = []
    sql_strategy = "N/A"
    raw_results = []

    if keywords:
        score_check = (
            "(CASE WHEN position ILIKE %s THEN 2 ELSE 0 END"
            " + CASE WHEN keyword ILIKE %s THEN 2 ELSE 0 END"
            " + CASE WHEN cv_text ILIKE %s THEN 1 ELSE 0 END"
            " + CASE WHEN highlights ILIKE %s THEN 1 ELSE 0 END)"
        )
        count_check = (
            "(CASE WHEN cv_text ILIKE %s OR position ILIKE %s OR highlights ILIKE %s OR keyword ILIKE %s"
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
            f" FROM ({subquery}) q"
            f" WHERE keyword_count >= %s"
            f" ORDER BY match_score DESC LIMIT %s"
        )

        sql_fetch_limit = 1000  # Fetch all candidates first, then filter by Search Tuning
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
            if len(raw_results) >= sql_fetch_limit:
                break
            # Note: in psycopg2, pass parameters as a tuple
            cur.execute(outer_sql, tuple(kw_params + kw_params + [n_required, sql_fetch_limit]))
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
                "highlights": row["highlights"] or "",
                "exp_years": row["exp_years"] or "",
                "kws": row["keyword"] or ""
            })

        if min_score > 0:
            sql_results = [item for item in sql_results if int(item["score"]) >= min_score]
        sql_results = sql_results[:limit]

        sql_filtered_reason = ""
        if min_score > 0 and len(sql_results) == 0:
            sql_filtered_reason = f"Does not satisfy min match score = {min_score}%"

    sql_time_ms = (time.perf_counter() - sql_start) * 1000

    # --- MILVUS VECTOR SEARCH ---
    vector_start = time.perf_counter()
    vector_results = []
    if cv_col is not None:
        query_vector = model.encode([query])
        # Fetch more candidates for re-ranking (Hybrid approach)
        fetch_limit = 1000  # Fetch all candidates first, then filter by Search Tuning
        v_res = cv_col.search(
            data=query_vector.tolist(),
            anns_field="vector",
            param={"metric_type": "COSINE"},
            limit=fetch_limit,
            output_fields=["position", "keyword", "cv_text"],
        )

        hits = v_res[0]
        if hits:
            # Fetch extra metadata from PostgreSQL
            hit_ids = [hit.id for hit in hits]
            placeholders = ','.join(['%s']*len(hit_ids))
            cur.execute(f"SELECT id, highlights, exp_years FROM cvs WHERE id IN ({placeholders})", tuple(hit_ids))
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
            
            for i, (final_score, hit) in enumerate(scored_hits):
                # Cap the percentage at 100% just in case
                score_pct = min(100, round(max(0.0, final_score) * 100))
                if score_pct < vector_threshold:
                    continue
                
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
                if len(vector_results) >= limit:
                    break
    vector_time_ms = (time.perf_counter() - vector_start) * 1000

    vector_filtered_reason = ""
    if vector_threshold > 0 and len(vector_results) == 0:
        vector_filtered_reason = f"Does not satisfy vector threshold = {vector_threshold}%"

    return {
        "query": query,
        "keywords": keywords,
        "sql_strategy": sql_strategy,
        "sql_time_ms": sql_time_ms,
        "vector_time_ms": vector_time_ms,
        "sql_results": sql_results,
        "vector_results": vector_results,
        "sql_filtered_reason": sql_filtered_reason,
        "vector_filtered_reason": vector_filtered_reason,
    }

# ── Auto-suggest endpoint ───────────────────────────────────────────────────

@app.get("/api/suggest")
def suggest(q: str = Query("")):
    if len(q) < 2: return {"suggestions": []}
    # Search for matching positions or keywords
    cur.execute(
        "SELECT DISTINCT position FROM cvs WHERE position ILIKE %s LIMIT 50",
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
            SUM(CASE WHEN exp_years ILIKE '%1%' OR exp_years ILIKE '%2%' THEN 1 ELSE 0 END) as junior,
            SUM(CASE WHEN exp_years ILIKE '%3%' OR exp_years ILIKE '%4%' OR exp_years ILIKE '%5%' THEN 1 ELSE 0 END) as mid,
            SUM(CASE WHEN exp_years ILIKE '%6%' OR exp_years ILIKE '%7%' OR exp_years ILIKE '%8%' OR exp_years ILIKE '%9%' OR exp_years ILIKE '%10%' THEN 1 ELSE 0 END) as senior
        FROM cvs
    """)
    exp = dict(cur.fetchone())
    
    # Top positions
    cur.execute("SELECT position, COUNT(*) as count FROM cvs GROUP BY position ORDER BY count DESC LIMIT 5")
    positions = [dict(row) for row in cur.fetchall()]
    
    return {
        "experience": {"Junior (1-2y)": int(exp["junior"] or 0), "Mid (3-5y)": int(exp["mid"] or 0), "Senior (6y+)": int(exp["senior"] or 0)},
        "top_positions": positions
    }

# ── Serve frontend as static files (fixes file:// CORS issue) ───────────────
# Open http://localhost:8001 instead of opening index.html directly

_ui_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "semantic-matcher-ui"))

if os.path.isdir(_ui_dir):
    app.mount("/", StaticFiles(directory=_ui_dir, html=True), name="frontend")
