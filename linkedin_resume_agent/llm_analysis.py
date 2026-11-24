import json
import os
import re
from .matcher import role_description, tokens


def _create_completion_with_json_retry(client, **request):
    for attempt in range(2):
        try:
            if attempt:
                request["temperature"] = 0
            return client.chat.completions.create(**request)
        except Exception as exc:
            body = getattr(exc, "body", None)
            if (
                attempt == 0
                and isinstance(body, dict)
                and body.get("code") == "json_validate_failed"
            ):
                continue
            raise


def _llm_settings():
            provider = (os.getenv("LLM_PROVIDER") or "openrouter").strip().lower()
            if provider == "openrouter":
                return (
                    provider,
                    os.getenv("OPENROUTER_API_KEY"),
                    "https://openrouter.ai/api/v1",
                    os.getenv("OPENROUTER_MODEL", "openrouter/free"),
                )
            if provider == "groq":
                return (
                    provider,
                    os.getenv("GROQ_API_KEY"),
                    "https://api.groq.com/openai/v1",
                    os.getenv("GROQ_MODEL", "openai/gpt-oss-20b"),
                )
            raise ValueError(f"Unsupported LLM_PROVIDER: {provider}")


def _llm_client(api_key, base_url):
            from openai import OpenAI

            return OpenAI(api_key=api_key, base_url=base_url, max_retries=0)


def _reasoning_options(provider, model):
            if provider == "groq" and model in {
                "openai/gpt-oss-20b",
                "openai/gpt-oss-120b",
            }:
                return {"reasoning_effort": "low"}
            return {}


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
    provider, api_key, base_url, model = _llm_settings()
    if not api_key:
        return {
            "summary": evidence_summary,
            "used": False,
            "reason": f"{provider.upper()}_API_KEY not configured; selected role-relevant resume evidence",
        }
    try:
        client = _llm_client(api_key, base_url)
        evidence = [{
            "company": x.get("company", ""), "position": x.get("position", ""),
            "project": x.get("project", ""), "highlights": x.get("highlights", [])
        } for x in resume.get("work", [])]
        skills = {g.get("name", ""): g.get("keywords", []) for g in resume.get("skills", [])}
        prompt = f'''
You are an evidence-bound resume editor tailoring a senior engineering resume
for one specific role. Write only the resume summary, not the full resume.

OUTPUT REQUIREMENTS:
- Return one plain-text paragraph only, with no JSON wrapper.
- Write 60-75 words and no more than 750 characters.
- Use standard, ATS-readable language; no heading, bullets, markdown, or keyword list.
- Prioritize the target role's core responsibilities and required qualifications,
  not generic seniority claims or repeated keywords.
- Translate directly relevant and transferable experience into the job
  description's terminology when the source facts support that connection.
- Preserve the strongest role-relevant skills and keywords already stated in the
  master summary and evidence; do not discard supported context just to rephrase.
- Include relevant skills and experience naturally; do not stuff keywords.

FACTUAL REQUIREMENTS:
- Use only facts explicitly present in the master summary, experience, or skills.
- You may frame an existing achievement using a JD responsibility's terminology
  only when the evidence describes that same work; distinguish transferable
  evidence from direct ownership.
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
        completion_options = {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.1,
            **_reasoning_options(provider, model),
        }
        response = _create_completion_with_json_retry(client, **completion_options)
        choice = response.choices[0]
        content = (choice.message.content or "").strip()
        if not content:
            raise ValueError(
                "LLM provider returned no summary text "
                f"(finish_reason={choice.finish_reason or 'unknown'})"
            )
        try:
            parsed = json.loads(content)
        except json.JSONDecodeError:
            candidate = content
        else:
            candidate = parsed.get("summary", "") if isinstance(parsed, dict) else ""
        candidate = candidate.strip().strip('"')
        if not candidate:
            raise ValueError("LLM returned an empty summary")
        if len(candidate.split()) < 50:
            raise ValueError(
                f"LLM summary is shorter than the 50-word minimum ({len(candidate.split())} words)"
            )
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


def tailor_experience_with_llm(job, resume):
    """Rewrite existing experience bullets for the JD without adding new claims."""
    import copy

    tailored = copy.deepcopy(resume)
    bullets = [
        {
            "source_id": f"w{work_index}b{bullet_index}",
            "work_index": work_index,
            "bullet_index": bullet_index,
            "text": highlight,
        }
        for work_index, work in enumerate(tailored.get("work", []))
        for bullet_index, highlight in enumerate(work.get("highlights", []))
    ]
    provider, api_key, base_url, model = _llm_settings()
    if not api_key:
        return tailored, {
            "used": False,
            "reason": f"{provider.upper()}_API_KEY not configured; retained source bullets",
            "rewritten_bullets": 0,
        }
    if not bullets:
        return tailored, {
            "used": False,
            "reason": "No experience bullets to tailor",
            "rewritten_bullets": 0,
        }

    try:
        client = _llm_client(api_key, base_url)
        evidence = []
        for item in bullets:
            work_item = tailored["work"][item["work_index"]]
            evidence.append({
                "source_id": item["source_id"],
                "role": work_item.get("position", ""),
                "project": work_item.get("project", ""),
                "bullet": item["text"],
            })
        batch_size = 5
        batches = [
            bullets[index:index + batch_size]
            for index in range(0, len(bullets), batch_size)
        ]
        request_count = 0

        def rewrite_batch(batch):
            nonlocal request_count
            batch_ids = {item["source_id"] for item in batch}
            batch_evidence = [
                item for item in evidence if item["source_id"] in batch_ids
            ]
            prompt = f'''
