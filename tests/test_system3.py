"""System 3（train/system3_core.py）とトリガー検出のテスト。ネットワークには接続しない。"""
import os
import sys
import time
import types
import unittest
from unittest import mock

sys.modules.setdefault("vizdoom", types.ModuleType("vizdoom"))

from train.jev_agent import BASE_INSTRUCTIONS, build_payload
from train.state_utils import AreaStagnationDetector, extract_key_events
from train.system3_core import (
    MIN_CALL_INTERVAL_SEC,
    ORDER_TTL_SEC,
    TRIGGER_FRONT_BLOCKED,
    TRIGGER_KEY_EVENT,
    StrategicCoreSystem3,
    local_order,
)


class FakeClock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


class FakeClient:
    def __init__(self, text=None, error=None):
        self.requests = []
        self.models = types.SimpleNamespace(generate_content=self._generate)
        self._text = text
        self._error = error

    def _generate(self, **kwargs):
        self.requests.append(kwargs)
        if self._error:
            raise self._error
        return types.SimpleNamespace(text=self._text)


def _dummy_core(clock=time.monotonic):
    with mock.patch.dict(os.environ, {"GEMINI_API_KEY": ""}):
        return StrategicCoreSystem3(clock=clock)


class TestSystem3DummyMode(unittest.TestCase):
    def setUp(self):
        self.clock = FakeClock()
        self.core = _dummy_core(self.clock)

    def test_no_api_key_means_dummy_mode(self):
        self.assertIsNone(self.core.client)

    def test_dormant_without_triggers(self):
        self.core.update_state({"health": 100})
        self.assertFalse(self.core.step())
        self.assertIsNone(self.core.get_current_instruction())

    def test_front_blocked_issues_local_order(self):
        self.core.update_state({"front_blocked": True}, [TRIGGER_FRONT_BLOCKED])
        self.assertTrue(self.core.step())
        self.assertIn("turn", self.core.get_current_instruction())

    def test_order_expires_after_ttl(self):
        self.core.update_state({"front_blocked": True}, [TRIGGER_FRONT_BLOCKED])
        self.core.step()
        self.clock.t += ORDER_TTL_SEC + 0.1
        self.assertIsNone(self.core.get_current_instruction())

    def test_min_call_interval(self):
        self.core.update_state({}, [TRIGGER_FRONT_BLOCKED])
        self.assertTrue(self.core.step())
        self.core.update_state({}, [TRIGGER_FRONT_BLOCKED])
        self.clock.t += MIN_CALL_INTERVAL_SEC / 2
        self.assertFalse(self.core.step())
        self.clock.t += MIN_CALL_INTERVAL_SEC
        self.assertTrue(self.core.step())

    def test_key_event_order_mentions_message(self):
        self.core.update_state({"key_events": ["Blue passcard secured!"]}, [TRIGGER_KEY_EVENT])
        self.core.step()
        self.assertIn("Blue passcard secured!", self.core.get_current_instruction())

    def test_background_thread_issues_order(self):
        core = _dummy_core()
        core.start()
        try:
            core.update_state({"front_blocked": True}, [TRIGGER_FRONT_BLOCKED])
            deadline = time.monotonic() + 2.0
            while core.get_current_instruction() is None and time.monotonic() < deadline:
                time.sleep(0.05)
            self.assertIsNotNone(core.get_current_instruction())
        finally:
            core.stop()


class TestSystem3GeminiPath(unittest.TestCase):
    def setUp(self):
        self.clock = FakeClock()
        self.core = _dummy_core(self.clock)

    def test_uses_macro_goal_from_gemini(self):
        self.core.client = FakeClient(text='{"macro_goal": "Open the door ahead."}')
        self.core.update_state({"front_blocked": True}, [TRIGGER_FRONT_BLOCKED])
        self.core.step()
        self.assertEqual(self.core.get_current_instruction(), "Open the door ahead.")
        self.assertIn('"triggers": ["front_blocked"]', self.core.client.requests[0]["contents"])

    def test_falls_back_to_local_rule_on_error(self):
        self.core.client = FakeClient(error=RuntimeError("503"))
        state = {"front_blocked": True}
        self.core.update_state(state, [TRIGGER_FRONT_BLOCKED])
        self.core.step()
        self.assertEqual(
            self.core.get_current_instruction(), local_order([TRIGGER_FRONT_BLOCKED], state)
        )

    def test_falls_back_when_macro_goal_missing(self):
        self.core.client = FakeClient(text='{"decision": "use"}')
        self.core.update_state({}, [TRIGGER_FRONT_BLOCKED])
        self.core.step()
        self.assertEqual(self.core.get_current_instruction(), local_order([TRIGGER_FRONT_BLOCKED], {}))


class TestTriggerDetection(unittest.TestCase):
    def test_stagnation_fires_when_window_stays_in_radius(self):
        det = AreaStagnationDetector(window=5, radius=10.0)
        results = [det.update((i % 2 * 3.0, 0.0)) for i in range(5)]
        self.assertEqual(results, [False, False, False, False, True])
        self.assertFalse(det.update((0.0, 0.0)))  # 発火後は窓を貯め直す

    def test_no_stagnation_while_travelling(self):
        det = AreaStagnationDetector(window=5, radius=10.0)
        self.assertFalse(any(det.update((29.0 * i, 0.0)) for i in range(10)))

    def test_extract_key_events(self):
        self.assertEqual(extract_key_events("Blue passcard secured!\n"), ["Blue passcard secured!"])
        self.assertEqual(extract_key_events("Picked up a health bonus.\n"), [])
        self.assertEqual(extract_key_events("\n\x1c+map01 - Hydroelectric Plant\n\n"), [])
        self.assertEqual(extract_key_events(None), [])


class TestPayloadOrder(unittest.TestCase):
    def test_order_goes_to_instructions_not_criteria(self):
        plain = build_payload("x")["questions"]["next_action"]
        ordered = build_payload("x", order="Turn around.")["questions"]["next_action"]
        self.assertEqual(plain["instructions"], BASE_INSTRUCTIONS)
        self.assertTrue(ordered["instructions"].startswith(BASE_INSTRUCTIONS))
        self.assertIn("Turn around.", ordered["instructions"])
        self.assertEqual(plain["criteria"], ordered["criteria"])


if __name__ == "__main__":
    unittest.main()
