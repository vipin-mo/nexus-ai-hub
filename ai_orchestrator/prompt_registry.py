"""Prompt versioning with the MLflow Prompt Registry.

The prompts in ``prompts.py`` are the source of truth in git. ``sync`` registers a new registry
version only when the text changed and points the ``production`` alias at it, so the release
flow is: edit prompt -> CI evaluation gate passes -> merge -> ``python -m
ai_orchestrator.prompt_registry --mlflow-uri ...``.

At runtime, with ``NEXUS_PROMPTS_FROM_REGISTRY=true`` the orchestrator loads
``prompts:/<name>@production`` (cached for 60 s), so a prompt can be rolled back by moving the
alias - no redeploy. If the registry is unreachable, the copy in code is used.
"""
from __future__ import annotations

import argparse
import logging
import os
import time

from ai_orchestrator import prompts

log = logging.getLogger(__name__)

PROMPTS = {
    "nexus-reasoner-system": prompts.REASONER_SYSTEM_PROMPT,
    "nexus-security-scan": prompts.SECURITY_SCAN_PROMPT,
    "nexus-router-fallback": prompts.ROUTER_FALLBACK_PROMPT,
}
ALIAS = "production"
_cache: dict[str, tuple[float, str, str]] = {}


def get_prompt(name: str) -> tuple[str, str]:
    """Return (text, version label) for a prompt."""
    local = PROMPTS[name], f"code:{prompts.PROMPT_VERSION}"
    if os.getenv("NEXUS_PROMPTS_FROM_REGISTRY", "false").lower() != "true":
        return local
    cached = _cache.get(name)
    if cached and time.monotonic() - cached[0] < 60:
        return cached[1], cached[2]
    try:
        import mlflow

        version = mlflow.genai.load_prompt(f"prompts:/{name}@{ALIAS}", link_to_model=False)
        result = (version.template, f"registry:{name}/v{version.version}")
    except Exception as exc:  # registry down or prompt not registered yet
        log.warning("Prompt registry unavailable for %s (%s); using code version", name, exc)
        result = local
    _cache[name] = (time.monotonic(), *result)
    return result


def sync(mlflow_uri: str) -> dict[str, str]:
    import mlflow

    mlflow.set_tracking_uri(mlflow_uri)
    out = {}
    for name, text in PROMPTS.items():
        current = mlflow.genai.load_prompt(f"prompts:/{name}@latest", allow_missing=True, link_to_model=False)
        if current is not None and current.template == text:
            out[name] = f"v{current.version} (unchanged)"
            continue
        version = mlflow.genai.register_prompt(
            name=name, template=text, commit_message=f"prompts.py {prompts.PROMPT_VERSION}",
            tags={"prompt_version": prompts.PROMPT_VERSION, "source": "ai_orchestrator/prompts.py"})
        mlflow.genai.set_prompt_alias(name, alias=ALIAS, version=version.version)
        out[name] = f"v{version.version} -> @{ALIAS}"
    return out


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Register prompts.py in the MLflow Prompt Registry")
    parser.add_argument("--mlflow-uri", default=os.getenv("MLFLOW_TRACKING_URI", "http://localhost:5001"))
    args = parser.parse_args()
    for prompt, status in sync(args.mlflow_uri).items():
        print(f"{prompt:28s} {status}")
