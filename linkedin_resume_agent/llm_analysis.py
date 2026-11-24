import json
import os
import re
from .matcher import role_description, tokens


def _evidence_selected_summary(job, resume):
    role_terms = set(tokens(role_description(job)))
    candidates = []
    for work_index, work in enumerate(resume.get("work", [])):
        for highlight_index, highlight in enumerate(work.get("highlights", [])):
            overlap = len(set(tokens(highlight)) & role_terms)
            if overlap:
                candidates.append((overlap, work_index, highlight_index, highlight))

    candidates.sort(key=lambda item: (-item[0], item[1], item[2]))
    selected = []
    word_count = 0
    for _, _, _, highlight in candidates:
        words = len(highlight.split())
        candidate = " ".join([*selected, highlight])
        if words + word_count > 85 or len(candidate) > 750:
            continue
        selected.append(highlight)
        word_count += words
        if len(selected) == 2:
            break
    return " ".join(selected) if selected else resume.get("basics", {}).get("summary", "")


def tailor_summary_with_llm(job, resume):
    original = resume.get("basics", {}).get("summary", "")
    evidence_summary = _evidence_selected_summary(job, resume)
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        return {
            "summary": evidence_summary,
            "used": False,
            "reason": "GROQ_API_KEY not configured; selected role-relevant resume evidence",
        }
    try:
        from openai import OpenAI
        client = OpenAI(api_key=api_key, base_url="https://api.groq.com/openai/v1")
        model = os.getenv("GROQ_MODEL", "openai/gpt-oss-20b")
        evidence = [{
            "company": x.get("company", ""), "position": x.get("position", ""),
            "project": x.get("project", ""), "highlights": x.get("highlights", [])
        } for x in resume.get("work", [])]
        skills = {g.get("name", ""): g.get("keywords", []) for g in resume.get("skills", [])}
        prompt = f'''
You are an evidence-bound resume editor tailoring a senior engineering resume
for one specific role. Write only the resume summary, not the full resume.

OUTPUT REQUIREMENTS:
- Return valid JSON only, with exactly one key: "summary".
- Write one plain-text paragraph of 60-75 words and no more than 750 characters.
- Use standard, ATS-readable language; no heading, bullets, markdown, or keyword list.
- Prioritize the role's most important requirements and use the job description's
  exact terminology when the supplied resume evidence supports it.
- Preserve the strongest role-relevant skills and keywords already stated in the
  master summary and evidence; do not discard supported context just to rephrase.
- Include relevant skills and experience naturally; do not stuff keywords.

FACTUAL REQUIREMENTS:
- Use only facts explicitly present in the master summary, experience, or skills.
- Never infer or claim a technology, responsibility, seniority, achievement,
  employer, title, certification, date, duration, team size, or outcome.
- Exclude job requirements that the resume evidence does not support. Do not
  imply that a keyword in the job description is a candidate qualification.
- Keep all numeric claims exactly supported by the resume evidence.

JOB TITLE: {job.get("title", "")}
COMPANY: {job.get("company", "")}
JOB DESCRIPTION:
{job.get("description", "")[:16000]}
MASTER SUMMARY:
{original}
RESUME EXPERIENCE EVIDENCE:
{json.dumps(evidence, ensure_ascii=False)[:18000]}
SKILLS:
{json.dumps(skills, ensure_ascii=False)[:6000]}
'''
        response = client.chat.completions.create(
            model=model, messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"}, temperature=0.1
        )
        candidate = json.loads(response.choices[0].message.content).get("summary", "").strip()
        if not candidate:
            raise ValueError("LLM returned an empty summary")
        if len(candidate.split()) > 85:
            raise ValueError(f"LLM summary exceeds the 85-word safety limit ({len(candidate.split())} words)")
        if len(candidate) > 750:
            raise ValueError(f"LLM summary exceeds the 750-character limit ({len(candidate)} characters)")
        source_numbers = set(re.findall(r"\d+(?:\.\d+)?", json.dumps(evidence) + " " + original))
        candidate_numbers = set(re.findall(r"\d+(?:\.\d+)?", candidate))
        if not candidate_numbers.issubset(source_numbers):
            raise ValueError("LLM summary introduced a numeric claim not present in the resume")
        return {"summary": candidate, "used": True, "model": model,
                "reason": "LLM-generated summary; factual review required"}
    except Exception as exc:
        return {
            "summary": evidence_summary,
            "used": False,
            "reason": (
                f"LLM fallback: {type(exc).__name__}: {exc}; "
                "selected role-relevant resume evidence"
            ),
        }


def optional_llm_analysis(job, match, resume):
    return None
