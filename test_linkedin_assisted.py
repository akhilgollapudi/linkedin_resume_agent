
from linkedin_assisted import make_job_record, get_job_id

sample = {
    "title": "Forward Deployed AI Engineer",
    "company": "Example AI Company",
    "location": "Hyderabad, Telangana, India",
    "url": "https://www.linkedin.com/jobs/view/4489747790/",
    "description": (
        "Build enterprise AI applications, work with customers, "
        "design RAG pipelines, and deploy production AI systems."
    )
}

record = make_job_record(sample)

assert record["job_id"] == "4489747790"
assert record["title"] == "Forward Deployed AI Engineer"
assert record["company"] == "Example AI Company"
assert "RAG pipelines" in record["description"]

print("Sample extraction test passed.")
print(record)
