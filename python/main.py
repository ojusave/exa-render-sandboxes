"""Compare code repair with and without live Exa search, using real Render Sandboxes."""

# Standard-library helpers handle CLI input, deadlines, saved evidence and safe encoding.
from __future__ import annotations
import argparse
import asyncio
import base64
import hashlib
import json
import os
import shlex
import signal
import sys
import time
import uuid
from urllib.parse import urlparse
from datetime import UTC, datetime, timedelta
from pathlib import Path

# httpx sends HTTPS requests. Render's official SDK manages sandbox lifecycle and commands.
import httpx
from render import RenderAsync
from render.experimental.sandbox import SandboxExecExit, SandboxExecOutput

ROOT = Path(__file__).resolve().parents[1]
SHARED = ROOT / "shared"
CONTRACT = json.loads((SHARED / "contract.json").read_text())
CASES = json.loads((SHARED / "cases.json").read_text())
REMOTE = base64.b64encode((SHARED / "remote.py").read_bytes()).decode()
DRIVER = (SHARED / "driver.py").read_text()


class DemoError(RuntimeError):
    """An application-written diagnostic that does not include secret response bodies."""


def digest(text):
    """A hash identifies the exact source used without trusting the model's description."""
    return hashlib.sha256(text.encode()).hexdigest()


def parse_candidate(body):
    """Reject malformed or oversized model output before uploading code to Render."""
    obj = json.loads(body)
    if not isinstance(obj, dict) or set(obj) != {"source", "explanation"}:
        raise DemoError("Model must return source and explanation")
    if not all(isinstance(obj[k], str) for k in obj) or not obj["source"].strip():
        raise DemoError("Model returned missing or invalid source text")
    if len(obj["source"].encode()) > CONTRACT["max_source_bytes"]:
        raise DemoError("Model source exceeded the file size limit")
    return obj


def judge(case, result):
    """The host compares real output with predeclared expectations, outside model control."""
    try:
        actual = json.loads(result["stdout"])
    except (ValueError, KeyError):
        actual = {"error": "InvalidOutput"}
    success = result.get("exit_code") == 0 and not result.get("limit")
    if case.get("expected_error"):
        success = success and isinstance(actual, dict) and actual.get("error") == "InvalidOperationError"
    else:
        success = success and json.dumps(actual, sort_keys=True) == json.dumps(case["expected"], sort_keys=True)
    return {"name": case["name"], "passed": bool(success), "actual": actual,
            "exit_code": result.get("exit_code"), "limit": result.get("limit")}


def make_messages(source, observed, evidence):
    """Both modes receive identical tasks; only the Exa mode receives retrieved documents."""
    request = {"task": CONTRACT["task"], "source": source, "public_cases": CASES["public"],
               "initial_failures": observed}
    if evidence is not None:
        request["retrieved_documentation"] = evidence
    return [{"role": "system", "content": CONTRACT["system"]},
            {"role": "user", "content": json.dumps(request)}]


