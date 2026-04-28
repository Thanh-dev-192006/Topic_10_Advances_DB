"""
=============================================================
  Semantic Recruitment Matcher — PostgreSQL Database Setup
=============================================================
Script này thực hiện toàn bộ quy trình:
  1. Load 1000 JDs + 1000 CVs từ HuggingFace
  2. Clean & chuẩn hoá dữ liệu
  3. Tạo schema PostgreSQL
  4. Insert toàn bộ data

Chạy: python setup_postgres_db.py
=============================================================
"""

import re
import sys
import os

# ── Kiểm tra thư viện ──────────────────────────────────────
try:
    import psycopg2
    from psycopg2.extras import execute_values
except ImportError:
    print("[ERROR] Thiếu psycopg2. Chạy: pip install psycopg2-binary")
    sys.exit(1)

try:
    from datasets import load_dataset
except ImportError:
    print("[ERROR] Thiếu datasets. Chạy: pip install datasets")
    sys.exit(1)


# ============================================================
# BƯỚC 1: CẤU HÌNH KẾT NỐI POSTGRESQL
# ── Sửa các giá trị này cho phù hợp với môi trường của bạn ──
# ============================================================
DB_CONFIG = {
    "host":     os.getenv("PG_HOST",  "localhost"),
    "port":     int(os.getenv("PG_PORT", "5432")),
    "dbname":   os.getenv("PG_DB",   "recruitment_db"),
    "user":     os.getenv("PG_USER", "postgres"),
    # Nếu pgAdmin không hỏi mật khẩu (trust auth) → để chuỗi rỗng ""
    # Nếu cần mật khẩu → điền vào hoặc set biến môi trường PG_PASSWORD
    "password": os.getenv("PG_PASSWORD", "chongcuavy24/7"),
}

# Số lượng bản ghi cần load
JD_LIMIT = 1000
CV_LIMIT = 1000


# ============================================================
# BƯỚC 2: HÀM TIỆN ÍCH — CLEAN DATA
# ============================================================
def clean_text(text) -> str:
    """Xử lý null + khoảng trắng thừa"""
    if not text or not isinstance(text, str):
        return ""
    return re.sub(r'\s+', ' ', text).strip()


def truncate(text: str, max_chars: int) -> str:
    """Cắt tại ranh giới từ, không đứt giữa chữ"""
    if not text:                  # ← Fix: xử lý None / ""
        return ""
    if len(text) <= max_chars:
        return text
    cut = text[:max_chars]
    last_space = cut.rfind(" ")
    return cut[:last_space] if last_space > 0 else cut


# ============================================================
# BƯỚC 3: LOAD VÀ CLEAN DATASET TỪ HUGGINGFACE
# ============================================================
def load_and_clean_datasets():
    print("\n[1/4] Đang load dataset từ HuggingFace...")

    # Load JDs — lấy tối đa JD_LIMIT bản ghi từ tập train
    jd_raw = load_dataset(
        "lang-uk/recruitment-dataset-job-descriptions-english",
        split=f"train[:{JD_LIMIT}]"
    )

    # Load CVs — lấy tối đa CV_LIMIT bản ghi từ tập train
    cv_raw = load_dataset(
        "lang-uk/recruitment-dataset-candidate-profiles-english",
        split=f"train[:{CV_LIMIT}]"
    )

    print(f"   Raw JDs: {len(jd_raw)} | Raw CVs: {len(cv_raw)}")
    print(f"   JD columns: {jd_raw.column_names}")
    print(f"   CV columns: {cv_raw.column_names}")

    # ── Clean JDs ──────────────────────────────────────────
    print("\n[2/4] Đang clean data...")
    cleaned_jd = []
    skipped_jd = 0

    for i, item in enumerate(jd_raw):
        description = clean_text(item.get("Long Description"))

        # Bỏ qua JD rỗng hoặc quá ngắn (< 20 ký tự)
        if len(description) < 20:
            skipped_jd += 1
            continue

        cleaned_jd.append({
            "id":          i + 1,
            "position":    truncate(clean_text(item.get("Position")) or "Unknown Position", 300),
            "description": truncate(description, 3000),
            "company":     truncate(clean_text(item.get("Company Name")) or "Unknown Company", 200),
            "keyword":     truncate(clean_text(item.get("Primary Keyword")) or "", 300),
            "exp_years":   truncate(clean_text(str(item.get("Exp Years") or "")), 50),
        })

    # ── Clean CVs ──────────────────────────────────────────
    cleaned_cv = []
    skipped_cv = 0

    for i, item in enumerate(cv_raw):
        cv_text = clean_text(item.get("CV"))

        # Bỏ qua CV rỗng hoặc quá ngắn
        if len(cv_text) < 20:
            skipped_cv += 1
            continue

        cleaned_cv.append({
            "id":           i + 1,
            "position":     truncate(clean_text(item.get("Position")) or "Unknown Position", 300),
            "cv_text":      truncate(cv_text, 3000),
            "highlights":   truncate(clean_text(item.get("Highlights")) or "", 1000),
            "keyword":      truncate(clean_text(item.get("Primary Keyword")) or "", 300),
            "exp_years":    truncate(clean_text(str(item.get("Experience Years") or "")), 50),
            "looking_for":  truncate(clean_text(item.get("Looking For")) or "", 500),
        })

    print(f"   JD: giữ {len(cleaned_jd)}, bỏ {skipped_jd} (rỗng/ngắn)")
    print(f"   CV: giữ {len(cleaned_cv)}, bỏ {skipped_cv} (rỗng/ngắn)")

    return cleaned_jd, cleaned_cv


