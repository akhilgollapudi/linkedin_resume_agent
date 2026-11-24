
from linkedin_assisted import make_job_record
from linkedin_resume_agent.pdf_generator import markup
from unittest.mock import patch
import builtins
import json
from types import SimpleNamespace
import linkedin_assisted
from main import include_preapproved_jd_bullet_proposals
from linkedin_resume_agent.llm_analysis import generate_jd_bullet_proposals

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

assert "cross-functional multi-agent end-to-end" in markup(
    "cross‑functional multi‑agent end‑to‑end"
)
print("PDF glyph regression test passed; Unicode hyphens are normalized to supported glyphs.")

selected_ids = []


class ListenerPage:
    def expose_binding(self, name, callback):
        assert name == "notifyLinkedInJobClick"
        self.callback = callback

    def add_init_script(self, script):
        self.script = script

    def evaluate(self, script):
        assert script == self.script
        assert "document.addEventListener('click'" in script
        assert "notifyLinkedInJobClick(jobId)" in script
        assert "data-occludable-job-id" in script


listener_page = ListenerPage()
linkedin_assisted.install_job_click_listener(listener_page, selected_ids)
listener_page.callback({}, "4448867536")
assert selected_ids == ["4448867536"]


class UrlSelectionPage:
    url = "https://www.linkedin.com/jobs/search-results/?currentJobId=4492680169"


url_selected_ids = []
previous_id = linkedin_assisted.detect_url_job_selection(
    UrlSelectionPage(),
    "4487699672",
    url_selected_ids,
)
assert previous_id == "4492680169"
assert url_selected_ids == ["4492680169"]
print("URL selection fallback test passed; currentJobId changes enqueue the newly selected job.")

opened_url_selected_ids = []
opened_job_id = linkedin_assisted.enqueue_requested_job_url(
    UrlSelectionPage.url,
    opened_url_selected_ids,
)
assert opened_job_id == "4492680169"
assert opened_url_selected_ids == ["4492680169"]
print("Opened URL test passed; the job in the initial currentJobId is queued automatically.")

jobs_landing_selected_ids = []
landed_job_id = linkedin_assisted.enqueue_requested_job_url(
    "https://www.linkedin.com/jobs/",
    jobs_landing_selected_ids,
)
assert landed_job_id == ""
assert jobs_landing_selected_ids == []
print("Generic jobs URL test passed; a redirected/remembered job is not queued before user selection.")


queued_jobs = ["301", "302"]
already_processed = set()
captured_ids = []
with patch.object(
    linkedin_assisted,
    "capture_current_job",
    side_effect=lambda _page, _jobs, on_job_captured, expected_job_id: (
        captured_ids.append(expected_job_id) or {"job_id": expected_job_id}
    ),
):
    linkedin_assisted.process_queued_job_selections(
        object(),
        {},
        queued_jobs,
        already_processed,
    )
assert captured_ids == ["301", "302"]
assert already_processed == {"301", "302"}
assert queued_jobs == []
print("Sequential selection test passed; the watcher processes the next job after the previous one finishes.")


class FakePage:
    def wait_for_timeout(self, _milliseconds):
        pass

details = iter([
    {
        "job_id": "101",
        "title": "First Engineer",
        "company": "First Co",
        "location": "Remote",
        "description": "Stale details from the previously selected job. " * 8,
    },
    {
        "job_id": "202",
        "title": "Second Engineer",
        "company": "Second Co",
        "location": "Remote",
        "description": "Details for the explicitly selected second job. " * 8,
    },
    {
        "job_id": "202",
        "title": "Second Engineer",
        "company": "Second Co",
        "location": "Remote",
        "description": "Details for the explicitly selected second job. " * 8,
    },
    {
        "job_id": "202",
        "title": "Second Engineer",
        "company": "Second Co",
        "location": "Remote",
        "description": "Details for the explicitly selected second job. " * 8,
    },
])
processed = []
with patch.object(linkedin_assisted, "is_linkedin_challenge", return_value=False):
    with patch.object(linkedin_assisted, "extract_current_job", side_effect=lambda _page: next(details)):
        with patch.object(linkedin_assisted, "add_or_update_job", return_value=True):
            with patch.object(linkedin_assisted, "save_jobs"):
                with patch.object(builtins, "input", side_effect=AssertionError("unexpected prompt")):
                    result = linkedin_assisted.capture_current_job(
                        FakePage(),
                        {},
                        on_job_captured=lambda job: processed.append(job["job_id"]),
                        expected_job_id="202",
                    )

