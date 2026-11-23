"""Isolated OpenCode execution. No file or DB permissions granted to model."""
import json
import re
import os
import subprocess
import tempfile
from pathlib import Path
from .prompts import BASE_PROMPT

def model_response(stdout: str):
    chunks = []
    for line in stdout.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(event, dict) and event.get("type") == "text":
            part = event.get("part") or {}
            if isinstance(part, dict) and isinstance(part.get("text"), str):
                chunks.append(part["text"])
        if isinstance(event, dict) and event.get("type") == "error":
            raise RuntimeError(f"OpenCode error: {str(event.get('error'))[:400]}")
    raw = "".join(chunks).strip() if chunks else stdout.strip()
    if raw.startswith("```"):
        raw = re.sub(r"\A```(?:json)?\s*|\s*```\Z", "", raw)
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError("OpenCode did not return parseable JSON: " + raw[:250]) from exc


def opencode(prompt: str, model: str, executable: str, timeout: int):
    # A temporary, tool-denied agent cannot modify or read arbitrary files.
    denied = [{"action": "*", "resource": "*", "effect": "deny"}]
    cfg = {"$schema": "https://opencode.ai/config.json", "permissions": denied,
           "policies": [{"action": "tool.use", "resource": "*", "effect": "deny"}],
           "agents": {"lexicon-enricher": {"mode": "primary", "steps": 1,
                       "permissions": denied}}}
    with tempfile.TemporaryDirectory(prefix="lexicon-enrichment-") as temp:
        work = Path(temp)
        (work / "opencode.json").write_text(json.dumps(cfg), encoding="utf-8")
        env = dict(os.environ)
        env.pop("OPENCODE_CONFIG", None)
        env.pop("OPENCODE_CONFIG_CONTENT", None)
        # OpenCode may use PWD for project discovery. subprocess.run(cwd=...)
        # changes the process cwd but does not update an inherited PWD.
        # Without this, our temporary agent config may not be loaded.
        env["PWD"] = str(work)
        command = [executable, "--standalone", "run", "--format", "json",
                   "--agent", "lexicon-enricher", "--model", model, prompt]
        try:
            result = subprocess.run(command, cwd=work, env=env, text=True,
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                    timeout=timeout, check=False, stdin=subprocess.DEVNULL)
        except FileNotFoundError as exc:
            raise RuntimeError("OpenCode is not installed on this machine") from exc
        if result.returncode:
            # In --format json mode OpenCode can report failures as JSONL on
            # stdout while leaving stderr empty. Surface these diagnostics.
            errors = []
            for line in result.stdout.splitlines():
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(event, dict) and event.get("type") == "error":
                    errors.append(json.dumps(event.get("error"), ensure_ascii=False))
            details = ("; ".join(errors) or result.stdout.strip())[-2000:] or "(empty)"
            stderr = result.stderr.strip()[-1000:] or "(empty)"
            raise RuntimeError(
                f"OpenCode exited {result.returncode}. "
                f"JSON errors/stdout: {details}; stderr: {stderr}"
            )
        return model_response(result.stdout)

