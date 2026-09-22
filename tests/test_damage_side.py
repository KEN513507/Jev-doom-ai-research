"""被弾方向（damage_side、案B）のテスト。角度は Doom の規約（0=東、反時計回りが正）。"""
import sys
import types
import unittest

sys.modules.setdefault("vizdoom", types.ModuleType("vizdoom"))

from train.jev_agent import state_to_text  # noqa: E402
from train.state_utils import damage_side  # noqa: E402


def _obj(x, y, category="Monster"):
    return types.SimpleNamespace(position_x=x, position_y=y, category=category)


class TestDamageSide(unittest.TestCase):
    def test_four_directions_facing_east(self):
        me = (0.0, 0.0)
        self.assertEqual(damage_side([_obj(100, 10)], me, 0.0), "front")
        self.assertEqual(damage_side([_obj(0, 100)], me, 0.0), "left")    # 北 = 左
        self.assertEqual(damage_side([_obj(0, -100)], me, 0.0), "right")  # 南 = 右
        self.assertEqual(damage_side([_obj(-100, 0)], me, 0.0), "behind")

    def test_uses_player_angle(self):
        # 北（90°）を向いていれば、西の敵は左、東の敵は右
        me = (0.0, 0.0)
        self.assertEqual(damage_side([_obj(-100, 0)], me, 90.0), "left")
        self.assertEqual(damage_side([_obj(100, 0)], me, 90.0), "right")
        # 角度の折り返し（350° 向きで 10° 方向の敵は正面）
        self.assertEqual(damage_side([_obj(100, 17)], me, 350.0), "front")

    def test_nearest_living_monster_only(self):
        me = (0.0, 0.0)
        objs = [
            _obj(10, 0, category="Gore"),        # 倒した敵（死体）は除外
            _obj(20, 0, category="Self"),        # 自分
            _obj(0, 50),                         # 最も近い生きている敵 → 左
            _obj(-500, 0),                       # 遠い敵
        ]
        self.assertEqual(damage_side(objs, me, 0.0), "left")

    def test_no_monsters(self):
        self.assertEqual(damage_side([_obj(10, 0, category="Gore")], (0.0, 0.0), 0.0), "unknown")
        self.assertEqual(damage_side(None, (0.0, 0.0), 0.0), "unknown")


class TestStateTextField(unittest.TestCase):
    def test_field_only_when_requested(self):
        text, _, _ = state_to_text(None, [100], took_damage=True, damage_dir="behind")
        self.assertIn("took_damage=yes, damage_side=behind", text)
        text, _, _ = state_to_text(None, [100], took_damage=False, damage_dir="behind")
        self.assertIn("damage_side=none", text)
        text, _, _ = state_to_text(None, [100], took_damage=True)
        self.assertNotIn("damage_side", text)


if __name__ == "__main__":
    unittest.main()
