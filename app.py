import os
from flask import Flask, render_template, request, redirect, url_for
import psycopg
from psycopg.rows import dict_row

app = Flask(__name__)

DATABASE_URL = os.environ.get("DATABASE_URL")


def get_db_connection():
    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        raise RuntimeError("DATABASE_URL is not set. Add it in Render Environment Variables.")
    # dict_row makes fetchall() return list of dicts (similar to RealDictCursor)
    return psycopg.connect(db_url, row_factory=dict_row)


def init_db():
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS jobs (
            id SERIAL PRIMARY KEY,
            title TEXT NOT NULL,
            company TEXT NOT NULL,
            location TEXT NOT NULL,
            description TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    cur.close()
    conn.close()


# Run table creation once when the app starts
init_db()


@app.route("/ping")
def ping():
    return "OK"


@app.route("/")
def home():
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT id, title, company, location, description, created_at
        FROM jobs
        ORDER BY created_at DESC
    """)
    jobs = cur.fetchall()  # list of dicts (dict_row)
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

        if not title or not company or not location:
            return "Title, Company, and Location are required", 400

        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO jobs (title, company, location, description)
            VALUES (%s, %s, %s, %s)
            """,
            (title, company, location, description)
        )
        conn.commit()
        cur.close()
        conn.close()

        return redirect(url_for("home"))

    return render_template("add_job.html")


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5050))
    app.run(host="0.0.0.0", port=port, debug=True)
