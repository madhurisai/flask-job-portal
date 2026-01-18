import os
import sqlite3
from flask import Flask, render_template, request, redirect, url_for

import psycopg
from psycopg.rows import dict_row

app = Flask(__name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SQLITE_PATH = os.path.join(BASE_DIR, "database.db")
DATABASE_URL = os.environ.get("DATABASE_URL")


def get_db_connection():
    # Render/Production (Postgres)
    if DATABASE_URL:
        return psycopg.connect(DATABASE_URL, row_factory=dict_row)

    # Local dev (SQLite)
    conn = sqlite3.connect(SQLITE_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db_connection()
    cur = conn.cursor()

    # Create table if it doesn't exist (new installs)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS jobs (
            id SERIAL PRIMARY KEY,
            source TEXT,
            source_job_id TEXT,
            title TEXT NOT NULL,
            company TEXT NOT NULL,
            location TEXT NOT NULL,
            description TEXT,
            apply_url TEXT,
            posted_at TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE (source, source_job_id)
        );
    """)

    # 🔹 Backward compatibility: add missing columns safely
    cur.execute("ALTER TABLE jobs ADD COLUMN IF NOT EXISTS source TEXT;")
    cur.execute("ALTER TABLE jobs ADD COLUMN IF NOT EXISTS source_job_id TEXT;")
    cur.execute("ALTER TABLE jobs ADD COLUMN IF NOT EXISTS description TEXT;")
    cur.execute("ALTER TABLE jobs ADD COLUMN IF NOT EXISTS apply_url TEXT;")
    cur.execute("ALTER TABLE jobs ADD COLUMN IF NOT EXISTS posted_at TIMESTAMP;")
    cur.execute("ALTER TABLE jobs ADD COLUMN IF NOT EXISTS created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP;")

    # 🔹 Ensure unique constraint exists
    cur.execute("""
    DO $$
    BEGIN
        IF NOT EXISTS (
            SELECT 1 FROM pg_constraint
            WHERE conname = 'jobs_source_source_job_id_key'
        ) THEN
            ALTER TABLE jobs
            ADD CONSTRAINT jobs_source_source_job_id_key
            UNIQUE (source, source_job_id);
        END IF;
    END $$;
    """)

    conn.commit()
    cur.close()
    conn.close()



# ✅ Run init_db safely on startup (won't crash without DATABASE_URL)
init_db()


@app.route("/ping")
def ping():
    return "OK"


@app.route("/")
def home():
    conn = get_db_connection()
    cur = conn.cursor()

    if DATABASE_URL:
        cur.execute("""
            SELECT title, company, location, description, apply_url, posted_at, created_at
            FROM jobs
            WHERE created_at::date = CURRENT_DATE
            ORDER BY COALESCE(posted_at, created_at) DESC
            LIMIT 200
        """)
    else:
        cur.execute("""
            SELECT title, company, location, description, apply_url, posted_at, created_at
            FROM jobs
            WHERE created_at::date = CURRENT_DATE
            ORDER BY created_at DESC
            LIMIT 200
        """)

    jobs = cur.fetchall()
    cur.close()
    conn.close()

    return render_template("index.html", jobs=jobs)


@app.route("/add", methods=["GET", "POST"])
def add_job():
    if request.method == "POST":
        title = request.form.get("title", "").strip()
        company = request.form.get("company", "").strip()
        location = request.form.get("location", "").strip()
        description = request.form.get("description", "").strip()
        apply_url = request.form.get("apply_url", "").strip()

        if not title or not company or not location:
            return "Title, Company, and Location are required", 400

        conn = get_db_connection()
        cur = conn.cursor()

        if DATABASE_URL:
            cur.execute(
                """INSERT INTO jobs (source, source_job_id, title, company, location, description, apply_url)
                   VALUES (%s, %s, %s, %s, %s, %s, %s)""",
                ("manual", f"manual-{title}-{company}-{location}", title, company, location, description, apply_url),
            )
        else:
            cur.execute(
                """INSERT INTO jobs (source, source_job_id, title, company, location, description, apply_url)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                ("manual", f"manual-{title}-{company}-{location}", title, company, location, description, apply_url),
            )

        conn.commit()
        cur.close()
        conn.close()

        return redirect(url_for("home"))

    return render_template("add_job.html")


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5050))
    app.run(host="0.0.0.0", port=port, debug=True)
