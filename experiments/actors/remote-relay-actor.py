"""Remote oneapi-relay LLM actor for the RACER paired pilot.

Loads credentials exclusively from the runtime environment variables
ANTHROPIC_AUTH_TOKEN / ANTHROPIC_BASE_URL (never from the repository), wraps
the shared StructuredLLMActor, and exposes the runner's Python-actor contract
(act/usage_snapshot).
"""
import importlib.util
import os
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_CANDIDATE_PATHS = (
    _ROOT / "llm_actor.py",  # Docker agent-runner image
    _ROOT / "services" / "agent_runner" / "llm_actor.py",  # project checkout
)
_MODULE_PATH = next((path for path in _CANDIDATE_PATHS if path.is_file()), None)
if _MODULE_PATH is None:
    raise RuntimeError("llm_actor.py is not available in the runner environment")
_SPEC = importlib.util.spec_from_file_location("remote_llm_actor_impl", _MODULE_PATH)
_MODULE = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = _MODULE
_SPEC.loader.exec_module(_MODULE)
LLMActorConfig = _MODULE.LLMActorConfig
StructuredLLMActor = _MODULE.StructuredLLMActor

_config = LLMActorConfig.from_env()
_actor = StructuredLLMActor(_config)


def act(observation, context):
    return _actor(observation, context)


def usage_snapshot():
    return _actor.usage_snapshot()


def actor_identity():
    return {
        "actor_id": _actor.actor_id,
        "provider": _config.provider,
        "model": _config.model,
        "base_url_origin": _config.base_url,
    }
