import os
import re
from datetime import datetime, timezone

import requests
import psycopg
from psycopg.rows import dict_row
from bs4 import BeautifulSoup

# ----------------------------
# Config
# ----------------------------
DATABASE_URL = os.environ.get("DATABASE_URL")

# ✅ Remove doordash (404 on greenhouse)
GREENHOUSE_COMPANIES = ["stripe", "airbnb", "databricks", "coinbase"]
LEVER_COMPANIES = []  # add slugs anytime

HEADERS = {
    "User-Agent": "job-portal-bot/1.0 (Render; +https://render.com)"
}


# ----------------------------
# DB helpers
# ----------------------------
def db_conn():
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL not set")
    return psycopg.connect(DATABASE_URL, row_factory=dict_row)


# ✅ Better UPSERT:
# - writes fetched_at every run
# - does NOT overwrite posted_at with NULL
UPSERT_SQL = """
INSERT INTO jobs (source, source_job_id, title, company, location, description, apply_url, posted_at, fetched_at)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s, NOW())
ON CONFLICT (source, source_job_id)
DO UPDATE SET
  title = EXCLUDED.title,
  company = EXCLUDED.company,
  location = EXCLUDED.location,
  description = EXCLUDED.description,
  apply_url = EXCLUDED.apply_url,
  posted_at = COALESCE(EXCLUDED.posted_at, jobs.posted_at),
  fetched_at = NOW();
"""


# ----------------------------
# Text cleaning
# ----------------------------
def safe_text(x, limit=4000):
    if not x:
        return None
    return str(x)[:limit]


def clean_html(html: str, limit=4000) -> str | None:
    """
    Convert HTML -> clean readable text
    Removes greenhouse editor junk like ace-line gutter-author classes.
    """
    if not html:
        return None

    soup = BeautifulSoup(html, "html.parser")

    # Remove script/style/noscript
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()

    # Remove empty/gutter-ish divs (optional extra cleanup)
    for div in soup.find_all("div"):
        cls = " ".join(div.get("class", []))
        if "ace-line" in cls or "gutter" in cls:
            div.decompose()

    text = soup.get_text(separator="\n")

    # Normalize whitespace
    text = re.sub(r"\r\n", "\n", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = text.strip()

    if not text:
        return None
    return text[:limit]


# ----------------------------
# Date parsing
# ----------------------------
def parse_iso_datetime(value):
    """
    Greenhouse often returns ISO timestamps like '2025-01-21T12:34:56Z'
    """
    if not value:
        return None
    try:
        s = str(value).strip()
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


# ----------------------------
# Source fetchers
# ----------------------------
def fetch_lever(company_slug):
    url = f"https://api.lever.co/v0/postings/{company_slug}?mode=json"
    r = requests.get(url, headers=HEADERS, timeout=30)
    r.raise_for_status()
    data = r.json()

    jobs = []
    for item in data:
        job_id = item.get("id") or item.get("hostedUrl") or item.get("applyUrl")
        if not job_id:
            continue

        location = (item.get("categories") or {}).get("location") or "N/A"
        title = item.get("text") or "Untitled"
        apply_url = item.get("hostedUrl") or item.get("applyUrl")

        posted_at = None
        created_ms = item.get("createdAt")
        if isinstance(created_ms, (int, float)):
            posted_at = datetime.fromtimestamp(created_ms / 1000, tz=timezone.utc)

        desc_raw = item.get("descriptionPlain") or item.get("description")
        description = clean_html(desc_raw) if (desc_raw and "<" in str(desc_raw)) else safe_text(desc_raw)

        jobs.append({
            "source": "lever",
            "source_job_id": str(job_id),
            "title": title,
            "company": company_slug,
            "location": location,
            "description": description,
            "apply_url": apply_url,
            "posted_at": posted_at,
        })
    return jobs


def fetch_greenhouse(company_token):
    url = f"https://boards-api.greenhouse.io/v1/boards/{company_token}/jobs?content=true"
    r = requests.get(url, headers=HEADERS, timeout=30)
    r.raise_for_status()
    data = r.json()

    jobs = []
    for item in data.get("jobs", []):
        job_id = item.get("id")
        if job_id is None:
            continue

        title = item.get("title") or "Untitled"
        location = (item.get("location") or {}).get("name") or "N/A"
        apply_url = item.get("absolute_url")

        content = item.get("content")
        description_html = None
        if isinstance(content, dict):
            description_html = content.get("description")
        else:
            description_html = content

        # ✅ Clean HTML -> readable text
        description = clean_html(description_html)

        # ✅ Use updated_at or created_at if available
        posted_at = parse_iso_datetime(item.get("updated_at")) or parse_iso_datetime(item.get("created_at"))

        jobs.append({
            "source": "greenhouse",
            "source_job_id": str(job_id),
            "title": title,
            "company": company_token,
            "location": location,
            "description": description,
            "apply_url": apply_url,
            "posted_at": posted_at,
        })
    return jobs


# ----------------------------
# Upsert
# ----------------------------
def upsert_jobs(all_jobs):
    if not all_jobs:
        return 0

    with db_conn() as conn:
        with conn.cursor() as cur:
            for j in all_jobs:
                cur.execute(
                    UPSERT_SQL,
                    (
                        j["source"],
                        j["source_job_id"],
                        j["title"],
                        j["company"],
                        j["location"],
                        j.get("description"),
                        j.get("apply_url"),
                        j.get("posted_at"),
                    ),
                )
    return len(all_jobs)


# ----------------------------
# Main
# ----------------------------
def main():
    all_jobs = []

    for c in LEVER_COMPANIES:
        try:
            all_jobs += fetch_lever(c)
            print(f"Lever {c}: OK")
        except Exception as e:
            print(f"Lever {c}: FAILED: {e}")

    for c in GREENHOUSE_COMPANIES:
        try:
            all_jobs += fetch_greenhouse(c)
            print(f"Greenhouse {c}: OK")
        except Exception as e:
            print(f"Greenhouse {c}: FAILED: {e}")

    count = upsert_jobs(all_jobs)
    print(f"Upserted {count} jobs")


if __name__ == "__main__":
    main()
