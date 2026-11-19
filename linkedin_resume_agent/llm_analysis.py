import json
import os
import re


def tailor_summary_with_llm(job, resume):
    original = resume.get("basics", {}).get("summary", "")
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        return {"summary": original, "used": False, "reason": "OPENAI_API_KEY not configured"}
    try:
        from openai import OpenAI
        client = OpenAI(api_key=api_key)
        model = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")
        evidence = [{
            "company": x.get("company", ""), "position": x.get("position", ""),
            "project": x.get("project", ""), "highlights": x.get("highlights", [])
        } for x in resume.get("work", [])]
        skills = {g.get("name", ""): g.get("keywords", []) for g in resume.get("skills", [])}
        prompt = f'''
You are tailoring a senior engineering resume summary to one job.
Return JSON only: {{ "summary": "..." }}.
Write 65-95 words, concise, senior-level, ATS-readable.
Use ONLY facts explicitly present in the supplied resume evidence.
Do not invent employers, job titles, years, team sizes, metrics, technologies,
certifications, responsibilities, or outcomes. Do not imply the candidate has
experience with a JD technology unless the resume explicitly supports it.
Prioritize the strongest overlap with this role. Keep claims defensible.
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
        if not candidate or len(candidate.split()) > 110 or len(candidate) > 1000:
            raise ValueError("LLM summary failed length validation")
        source_numbers = set(re.findall(r"\d+(?:\.\d+)?", json.dumps(evidence) + " " + original))
        candidate_numbers = set(re.findall(r"\d+(?:\.\d+)?", candidate))
        if not candidate_numbers.issubset(source_numbers):
            raise ValueError("LLM summary introduced a numeric claim not present in the resume")
        return {"summary": candidate, "used": True, "model": model,
                "reason": "LLM-generated summary; factual review required"}
    except Exception as exc:
        return {"summary": original, "used": False,
                "reason": f"LLM fallback: {type(exc).__name__}: {exc}"}


def optional_llm_analysis(job, match, resume):
    return None
