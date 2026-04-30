"""
=============================================================
  Semantic Recruitment Matcher - Load Data into PostgreSQL
=============================================================
Requirements:
  - Database and schema already exist
  - Use config.properties or PG_* env vars

Run: python load_data.py
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
    print("[ERROR] Missing psycopg2. Run: pip install psycopg2-binary")
    sys.exit(1)

try:
    from datasets import load_dataset
except ImportError:
    print("[ERROR] Missing datasets. Run: pip install datasets")
    sys.exit(1)


# =============================================================
#   Load config
# =============================================================

def load_db_config(config_file: str = "config.properties") -> dict:
    """Load PostgreSQL config."""
    config_path = os.path.join(os.path.dirname(__file__), config_file)
    default_config = {
        "host": os.getenv("PG_HOST", "localhost"),
        "port": int(os.getenv("PG_PORT", "5432")),
        "dbname": os.getenv("PG_DB", "recruitment_db"),
        "user": os.getenv("PG_USER", "postgres"),
        "password": os.getenv("PG_PASSWORD", ""),
    }

    if not os.path.exists(config_path):
        print(f"[WARN] Config not found: {config_path}")
        print("  Using PG_* env vars or defaults.")
        return default_config

    config = configparser.ConfigParser()
    try:
        config.read(config_path, encoding="utf-8")
    except configparser.MissingSectionHeaderError:
        with open(config_path, "r", encoding="utf-8") as f:
            raw_config = f.read()
        config.read_string("[postgresql]\n" + raw_config)

    if "postgresql" not in config:
        print("[WARN] Missing [postgresql] section.")
        print("  Using PG_* env vars or defaults.")
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
#   Load limits
# =============================================================

JD_LIMIT = 1000
CV_LIMIT = 1000


# =============================================================
#   Clean data
# =============================================================

def clean_text(text) -> str:
    """Normalize text."""
    if not text or not isinstance(text, str):
        return ""
    return re.sub(r"\s+", " ", text).strip()


def clean_scalar(value) -> str:
    """Normalize scalar."""
    if value is None:
        return ""
    return clean_text(str(value))


def truncate(text: str, max_chars: int) -> str:
    """Trim on word boundary."""
    if not text:
        return ""
    if len(text) <= max_chars:
        return text
    cut = text[:max_chars]
    last_space = cut.rfind(" ")
    return cut[:last_space] if last_space > 0 else cut


def sanitize_jd_row(item: dict):
    """Clean one JD row."""
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
    """Clean one CV row."""
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
#   Load datasets
# =============================================================

def load_and_clean_datasets():
    print("\n[1/3] Loading HuggingFace datasets...")

    jd_raw = load_dataset(
        "lang-uk/recruitment-dataset-job-descriptions-english",
        split=f"train[:{JD_LIMIT}]",
    )
    cv_raw = load_dataset(
        "lang-uk/recruitment-dataset-candidate-profiles-english",
        split=f"train[:{CV_LIMIT}]",
    )

    print(f"   Raw JDs : {len(jd_raw)} rows | columns: {jd_raw.column_names}")
    print(f"   Raw CVs : {len(cv_raw)} rows | columns: {cv_raw.column_names}")

    print("\n[2/3] Cleaning data...")

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

    print(f"   JD: kept {len(cleaned_jd)}, skipped {skipped_jd} (empty/short)")
    print(f"   CV: kept {len(cleaned_cv)}, skipped {skipped_cv} (empty/short)")

    return cleaned_jd, cleaned_cv


# =============================================================
#   Insert data
# =============================================================

def insert_data(cur, cleaned_jd: list, cleaned_cv: list):
    print("\n[3/3] Inserting into PostgreSQL...")

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
#   Verify data
# =============================================================

def verify_data(cur):
    print("\n" + "=" * 55)
    print("  VERIFY - PostgreSQL data")
    print("=" * 55)

    cur.execute("SELECT COUNT(*) FROM job_descriptions;")
    jd_count = cur.fetchone()[0]

    cur.execute("SELECT COUNT(*) FROM cvs;")
    cv_count = cur.fetchone()[0]

    print(f"\n  Total job_descriptions : {jd_count}")
    print(f"  Total cvs              : {cv_count}")

    print("\n  -- Sample JD (first 3 rows) --")
    cur.execute("SELECT id, position, company, keyword, exp_years FROM job_descriptions LIMIT 3;")
    for row in cur.fetchall():
        print(f"   [{row[0]}] {row[1][:40]} | {row[2][:25]} | kw: {row[3][:20]} | exp: {row[4]}")

    print("\n  -- Sample CV (first 3 rows) --")
    cur.execute("SELECT id, position, keyword, exp_years FROM cvs LIMIT 3;")
    for row in cur.fetchall():
        print(f"   [{row[0]}] {row[1][:40]} | kw: {row[2][:20]} | exp: {row[3]}")

    print("\n  -- Demo full-text search: CVs with 'Python' --")
    cur.execute(
        """
        SELECT id, position, keyword
        FROM cvs
        WHERE to_tsvector('english', cv_text) @@ to_tsquery('english', 'python')
        LIMIT 5;
        """
    )
    rows = cur.fetchall()
    print(f"  Found {len(rows)} results (top 5)")
    for row in rows:
        print(f"   [{row[0]}] {row[1][:40]} | kw: {row[2][:25]}")

    print("\n  Data is ready.")


# =============================================================
#   Main
# =============================================================

def main():
    print("=" * 55)
    print("  Recruitment DB - Load Data")
    print(f"  Target: {JD_LIMIT} JDs + {CV_LIMIT} CVs")
    print("=" * 55)

    # Load config
    db_config = load_db_config("config.properties")

    # Load and clean before connecting
    cleaned_jd, cleaned_cv = load_and_clean_datasets()

    # Connect to PostgreSQL
    print(f"\n  Connecting: {db_config['host']}:{db_config['port']}/{db_config['dbname']}...")
    try:
        conn = psycopg2.connect(**db_config)
        conn.autocommit = False
        cur = conn.cursor()
        print("  Connected.")
    except psycopg2.OperationalError as e:
        print(f"\n[ERROR] PostgreSQL connection failed:\n  {e}")
        print("\nCheck config.properties:")
        print("  host / port / dbname / user / password")
        sys.exit(1)

    # Insert + verify
    try:
        # Avoid duplicate inserts
        cur.execute("SELECT COUNT(*) FROM job_descriptions;")
        existing = cur.fetchone()[0]
        if existing > 0:
            print(f"\n  [SKIP] job_descriptions already has {existing} rows.")
            print("  To reload: TRUNCATE job_descriptions, cvs;")
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
