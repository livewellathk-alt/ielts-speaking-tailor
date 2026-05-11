from __future__ import annotations

import json
import mimetypes
import re
import threading
import time
import uuid
import webbrowser
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import yaml

from .bank import import_bank, load_question_bank
from .coverage import analyze_coverage
from .generation import GenerationConfig, GenerationPipeline, TimingConfig, word_targets_for
from .openai_client import OpenAICompatibleClient
from .profile_builder import build_generation_profile
from .questionnaire import build_questionnaire_model
from .rendering import render_outputs
from .strategy import cluster_part2_blocks


ASSET_DIR = Path(__file__).with_name("web_assets")
GENERATION_JOBS: dict[str, dict[str, Any]] = {}
GENERATION_JOBS_LOCK = threading.Lock()


def run_web_server(*, config_path: str | Path, host: str = "127.0.0.1", port: int = 8765, open_browser: bool = True) -> None:
    config = Path(config_path).resolve()
    handler = _handler_for(config)
    server = ThreadingHTTPServer((host, port), handler)
    url = f"http://{host}:{port}/"
    print(f"IELTS Speaking Tailor web interface: {url}")
    print("Press Ctrl+C to stop the server.")
    if open_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping web interface.")
    finally:
        server.server_close()


def load_web_state(config_path: str | Path) -> dict[str, Any]:
    config_path = Path(config_path).resolve()
    root, config, paths = _load_config(config_path)
    generation = config["generation"]
    timing = _timing_from_config(generation.get("timing", {}))
    output_dir = root / paths["output_dir"]
    bank_path = root / paths["question_bank"]
    profile_path = root / paths["student_profile"]
    result_path = output_dir / "ielts_speaking_answers.md"
    sample_result_path = output_dir / "ielts_speaking_sample.md"
    responses_path = output_dir / "profile_responses.yaml"
    bank = load_question_bank(bank_path) if bank_path.exists() else {"part1_topics": [], "part2_blocks": []}
    profile = yaml.safe_load(profile_path.read_text(encoding="utf-8")) if profile_path.exists() else {}
    responses = yaml.safe_load(responses_path.read_text(encoding="utf-8")) if responses_path.exists() else {}
    questionnaire = build_questionnaire_model(bank)
    coverage = analyze_coverage(bank, responses or {})
    active_result_path = result_path if result_path.exists() else sample_result_path
    result_source = "full" if result_path.exists() else "sample" if sample_result_path.exists() else ""
    return {
        "config": config,
        "settings": _settings_from_config(config),
        "paths": {
            "root": str(root),
            "config": str(config_path),
            "question_bank": str(bank_path),
            "student_profile": str(profile_path),
            "output_dir": str(output_dir),
            "profile_responses": str(responses_path),
            "result_markdown": str(result_path),
            "sample_markdown": str(sample_result_path),
        },
        "files": {
            "question_bank_exists": bank_path.exists(),
            "student_profile_exists": profile_path.exists(),
            "profile_responses_exists": responses_path.exists(),
            "result_markdown_exists": result_path.exists(),
            "sample_markdown_exists": sample_result_path.exists(),
        },
        "profile": profile or {},
        "responses": responses or {},
        "questionnaire": questionnaire,
        "poll_progress": _poll_progress(questionnaire, responses or {}),
        "coverage": coverage,
        "word_targets": word_targets_for(int(generation.get("speaking_speed_wpm", 80)), timing),
        "result_markdown": active_result_path.read_text(encoding="utf-8") if active_result_path.exists() else "",
        "result_markdown_source": result_source,
    }


def save_profile_responses(config_path: str | Path, responses: dict[str, Any]) -> Path:
    root, _config, paths = _load_config(config_path)
    output_dir = root / paths["output_dir"]
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / "profile_responses.yaml"
    path.write_text(yaml.safe_dump(responses, sort_keys=False, allow_unicode=True), encoding="utf-8")
    return path


def save_result_markdown(config_path: str | Path, markdown: str) -> Path:
    root, _config, paths = _load_config(config_path)
    output_dir = root / paths["output_dir"]
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / "ielts_speaking_answers.md"
    path.write_text(markdown, encoding="utf-8")
    return path


