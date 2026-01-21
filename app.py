import os
import sqlite3
import hashlib
from flask import Flask, render_template, request, redirect, url_for

import psycopg
from psycopg.rows import dict_row

app = Flask(__name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SQLITE_PATH = os.path.join(BASE_DIR, "database.db")
DATABASE_URL = os.environ.get("DATABASE_URL")  # Render sets this in production


def is_postgres() -> bool:
    return bool(DATABASE_URL)


def get_db_connection():
    # Production (Render) -> Postgres
    if is_postgres():
        return psycopg.connect(DATABASE_URL, row_factory=dict_row)

    # Local dev -> SQLite
    conn = sqlite3.connect(SQLITE_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def sqlite_column_exists(cur, table: str, col: str) -> bool:
    cur.execute(f"PRAGMA table_info({table})")
    rows = cur.fetchall()
    return any(r["name"] == col for r in rows)


def init_db():
    conn = get_db_connection()
    cur = conn.cursor()

    if is_postgres():
        # ---- Postgres schema ----
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS jobs (
                id BIGSERIAL PRIMARY KEY,
                source TEXT,
                source_job_id TEXT,
                title TEXT NOT NULL,
                company TEXT NOT NULL,
                location TEXT NOT NULL,
                description TEXT,
                apply_url TEXT,
                posted_at TIMESTAMPTZ,
                fetched_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                UNIQUE (source, source_job_id)
            );
            """
        )

        # Backward compatibility (safe in Postgres)
        cur.execute("ALTER TABLE jobs ADD COLUMN IF NOT EXISTS description TEXT;")
        cur.execute("ALTER TABLE jobs ADD COLUMN IF NOT EXISTS apply_url TEXT;")
        cur.execute("ALTER TABLE jobs ADD COLUMN IF NOT EXISTS posted_at TIMESTAMPTZ;")
        cur.execute("ALTER TABLE jobs ADD COLUMN IF NOT EXISTS fetched_at TIMESTAMPTZ NOT NULL DEFAULT NOW();")
        cur.execute("ALTER TABLE jobs ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ NOT NULL DEFAULT NOW();")

        # Helpful indexes
        cur.execute("CREATE INDEX IF NOT EXISTS idx_jobs_created_at ON jobs (created_at DESC);")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_jobs_posted_at ON jobs (posted_at DESC);")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_jobs_fetched_at ON jobs (fetched_at DESC);")

    else:
        # ---- SQLite schema ----
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS jobs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source TEXT,
                source_job_id TEXT,
                title TEXT NOT NULL,
                company TEXT NOT NULL,
                location TEXT NOT NULL,
                description TEXT,
                apply_url TEXT,
                posted_at TEXT,
                fetched_at TEXT DEFAULT (datetime('now')),
                created_at TEXT DEFAULT (datetime('now')),
                UNIQUE (source, source_job_id)
            );
            """
        )

        # Backward compatibility (SQLite-safe)
        if not sqlite_column_exists(cur, "jobs", "source"):
            cur.execute("ALTER TABLE jobs ADD COLUMN source TEXT;")
        if not sqlite_column_exists(cur, "jobs", "source_job_id"):
            cur.execute("ALTER TABLE jobs ADD COLUMN source_job_id TEXT;")
        if not sqlite_column_exists(cur, "jobs", "description"):
            cur.execute("ALTER TABLE jobs ADD COLUMN description TEXT;")
        if not sqlite_column_exists(cur, "jobs", "apply_url"):
            cur.execute("ALTER TABLE jobs ADD COLUMN apply_url TEXT;")
        if not sqlite_column_exists(cur, "jobs", "posted_at"):
            cur.execute("ALTER TABLE jobs ADD COLUMN posted_at TEXT;")
        if not sqlite_column_exists(cur, "jobs", "fetched_at"):
            cur.execute("ALTER TABLE jobs ADD COLUMN fetched_at TEXT;")
        if not sqlite_column_exists(cur, "jobs", "created_at"):
            cur.execute("ALTER TABLE jobs ADD COLUMN created_at TEXT;")

        # Helpful indexes (SQLite)
        cur.execute("CREATE INDEX IF NOT EXISTS idx_jobs_created_at ON jobs (created_at);")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_jobs_posted_at ON jobs (posted_at);")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_jobs_fetched_at ON jobs (fetched_at);")

    conn.commit()
    cur.close()
    conn.close()


# Run init_db on startup
init_db()


@app.route("/ping")
def ping():
    return "OK"


# Home page: show only "today's" jobs (B option)
@app.route("/")
def home():
    conn = get_db_connection()
    cur = conn.cursor()

    if is_postgres():
        cur.execute(
            """
            SELECT title, company, location, description, apply_url, posted_at, fetched_at, created_at
            FROM jobs
            WHERE created_at::date = CURRENT_DATE
            ORDER BY COALESCE(posted_at, fetched_at, created_at) DESC
            LIMIT 200;
            """
        )
    else:
        cur.execute(
            """
            SELECT title, company, location, description, apply_url, posted_at, fetched_at, created_at
            FROM jobs
            WHERE date(created_at) = date('now')
            ORDER BY COALESCE(posted_at, fetched_at, created_at) DESC
            LIMIT 200;
            """
        )

    jobs = cur.fetchall()
    cur.close()
    conn.close()
    return render_template("index.html", jobs=jobs)