class Run:
    """Own one comparison and every cloud resource created for it."""
    def __init__(self, output, model):
        self.output = output
        output.mkdir(parents=True, exist_ok=False)
        self.api = RenderAsync().experimental.sandboxes
        self.state = {"language": "python", "started_at": datetime.now(UTC).isoformat(),
                      "workspace": os.environ["RENDER_WORKSPACE_ID"], "model": model,
                      "sandboxes": [], "snapshots": [], "trials": [], "complete": False,
                      "fixture_sha256": digest((SHARED / "cases.json").read_text()),
                      "contract_sha256": digest((SHARED / "contract.json").read_text()),
                      "source_sha256": {str(p.relative_to(ROOT)): digest(p.read_text()) for p in
                        [Path(__file__), *sorted(SHARED.glob("*.py")), SHARED / "contract.json", SHARED / "cases.json"]}}
        self.save()

    def save(self):
        """Replace the journal atomically so interruption leaves a readable cleanup record."""
        temporary = self.output / "run.json.tmp"
        temporary.write_text(json.dumps(self.state, indent=2) + "\n")
        temporary.replace(self.output / "run.json")

    async def get(self, sid):
        """Read effective cloud settings from the public API, including full network rules."""
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.get("https://api.render.com/v1/sandboxes/" + sid,
                headers={"Authorization": "Bearer " + os.environ["RENDER_API_KEY"]})
            if response.status_code != 200:
                raise DemoError(f"Sandbox read returned HTTP {response.status_code}")
            return response.json()

    async def create(self, snapshot=None, bootstrap=False):
        """Create once, save the ID, wait for readiness and verify the outbound policy."""
        policy = {"type": "allow-list", "rules": [
            {"domain": host, "protocol": "https"} for host in ["pypi.org", "files.pythonhosted.org"]
        ]} if bootstrap else {"type": "deny-all"}
        self.state["pending_create"] = {"time": datetime.now(UTC).isoformat(), "policy": policy}
        self.save()
        if bootstrap:
            # The pinned SDK cannot express these destination rules; use the public REST API.
            async with httpx.AsyncClient(timeout=40) as client:
                response = await client.post("https://api.render.com/v1/sandboxes",
                    headers={"Authorization": "Bearer " + os.environ["RENDER_API_KEY"]},
                    json={"ownerId": self.state["workspace"], "plan": "starter",
                          "timeoutSeconds": 600, "networkPolicy": policy})
                if response.status_code not in (200, 201, 202):
                    # A definite rejection did not create a sandbox. Lost replies remain pending.
                    if response.status_code < 500:
                        self.state.pop("pending_create", None)
                        self.save()
                    raise DemoError(f"Sandbox create returned HTTP {response.status_code}")
                sid = response.json()["id"]
        else:
            async with asyncio.timeout(40):
                sandbox = await self.api.create(plan="starter", timeout_seconds=600,
                    network_policy="deny-all", snapshot_id=snapshot)
                sid = sandbox.id
        self.state["sandboxes"].append({"id": sid, "terminated": False, "bootstrap": bootstrap})
        self.state.pop("pending_create", None)
        self.save()
        for _ in range(30):
            current = await self.get(sid)
            if current["status"] == "running":
                effective = current["networkPolicy"]
                if (effective.get("type", effective.get("default")) != policy["type"] or
                    (bootstrap and effective.get("rules") != policy["rules"])):
                    raise DemoError("Effective sandbox network policy differs from requested policy")
                return sid
            if current["status"] not in ("creating", "pending", "resuming"):
                raise DemoError("Sandbox did not reach running")
            await asyncio.sleep(1)
        raise DemoError("Sandbox readiness deadline exceeded")

    async def command(self, sid, command, seconds=40):
        """Require an exit event, cap output and never replay an uncertain command."""
        chunks, size, exit_code = [], 0, None
        async with asyncio.timeout(seconds):
            async for event in self.api.exec(sid, command):
                if isinstance(event, SandboxExecOutput):
                    size += len(event.data.encode())
                    if size > 131072:
                        raise DemoError("Sandbox output exceeded its limit")
                    chunks.append(event.data)
                elif isinstance(event, SandboxExecExit):
                    exit_code = event.exit_code
        if exit_code is None:
            raise DemoError("Sandbox stream ended without an exit event")
        return {"exit_code": exit_code, "output": "".join(chunks)}

    async def rpc(self, sid, payload):
        """Send encoded data to the fixed helper, never interpolate model text into a shell."""
        encoded = base64.b64encode(json.dumps(payload).encode()).decode()
        command = shlex.join(["/opt/demo/bin/python", "-I", "-c", f"import base64;exec(base64.b64decode({REMOTE!r}))", encoded])
        result = await self.command(sid, command)
        if result["exit_code"]:
            raise DemoError("Remote helper failed")
        return json.loads(result["output"])

    async def checks(self, sid, cases):
        """Run each input separately and retain per-case evidence rather than a claimed pass."""
        results = []
        for case in cases:
            observed = await self.rpc(sid, {"op": "check", "driver": DRIVER, "case": case["input"]})
            results.append(judge(case, observed))
        return results

    async def terminate(self, sid):
        """Retry only termination of an owned ID and confirm the terminal cloud state."""
        record = next(r for r in self.state["sandboxes"] if r["id"] == sid)
        if record["terminated"]:
            return
        for attempt in range(3):
            try:
                await asyncio.wait_for(self.api.terminate(sid), 20)
            except Exception:
                pass  # A lost reply is not proof of failure; the subsequent read resolves it.
            try:
                state = await self.get(sid)
                if state["status"] == "terminated":
                    record.update(terminated=True, final_status=state["status"])
                    self.save()
                    return
            except Exception:
                pass
            await asyncio.sleep(attempt + 1)
        raise DemoError("Cleanup unconfirmed for " + sid)

    async def prepare(self):
        """Install trusted dependencies once, then snapshot before any generated code exists."""
        sid = await self.create(bootstrap=True)
        result = await self.command(sid, "python3 -m venv /opt/demo && /opt/demo/bin/pip install --disable-pip-version-check --no-cache-dir polars==2.0.0", 150)
        self.state["installation"] = result
        self.save()
        if result["exit_code"]:
            raise DemoError("Pinned Polars installation failed")
        self.state["pending_snapshot"] = sid
        self.save()
        snapshot = await asyncio.wait_for(self.api.snapshots.create(sid, kind="filesystem",
            name="exa-" + self.output.name, expires_at=datetime.now(UTC) + timedelta(hours=1)), 40)
        record = {"id": snapshot.id, "group": snapshot.sandbox_group_id, "deleted": False}
        self.state["snapshots"].append(record)
        self.state.pop("pending_snapshot", None)
        self.save()
        for _ in range(60):
            current = await asyncio.wait_for(self.api.snapshots.from_id(
                sandbox_group_id=record["group"], snapshot_id=record["id"]), 20)
            if current.status == "available":
                await self.terminate(sid)
                return snapshot.id
            if current.status == "failed":
                raise DemoError("Prepared snapshot failed")
            await asyncio.sleep(1)
        raise DemoError("Snapshot readiness deadline exceeded")

    async def search(self):
        """Fetch current official documentation through Exa and save its exact returned text."""
        started = time.monotonic()
        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.post("https://api.exa.ai/search",
                headers={"x-api-key": os.environ["EXA_API_KEY"]},
                json={"query": CONTRACT["search_query"], "type": "auto",
                      "numResults": CONTRACT["search_results"], "includeDomains": CONTRACT["search_domains"],
                      "contents": {"text": {"maxCharacters": 14000}}})
        if response.status_code != 200:
            raise DemoError(f"Exa returned HTTP {response.status_code}")
        body = response.json()
        evidence = [{"url": row["url"], "title": row.get("title", ""),
                     "text": row.get("text", "")[:14000]} for row in body.get("results", [])]
        evidence = [row for row in evidence if urlparse(row["url"]).scheme == "https"
                    and urlparse(row["url"]).hostname in CONTRACT["search_domains"]]
        if not evidence or not any(row["text"].strip() for row in evidence):
            raise DemoError("Exa returned no readable evidence; search mode cannot proceed")
        return {"request_id": body.get("requestId"), "seconds": time.monotonic() - started,
                "cost_usd": body.get("costDollars", {}).get("total"), "results": evidence}

    async def preflight_model(self):
        """Check funds and supported settings before allocating any paid cloud machine."""
        async with httpx.AsyncClient(timeout=25) as client:
            headers = {"Authorization": "Bearer " + os.environ["OPENROUTER_API_KEY"]}
            response = await client.get("https://openrouter.ai/api/v1/credits", headers=headers)
            if response.status_code != 200:
                raise DemoError("Could not verify OpenRouter credit")
            funds = response.json()["data"]
            if funds["total_credits"] <= funds["total_usage"]:
                raise DemoError("OpenRouter has no remaining credit; no sandboxes allocated")
            response = await client.get("https://openrouter.ai/api/v1/key", headers=headers)
            if response.status_code != 200:
                raise DemoError("Could not verify the OpenRouter key limit")
            remaining = response.json()["data"].get("limit_remaining")
            if remaining is not None and remaining <= 0:
                raise DemoError("OpenRouter key spending limit exhausted")
            response = await client.get("https://openrouter.ai/api/v1/models/" + self.state["model"] + "/endpoints")
            if response.status_code != 200 or not any(
                {"max_tokens", "response_format", "reasoning"}.issubset(e.get("supported_parameters", []))
                for e in response.json().get("data", {}).get("endpoints", [])
            ):
                raise DemoError("No model endpoint supports the requested settings")
        self.state["model_preflight"] = "passed"
        self.save()

    async def model(self, messages):
        """Send only the public fixture and optional documentation to the chosen model."""
        started = time.monotonic()
        self.state["model_requests"] = self.state.get("model_requests", 0) + 1
        self.save()
        async with httpx.AsyncClient(timeout=90) as client:
            response = await client.post("https://openrouter.ai/api/v1/chat/completions",
                headers={"Authorization": "Bearer " + os.environ["OPENROUTER_API_KEY"],
                         "X-OpenRouter-Title": "Exa + Render repair comparison"},
                json={"model": self.state["model"], "messages": messages, "reasoning": {"enabled": False},
                      "max_tokens": CONTRACT["max_tokens"], "response_format": {"type": "json_object"},
                      "provider": {"require_parameters": True}})
        if response.status_code != 200:
            raise DemoError(f"Model provider returned HTTP {response.status_code}")
        body = response.json()
        if body.get("error") or not body.get("choices"):
            raise DemoError("Model provider did not return a completion")
        choice = body["choices"][0]
        meta = {"id": body.get("id"), "model": body.get("model"), "usage": body.get("usage"),
                "seconds": time.monotonic() - started, "finish_reason": choice.get("finish_reason")}
        return choice["message"], meta

    async def trial(self, snapshot, mode, repetition):
        """Repair in one sandbox, lock the candidate, and verify it in a different sandbox."""
        trial = {"mode": mode, "repetition": repetition, "attempts": [], "passed": False}
        self.state["trials"].append(trial)
        self.save()
        sid = await self.create(snapshot)
        trial["repair_sandbox"] = sid
        if not self.state.get("fixture_reference"):
            await self.validate_fixture(snapshot, sid)
        # Measure both modes after identical setup; calibration is excluded from timing.
        started = time.monotonic()
        source = (SHARED / "starter.py").read_text()
        await self.rpc(sid, {"op": "write", "source": source})
        initial = await self.checks(sid, CASES["public"])
        trial["initial"] = initial
        if any(row["passed"] for row in initial):
            raise DemoError("Fixture no longer reproduces all three intended failures")
        search = await self.search() if mode == "exa" else None
        trial["search"] = search
        messages = make_messages(source, initial, search["results"] if search else None)
        for attempt in range(CONTRACT["max_attempts"]):
            message, meta = await self.model(messages)
            item = {"call": meta}
            trial["attempts"].append(item)
            self.save()
            if meta["finish_reason"] != "stop":
                item["error"] = "Model response was incomplete"
                break
            try:
                candidate = parse_candidate(message.get("content", ""))
            except (ValueError, DemoError):
                item["error"] = "Invalid candidate JSON or source size"
                messages.extend([message, {"role": "user", "content": item["error"]}])
                continue
            source = candidate["source"]
            item.update(candidate, source_sha256=digest(source))
            await self.rpc(sid, {"op": "write", "source": source})
            checks = await self.checks(sid, CASES["public"])
            item["public_checks"] = checks
            self.save()
            if all(row["passed"] for row in checks):
                break
            messages.extend([message, {"role": "user", "content": json.dumps({"test_feedback": checks})}])
        # The host retains exactly the submitted bytes; a model cannot overwrite our tests.
        filename = f"{mode}-{repetition}-solution.py"
        (self.output / filename).write_text(source)
        trial.update(candidate_file=filename, source_sha256=digest(source))
        await self.terminate(sid)
        verifier = await self.create(snapshot)
        trial["verification_sandbox"] = verifier
        await self.rpc(verifier, {"op": "write", "source": source})
        trial["verification"] = await self.checks(verifier, CASES["public"] + CASES["held_out"])
        trial["passed"] = all(row["passed"] for row in trial["verification"])
        await self.terminate(verifier)
        trial["seconds"] = time.monotonic() - started
        trial["model_cost_usd"] = sum(a["call"]["usage"]["cost"] for a in trial["attempts"] if isinstance(a["call"].get("usage", {}).get("cost"), (int, float)))
        trial["model_cost_complete"] = all(isinstance(a["call"].get("usage", {}).get("cost"), (int, float)) for a in trial["attempts"])
        self.save()
        print(f"{mode} repetition {repetition}: {sum(r['passed'] for r in trial['verification'])}/15 checks, {trial['seconds']:.1f}s", flush=True)

    async def cleanup(self):
        """Remove all owned machines and snapshots, preserving both workload and cleanup errors."""
        errors = []
        for record in self.state["sandboxes"]:
            try:
                await self.terminate(record["id"])
            except Exception as exc:
                errors.append(record["id"] + ": " + type(exc).__name__)
        for record in self.state["snapshots"]:
            if record["deleted"]:
                continue
            try:
                try:
                    await asyncio.wait_for(self.api.snapshots.delete(sandbox_group_id=record["group"], snapshot_id=record["id"]), 30)
                except Exception:
                    pass  # An already-deleted snapshot is resolved by the independent list below.
                # Verify absence across all pages. Deletion is separate from machine termination.
                cursor, absent = None, True
                for _ in range(100):
                    page = await asyncio.wait_for(self.api.snapshots.list(sandbox_group_id=record["group"], limit=100, cursor=cursor), 20)
                    absent = absent and not any(s.id == record["id"] for s in page.snapshots)
                    if not page.next_cursor or not page.snapshots:
                        break
                    if page.next_cursor == cursor:
                        raise DemoError("Snapshot pagination did not advance")
                    cursor = page.next_cursor
                else:
                    raise DemoError("Snapshot listing exceeded its budget")
                if not absent:
                    raise DemoError("Snapshot remains listed")
                record["deleted"] = True
            except Exception as exc:
                errors.append(record["id"] + ": " + type(exc).__name__)
        if self.state.get("pending_create") or self.state.get("pending_snapshot"):
            errors.append("Unknown creation outcome requires provider reconciliation")
        self.state.update(cleanup_verified=not errors, cleanup_errors=errors)
        self.save()
        if errors:
            raise DemoError("Cleanup needs attention; inspect run.json")

    async def validate_fixture(self, snapshot, existing_sid=None):
        """Prove the original fails and the maintainer solution passes before measuring models."""
        sid = existing_sid or await self.create(snapshot)
        self.state["environment"] = await self.rpc(sid, {"op": "environment"})
        if self.state["environment"] != {"polars": "2.0.0", "credentials_absent": True}:
            raise DemoError("Unexpected sandbox environment")
        # These fixed probes run inside the sandbox and contain no generated instructions.
        # The package installation already proves PyPI was reachable in the setup machine.
        async with httpx.AsyncClient(timeout=10) as client:
            control = await client.get("https://pypi.org/simple/polars/")
            control.raise_for_status()
        self.state["network_host_control"] = control.status_code
        probes = {
            "timeout": {"driver": "import time; time.sleep(30)", "seconds": 0.3},
            "output_limit": {"driver": "print('x' * 20000)"},
            "network": {"driver": "import json, urllib.request\ntry:\n urllib.request.urlopen('https://pypi.org/simple/polars/',timeout=2); print(json.dumps({'blocked':False}))\nexcept Exception:\n print(json.dumps({'blocked':True}))"},
        }
        observations = {name: await self.rpc(sid, {"op": "check", "case": {}, **probe})
                        for name, probe in probes.items()}
        self.state["network_observation"] = observations["network"]
        self.state["boundary_checks"] = {
            "timeout": observations["timeout"].get("limit") == "timeout",
            "output_limit": observations["output_limit"].get("limit") == "output_limit",
            "network": observations["network"].get("limit") == "timeout" or (
                       observations["network"].get("exit_code") == 0 and
                       json.loads(observations["network"]["stdout"]) == {"blocked": True}),
            "credentials_absent": self.state["environment"]["credentials_absent"],
        }
        if not all(self.state["boundary_checks"].values()):
            raise DemoError("A live sandbox boundary check failed")
        await self.rpc(sid, {"op": "write", "source": (SHARED / "starter.py").read_text()})
        self.state["fixture_initial"] = await self.checks(sid, CASES["public"])
        if any(row["passed"] for row in self.state["fixture_initial"]):
            raise DemoError("Fixture no longer reproduces its intended failures")
        await self.rpc(sid, {"op": "write", "source": (SHARED / "reference.py").read_text()})
        self.state["fixture_reference"] = await self.checks(sid, CASES["public"] + CASES["held_out"])
        self.save()
        if not all(c["passed"] for c in self.state["fixture_reference"]):
            raise DemoError("Maintainer fixture does not pass its expectations")
        if existing_sid is None:
            await self.terminate(sid)