# ============================================================
# BƯỚC 4: TẠO SCHEMA TRONG POSTGRESQL
# ============================================================
CREATE_JD_TABLE = """
CREATE TABLE IF NOT EXISTS job_descriptions (
    id          SERIAL      PRIMARY KEY,
    position    VARCHAR(300)    NOT NULL DEFAULT '',
    description TEXT            NOT NULL,
    company     VARCHAR(200)    NOT NULL DEFAULT '',
    keyword     VARCHAR(300)    NOT NULL DEFAULT '',
    exp_years   VARCHAR(50)     NOT NULL DEFAULT '',
    created_at  TIMESTAMP       DEFAULT NOW()
);
"""

CREATE_CV_TABLE = """
CREATE TABLE IF NOT EXISTS cvs (
    id          SERIAL      PRIMARY KEY,
    position    VARCHAR(300)    NOT NULL DEFAULT '',
    cv_text     TEXT            NOT NULL,
    highlights  TEXT            NOT NULL DEFAULT '',
    keyword     VARCHAR(300)    NOT NULL DEFAULT '',
    exp_years   VARCHAR(50)     NOT NULL DEFAULT '',
    looking_for TEXT            NOT NULL DEFAULT '',
    created_at  TIMESTAMP       DEFAULT NOW()
);
"""

# psycopg2 chỉ chạy được 1 câu SQL mỗi lần cur.execute()
# → phải tách thành list, không gom chung 1 string
CREATE_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_jd_position ON job_descriptions USING gin(to_tsvector('english', position))",
    "CREATE INDEX IF NOT EXISTS idx_jd_keyword  ON job_descriptions USING gin(to_tsvector('english', keyword))",
    "CREATE INDEX IF NOT EXISTS idx_jd_desc     ON job_descriptions USING gin(to_tsvector('english', description))",
    "CREATE INDEX IF NOT EXISTS idx_cv_position ON cvs USING gin(to_tsvector('english', position))",
    "CREATE INDEX IF NOT EXISTS idx_cv_keyword  ON cvs USING gin(to_tsvector('english', keyword))",
    "CREATE INDEX IF NOT EXISTS idx_cv_text     ON cvs USING gin(to_tsvector('english', cv_text))",
]


def setup_schema(cur):
    """Tạo tables và indexes trong PostgreSQL"""
    print("\n[3/4] Đang tạo schema...")

    cur.execute("DROP TABLE IF EXISTS job_descriptions CASCADE;")
    cur.execute("DROP TABLE IF EXISTS cvs CASCADE;")
    print("   Dropped tables cũ (nếu có)")

    cur.execute(CREATE_JD_TABLE)
    print("   ✓ Tạo bảng job_descriptions")

    cur.execute(CREATE_CV_TABLE)
    print("   ✓ Tạo bảng cvs")

    # Chạy từng câu CREATE INDEX riêng lẻ
    for sql in CREATE_INDEXES:
        cur.execute(sql)
    print("   ✓ Tạo 6 GIN indexes cho full-text search")


