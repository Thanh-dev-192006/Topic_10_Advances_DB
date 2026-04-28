"""
=============================================================
  Semantic Recruitment Matcher - Load Data vao PostgreSQL
=============================================================
Yeu cau:
  - Da tao database + schema thu cong trong pgAdmin/psql
  - Co the dung config.properties hoac bien moi truong PG_*

Chay: python load_data.py
=============================================================
"""

import os
import re
import sys
import configparser

try:
    import psycopg2
    from psycopg2.extras import execute_values
except ImportError:
    print("[ERROR] Thieu psycopg2. Chay: pip install psycopg2-binary")
    sys.exit(1)

try:
    from datasets import load_dataset
except ImportError:
    print("[ERROR] Thieu datasets. Chay: pip install datasets")
    sys.exit(1)


# =============================================================
#   Doc config tu config.properties
# =============================================================

def load_db_config(config_file: str = "config.properties") -> dict:
    """Doc thong tin ket noi PostgreSQL tu config file, fallback sang env/default."""
    config_path = os.path.join(os.path.dirname(__file__), config_file)
    default_config = {
        "host": os.getenv("PG_HOST", "localhost"),
        "port": int(os.getenv("PG_PORT", "5432")),
        "dbname": os.getenv("PG_DB", "recruitment_db"),
        "user": os.getenv("PG_USER", "postgres"),
        "password": os.getenv("PG_PASSWORD", ""),
    }

    if not os.path.exists(config_path):
        print(f"[WARN] Khong tim thay file: {config_path}")
        print("  Dang dung bien moi truong PG_* hoac gia tri mac dinh.")
        return default_config

    config = configparser.ConfigParser()
    try:
        config.read(config_path, encoding="utf-8")
    except configparser.MissingSectionHeaderError:
        with open(config_path, "r", encoding="utf-8") as f:
            raw_config = f.read()
        config.read_string("[postgresql]\n" + raw_config)

    if "postgresql" not in config:
        print("[WARN] File config.properties thieu section [postgresql]")
        print("  Dang dung bien moi truong PG_* hoac gia tri mac dinh.")
        return default_config

    pg = config["postgresql"]
    return {
        "host": pg.get("host", default_config["host"]),
        "port": int(pg.get("port", str(default_config["port"]))),
        "dbname": pg.get("dbname", default_config["dbname"]),
        "user": pg.get("user", default_config["user"]),
        "password": pg.get("password", default_config["password"]),
    }


# =============================================================
#   Gioi han so luong ban ghi load
# =============================================================

JD_LIMIT = 1000
CV_LIMIT = 1000


# =============================================================
#   Ham lam sach du lieu
# =============================================================

def clean_text(text) -> str:
    """Xu ly null va khoang trang thua."""
    if not text or not isinstance(text, str):
        return ""
    return re.sub(r"\s+", " ", text).strip()


def clean_scalar(value) -> str:
    """Chuan hoa scalar, doi None thanh chuoi rong."""
    if value is None:
        return ""
    return clean_text(str(value))


def truncate(text: str, max_chars: int) -> str:
    """Cat tai ranh gioi tu, khong dut giua chu."""
    if not text:
        return ""
    if len(text) <= max_chars:
        return text
    cut = text[:max_chars]
    last_space = cut.rfind(" ")
    return cut[:last_space] if last_space > 0 else cut


def sanitize_jd_row(item: dict):
    """Lam sach 1 JD truoc khi insert. Tra ve None neu description qua ngan."""
    description = truncate(clean_scalar(item.get("Long Description")), 3000)
    if len(description) < 20:
        return None

    return {
        "position":    truncate(clean_scalar(item.get("Position"))    or "Unknown Position", 300),
        "description": description,
        "company":     truncate(clean_scalar(item.get("Company Name")) or "Unknown Company",  200),
        "keyword":     truncate(clean_scalar(item.get("Primary Keyword")),                    300),
        "exp_years":   truncate(clean_scalar(item.get("Exp Years")),                           50),
    }


def sanitize_cv_row(item: dict):
    """Lam sach 1 CV truoc khi insert. Tra ve None neu cv_text qua ngan."""
    cv_text = truncate(clean_scalar(item.get("CV")), 3000)
    if len(cv_text) < 20:
        return None

    return {
        "position":    truncate(clean_scalar(item.get("Position"))         or "Unknown Position", 300),
        "cv_text":     cv_text,
        "highlights":  truncate(clean_scalar(item.get("Highlights")),                            1000),
        "keyword":     truncate(clean_scalar(item.get("Primary Keyword")),                        300),
        "exp_years":   truncate(clean_scalar(item.get("Experience Years")),                        50),
        "looking_for": truncate(clean_scalar(item.get("Looking For")),                            500),
    }


# =============================================================
#   Load va clean dataset tu HuggingFace
# =============================================================

