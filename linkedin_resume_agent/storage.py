import sqlite3
from pathlib import Path


class JobStore:
    def __init__(self, path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path)
        self.db.execute("""CREATE TABLE IF NOT EXISTS jobs (
            job_id TEXT PRIMARY KEY, title TEXT, company TEXT, url TEXT,
            status TEXT NOT NULL, match_score INTEGER, output_dir TEXT, processed_at TEXT DEFAULT CURRENT_TIMESTAMP
        )""")
        self.db.commit()

    def is_processed(self, job_id):
        row = self.db.execute("SELECT status FROM jobs WHERE job_id=?", (job_id,)).fetchone()
        return bool(row and row[0] == "processed")

    def save(self, job, status, score=None, output_dir=None):
        self.db.execute("""INSERT INTO jobs(job_id,title,company,url,status,match_score,output_dir)
            VALUES(?,?,?,?,?,?,?) ON CONFLICT(job_id) DO UPDATE SET title=excluded.title,
            company=excluded.company,url=excluded.url,status=excluded.status,
            match_score=excluded.match_score,output_dir=excluded.output_dir,processed_at=CURRENT_TIMESTAMP""",
            (job["job_id"], job.get("title"), job.get("company"), job.get("url"), status, score, output_dir))
        self.db.commit()

    def list(self):
        return self.db.execute("SELECT job_id,title,company,status,match_score,output_dir FROM jobs ORDER BY processed_at DESC").fetchall()