You are an expert resume editor tailoring the supplied experience to the exact
target role and its responsibilities.
Return valid JSON only with exactly one key "bullets", an array of objects
with "source_id" and "text".

Return exactly one item for every supplied source_id in this batch, with no
duplicates. Order these bullets by relevance to the job, preserving each
source_id so the application can keep every bullet under its original
role/project. Rewrite bullets to foreground the specific responsibilities and
qualifications from the JD that the source facts substantiate. Prefer precise
role-specific language over generic wording, and use transferable experience
when it is genuinely supported by the source. Preserve each bullet's factual
meaning, scope, technologies, ownership, dates, and outcomes. Never claim that
the candidate performed a responsibility solely because it appears in the JD.
Do not invent missing details. Preserve numeric claims exactly.

JOB TITLE: {job.get("title", "")}
COMPANY: {job.get("company", "")}
JOB DESCRIPTION:
{job.get("description", "")[:16000]}
SOURCE EXPERIENCE BULLETS:
{json.dumps(batch_evidence, ensure_ascii=False)}
'''
            try:
                request_count += 1
                response = _create_completion_with_json_retry(
                    client,
                    model=model,
                    messages=[{"role": "user", "content": prompt}],
                    response_format={"type": "json_object"},
                    temperature=0.1,
                    **_reasoning_options(provider, model),
                )
            except Exception as exc:
                error_body = getattr(exc, "body", None)
                if (
                    len(batch) > 1
                    and isinstance(error_body, dict)
                    and error_body.get("code") == "json_validate_failed"
                ):
                    midpoint = len(batch) // 2
                    return (
                        rewrite_batch(batch[:midpoint])
                        + rewrite_batch(batch[midpoint:])
                    )
                raise

            choice = response.choices[0]
            content = (choice.message.content or "").strip()
            if not content:
                raise ValueError(
                    "LLM provider returned no experience JSON "
                    f"(finish_reason={choice.finish_reason or 'unknown'})"
                )
            rewritten = json.loads(content).get("bullets")
            if not isinstance(rewritten, list):
                raise ValueError("LLM response does not contain a bullets array")

            source_by_id = {item["source_id"]: item for item in batch}
            batch_seen_ids = set()
            batch_validated = []
            for item in rewritten:
                if not isinstance(item, dict):
                    raise ValueError("LLM returned a malformed bullet entry")
                source_id = item.get("source_id")
                text = item.get("text", "").strip()
                if (
                    source_id not in source_by_id
                    or source_id in batch_seen_ids
                    or not text
                ):
                    raise ValueError("LLM returned an unknown, duplicate, or empty bullet")
                source_numbers = set(re.findall(
                    r"\d+(?:\.\d+)?",
                    source_by_id[source_id]["text"],
                ))
                candidate_numbers = set(re.findall(r"\d+(?:\.\d+)?", text))
                if not candidate_numbers.issubset(source_numbers):
                    raise ValueError(f"LLM introduced an unsupported number in {source_id}")
                batch_seen_ids.add(source_id)
                batch_validated.append((source_by_id[source_id], text))

            if batch_seen_ids != batch_ids:
                raise ValueError("LLM omitted one or more source bullets")
            return batch_validated

        validated = []
        seen_ids = set()
        for batch in batches:
            for source, text in rewrite_batch(batch):
                if source["source_id"] in seen_ids:
                    raise ValueError("LLM returned a duplicate source bullet across batches")
                seen_ids.add(source["source_id"])
                validated.append((source, text))

        ordered_highlights = {
            index: []
            for index in range(len(tailored.get("work", [])))
        }
        for source, text in validated:
            ordered_highlights[source["work_index"]].append(text)
        for index, work_item in enumerate(tailored.get("work", [])):
            work_item["highlights"] = ordered_highlights[index]
        return tailored, {
            "used": True,
            "model": model,
            "reason": "Existing bullets were rewritten and relevance-ordered; no new claims requested",
            "rewritten_bullets": len(validated),
            "batches": request_count,
        }
    except Exception as exc:
        return resume, {
            "used": False,
            "reason": f"LLM fallback ({type(exc).__name__}: {exc}); retained source bullets",
            "rewritten_bullets": 0,
        }


def generate_jd_bullet_proposals(job, resume, max_proposals=2):
    """Generate JD-focused additions under the user's automatic-inclusion authorization."""
    provider, api_key, base_url, model = _llm_settings()
    if not api_key:
        return [], {
            "used": False,
            "reason": f"{provider.upper()}_API_KEY not configured; no JD-only proposals generated",
            "model": None,
        }

    work_context = [
        {
            "role_index": index,
            "company": work.get("company", ""),
            "position": work.get("position", ""),
            "project": work.get("project", ""),
            "existing_bullets": work.get("highlights", []),
        }
        for index, work in enumerate(resume.get("work", []))
    ]
    if not work_context:
        return [], {
            "used": False,
            "reason": "No existing work roles available for proposal context",
            "model": None,
        }

    try:
        client = _llm_client(api_key, base_url)
        prompt = f'''