async def main():
    """Provide a runnable comparison and an explicit recovery command for saved resource IDs."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=["compare", "cleanup", "smoke", "integration", "fail-after-create"])
    parser.add_argument("--repetitions", type=int, choices=range(1, 4), default=1)
    parser.add_argument("--run-dir", type=Path)
    args = parser.parse_args()
    needed = ["RENDER_API_KEY", "RENDER_WORKSPACE_ID"] + (["EXA_API_KEY", "OPENROUTER_API_KEY"] if args.mode == "compare" else [])
    if args.mode == "integration":
        needed.append("EXA_API_KEY")
    if any(not os.getenv(k) for k in needed):
        raise DemoError("Set " + ", ".join(needed))
    if os.getenv("RENDER_USE_LOCAL_DEV") or os.getenv("RENDER_LOCAL_DEV_URL"):
        raise DemoError("Unset Render local development overrides for cloud validation")
    output = args.run_dir or ROOT / ".runs" / ("python-" + uuid.uuid4().hex[:10])
    if args.mode == "cleanup":
        if args.run_dir is None:
            raise DemoError("cleanup requires --run-dir")
        run = object.__new__(Run)
        run.output, run.api = output, RenderAsync().experimental.sandboxes
        run.state = json.loads((output / "run.json").read_text())
        if run.state["workspace"] != os.environ["RENDER_WORKSPACE_ID"]:
            raise DemoError("Cleanup workspace does not match the run")
        await run.cleanup()
        return
    run = Run(output, os.getenv("OPENROUTER_MODEL", CONTRACT["model"]))
    print("Run journal: " + str(output / "run.json"), flush=True)
    # SIGINT/SIGTERM cancel work and enter finally; cleanup then uses its own time budget.
    task = asyncio.current_task()
    for sig in (signal.SIGINT, signal.SIGTERM):
        asyncio.get_running_loop().add_signal_handler(sig, task.cancel)
    try:
        async with asyncio.timeout(1200):
            if args.mode == "fail-after-create":
                await run.create()
                raise DemoError("Intentional failure after allocation")
            if args.mode == "compare":
                await run.preflight_model()
            if args.mode == "integration":
                run.state["integration_search"] = await run.search()
                run.save()
            snapshot = await run.prepare()
            if args.mode != "compare":
                await run.validate_fixture(snapshot)
            if args.mode == "compare":
                for repetition in range(1, args.repetitions + 1):
                    # Reverse the order on alternating pairs to reduce systematic timing bias.
                    for mode in (["baseline", "exa"] if repetition % 2 else ["exa", "baseline"]):
                        await run.trial(snapshot, mode, repetition)
            run.state["complete"] = True
    except BaseException as exc:
        run.state["failure"] = str(exc) if isinstance(exc, DemoError) else type(exc).__name__
        raise
    finally:
        await run.cleanup()
        print("Cleanup verified: " + str(run.state["cleanup_verified"]), flush=True)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (Exception, KeyboardInterrupt) as exc:
        # Do not let transport exceptions print request headers or other credential material.
        print(str(exc) if isinstance(exc, DemoError) else type(exc).__name__, file=sys.stderr)
        sys.exit(1)