# ============================================================
# BƯỚC 5: INSERT DATA VÀO POSTGRESQL
# ============================================================
def insert_data(cur, cleaned_jd, cleaned_cv):
    """Insert toàn bộ data dùng execute_values (batch insert nhanh)"""
    print("\n[4/4] Đang insert data...")

    # ── Insert JDs ─────────────────────────────────────────
    jd_rows = [
        (
            item["position"],
            item["description"],
            item["company"],
            item["keyword"],
            item["exp_years"],
        )
        for item in cleaned_jd
    ]
    execute_values(
        cur,
        """
        INSERT INTO job_descriptions (position, description, company, keyword, exp_years)
        VALUES %s
        """,
        jd_rows,
        page_size=200  # Insert 200 hàng mỗi batch
    )
    print(f"   ✓ Inserted {len(jd_rows)} job descriptions")

    # ── Insert CVs ─────────────────────────────────────────
    cv_rows = [
        (
            item["position"],
            item["cv_text"],
            item["highlights"],
            item["keyword"],
            item["exp_years"],
            item["looking_for"],
        )
        for item in cleaned_cv
    ]
    execute_values(
        cur,
        """
        INSERT INTO cvs (position, cv_text, highlights, keyword, exp_years, looking_for)
        VALUES %s
        """,
        cv_rows,
        page_size=200
    )
    print(f"   ✓ Inserted {len(cv_rows)} candidate CVs")


# ============================================================
# BƯỚC 6: VERIFY — KIỂM TRA KẾT QUẢ SAU KHI INSERT
# ============================================================
def verify_data(cur):
    """Chạy một số query kiểm tra để xác nhận data đã vào đúng"""
    print("\n" + "="*55)
    print("  VERIFY — Kiểm tra data trong PostgreSQL")
    print("="*55)

    cur.execute("SELECT COUNT(*) FROM job_descriptions;")
    jd_count = cur.fetchone()[0]

    cur.execute("SELECT COUNT(*) FROM cvs;")
    cv_count = cur.fetchone()[0]

    print(f"\n  Tổng job_descriptions : {jd_count}")
    print(f"  Tổng cvs              : {cv_count}")

    # Sample JD
    print("\n  -- Sample JD (3 bản ghi đầu) --")
    cur.execute("SELECT id, position, company, keyword, exp_years FROM job_descriptions LIMIT 3;")
    for row in cur.fetchall():
        print(f"   [{row[0]}] {row[1][:40]} | {row[2][:25]} | kw: {row[3][:20]} | exp: {row[4]}")

    # Sample CV
    print("\n  -- Sample CV (3 bản ghi đầu) --")
    cur.execute("SELECT id, position, keyword, exp_years FROM cvs LIMIT 3;")
    for row in cur.fetchall():
        print(f"   [{row[0]}] {row[1][:40]} | kw: {row[2][:20]} | exp: {row[3]}")

    # Demo LIKE query
    print("\n  -- Demo SQL LIKE query: tìm CV có 'Python' --")
    cur.execute("""
        SELECT id, position, keyword, cv_text
        FROM cvs
        WHERE cv_text ILIKE '%python%'
           OR keyword ILIKE '%python%'
        LIMIT 5;
    """)
    rows = cur.fetchall()
    print(f"  Tìm thấy (top 5 / tổng nhiều hơn): {len(rows)} kết quả")
    for row in rows:
        print(f"   [{row[0]}] {row[1][:35]} | {row[2][:25]}")

    print("\n  ✅ Database sẵn sàng sử dụng!")
    print(f"     Host: {DB_CONFIG['host']}:{DB_CONFIG['port']}")
    print(f"     DB  : {DB_CONFIG['dbname']}")
    print(f"     User: {DB_CONFIG['user']}")


# ============================================================
# MAIN
# ============================================================
def main():
    print("="*55)
    print("  Recruitment DB Setup — PostgreSQL")
    print(f"  Target: {JD_LIMIT} JDs + {CV_LIMIT} CVs")
    print("="*55)

    # Load + clean data
    cleaned_jd, cleaned_cv = load_and_clean_datasets()

    # Kết nối PostgreSQL
    print(f"\n   Connecting to PostgreSQL: {DB_CONFIG['host']}:{DB_CONFIG['port']}/{DB_CONFIG['dbname']}...")
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        conn.autocommit = False
        cur = conn.cursor()
        print("   ✓ Kết nối thành công")
    except psycopg2.OperationalError as e:
        print(f"\n[ERROR] Không kết nối được PostgreSQL:\n  {e}")
        print("\nKiểm tra lại DB_CONFIG ở đầu file hoặc biến môi trường:")
        print("  PG_HOST / PG_PORT / PG_DB / PG_USER / PG_PASSWORD")
        sys.exit(1)

    try:
        setup_schema(cur)
        insert_data(cur, cleaned_jd, cleaned_cv)
        conn.commit()
        verify_data(cur)
    except Exception as e:
        conn.rollback()
        print(f"\n[ERROR] {e}")
        raise
    finally:
        cur.close()
        conn.close()
        print("\n   Connection closed.")


if __name__ == "__main__":
    main()