assert result["job_id"] == "202"
assert processed == ["202"]
print("Selected-job regression test passed; clicked job IDs trigger automatic processing after details stabilize.")

from linkedin_resume_agent.matcher import analyze_job_alignment, tailor_resume
from linkedin_resume_agent.llm_analysis import (
    _llm_settings,
    tailor_experience_with_llm,
    tailor_summary_with_llm,
)
with patch.dict(
    "os.environ",
    {"OPENROUTER_API_KEY": "test-key"},
    clear=True,
):
    assert _llm_settings() == (
        "openrouter",
        "test-key",
        "https://openrouter.ai/api/v1",
        "openrouter/free",
    )
with patch.dict(
    "os.environ",
    {
        "LLM_PROVIDER": "groq",
        "GROQ_API_KEY": "test-key",
        "GROQ_MODEL": "openai/gpt-oss-20b",
    },
    clear=True,
):
    assert _llm_settings() == (
        "groq",
        "test-key",
        "https://api.groq.com/openai/v1",
        "openai/gpt-oss-20b",
    )
print("LLM provider selection test passed; OpenRouter free routing is default and Groq remains opt-in.")
resume = {"basics": {"label": "Existing headline"}, "work": [], "skills": []}
targeted = tailor_resume(
    resume,
    {"job_id": "202", "title": "Second Engineer", "company": "Second Co", "description": ""},
    {"score": 0},
)
assert targeted["basics"]["label"] == "Existing headline"
assert targeted["targeting"]["role"] == "Second Engineer"
print("Tailoring regression test passed; resume headline stays unchanged while role remains in metadata.")

alignment = analyze_job_alignment(
    {
        "description": (
            "Lead distributed platform architecture and cloud delivery. "
            "Manage a global sales quota and own quarterly bookings."
        )
    },
    {
        "work": [{
            "company": "Example",
            "position": "Principal Engineer",
            "project": "Distributed Platform",
            "highlights": [
                "Designed distributed platform architecture and delivered cloud services."
            ],
        }],
        "skills": [{"name": "Cloud", "keywords": ["AWS"]}],
    },
)
assert alignment["requirements_reviewed"] == 2, alignment
assert alignment["requirements"][0]["status"] == "supported", alignment
assert alignment["requirements"][1]["status"] == "no_direct_match", alignment
assert alignment["requirements"][1]["evidence"] == [], alignment
print("JD alignment test passed; existing evidence is mapped and unsupported requirements remain gaps.")

experience_resume = {
    "work": [{
        "position": "Principal Engineer",
        "project": "Platform",
        "highlights": [
            "Designed distributed cloud services for the platform.",
            "Reduced deployment time by 30%.",
        ],
    }]
}
with patch.dict("os.environ", {}, clear=False):
    with patch("linkedin_resume_agent.llm_analysis.os.getenv", return_value=""):
        tailored_experience, experience_meta = tailor_experience_with_llm(
            {"title": "Principal Platform Engineer", "description": "Lead platform engineering."},
            experience_resume,
        )
assert tailored_experience == experience_resume
assert experience_meta["used"] is False
print("No-key experience fallback test passed; source facts remain unchanged without manual prompts.")


class FakeCompletion:
    def __init__(self):
        self.choices = [SimpleNamespace(
            message=SimpleNamespace(content=json.dumps({"bullets": [
                {"source_id": "w0b1", "text": "Reduced deployment time by 30%."},
                {"source_id": "w0b0", "text": "Designed distributed cloud services for the platform."},
            ]}))
        )]


class FakeOpenAI:
    client_options = None
    request_options = None

    def __init__(self, **kwargs):
        type(self).client_options = kwargs
        self.chat = SimpleNamespace(
            completions=SimpleNamespace(create=self.create_completion)
        )

    def create_completion(self, **params):
        type(self).request_options = params
        return FakeCompletion()


FakeOpenAI.client_options = None
FakeOpenAI.request_options = None
with patch.dict("os.environ", {"LLM_PROVIDER": "groq", "GROQ_API_KEY": "test-key"}, clear=False):
    with patch("openai.OpenAI", FakeOpenAI):
        rewritten, rewrite_meta = tailor_experience_with_llm(
            {"title": "Principal Platform Engineer", "description": "Lead platform engineering."},
            experience_resume,
        )
