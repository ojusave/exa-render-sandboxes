"""Bounded file and process helper, executed inside a credential-free Render Sandbox."""

# Standard-library modules handle encoded inputs, files, child processes and deadlines.
import base64
import json
import os
import selectors
import signal
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path("/workspace")
MAX_OUTPUT = 16_384


def execute(driver, case, seconds=8):
    """Run one generated-code case in a separate process and cap its time and output."""
    # The child receives a deliberately small environment. The application keys stay on
    # the host. -I ignores user Python settings, while -B avoids bytecode cache files.
    process = subprocess.Popen(
        [sys.executable, "-I", "-B", "-c", driver], cwd=ROOT,
        env={"PATH": "/usr/local/bin:/usr/bin:/bin", "HOME": "/tmp", "POLARS_MAX_THREADS": "2"},
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        start_new_session=True,
    )
    process.stdin.write(json.dumps(case).encode())
    process.stdin.close()
    output = {"stdout": bytearray(), "stderr": bytearray()}
    selector = selectors.DefaultSelector()
    selector.register(process.stdout, selectors.EVENT_READ, "stdout")
    selector.register(process.stderr, selectors.EVENT_READ, "stderr")
    deadline, limited = time.monotonic() + seconds, None
    try:
        # Read both pipes together so a noisy error stream cannot freeze the parent.
        while selector.get_map():
            if time.monotonic() >= deadline:
                limited = "timeout"
                break
            for key, _ in selector.select(0.1):
                chunk = os.read(key.fileobj.fileno(), 8192)
                if not chunk:
                    selector.unregister(key.fileobj)
                    continue
                room = MAX_OUTPUT - sum(map(len, output.values()))
                output[key.data].extend(chunk[:room])
                if len(chunk) > room:
                    limited = "output_limit"
                    break
            if limited:
                break
        if not limited:
            try:
                process.wait(timeout=max(0.01, deadline - time.monotonic()))
            except subprocess.TimeoutExpired:
                limited = "timeout"
    finally:
        # Killing the process group also removes any child processes the code started.
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.wait(timeout=2)
        selector.close()
        process.stdout.close()
        process.stderr.close()
    return {**{k: bytes(v).decode(errors="replace") for k, v in output.items()},
            "exit_code": 124 if limited == "timeout" else 125 if limited else process.returncode,
            "limit": limited}


def main(payload):
    """Accept only the operations the host application knows how to request."""
    ROOT.mkdir(exist_ok=True)
    if payload["op"] == "write":
        code = payload["source"]
        if not isinstance(code, str) or len(code.encode()) > 24_576:
            raise ValueError("Source must fit the file limit")
        # Refuse a symbolic-link destination, which could redirect a write elsewhere.
        flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW
        with os.fdopen(os.open(ROOT / "solution.py", flags, 0o600), "w") as file:
            file.write(code)
        return {"written": True}
    if payload["op"] == "check":
        return execute(payload["driver"], payload["case"], payload.get("seconds", 8))
    if payload["op"] == "environment":
        import polars
        return {"polars": polars.__version__, "credentials_absent": not any(
            os.environ.get(k) for k in ["RENDER_API_KEY", "EXA_API_KEY", "OPENROUTER_API_KEY"])}
    raise ValueError("Unknown remote operation")


# The command-line argument is encoded data, not executable shell text.
if __name__ == "__main__":
    try:
        print(json.dumps(main(json.loads(base64.b64decode(sys.argv[1])))))
    except Exception as exc:
        print(json.dumps({"error": type(exc).__name__}))
        sys.exit(1)
