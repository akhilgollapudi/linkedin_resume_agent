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


def analyze_job_alignment(job, resume):
    """Map JD statements to existing resume evidence using a transparent lexical heuristic."""
    description = role_description(job)
    statements = re.split(r"[\n\r•▪●]+|(?<=[.!?])\s+", description)
    requirements = []
    seen = set()
    for statement in statements:
        text = re.sub(r"^\s*[-*]\s*", "", statement).strip()
        statement_tokens = set(tokens(text))
        normalized = text.lower()
        if len(statement_tokens) < 3 or len(text) < 20 or normalized in seen:
            continue
        seen.add(normalized)
        requirements.append((text, statement_tokens))
        if len(requirements) == 30:
            break

    evidence = []
    for work in resume.get("work", []):
        source = " | ".join(
            value for value in (
                work.get("company", ""),
                work.get("position", ""),
                work.get("project", ""),
            ) if value
        )
        for highlight in work.get("highlights", []):
            evidence.append({
                "source": source,
                "text": highlight,
                "tokens": set(tokens(f"{source} {highlight}")),
            })
    for group in resume.get("skills", []):
        for skill in [group.get("name", ""), *group.get("keywords", [])]:
            skill_tokens = set(tokens(skill))
            if skill_tokens:
                evidence.append({
                    "source": group.get("name", "Skills"),
                    "text": skill,
                    "tokens": skill_tokens,
                })

    mapped = []
    for statement, required_tokens in requirements:
        matches = []
        for item in evidence:
            overlap = required_tokens & item["tokens"]
            if overlap:
                matches.append((
                    len(overlap) / len(required_tokens),
                    len(overlap),
                    item,
                ))
        matches.sort(key=lambda result: (result[0], result[1]), reverse=True)
        best_score, best_overlap, _ = matches[0] if matches else (0, 0, None)
        status = (
            "supported" if best_score >= 0.3 and best_overlap >= 2
            else "partial" if best_score >= 0.15 or best_overlap >= 1
            else "no_direct_match"
        )
        mapped.append({
            "requirement": statement,
            "status": status,
            "evidence": [
                {"source": item["source"], "text": item["text"]}
                for _, _, item in matches[:2]
            ],
        })

    return {
        "method": "Token overlap; use as a review aid, not semantic proof.",
        "requirements_reviewed": len(mapped),
        "supported": sum(item["status"] == "supported" for item in mapped),
        "partial": sum(item["status"] == "partial" for item in mapped),
        "no_direct_match": sum(item["status"] == "no_direct_match" for item in mapped),
        "requirements": mapped,
    }


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
    # Keep the candidate's existing headline; job targeting stays in metadata.
    tailored["targeting"] = {"company": job.get("company", ""), "role": job.get("title", ""),
                             "job_id": job.get("job_id", ""), "match_score": match["score"]}
    return tailored
