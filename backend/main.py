from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import sqlite3
import time
import re
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

# Global variables
conn = None
cur = None
model = None
cv_col = None

def clean_text(text):
    if not text or not isinstance(text, str): return ""
    return re.sub(r'\s+', ' ', text).strip()

def truncate_text(text, max_length=500):
    if len(text) <= max_length: return text
    truncated = text[:max_length]
    last_space = truncated.rfind(" ")
    return truncated[:last_space] if last_space > 0 else truncated

def extract_keywords(query: str) -> list[str]:
    STOP_WORDS = {"with", "and", "the", "for", "in", "of", "to", "a", "an", "is", "are", "that", "this", "have", "has", "been", "will", "can", "from", "or", "on", "at", "by", "who", "our"}
    words = re.findall(r'[a-zA-Z]+', query.lower())
    return [w for w in words if len(w) >= 3 and w not in STOP_WORDS]

@app.on_event("startup")
def startup_event():
    global conn, cur, model, cv_col
    print("Loading datasets...")
    cv_data = load_dataset("lang-uk/recruitment-dataset-candidate-profiles-english", split="train[:300]")
    
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
    cur.executemany("INSERT INTO cvs VALUES (:id, :position, :cv_text, :highlights, :keyword, :exp_years, :looking_for)", cleaned_cv)
    conn.commit()

    print("Loading SentenceTransformer model...")
    model = SentenceTransformer("paraphrase-multilingual-MiniLM-L12-v2")

    print("Connecting to Milvus...")
    try:
        connections.connect(host="localhost", port="19530")
        cv_col = Collection("cvs")
        cv_col.load()
    except Exception as e:
        print(f"Milvus connection error: {e}")

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
    sql_strategy = "AND"
    
    if keywords:
        and_conditions = " AND ".join(f"(cv_text LIKE '%{kw}%' OR position LIKE '%{kw}%' OR highlights LIKE '%{kw}%' OR keyword LIKE '%{kw}%')" for kw in keywords)
        match_score_expr = " + ".join(f"(CASE WHEN cv_text LIKE '%{kw}%' OR position LIKE '%{kw}%' OR highlights LIKE '%{kw}%' THEN 1 ELSE 0 END)" for kw in keywords)
        
        and_sql = f"SELECT id, position, keyword, cv_text, highlights, ({match_score_expr}) AS match_score FROM cvs WHERE {and_conditions} ORDER BY match_score DESC LIMIT {limit}"
        cur.execute(and_sql)
        raw_results = [dict(row) for row in cur.fetchall()]
        
        if not raw_results:
            sql_strategy = "OR"
            or_conditions = " OR ".join(f"(cv_text LIKE '%{kw}%' OR position LIKE '%{kw}%' OR highlights LIKE '%{kw}%' OR keyword LIKE '%{kw}%')" for kw in keywords)
            or_sql = f"SELECT id, position, keyword, cv_text, highlights, ({match_score_expr}) AS match_score FROM cvs WHERE {or_conditions} ORDER BY match_score DESC LIMIT {limit}"
            cur.execute(or_sql)
            raw_results = [dict(row) for row in cur.fetchall()]
        
        for i, row in enumerate(raw_results):
            sql_results.append({
                "rank": i + 1,
                "title": row["position"],
                "score": f"{row['match_score']}/{len(keywords)}",
                "text": row["cv_text"][:150] + "..."
            })
    sql_time_ms = (time.perf_counter() - sql_start) * 1000

    # --- MILVUS VECTOR SEARCH ---
    vector_start = time.perf_counter()
    vector_results = []
    if cv_col is not None:
        query_vector = model.encode([query])
        v_res = cv_col.search(
            data=query_vector.tolist(),
            anns_field="vector",
            param={"metric_type": "COSINE"},
            limit=limit,
            output_fields=["position", "keyword", "cv_text"]
        )
        for i, hit in enumerate(v_res[0]):
            score_percent = f"{hit.score:.2f}"
            vector_results.append({
                "rank": i + 1,
                "title": hit.entity.get('position'),
                "score": score_percent,
                "text": hit.entity.get('cv_text')[:150] + "..."
            })
    vector_time_ms = (time.perf_counter() - vector_start) * 1000

    return {
        "query": query,
        "keywords": keywords,
        "sql_strategy": sql_strategy,
        "sql_time_ms": sql_time_ms,
        "vector_time_ms": vector_time_ms,
        "sql_results": sql_results,
        "vector_results": vector_results
    }
