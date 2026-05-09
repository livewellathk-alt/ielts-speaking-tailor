from __future__ import annotations

import json
import mimetypes
import webbrowser
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import yaml

from .bank import load_question_bank
from .coverage import analyze_coverage
from .generation import GenerationConfig, GenerationPipeline, TimingConfig, word_targets_for
from .openai_client import OpenAICompatibleClient
from .profile_builder import build_generation_profile
from .questionnaire import build_questionnaire_model
from .rendering import render_outputs


ASSET_DIR = Path(__file__).with_name("web_assets")


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
    responses_path = output_dir / "profile_responses.yaml"
    bank = load_question_bank(bank_path) if bank_path.exists() else {"part1_topics": [], "part2_blocks": []}
    profile = yaml.safe_load(profile_path.read_text(encoding="utf-8")) if profile_path.exists() else {}
    responses = yaml.safe_load(responses_path.read_text(encoding="utf-8")) if responses_path.exists() else {}
    coverage = analyze_coverage(bank, responses or {})
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
        },
        "files": {
            "question_bank_exists": bank_path.exists(),
            "student_profile_exists": profile_path.exists(),
            "profile_responses_exists": responses_path.exists(),
            "result_markdown_exists": result_path.exists(),
        },
        "profile": profile or {},
        "responses": responses or {},
        "questionnaire": build_questionnaire_model(bank),
        "coverage": coverage,
        "word_targets": word_targets_for(int(generation.get("speaking_speed_wpm", 80)), timing),
        "result_markdown": result_path.read_text(encoding="utf-8") if result_path.exists() else "",
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


def generate_answers(config_path: str | Path) -> dict[str, Any]:
    root, config, paths = _load_config(config_path)
    bank = load_question_bank(root / paths["question_bank"])
    responses_path = root / paths["output_dir"] / "profile_responses.yaml"
    responses = yaml.safe_load(responses_path.read_text(encoding="utf-8")) if responses_path.exists() else {}
    coverage = analyze_coverage(bank, responses or {})
    if not coverage["can_generate_full"]:
        raise RuntimeError("资料不足，暂时不建议全量生成。请先根据补充建议完善素材。")
    return _run_generation(config_path, bank=bank, profile=_merged_profile(root, paths, responses), basename="ielts_speaking_answers")


def generate_sample_answers(config_path: str | Path) -> dict[str, Any]:
    root, _config, paths = _load_config(config_path)
    bank = load_question_bank(root / paths["question_bank"])
    responses_path = root / paths["output_dir"] / "profile_responses.yaml"
    responses = yaml.safe_load(responses_path.read_text(encoding="utf-8")) if responses_path.exists() else {}
    coverage = analyze_coverage(bank, responses or {})
    if not coverage["can_generate_sample"]:
        guidance = "；".join(coverage["followups"][:3]) or "请补充 Part 2 故事和 Part 3 观点。"
        raise RuntimeError(f"资料不足，无法生成测试样本。{guidance}")
    sample_bank = _sample_bank(bank)
    return _run_generation(
        config_path,
        bank=sample_bank,
        profile=_merged_profile(root, paths, responses),
        basename="ielts_speaking_sample",
    )


def _run_generation(config_path: str | Path, *, bank: dict[str, Any], profile: dict[str, Any], basename: str) -> dict[str, Any]:
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
        output_dir=root / paths["output_dir"],
    )
    result = GenerationPipeline(client=client, reviewer_client=reviewer_client, config=pipeline_config).run(bank=bank, profile=profile)
    rendered = render_outputs(result, output_dir=root / paths["output_dir"], basename=basename)
    return {"result": result, "rendered": {key: str(path) for key, path in rendered.items()}}


def _load_config(config_path: str | Path) -> tuple[Path, dict[str, Any], dict[str, str]]:
    config_path = Path(config_path).resolve()
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    return config_path.parent, config, config["paths"]


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
    for block in bank.get("part2_blocks", []):
        theme = block.get("theme") or ""
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
                self.send_error(HTTPStatus.NOT_FOUND)
            except Exception as exc:
                self._send_json({"ok": False, "error": str(exc)}, status=HTTPStatus.INTERNAL_SERVER_ERROR)

        def _read_json(self) -> dict[str, Any]:
            length = int(self.headers.get("Content-Length", "0"))
            if length == 0:
                return {}
            return json.loads(self.rfile.read(length).decode("utf-8"))

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
