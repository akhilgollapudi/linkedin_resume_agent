import re
from collections import Counter
from .utils import plain_text

STOP = set("the and for with from that this will your you our are was were have has had into about their they them its role team work working ability strong excellent experience years required preferred including across using use build built design develop deliver responsible responsibilities qualifications skills knowledge a an to of in on as is be or by at we it".split())


def tokens(text):
    words = re.findall(r"[a-zA-Z][a-zA-Z0-9+#./-]{1,}", plain_text(text).lower())
    return [w for w in words if w not in STOP and len(w) > 2]


def resume_corpus(resume):
    chunks = [resume.get("basics", {}).get("summary", "")]
    for w in resume.get("work", []):
        chunks.extend([w.get("position", ""), w.get("project", ""), " ".join(w.get("highlights", [])), w.get("technologies", "")])
    for s in resume.get("skills", []):
        chunks.extend([s.get("name", ""), " ".join(s.get("keywords", []))])
    return " ".join(chunks)


def score_job(resume, job):
    jd = job.get("description", "")
    jd_tokens = Counter(tokens(jd))
    corpus_tokens = set(tokens(resume_corpus(resume)))
    if not jd_tokens:
        return {"score": 0, "matched_terms": [], "missing_terms": [], "reason": "No job description text supplied."}
    ranked = [t for t, _ in jd_tokens.most_common(80)]
    matched = [t for t in ranked if t in corpus_tokens]
    missing = [t for t in ranked if t not in corpus_tokens]
    # Weighted by term frequency, capped to keep the metric interpretable.
    total = sum(jd_tokens[t] for t in ranked)
    hit = sum(jd_tokens[t] for t in matched)
    score = round(100 * hit / max(total, 1))
    return {"score": score, "matched_terms": matched[:35], "missing_terms": missing[:25],
            "reason": "Heuristic JD vocabulary overlap; not an ATS score or hiring probability."}


def role_description(job):
    description = job.get("description", "")
    for marker in ("Applicants:", "To all Staffing and Recruiting Agencies:",
                   "Qualcomm expects its employees"):
        description = description.split(marker, 1)[0]
    return description


def tailor_resume(resume, job, match):
    """Create a per-job copy by ranking existing evidence; never invent or rewrite claims."""
    import copy
    tailored = copy.deepcopy(resume)
    jd_tokens = set(tokens(role_description(job)))

    def relevance(item):
        text = " ".join([item.get("position", ""), item.get("project", ""),
                         " ".join(item.get("highlights", [])), item.get("technologies", "")])
        return len(set(tokens(text)) & jd_tokens)

    tailored["work"] = sorted(tailored.get("work", []), key=relevance, reverse=True)
    for project in tailored["work"]:
        project["highlights"] = [
            highlight for _, highlight in sorted(
                enumerate(project.get("highlights", [])),
                key=lambda indexed: (
                    len(set(tokens(indexed[1])) & jd_tokens),
                    -indexed[0],
                ),
                reverse=True,
            )
        ]
    for group in tailored.get("skills", []):
        kws = group.get("keywords", [])
        group["keywords"] = sorted(kws, key=lambda x: len(set(tokens(x)) & jd_tokens), reverse=True)
    tailored["skills"] = sorted(tailored.get("skills", []),
                                key=lambda g: sum(len(set(tokens(k)) & jd_tokens) for k in g.get("keywords", [])),
                                reverse=True)
    if job.get("title"):
        tailored.setdefault("basics", {})["label"] = f'Target role: {job["title"]}'
    # Retain exact factual wording; add a target label only to metadata, not as an experience claim.
    tailored["targeting"] = {"company": job.get("company", ""), "role": job.get("title", ""),
                             "job_id": job.get("job_id", ""), "match_score": match["score"]}
    return tailored