assert rewritten["work"][0]["highlights"] == [
    "Reduced deployment time by 30%.",
    "Designed distributed cloud services for the platform.",
]
assert rewrite_meta["used"] is True
assert FakeOpenAI.client_options["max_retries"] == 0
assert FakeOpenAI.request_options["reasoning_effort"] == "low"
assert experience_resume["work"][0]["highlights"][0].startswith("Designed")
print("LLM experience test passed; existing bullets can be automatically rephrased/reordered without mutating master data.")


class MultiBatchOpenAI:
    call_count = 0

    def __init__(self, **_kwargs):
        self.chat = SimpleNamespace(
            completions=SimpleNamespace(create=self.create_completion)
        )

    def create_completion(self, **params):
        type(self).call_count += 1
        prompt = params["messages"][0]["content"]
        batch = json.loads(prompt.rsplit("SOURCE EXPERIENCE BULLETS:\n", 1)[1])
        content = json.dumps({
            "bullets": [
                {"source_id": item["source_id"], "text": item["bullet"]}
                for item in batch
            ]
        })
        return SimpleNamespace(choices=[SimpleNamespace(
            message=SimpleNamespace(content=content)
        )])


multi_batch_resume = {
    "work": [{
        "position": "Principal Engineer",
        "project": "Platform",
        "highlights": [f"Implemented platform capability {index}." for index in range(12)],
    }]
}
MultiBatchOpenAI.call_count = 0
with patch.dict("os.environ", {"LLM_PROVIDER": "groq", "GROQ_API_KEY": "test-key"}, clear=False):
    with patch("openai.OpenAI", MultiBatchOpenAI):
        batched_resume, batch_meta = tailor_experience_with_llm(
            {"title": "Principal Platform Engineer", "description": "Build platforms."},
            multi_batch_resume,
        )
assert MultiBatchOpenAI.call_count == 3
assert batched_resume["work"][0]["highlights"] == multi_batch_resume["work"][0]["highlights"]
assert batch_meta["used"] is True
assert batch_meta["rewritten_bullets"] == 12
assert batch_meta["batches"] == 3
print("LLM experience batching test passed; all bullets are validated across bounded requests.")


class JsonValidationBatchError(Exception):
    body = {"code": "json_validate_failed"}


class RetrySummaryOpenAI:
    call_count = 0

    def __init__(self, **_kwargs):
        self.chat = SimpleNamespace(
            completions=SimpleNamespace(create=self.create_completion)
        )

    def create_completion(self, **_params):
        type(self).call_count += 1
        if type(self).call_count == 1:
            raise JsonValidationBatchError("Groq rejected generated JSON")
        return SimpleNamespace(choices=[SimpleNamespace(
            message=SimpleNamespace(content=json.dumps({
                "summary": (
                    "Experienced engineer delivering distributed cloud software systems "
                    "for customers and teams, with expertise in architecture, application "
                    "development, platform engineering, reliability, data workflows, and "
                    "technical collaboration across product and engineering groups. "
                    "Focused on building practical solutions, clarifying requirements, "
                    "improving quality, and supporting dependable delivery from design "
                    "through implementation in complex organizational environments."
                )
            }))
        )])


RetrySummaryOpenAI.call_count = 0
with patch.dict("os.environ", {"LLM_PROVIDER": "groq", "GROQ_API_KEY": "test-key"}, clear=False):
    with patch("openai.OpenAI", RetrySummaryOpenAI):
        summary_result = tailor_summary_with_llm(
            {"title": "Principal Engineer", "description": "Build cloud systems."},
            {"basics": {"summary": "Software engineer."}, "work": [], "skills": []},
        )
assert RetrySummaryOpenAI.call_count == 2
assert summary_result["used"] is True
print("LLM JSON retry test passed; transient Groq JSON validation errors are retried once.")


class ShortSummaryOpenAI:
    def __init__(self, **_kwargs):
        self.chat = SimpleNamespace(
            completions=SimpleNamespace(create=lambda **_params: SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(
                    content="Architected and delivered a production-grade, multi-agent"
                ))]
            ))
        )


source_summary = (
    "Experienced engineer delivering distributed cloud software systems for "
    "customers and teams through architecture, platform development, and "
    "reliable production services."
)
with patch.dict("os.environ", {"LLM_PROVIDER": "groq", "GROQ_API_KEY": "test-key"}, clear=False):
    with patch("openai.OpenAI", ShortSummaryOpenAI):
        short_summary_result = tailor_summary_with_llm(
            {"title": "Principal Engineer", "description": "Build multi-agent systems."},
            {"basics": {"summary": source_summary}, "work": [], "skills": []},
        )
