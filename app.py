from flask import Flask, render_template, request, redirect, url_for, flash
import sqlite3
from datetime import datetime

app = Flask(__name__)
app.secret_key = "supersecretkey"  # required for flash messages


def get_db_connection():
    conn = sqlite3.connect("database.db")
    conn.row_factory = sqlite3.Row
    return conn


@app.route("/")
def home():
    q = request.args.get("q", "").strip()
    conn = get_db_connection()

    if q:
        jobs = conn.execute(
            """
            SELECT id, title, company, location, posted_date
            FROM jobs
            WHERE title LIKE ? OR company LIKE ? OR location LIKE ?
            ORDER BY id DESC
            """,
            (f"%{q}%", f"%{q}%", f"%{q}%"),
        ).fetchall()
    else:
        jobs = conn.execute(
            """
            SELECT id, title, company, location, posted_date
            FROM jobs
            ORDER BY id DESC
            """
        ).fetchall()

    conn.close()
    return render_template("index.html", jobs=jobs, q=q)


@app.route("/add", methods=["GET", "POST"])
def add_job():
    if request.method == "POST":
        title = request.form.get("title", "").strip()
        company = request.form.get("company", "").strip()
        location = request.form.get("location", "").strip()

        if not title or not company or not location:
            flash("⚠️ Please fill all fields.")
            return redirect(url_for("add_job"))

        posted_date = datetime.now().strftime("%Y-%m-%d")

        conn = get_db_connection()
        conn.execute(
            "INSERT INTO jobs (title, company, location, posted_date) VALUES (?, ?, ?, ?)",
            (title, company, location, posted_date),
        )
        conn.commit()
        conn.close()

        flash("✅ Job added successfully!")
        return redirect(url_for("home"))

    return render_template("add_job.html")


@app.route("/edit/<int:job_id>", methods=["GET", "POST"])
def edit_job(job_id):
    conn = get_db_connection()

    if request.method == "POST":
        title = request.form.get("title", "").strip()
        company = request.form.get("company", "").strip()
        location = request.form.get("location", "").strip()

        if not title or not company or not location:
            flash("⚠️ Please fill all fields.")
            conn.close()
            return redirect(url_for("edit_job", job_id=job_id))

        conn.execute(
            "UPDATE jobs SET title = ?, company = ?, location = ? WHERE id = ?",
            (title, company, location, job_id),
        )
        conn.commit()
        conn.close()

        flash("✏️ Job updated successfully!")
        return redirect(url_for("home"))

    job = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    conn.close()

    if job is None:
        flash("❌ Job not found.")
        return redirect(url_for("home"))

    return render_template("edit_job.html", job=job)


@app.route("/delete/<int:job_id>", methods=["POST"])
def delete_job(job_id):
    conn = get_db_connection()
    conn.execute("DELETE FROM jobs WHERE id = ?", (job_id,))
    conn.commit()
    conn.close()

    flash("🗑️ Job deleted!")
    return redirect(url_for("home"))


@app.route("/ping")
def ping():
    return "OK"


if __name__ == "__main__":
    app.run(debug=True, port=5050)