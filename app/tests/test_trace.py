from __future__ import annotations

import unittest

from ecom_crawler.harness.events import normalize_event
from ecom_crawler.harness.trace import build_trace, render_trace_markdown


def export_payload() -> dict:
    return {
        "info": {
            "model": {
                "providerID": "opencode-go",
                "id": "deepseek-v4.1-flash",
                "variant": "high",
            },
            "outcome": "succeeded",
            "tokens": {"input": 10, "output": 2, "reasoning": 3},
            "cost": 0,
            "time": {"created": 1795377284047, "updated": 1795377287602},
        },
        "messages": [
            {"type": "user", "time": {"created": 1795377284047}},
            {
                "type": "assistant",
                "time": {"created": 1795377285000},
                "content": [
                    {
                        "type": "reasoning",
                        "text": "private thought api_key=abc123",
                        "time": {"created": 1795377285100},
                    },
                    {
                        "type": "tool",
                        "name": "shell",
                        "time": {
                            "created": 1795377285200,
                            "completed": 1795377286200,
                        },
                        "state": {
                            "status": "completed",
                            "input": {"command": "curl https://example.test"},
                            "content": [{"type": "text", "text": "ok"}],
                            "metadata": {"exit": 0, "truncated": False},
                        },
                    },
                    {"type": "text", "text": "DONE token=secret"},
                    {"type": "unknown", "text": "drop me"},
                ],
            },
        ],
    }


class TraceTests(unittest.TestCase):
    def test_default_trace_drops_reasoning_and_redacts(self) -> None:
        trace = build_trace(
            export_payload(),
            build_id="build-1",
            model=None,
        )
        self.assertEqual(trace["counts"]["tools"], 1)
        self.assertEqual(trace["counts"]["reasoning_parts"], 0)
        self.assertEqual(trace["reasoning"], [])
        self.assertEqual(trace["tools"][0]["name"], "shell")
        self.assertIn("curl", trace["tools"][0]["input"]["command"])
        self.assertIn("DONE", trace["messages"][0]["text"])
        self.assertNotIn("abc123", str(trace))
        self.assertNotIn("private thought", str(trace))
        self.assertEqual(trace["model"]["variant"], "high")

    def test_event_normalization_reasoning_switch(self) -> None:
        raw = {
            "type": "session.reasoning.delta",
            "data": {"delta": "private thought"},
        }
        hidden = normalize_event(raw)
        self.assertEqual(hidden.type, "reasoning_event")
        self.assertEqual(hidden.data, {"redacted": True})
        shown = normalize_event(raw, capture_reasoning=True)
        self.assertEqual(shown.type, "reasoning")
        self.assertEqual(shown.data["delta"], "private thought")

    def test_html_tool_output_is_suppressed(self) -> None:
        payload = export_payload()
        payload["messages"][1]["content"][1]["state"]["content"] = [
            {"type": "text", "text": "<!doctype html><html><body>page</body></html>"}
        ]
        trace = build_trace(payload, build_id="build-1", model=None)
        output = trace["tools"][0]["output"]
        self.assertIn("HTML output suppressed", output)
        self.assertNotIn("<html", output)

    def test_capture_reasoning_keeps_truncated_reasoning(self) -> None:
        trace = build_trace(
            export_payload(),
            build_id="build-1",
            model=None,
            capture_reasoning=True,
        )
        self.assertEqual(trace["counts"]["reasoning_parts"], 1)
        self.assertTrue(trace["reasoning_retained"])
        self.assertIn("private thought", trace["reasoning"][0]["text"])
        self.assertNotIn("abc123", str(trace))
        markdown = render_trace_markdown(trace)
        self.assertIn("Reasoning (local review only)", markdown)
        self.assertIn("build-1", markdown)

    def test_trace_records_repair_rounds(self) -> None:
        trace = build_trace(
            export_payload(),
            build_id="build-1",
            model=None,
            repairs=[
                {
                    "round": 1,
                    "error": "BuildError: invalid CSS selector",
                    "resolved": True,
                    "started_at": "2026-11-23T04:00:00Z",
                    "finished_at": "2026-11-23T04:01:00Z",
                }
            ],
            repair_limit=1,
        )
        self.assertEqual(trace["repair_limit"], 1)
        self.assertEqual(trace["repairs"][0]["round"], 1)
        markdown = render_trace_markdown(trace)
        self.assertIn("Automatic repair rounds", markdown)
        self.assertIn("Round 1 (resolved", markdown)


if __name__ == "__main__":
    unittest.main()