def save_settings(config_path: str | Path, settings: dict[str, Any]) -> Path:
    config_path = Path(config_path).resolve()
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    generation = config.setdefault("generation", {})
    timing = generation.setdefault("timing", {})
    llm = config.setdefault("llm", {})
    _set_int(generation, "target_band", settings)
    _set_int(generation, "speaking_speed_wpm", settings)
    _set_int(timing, "part1_seconds", settings)
    _set_int(timing, "part2_min_seconds", settings)
    _set_int(timing, "part2_max_seconds", settings)
    _set_int(timing, "part3_seconds", settings)
    for key in ["base_url", "api_key_env", "model", "reviewer_model"]:
        if key in settings:
            llm[key] = settings[key] or None
    config_path.write_text(yaml.safe_dump(config, sort_keys=False, allow_unicode=True), encoding="utf-8")
    return config_path


def import_uploaded_question_bank(config_path: str | Path, *, filename: str, content: bytes, region: str = "mainland") -> dict[str, str]:
    if not filename:
        raise ValueError("question bank filename is required")
    safe_name = _safe_upload_name(filename)
    if Path(safe_name).suffix.lower() not in {".pdf", ".txt", ".md"}:
        raise ValueError("question bank must be a PDF, TXT, or Markdown file")
    root, _config, paths = _load_config(config_path)
    upload_dir = root / paths["output_dir"] / "uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)
    uploaded_path = upload_dir / safe_name
    uploaded_path.write_bytes(content)
    question_bank_path = root / paths["question_bank"]
    import_bank(uploaded_path, region=region, output_path=question_bank_path)
    return {"uploaded_path": str(uploaded_path), "question_bank_path": str(question_bank_path)}


def _poll_progress(questionnaire: dict[str, Any], responses: dict[str, Any]) -> dict[str, Any]:
    stories = questionnaire.get("umbrella_stories", [])
    story_responses = responses.get("umbrella_stories", {})
    items = []
    for story in stories:
        key = story.get("scope_id") or story.get("theme", "")
        answer = story_responses.get(key, {})
        answered = _story_response_complete(answer)
        items.append(
            {
                "key": key,
                "label": story.get("scope_label") or key.replace("_", "/"),
                "answered": answered,
            }
        )
    total = len(items)
    answered_count = len([item for item in items if item["answered"]])
    percent = 100 if total == 0 else round(answered_count / total * 100)
    return {"total": total, "answered": answered_count, "percent": percent, "items": items}


def _story_response_complete(answer: dict[str, Any]) -> bool:
    return (
        isinstance(answer, dict)
        and _has_text(answer.get("story"), min_chars=20)
        and _detail_count(answer.get("details")) >= 3
        and _has_text(answer.get("lesson"), min_chars=10)
    )


def _has_text(value: Any, min_chars: int = 3) -> bool:
    return isinstance(value, str) and len(value.strip()) >= min_chars


def _detail_count(value: Any) -> int:
    if isinstance(value, list):
        return len([item for item in value if str(item).strip()])
    if not isinstance(value, str):
        return 0
    normalized = value
    for separator in ["，", "、", ";", "；", "\n"]:
        normalized = normalized.replace(separator, ",")
    return len([item for item in normalized.split(",") if item.strip()])


def generate_answers(config_path: str | Path, progress_callback: Any | None = None) -> dict[str, Any]:
    root, config, paths = _load_config(config_path)
    bank = load_question_bank(root / paths["question_bank"])
    responses_path = root / paths["output_dir"] / "profile_responses.yaml"
    responses = yaml.safe_load(responses_path.read_text(encoding="utf-8")) if responses_path.exists() else {}
    coverage = analyze_coverage(bank, responses or {})
    if not coverage["can_generate_full"]:
        raise RuntimeError(_coverage_error_message(coverage, mode="full"))
    return _run_generation(
        config_path,
        bank=bank,
        profile=_merged_profile(root, paths, responses),
        basename="ielts_speaking_answers",
        progress_callback=progress_callback,
    )


def generate_sample_answers(config_path: str | Path, progress_callback: Any | None = None) -> dict[str, Any]:
    root, _config, paths = _load_config(config_path)
    bank = load_question_bank(root / paths["question_bank"])
    responses_path = root / paths["output_dir"] / "profile_responses.yaml"
    responses = yaml.safe_load(responses_path.read_text(encoding="utf-8")) if responses_path.exists() else {}
    coverage = analyze_coverage(bank, responses or {})
    if not coverage["can_generate_sample"]:
        raise RuntimeError(_coverage_error_message(coverage, mode="sample"))
    sample_bank = _sample_bank(bank)
    return _run_generation(
        config_path,
        bank=sample_bank,
        profile=_merged_profile(root, paths, responses),
        basename="ielts_speaking_sample",
        progress_callback=progress_callback,
    )