def load_and_clean_datasets():
    print("\n[1/3] Dang load dataset tu HuggingFace...")

    jd_raw = load_dataset(
        "lang-uk/recruitment-dataset-job-descriptions-english",
        split=f"train[:{JD_LIMIT}]",
    )
    cv_raw = load_dataset(
        "lang-uk/recruitment-dataset-candidate-profiles-english",
        split=f"train[:{CV_LIMIT}]",
    )

    print(f"   Raw JDs : {len(jd_raw)} ban ghi | columns: {jd_raw.column_names}")
    print(f"   Raw CVs : {len(cv_raw)} ban ghi | columns: {cv_raw.column_names}")

    print("\n[2/3] Dang clean data...")

    cleaned_jd, skipped_jd = [], 0
    for item in jd_raw:
        row = sanitize_jd_row(item)
        if row is None:
            skipped_jd += 1
        else:
            cleaned_jd.append(row)

    cleaned_cv, skipped_cv = [], 0
    for item in cv_raw:
        row = sanitize_cv_row(item)
        if row is None:
            skipped_cv += 1
        else:
            cleaned_cv.append(row)

    print(f"   JD: giu {len(cleaned_jd)}, bo {skipped_jd} (rong/qua ngan)")
    print(f"   CV: giu {len(cleaned_cv)}, bo {skipped_cv} (rong/qua ngan)")

    return cleaned_jd, cleaned_cv


# =============================================================
#   Insert du lieu vao PostgreSQL
# =============================================================

def insert_data(cur, cleaned_jd: list, cleaned_cv: list):
    print("\n[3/3] Dang insert data vao PostgreSQL...")

    # --- Job Descriptions ---
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

    if jd_rows:
        execute_values(
            cur,
            """
            INSERT INTO job_descriptions (position, description, company, keyword, exp_years)
            VALUES %s
            """,
            jd_rows,
            page_size=200,
        )
    print(f"   Inserted {len(jd_rows)} job descriptions")

    # --- CVs ---
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

    if cv_rows:
        execute_values(
            cur,
            """
            INSERT INTO cvs (position, cv_text, highlights, keyword, exp_years, looking_for)
            VALUES %s
            """,
            cv_rows,
            page_size=200,
        )
    print(f"   Inserted {len(cv_rows)} candidate CVs")


# =============================================================
#   Verify du lieu sau khi insert
# =============================================================

def verify_data(cur):
    print("\n" + "=" * 55)
    print("  VERIFY - Kiem tra data trong PostgreSQL")
    print("=" * 55)

    cur.execute("SELECT COUNT(*) FROM job_descriptions;")
    jd_count = cur.fetchone()[0]

    cur.execute("SELECT COUNT(*) FROM cvs;")
    cv_count = cur.fetchone()[0]

    print(f"\n  Tong job_descriptions : {jd_count}")
    print(f"  Tong cvs              : {cv_count}")

    print("\n  -- Sample JD (3 ban ghi dau) --")
    cur.execute("SELECT id, position, company, keyword, exp_years FROM job_descriptions LIMIT 3;")
    for row in cur.fetchall():
        print(f"   [{row[0]}] {row[1][:40]} | {row[2][:25]} | kw: {row[3][:20]} | exp: {row[4]}")

    print("\n  -- Sample CV (3 ban ghi dau) --")
    cur.execute("SELECT id, position, keyword, exp_years FROM cvs LIMIT 3;")
    for row in cur.fetchall():
        print(f"   [{row[0]}] {row[1][:40]} | kw: {row[2][:20]} | exp: {row[3]}")

    print("\n  -- Demo Full-text search: tim CV co 'Python' --")
    cur.execute(
        """
        SELECT id, position, keyword
        FROM cvs
        WHERE to_tsvector('english', cv_text) @@ to_tsquery('english', 'python')
        LIMIT 5;
        """
    )
    rows = cur.fetchall()
    print(f"  Tim thay {len(rows)} ket qua (top 5)")
    for row in rows:
        print(f"   [{row[0]}] {row[1][:40]} | kw: {row[2][:25]}")

    print("\n  Data da san sang!")


# =============================================================
#   Main
# =============================================================

def main():
    print("=" * 55)
    print("  Recruitment DB - Load Data")
    print(f"  Target: {JD_LIMIT} JDs + {CV_LIMIT} CVs")
    print("=" * 55)

    # Doc config
    db_config = load_db_config("config.properties")

    # Load + clean data truoc khi ket noi DB
    cleaned_jd, cleaned_cv = load_and_clean_datasets()

    # Ket noi PostgreSQL
    print(f"\n  Connecting: {db_config['host']}:{db_config['port']}/{db_config['dbname']}...")
    try:
        conn = psycopg2.connect(**db_config)
        conn.autocommit = False
        cur = conn.cursor()
        print("  Connected thanh cong!")
    except psycopg2.OperationalError as e:
        print(f"\n[ERROR] Khong ket noi duoc PostgreSQL:\n  {e}")
        print("\nKiem tra lai config.properties:")
        print("  host / port / dbname / user / password")
        sys.exit(1)

    # Insert + verify
    try:
        # Kiem tra bang co du lieu chua de tranh insert trung
        cur.execute("SELECT COUNT(*) FROM job_descriptions;")
        existing = cur.fetchone()[0]
        if existing > 0:
            print(f"\n  [SKIP] Bang job_descriptions da co {existing} ban ghi.")
            print("  Xoa data cu truoc neu muon load lai: TRUNCATE job_descriptions, cvs;")
        else:
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
        print("\n  Connection closed.")


if __name__ == "__main__":
    main()