You are drafting JD-focused resume bullet additions under the user's explicit
standing authorization to include generated responsibilities automatically.

Return valid JSON only with exactly one key "proposals", an array of at most
{max_proposals} objects. Each object must have:
- "role_index": an integer copied from the supplied role context
- "responsibility": a short responsibility from the job description
- "bullet": a concise, role-specific proposed resume bullet

Draft concise, credible bullets that align this candidate with the job's core
role and responsibilities, including responsibilities that are not explicit
in the current bullets. Use the role/project context to attach each generated
bullet to the most plausible existing role. Do not invent employers, titles,
dates, technologies, certifications, metrics, team sizes, or quantified
outcomes. Avoid numeric claims unless the exact number occurs in that role's
supplied bullets. Do not duplicate existing bullets. These generated bullets
will be included automatically based on the user's authorization; label them
as AI-generated in the output report.

JOB TITLE: {job.get("title", "")}
COMPANY: {job.get("company", "")}
JOB DESCRIPTION:
{job.get("description", "")[:16000]}
EXISTING RESUME ROLES AND BULLETS:
{json.dumps(work_context, ensure_ascii=False)[:20000]}
'''
        response = _create_completion_with_json_retry(
            client,
            model=model,
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
            temperature=0.2,
            **_reasoning_options(provider, model),
        )
        choice = response.choices[0]
        content = (choice.message.content or "").strip()
        if not content:
            raise ValueError(
                "LLM provider returned no proposal JSON "
                f"(finish_reason={choice.finish_reason or 'unknown'})"
            )
        proposals = json.loads(content).get("proposals")
        if not isinstance(proposals, list):
            raise ValueError("LLM response does not contain a proposals array")

        validated = []
        seen = set()
        for proposal in proposals[:max_proposals]:
            if not isinstance(proposal, dict):
                continue
            role_index = proposal.get("role_index")
            responsibility = proposal.get("responsibility", "").strip()
            bullet = proposal.get("bullet", "").strip()
            if (
                not isinstance(role_index, int)
                or not 0 <= role_index < len(work_context)
                or not responsibility
                or not bullet
            ):
                continue
            key = (role_index, bullet.casefold())
            if key in seen:
                continue
            existing_text = " ".join(work_context[role_index]["existing_bullets"]).casefold()
            if bullet.casefold() in existing_text:
                continue
            numeric_claims = set(re.findall(r"\d+(?:\.\d+)?", bullet))
            source_numbers = set(re.findall(
                r"\d+(?:\.\d+)?",
                json.dumps(work_context[role_index]["existing_bullets"]),
            ))
            if not numeric_claims.issubset(source_numbers):
                continue
            seen.add(key)
            validated.append({
                "role_index": role_index,
                "responsibility": responsibility,
                "bullet": bullet,
                "status": "ai_generated_user_preapproved",
                "approved": False,
            })

        return validated, {
            "used": True,
            "model": model,
            "reason": "JD-based bullets are proposals and require explicit candidate approval",
        }
    except Exception as exc:
        return [], {
            "used": False,
            "reason": f"Proposal generation failed: {type(exc).__name__}: {exc}",
            "model": model,
        }


def optional_llm_analysis(job, match, resume):
    return None
