"""Local checks for the trusted runner. These tests never call a paid service."""

# Import the client without starting its command-line entry point or executing model code.
import importlib.util
import json
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

spec = importlib.util.spec_from_file_location("exa_client", Path(__file__).parents[1] / "python/main.py")
client = importlib.util.module_from_spec(spec)
spec.loader.exec_module(client)


def fake_run():
    """Keep simulated cloud IDs in memory so cleanup behavior can be tested safely."""
    run = object.__new__(client.Run)
    run.state = {"sandboxes": [], "snapshots": []}
    run.save = lambda: None
    run.api = SimpleNamespace(snapshots=SimpleNamespace(delete=AsyncMock(), list=AsyncMock()))
    return run


class DataTests(unittest.TestCase):
    def test_candidate_requires_exact_shape_and_size(self):
        # A model response is accepted as text only, and unexpected extra fields are rejected.
        valid = {"source": "# Example source\n", "explanation": "Example"}
        self.assertEqual(client.parse_candidate(json.dumps(valid)), valid)
        for value in [None, [], {**valid, "passed": True}, {**valid, "source": " "},
                      {**valid, "source": "x" * 24577}, {**valid, "explanation": False}]:
            with self.subTest(value_type=type(value).__name__), self.assertRaises(client.DemoError):
                client.parse_candidate(json.dumps(value))

    def test_judge_requires_expected_values_and_clean_exit(self):
        # Saying "passed" is insufficient. The host requires actual expected output.
        case = {"name": "number", "expected": {"result": [1, 2]}}
        result = {"stdout": '{"result":[1,2]}', "exit_code": 0}
        self.assertTrue(client.judge(case, result)["passed"])
        for changed in [{"stdout": '{"passed":true}'}, {"stdout": '{"result":[2,1]}'},
                        {"stdout": "not json"}, {"stdout": '{"result":[true,2]}'}, {"exit_code": 1}, {"limit": "timeout"}]:
            self.assertFalse(client.judge(case, {**result, **changed})["passed"])

    def test_invalid_date_output_must_be_an_error_object(self):
        # Valid JSON can still have the wrong shape, including null or a list.
        case = {"name": "invalid date", "expected_error": True}
        for output in ["null", "[]", "true", "1", '{"error":"ValueError"}']:
            self.assertFalse(client.judge(case, {"stdout": output, "exit_code": 0})["passed"])
        self.assertTrue(client.judge(case, {"stdout": '{"error":"InvalidOperationError"}', "exit_code": 0})["passed"])

    def test_only_search_evidence_differs_between_prompts(self):
        # Hold the task and initial errors constant. Hidden inputs never enter the prompt.
        a = client.make_messages("source", [], None)
        b = client.make_messages("source", [], [{"url": "https://pola.rs/", "text": "docs"}])
        body = json.loads(b[1]["content"])
        body.pop("retrieved_documentation")
        self.assertEqual(body, json.loads(a[1]["content"]))
        self.assertEqual(a[0], b[0])
        for hidden in client.CASES["held_out"]:
            self.assertNotIn(hidden["name"], a[1]["content"])


class LifecycleTests(unittest.IsolatedAsyncioTestCase):
    async def test_credit_preflight_stops_before_any_cloud_allocation(self):
        # Exhausted credit is detected through a read-only request, before creating a sandbox.
        run = fake_run()
        run.state["model"] = "anthropic/claude-haiku-5.5"
        response = SimpleNamespace(status_code=200, json=lambda: {"data": {"total_credits": 1, "total_usage": 2}})
        http = AsyncMock()
        http.__aenter__.return_value = http
        http.get.return_value = response
        with patch.dict(client.os.environ, {"OPENROUTER_API_KEY": "test-only"}), patch.object(client.httpx, "AsyncClient", return_value=http):
            with self.assertRaisesRegex(client.DemoError, "no remaining credit"):
                await run.preflight_model()
        self.assertEqual(http.get.await_count, 1)
        self.assertEqual(run.state["sandboxes"], [])

    async def test_lost_delete_reply_is_resolved_by_absence(self):
        # A repeated cleanup may receive 404 after an earlier successful deletion.
        run = fake_run()
        record = {"id": "owned-snapshot", "group": "owned-group", "deleted": False}
        run.state["snapshots"] = [record]
        run.api.snapshots.delete.side_effect = RuntimeError("already deleted")
        run.api.snapshots.list.return_value = SimpleNamespace(snapshots=[], next_cursor=None)
        await run.cleanup()
        self.assertTrue(record["deleted"])
        self.assertTrue(run.state["cleanup_verified"])

    async def test_snapshot_on_later_page_prevents_false_cleanup_success(self):
        # Read every page; finding only an empty first match is not evidence of deletion.
        run = fake_run()
        run.state["snapshots"] = [{"id": "owned", "group": "group", "deleted": False}]
        run.api.snapshots.list.side_effect = [
            SimpleNamespace(snapshots=[SimpleNamespace(id="other")], next_cursor="next"),
            SimpleNamespace(snapshots=[SimpleNamespace(id="owned")], next_cursor=None),
        ]
        with self.assertRaises(client.DemoError):
            await run.cleanup()
        self.assertFalse(run.state["cleanup_verified"])

    async def test_unknown_create_outcome_remains_visible(self):
        # A lost creation reply must not be reported as fully cleaned up.
        run = fake_run()
        run.state["pending_create"] = {"time": "example"}
        with self.assertRaises(client.DemoError):
            await run.cleanup()
        self.assertIn("Unknown creation", run.state["cleanup_errors"][0])

    async def test_stream_needs_exit_event_and_bounded_output(self):
        # A disconnected stream and excessive output both fail, even without an API error.
        async def stream(events):
            for event in events:
                yield event
        for events in [[client.SandboxExecOutput("stdout", "partial")],
                       [client.SandboxExecOutput("stdout", "x" * 131073)]]:
            run = fake_run()
            run.api.exec = lambda *args: stream(events)
            with self.assertRaises(client.DemoError):
                await run.command("owned", "trusted command")
        run.api.exec = lambda *args: stream([client.SandboxExecOutput("stdout", "ok"), client.SandboxExecExit(0)])
        self.assertEqual(await run.command("owned", "trusted command"), {"exit_code": 0, "output": "ok"})


if __name__ == "__main__":
    unittest.main()
