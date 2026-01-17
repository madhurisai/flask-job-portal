from flask import Flask, render_template, request, redirect, url_for
import os
import sqlite3

app = Flask(__name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "database.db")
DATABASE_URL = os.environ.get("DATABASE_URL")


def get_db_connection():
    if DATABASE_URL:
        import psycopg2
        return psycopg2.connect(DATABASE_URL)
    else:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        return conn


def init_db():
    conn = get_db_connection()
    cur = conn.cursor()

    if DATABASE_URL:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS jobs (
                id SERIAL PRIMARY KEY,
                title TEXT NOT NULL,
                company TEXT NOT NULL,
                location TEXT NOT NULL
            );
        """)
    else:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS jobs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                company TEXT NOT NULL,
                location TEXT NOT NULL
            );
        """)

    conn.commit()
    conn.close()


@app.route("/")
def home():
    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("SELECT id, title, company, location FROM jobs ORDER BY id DESC;")
    rows = cur.fetchall()

    # Make rows work for both Postgres (tuples) and SQLite (Row objects)
    if DATABASE_URL:
        jobs = [{"id": r[0], "title": r[1], "company": r[2], "location": r[3]} for r in rows]
    else:
        jobs = rows

    conn.close()
    return render_template("index.html", jobs=jobs)


@app.route("/add", methods=["GET", "POST"])
def add_job():
    if request.method == "POST":
        title = request.form.get("title")
        company = request.form.get("company")
        location = request.form.get("location")

        conn = get_db_connection()
        cur = conn.cursor()

        if DATABASE_URL:
            cur.execute(
                "INSERT INTO jobs (title, company, location) VALUES (%s, %s, %s);",
                (title, company, location)
            )
        else:
            cur.execute(
                "INSERT INTO jobs (title, company, location) VALUES (?, ?, ?);",
                (title, company, location)
            )

        conn.commit()
        conn.close()
        return redirect(url_for("home"))

    return render_template("add_job.html")


# Initialize DB once on startup
init_db()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5050))
    app.run(host="0.0.0.0", port=port, debug=True)