# Search page: search across all jobs (keyword + location + last N days)
@app.route("/search")
def search():
    q = (request.args.get("q") or "").strip()
    location = (request.args.get("location") or "").strip()
    company = (request.args.get("company") or "").strip()
    source = (request.args.get("source") or "").strip()
    days = request.args.get("days") or "30"

    try:
        days = max(1, min(int(days), 365))
    except ValueError:
        days = 30

    like_q = f"%{q}%"
    like_loc = f"%{location}%"
    like_company = f"%{company}%"
    like_source = f"%{source}%"

    conn = get_db_connection()
    cur = conn.cursor()

    # Build dropdown options (distinct values)
    if is_postgres():
        cur.execute("SELECT DISTINCT source FROM jobs WHERE source IS NOT NULL ORDER BY source;")
    else:
        cur.execute("SELECT DISTINCT source FROM jobs WHERE source IS NOT NULL ORDER BY source;")
    sources = [r[0] if not is_postgres() else r["source"] for r in cur.fetchall()]

    if is_postgres():
        cur.execute("SELECT DISTINCT company FROM jobs WHERE company IS NOT NULL ORDER BY company;")
    else:
        cur.execute("SELECT DISTINCT company FROM jobs WHERE company IS NOT NULL ORDER BY company;")
    companies = [r[0] if not is_postgres() else r["company"] for r in cur.fetchall()]

    # Main search query
    if is_postgres():
        sql = """
        SELECT title, company, location, description, apply_url, posted_at, fetched_at, created_at, source
        FROM jobs
        WHERE
          (
            posted_at >= NOW() - (%s || ' days')::interval
            OR (posted_at IS NULL AND fetched_at >= NOW() - (%s || ' days')::interval)
          )
          AND (%s = '' OR (title ILIKE %s OR company ILIKE %s OR location ILIKE %s))
          AND (%s = '' OR location ILIKE %s)
          AND (%s = '' OR company ILIKE %s)
          AND (%s = '' OR source ILIKE %s)
        ORDER BY posted_at DESC NULLS LAST, fetched_at DESC, created_at DESC
        LIMIT 500;
        """
        cur.execute(
            sql,
            (
                days, days,
                q, like_q, like_q, like_q,
                location, like_loc,
                company, like_company,
                source, like_source,
            ),
        )
    else:
        since = f"-{days} days"
        sql = """
        SELECT title, company, location, description, apply_url, posted_at, fetched_at, created_at, source
        FROM jobs
        WHERE
          (
            (posted_at IS NOT NULL AND posted_at >= datetime('now', ?))
            OR (posted_at IS NULL AND fetched_at >= datetime('now', ?))
          )
          AND (? = '' OR (title LIKE ? OR company LIKE ? OR location LIKE ?))
          AND (? = '' OR location LIKE ?)
          AND (? = '' OR company LIKE ?)
          AND (? = '' OR source LIKE ?)
        ORDER BY COALESCE(posted_at, fetched_at, created_at) DESC
        LIMIT 500;
        """
        cur.execute(
            sql,
            (
                since, since,
                q, like_q, like_q, like_q,
                location, like_loc,
                company, like_company,
                source, like_source,
            ),
        )

    jobs = cur.fetchall()
    cur.close()
    conn.close()

    return render_template(
        "search.html",
        jobs=jobs,
        q=q,
        location=location,
        company=company,
        source=source,
        days=days,
        sources=sources,
        companies=companies,
    )



@app.route("/add", methods=["GET", "POST"])
def add_job():
    if request.method == "POST":
        title = (request.form.get("title") or "").strip()
        company = (request.form.get("company") or "").strip()
        location = (request.form.get("location") or "").strip()
        description = (request.form.get("description") or "").strip()
        apply_url = (request.form.get("apply_url") or "").strip()

        if not title or not company or not location:
            return "Title, Company, and Location are required", 400

        # Stable manual id to avoid duplicates
        raw = f"{title}|{company}|{location}|{apply_url}"
        manual_id = "manual-" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:20]

        conn = get_db_connection()
        cur = conn.cursor()

        if is_postgres():
            cur.execute(
                """
                INSERT INTO jobs (source, source_job_id, title, company, location, description, apply_url, fetched_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, NOW())
                ON CONFLICT (source, source_job_id)
                DO UPDATE SET
                  title = EXCLUDED.title,
                  company = EXCLUDED.company,
                  location = EXCLUDED.location,
                  description = EXCLUDED.description,
                  apply_url = EXCLUDED.apply_url,
                  fetched_at = NOW();
                """,
                ("manual", manual_id, title, company, location, description or None, apply_url or None),
            )
        else:
            cur.execute(
                """
                INSERT INTO jobs (source, source_job_id, title, company, location, description, apply_url, fetched_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now'))
                ON CONFLICT(source, source_job_id)
                DO UPDATE SET
                  title=excluded.title,
                  company=excluded.company,
                  location=excluded.location,
                  description=excluded.description,
                  apply_url=excluded.apply_url,
                  fetched_at=datetime('now');
                """,
                ("manual", manual_id, title, company, location, description or None, apply_url or None),
            )

        conn.commit()
        cur.close()
        conn.close()

        return redirect(url_for("home"))

    return render_template("add_job.html")


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5050))
    # debug=True locally; Render ignores __main__ and runs gunicorn
    app.run(host="0.0.0.0", port=port, debug=True)
