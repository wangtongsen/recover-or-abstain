import hashlib
import json
import os
import sys
from pathlib import Path
from urllib.parse import quote
from urllib.request import Request, urlopen
from http.server import BaseHTTPRequestHandler, HTTPServer

_COMMON_DIR = next(
    candidate
    for candidate in (Path(__file__).resolve().parent / "common", Path(__file__).resolve().parents[1] / "common")
    if candidate.is_dir()
)
if str(_COMMON_DIR) not in sys.path:
    sys.path.insert(0, str(_COMMON_DIR))
from environment_contract import environment_contract, validate_replay_contract

TASK_ENV_URL = os.environ.get("TASK_ENV_URL", "http://task-env:8080")


REQUEST_TIMEOUT = float(os.environ.get("REQUEST_TIMEOUT", "5"))


def call(path, payload=None):
    if payload is None:
        with urlopen(TASK_ENV_URL + path, timeout=REQUEST_TIMEOUT) as response:
            return json.load(response)
    data = json.dumps(payload).encode()
    request = Request(TASK_ENV_URL + path, data=data, headers={"Content-Type": "application/json"})
    with urlopen(request, timeout=REQUEST_TIMEOUT) as response:
        return json.load(response)


def _requested_action(item):
    if not isinstance(item, dict):
        return {}
    action = item.get("requested_action")
    if isinstance(action, dict):
        return action
    action = item.get("action", item)
    return action if isinstance(action, dict) else {}


def _failed_replay(reason, replay_run_id, source_contract):
    return {
        "run_id": replay_run_id,
        "source_run_id": source_contract.get("source_run_id"),
        "episode_id": source_contract.get("episode_id"),
        "replay_provenance": {"valid": False, "reason": reason},
        "trace": [],
        "evaluation": {
            "success": False,
            "side_effect": False,
            "counterfactual_supported": False,
            "replay_valid": False,
            "replay_failure_reason": reason,
        },
    }


def replay(
    prefix,
    patch,
    suffix=None,
    run_id=None,
    source_seed=None,
    source_faults=None,
    env_config=None,
    episode_id=None,
    source_contract=None,
    replay_contract=None,
    strict_replay=False,
):
    # Derive a stable isolated replay session from the source run. For legacy
    # payloads without run_id, hash the replay content for deterministic IDs.
    if run_id:
        replay_run_id = f"{run_id}:cf"
    else:
        material = json.dumps({"prefix": prefix, "patch": patch, "suffix": suffix or []}, sort_keys=True, separators=(",", ":"))
        replay_run_id = "cf-" + hashlib.sha256(material.encode()).hexdigest()[:16]
    replay_seed = source_seed if source_seed is not None else 0
    source_contract = source_contract if isinstance(source_contract, dict) else environment_contract(
        env_config=env_config,
        seed=replay_seed,
        run_id=run_id or replay_run_id,
        episode_id=episode_id,
        source_run_id=run_id or replay_run_id,
    )
    if strict_replay:
        valid, reason = validate_replay_contract(source_contract, replay_contract, replay_run_id)
        if not valid:
            return _failed_replay(reason, replay_run_id, source_contract)
    # Preserve the complete source environment configuration while making the
    # counterfactual clean: only faults are replaced with an empty list.
    replay_config = dict(env_config) if isinstance(env_config, dict) else {}
    nested_config = replay_config.get("env_config") if isinstance(replay_config.get("env_config"), dict) else {}
    if nested_config:
        replay_config = {**nested_config, **{key: value for key, value in replay_config.items() if key != "env_config"}}
    replay_config["faults"] = []
    replay_payload = {"run_id": replay_run_id, "seed": replay_seed, **replay_config}
    replay_payload["env_config"] = dict(replay_config)
    call("/reset", replay_payload)
    replayed = []
    for item in prefix:
        replayed.append(call("/step", {"run_id": replay_run_id, **_requested_action(item)}))
    if patch:
        replayed.append(call("/step", {"run_id": replay_run_id, **patch}))
    for item in suffix or []:
        action = _requested_action(item)
        replayed.append(call("/step", {"run_id": replay_run_id, **action}))
    evaluation = call(f"/evaluate?run_id={quote(replay_run_id, safe='')}")
    if not isinstance(evaluation, dict):
        evaluation = {"success": False, "side_effect": False}
    evaluation = dict(evaluation)
    evaluation["counterfactual_supported"] = True
    evaluation["replay_valid"] = True
    return {
        "trace": replayed,
        "evaluation": evaluation,
        "run_id": replay_run_id,
        "source_run_id": source_contract.get("source_run_id"),
        "episode_id": source_contract.get("episode_id"),
        "replay_provenance": {"valid": True, "strict": bool(strict_replay), "source_contract": source_contract},
    }


class Handler(BaseHTTPRequestHandler):
    def _send(self, payload, status=200):
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/health":
            return self._send({"ok": True})
        return self._send({"error": "not found"}, 404)

    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        payload = json.loads(self.rfile.read(length) or b"{}")
        if self.path == "/replay":
            return self._send(
                replay(
                    payload.get("prefix", []),
                    payload.get("patch"),
                    payload.get("suffix", []),
                    payload.get("run_id"),
                    payload.get("source_seed", payload.get("seed")),
                    payload.get("source_faults", payload.get("faults")),
                    payload.get("env_config", payload.get("reset")),
                    payload.get("episode_id"),
                    payload.get("source_contract"),
                    payload.get("replay_contract"),
                    payload.get("strict_replay", False),
                )
            )
        return self._send({"error": "not found"}, 404)

    def log_message(self, *_):
        return


HTTPServer(("0.0.0.0", 8080), Handler).serve_forever()
