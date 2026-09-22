"""Tests for overlay status output (train/jev_agent.py) and parsing (tools/overlay.py)."""
import importlib.util
import os
import tempfile
import unittest
from pathlib import Path

from train.jev_agent import format_status, write_status

_spec = importlib.util.spec_from_file_location(
    "overlay", Path(__file__).parent.parent / "tools" / "overlay.py"
)
overlay_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(overlay_mod)
parse_line = overlay_mod.parse_line


def _info(state_text="var0=100 enemy_centered=no, enemy_side=left, front_blocked=no"):
    return {"state_text": state_text, "enemy_visible": True, "red_mean": 63.4}


class TestFormatStatus(unittest.TestCase):
    def test_all_layers_present(self):
        lines = format_status(jev_line="Jev -> turn_left", reason="Rotate", sys1_events=[],
                              order="Open the door ahead.", health=100, info=_info(), tic=120)
        tags = [line.split("|", 1)[0] for line in lines]
        self.assertEqual(set(tags), {"SYS1", "SYS2", "SYS3", "GAME"})
        self.assertIn("SYS2|Jev -> turn_left", lines)
        self.assertIn("SYS1|(no reflex)", lines)
        self.assertIn("SYS3|Commander: Open the door ahead.", lines)
        self.assertIn("GAME|HP=100 Enemy=yes Centered=no Side=left Blocked=no", lines)
        self.assertIn("GAME|red_mean=63.4 tic=120", lines)

    def test_sys1_events_and_no_order(self):
        lines = format_status(jev_line="(bypassed by System 1)", reason="",
                              sys1_events=["force_attack (width=22)", "WallAvoider: move_forward -> use"],
                              order=None, health=80, info=_info(), tic=8)
        self.assertIn("SYS1|force_attack (width=22)", lines)
        self.assertIn("SYS1|WallAvoider: move_forward -> use", lines)
        self.assertIn("SYS3|(no active order)", lines)
        self.assertFalse(any(line.startswith("SYS2|Reason") for line in lines))

    def test_missing_info_after_api_failure(self):
        lines = format_status(jev_line="[skip] timeout", reason="", sys1_events=[],
                              order=None, health=50, info=None, tic=4)
        self.assertIn("GAME|HP=50 Enemy=no Centered=- Side=- Blocked=-", lines)
        self.assertIn("GAME|tic=4", lines)


class TestWriteStatus(unittest.TestCase):
    def test_atomic_write_leaves_no_tmp(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "status.txt")
            write_status(["SYS2|Jev -> attack", "GAME|tic=4"], path=path)
            self.assertEqual(Path(path).read_text(), "SYS2|Jev -> attack\nGAME|tic=4\n")
            self.assertFalse(os.path.exists(path + ".tmp"))


class TestParseLine(unittest.TestCase):
    def test_known_tag(self):
        self.assertEqual(parse_line("SYS3|Commander: turn\n"), ("SYS3", "Commander: turn"))

    def test_trailing_n_is_kept(self):
        # 旧版の rstrip("\\n") は末尾の 'n' を削っていた
        self.assertEqual(parse_line("SYS2|Jev -> turn_right")[1], "Jev -> turn_right")

    def test_unknown_or_untagged_is_meta(self):
        self.assertEqual(parse_line("FOO|x"), ("META", "FOO|x"))
        self.assertEqual(parse_line("plain"), ("META", "plain"))


if __name__ == "__main__":
    unittest.main()