def start_generation_job(config_path: str | Path, *, mode: str) -> dict[str, Any]:
    if mode not in {"sample", "full"}:
        raise ValueError("mode must be 'sample' or 'full'")
    job_id = uuid.uuid4().hex
    job = {
        "job_id": job_id,
        "mode": mode,
        "status": "running",
        "percent": 1,
        "events": [],
        "result": None,
        "error": None,
        "state": None,
        "created_at": time.time(),
        "updated_at": time.time(),
    }
    with GENERATION_JOBS_LOCK:
        GENERATION_JOBS[job_id] = job
    thread = threading.Thread(target=_run_generation_job, args=(job_id, Path(config_path), mode), daemon=True)
    thread.start()
    return get_generation_job(job_id)


def get_generation_job(job_id: str) -> dict[str, Any]:
    with GENERATION_JOBS_LOCK:
        job = GENERATION_JOBS.get(job_id)
        if not job:
            raise KeyError(f"unknown generation job: {job_id}")
        return json.loads(json.dumps(job))


def _run_generation_job(job_id: str, config_path: Path, mode: str) -> None:
    def progress(event: dict[str, Any]) -> None:
        _append_job_event(job_id, event)

    try:
        if mode == "sample":
            result = generate_sample_answers(config_path, progress_callback=progress)
        else:
            result = generate_answers(config_path, progress_callback=progress)
        _complete_generation_job(job_id, status="completed", result=result, state=load_web_state(config_path))
    except Exception as exc:
        _complete_generation_job(job_id, status="failed", error=str(exc), state=load_web_state(config_path))


def _append_job_event(job_id: str, event: dict[str, Any]) -> None:
    item = {
        "stage": event.get("stage", ""),
        "message": event.get("message", ""),
        "details": event.get("details", {}),
        "timestamp": time.time(),
    }
    with GENERATION_JOBS_LOCK:
        job = GENERATION_JOBS[job_id]
        job["events"].append(item)
        job["percent"] = max(int(job.get("percent", 1)), _progress_percent(job["events"]))
        job["updated_at"] = item["timestamp"]


def _complete_generation_job(
    job_id: str,
    *,
    status: str,
    result: dict[str, Any] | None = None,
    error: str | None = None,
    state: dict[str, Any] | None = None,
) -> None:
    with GENERATION_JOBS_LOCK:
        job = GENERATION_JOBS[job_id]
        job["status"] = status
        job["percent"] = 100
        job["result"] = result
        job["error"] = error
        job["state"] = state
        job["updated_at"] = time.time()


def _run_generation(
    config_path: str | Path,
    *,
    bank: dict[str, Any],
    profile: dict[str, Any],
    basename: str,
    progress_callback: Any | None = None,
) -> dict[str, Any]:
    root, config, paths = _load_config(config_path)
    generation = config["generation"]
    llm = config["llm"]
    client = OpenAICompatibleClient(
        base_url=llm["base_url"],
        api_key_env=llm["api_key_env"],
        model=llm["model"],
    )
    reviewer_client = None
    if llm.get("reviewer_model"):
        reviewer_client = OpenAICompatibleClient(
            base_url=llm["base_url"],
            api_key_env=llm["api_key_env"],
            model=llm["reviewer_model"],
        )
    pipeline_config = GenerationConfig(
        target_band=int(generation["target_band"]),
        answer_length=str(generation["answer_length"]),
        speaking_speed_wpm=int(generation.get("speaking_speed_wpm", 80)),
        timing=_timing_from_config(generation.get("timing", {})),
        checkpoint_mode=bool(generation.get("checkpoint_mode", True)),
        answer_batch_size=int(generation.get("answer_batch_size", 8)),
        max_revision_items=int(generation.get("max_revision_items", 20)),
        output_dir=root / paths["output_dir"],
    )
    result = GenerationPipeline(
        client=client,
        reviewer_client=reviewer_client,
        config=pipeline_config,
        progress_callback=progress_callback,
    ).run(bank=bank, profile=profile)
    rendered = render_outputs(result, output_dir=root / paths["output_dir"], basename=basename)
    rendered_paths = {key: str(path) for key, path in rendered.items()}
    if progress_callback:
        progress_callback({"stage": "render_output", "message": "Rendered Markdown and DOCX output.", "details": rendered_paths})
    return {"result": result, "rendered": rendered_paths}


def _coverage_error_message(coverage: dict[str, Any], *, mode: str) -> str:
    if mode == "full":
        prefix = "资料不足，暂时不建议全量生成。"
    else:
        prefix = "资料不足，无法生成测试样本。"
    followups = coverage.get("followups", [])[:5]
    if followups:
        return f"{prefix}请先补充：{'；'.join(followups)}"
    theme_details = [
        f"{report.get('label', report.get('theme', '主题'))} {report.get('status', '')} {report.get('score', 0)}%"
        for report in coverage.get("theme_reports", [])
        if report.get("status") != "资料充足"
    ]
    if theme_details:
        return f"{prefix}请检查这些主题：{'；'.join(theme_details)}"
    return f"{prefix}请补充 Part 1 直接回答、Part 2 真实故事和 Part 3 观点例子。"