assert short_summary_result["used"] is False
assert short_summary_result["summary"] == source_summary
assert "shorter than the 50-word minimum" in short_summary_result["reason"]
print("Short-summary regression test passed; incomplete LLM summaries fall back to source evidence.")


class EmptySummaryOpenAI:
    request_options = None

    def __init__(self, **_kwargs):
        self.chat = SimpleNamespace(
            completions=SimpleNamespace(create=self.create_completion)
        )

    def create_completion(self, **params):
        type(self).request_options = params
        return SimpleNamespace(choices=[SimpleNamespace(
            message=SimpleNamespace(content=None),
            finish_reason="stop",
        )])


EmptySummaryOpenAI.request_options = None
with patch.dict("os.environ", {"LLM_PROVIDER": "groq", "GROQ_API_KEY": "test-key"}, clear=False):
    with patch("openai.OpenAI", EmptySummaryOpenAI):
        empty_summary_result = tailor_summary_with_llm(
            {"title": "Principal Engineer", "description": "Build cloud systems."},
            {"basics": {"summary": source_summary}, "work": [], "skills": []},
        )
assert empty_summary_result["used"] is False
assert empty_summary_result["summary"] == source_summary
assert "finish_reason=stop" in empty_summary_result["reason"]
assert EmptySummaryOpenAI.request_options["reasoning_effort"] == "low"
print("Empty-summary regression test passed; GPT-OSS uses low reasoning and preserves evidence fallback.")


class AdaptiveBatchOpenAI(MultiBatchOpenAI):
    def create_completion(self, **params):
        type(self).call_count += 1
        prompt = params["messages"][0]["content"]
        batch = json.loads(prompt.rsplit("SOURCE EXPERIENCE BULLETS:\n", 1)[1])
        if type(self).call_count <= 2 and len(batch) > 1:
            raise JsonValidationBatchError("Groq rejected generated JSON")
        content = json.dumps({
            "bullets": [
                {"source_id": item["source_id"], "text": item["bullet"]}
                for item in batch
            ]
        })
        return SimpleNamespace(choices=[SimpleNamespace(
            message=SimpleNamespace(content=content)
        )])


AdaptiveBatchOpenAI.call_count = 0
with patch.dict("os.environ", {"LLM_PROVIDER": "groq", "GROQ_API_KEY": "test-key"}, clear=False):
    with patch("openai.OpenAI", AdaptiveBatchOpenAI):
        retried_resume, retried_meta = tailor_experience_with_llm(
            {"title": "Principal Platform Engineer", "description": "Build platforms."},
            multi_batch_resume,
        )
assert AdaptiveBatchOpenAI.call_count == 6
assert retried_resume["work"][0]["highlights"] == multi_batch_resume["work"][0]["highlights"]
assert retried_meta["used"] is True
assert retried_meta["rewritten_bullets"] == 12
assert retried_meta["batches"] == 5
print("LLM JSON-validation retry test passed; rejected batches are subdivided and retried.")


class ProposalCompletion:
    def __init__(self):
        self.choices = [SimpleNamespace(message=SimpleNamespace(content=json.dumps({
            "proposals": [
                {
                    "role_index": 0,
                    "responsibility": "Drive operational readiness.",
                    "bullet": "Coordinated operational readiness for platform services.",
                },
                {
                    "role_index": 99,
                    "responsibility": "Invalid role index.",
                    "bullet": "Built imaginary systems.",
                },
            ]
        })))]


class ProposalOpenAI:
    def __init__(self, **_kwargs):
        self.chat = SimpleNamespace(
            completions=SimpleNamespace(
                create=lambda **_params: ProposalCompletion()
            )
        )


with patch.dict("os.environ", {"LLM_PROVIDER": "groq", "GROQ_API_KEY": "test-key"}, clear=False):
    with patch("openai.OpenAI", ProposalOpenAI):
        proposals, proposal_meta = generate_jd_bullet_proposals(
            {
                "title": "Principal Platform Engineer",
                "description": "Drive operational readiness for cloud platforms.",
            },
            experience_resume,
        )
assert len(proposals) == 1
assert proposals[0]["status"] == "ai_generated_user_preapproved"
assert proposals[0]["approved"] is False
assert proposal_meta["used"] is True
approved = include_preapproved_jd_bullet_proposals(proposals)
assert approved == proposals
assert proposals[0]["approved"] is True
assert proposals[0]["approval_basis"] == "User authorized automatic inclusion"
print("JD proposal test passed; validated Groq proposals are included automatically under user authorization.")