def _load_config(config_path: str | Path) -> tuple[Path, dict[str, Any], dict[str, str]]:
    config_path = Path(config_path).resolve()
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    return config_path.parent, config, config["paths"]


def _safe_upload_name(filename: str) -> str:
    name = Path(filename).name
    safe = re.sub(r"[^A-Za-z0-9._ -]+", "_", name).strip(" .")
    return safe or "question-bank.pdf"


def _progress_percent(events: list[dict[str, Any]]) -> int:
    stage_weights = {
        "scope_analysis": 10,
        "style_guide": 20,
        "checkpoint_samples": 35,
        "answer_batch": 60,
        "quality_review": 78,
        "revision": 88,
        "render_output": 96,
    }
    percent = 1
    for event in events:
        percent = max(percent, stage_weights.get(str(event.get("stage", "")), percent))
    return percent


def _timing_from_config(timing: dict[str, Any]) -> TimingConfig:
    return TimingConfig(
        part1_seconds=int(timing.get("part1_seconds", 15)),
        part2_min_seconds=int(timing.get("part2_min_seconds", 100)),
        part2_max_seconds=int(timing.get("part2_max_seconds", 110)),
        part3_seconds=int(timing.get("part3_seconds", 40)),
    )


def _settings_from_config(config: dict[str, Any]) -> dict[str, Any]:
    generation = config.get("generation", {})
    timing = generation.get("timing", {})
    llm = config.get("llm", {})
    return {
        "target_band": int(generation.get("target_band", 7)),
        "speaking_speed_wpm": int(generation.get("speaking_speed_wpm", 80)),
        "part1_seconds": int(timing.get("part1_seconds", 15)),
        "part2_min_seconds": int(timing.get("part2_min_seconds", 100)),
        "part2_max_seconds": int(timing.get("part2_max_seconds", 110)),
        "part3_seconds": int(timing.get("part3_seconds", 40)),
        "base_url": llm.get("base_url", ""),
        "api_key_env": llm.get("api_key_env", ""),
        "model": llm.get("model", ""),
        "reviewer_model": llm.get("reviewer_model") or "",
    }


def _set_int(target: dict[str, Any], key: str, source: dict[str, Any]) -> None:
    if key in source:
        target[key] = int(source[key])


def _merged_profile(root: Path, paths: dict[str, str], responses: dict[str, Any]) -> dict[str, Any]:
    profile_path = root / paths["student_profile"]
    base_profile = yaml.safe_load(profile_path.read_text(encoding="utf-8")) if profile_path.exists() else {}
    return build_generation_profile(base_profile or {}, responses or {})


def _sample_bank(bank: dict[str, Any]) -> dict[str, Any]:
    sample = dict(bank)
    sample["part1_topics"] = []
    remaining = 3
    for topic in bank.get("part1_topics", []):
        if remaining <= 0:
            break
        questions = topic.get("questions", [])[:remaining]
        if questions:
            sampled_topic = dict(topic)
            sampled_topic["questions"] = questions
            sample["part1_topics"].append(sampled_topic)
            remaining -= len(questions)
    sample["part2_blocks"] = []
    seen_themes = set()
    for block in cluster_part2_blocks(bank.get("part2_blocks", [])):
        theme = block.get("scope_id") or block.get("theme") or ""
        if theme in seen_themes:
            continue
        sampled = dict(block)
        sampled["part3"] = block.get("part3", [])[:2]
        sample["part2_blocks"].append(sampled)
        seen_themes.add(theme)
        if len(sample["part2_blocks"]) >= 2:
            break
    if not sample["part2_blocks"]:
        sample["part2_blocks"] = bank.get("part2_blocks", [])[:2]
    return sample


def _handler_for(config_path: Path) -> type[SimpleHTTPRequestHandler]:
    class IELTSWebHandler(SimpleHTTPRequestHandler):
        server_version = "IELTSTailorWeb/0.1"

        def log_message(self, format: str, *args: Any) -> None:
            return

        def do_GET(self) -> None:
            route = urlparse(self.path).path
            if route == "/api/state":
                self._send_json(load_web_state(config_path))
                return
            if route.startswith("/api/generation-jobs/"):
                job_id = route.removeprefix("/api/generation-jobs/")
                try:
                    self._send_json(get_generation_job(job_id))
                except KeyError as exc:
                    self._send_json({"ok": False, "error": str(exc)}, status=HTTPStatus.NOT_FOUND)
                return
            if route == "/":
                self._send_asset(ASSET_DIR / "index.html")
                return
            if route.startswith("/assets/"):
                self._send_asset(ASSET_DIR / route.removeprefix("/assets/"))
                return
            self.send_error(HTTPStatus.NOT_FOUND)

        def do_POST(self) -> None:
            route = urlparse(self.path).path
            try:
                if route == "/api/question-bank":
                    form = self._read_multipart()
                    file_item = form.get("file")
                    if not isinstance(file_item, dict):
                        raise ValueError("question bank file is required")
                    imported = import_uploaded_question_bank(
                        config_path,
                        filename=str(file_item.get("filename", "")),
                        content=bytes(file_item.get("content", b"")),
                        region=str(form.get("region") or "mainland"),
                    )
                    self._send_json({"ok": True, **imported, "state": load_web_state(config_path)})
                    return
                payload = self._read_json()
                if route == "/api/profile-responses":
                    path = save_profile_responses(config_path, payload.get("responses", {}))
                    self._send_json({"ok": True, "path": str(path), "state": load_web_state(config_path)})
                    return
                if route == "/api/result-markdown":
                    path = save_result_markdown(config_path, str(payload.get("markdown", "")))
                    self._send_json({"ok": True, "path": str(path), "state": load_web_state(config_path)})
                    return
                if route == "/api/settings":
                    path = save_settings(config_path, payload.get("settings", {}))
                    self._send_json({"ok": True, "path": str(path), "state": load_web_state(config_path)})
                    return
                if route == "/api/generate-sample":
                    generated = generate_sample_answers(config_path)
                    self._send_json({"ok": True, **generated, "state": load_web_state(config_path)})
                    return
                if route == "/api/generate":
                    generated = generate_answers(config_path)
                    self._send_json({"ok": True, **generated, "state": load_web_state(config_path)})
                    return
                if route == "/api/generation-jobs":
                    job = start_generation_job(config_path, mode=str(payload.get("mode", "sample")))
                    self._send_json({"ok": True, **job})
                    return
                self.send_error(HTTPStatus.NOT_FOUND)
            except Exception as exc:
                self._send_json({"ok": False, "error": str(exc)}, status=HTTPStatus.INTERNAL_SERVER_ERROR)

        def _read_json(self) -> dict[str, Any]:
            length = int(self.headers.get("Content-Length", "0"))
            if length == 0:
                return {}
            return json.loads(self.rfile.read(length).decode("utf-8"))

        def _read_multipart(self) -> dict[str, Any]:
            content_type = self.headers.get("Content-Type", "")
            boundary_match = re.search(r"boundary=(?P<boundary>[^;]+)", content_type)
            if not boundary_match:
                raise ValueError("multipart boundary is missing")
            boundary = boundary_match.group("boundary").strip('"').encode("utf-8")
            length = int(self.headers.get("Content-Length", "0"))
            body = self.rfile.read(length)
            form: dict[str, Any] = {}
            for part in body.split(b"--" + boundary):
                part = part.strip()
                if not part or part == b"--":
                    continue
                headers_blob, _, content = part.partition(b"\r\n\r\n")
                if content.endswith(b"\r\n"):
                    content = content[:-2]
                headers = headers_blob.decode("utf-8", errors="replace")
                disposition = next((line for line in headers.split("\r\n") if line.lower().startswith("content-disposition:")), "")
                name_match = re.search(r'name="([^"]+)"', disposition)
                if not name_match:
                    continue
                name = name_match.group(1)
                filename_match = re.search(r'filename="([^"]*)"', disposition)
                if filename_match:
                    form[name] = {"filename": filename_match.group(1), "content": content}
                else:
                    form[name] = content.decode("utf-8", errors="replace")
            return form

        def _send_json(self, payload: dict[str, Any], status: HTTPStatus = HTTPStatus.OK) -> None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _send_asset(self, path: Path) -> None:
            resolved = path.resolve()
            asset_root = ASSET_DIR.resolve()
            if asset_root not in resolved.parents and resolved != asset_root:
                self.send_error(HTTPStatus.FORBIDDEN)
                return
            if not resolved.exists() or not resolved.is_file():
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            body = resolved.read_bytes()
            content_type = mimetypes.guess_type(str(resolved))[0] or "application/octet-stream"
            if resolved.suffix == ".js":
                content_type = "text/javascript"
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    return IELTSWebHandler
