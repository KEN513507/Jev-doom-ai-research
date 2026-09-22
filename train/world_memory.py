"""WorldMemory: 空間トポロジーの記憶層

System 3（Gemini）と Jev に「過去の文脈」を提供する。
"""
import re
from collections import deque
from dataclasses import dataclass, field

try:
    from train.state_utils import extract_key_events
except ImportError:  # python train/jev_agent.py 直接実行時
    from state_utils import extract_key_events


@dataclass
class KeyEvent:
    color: str
    tic: int


@dataclass
class DoorEvent:
    x: float
    y: float
    color: str  # "blue"/"red"/"yellow"/"none"
    tic: int


class WorldMemory:
    """エピソード内の空間記憶"""
    
    GRID_SIZE = 128
    
    def __init__(self, max_history=200):
        self.visited_cells = set()
        self.path_history = deque(maxlen=max_history)
        self.keys_obtained = []
        self.doors_seen = []
        self.stuck_events = []
        self.start_position = None
        self.max_distance = 0.0
        self.last_position = None
        self.dead_ends = set()  # 行き止まりセル
    
    def update(self, position, tic, notifications="", front_blocked=False):
        """毎判断フレームで呼ぶ"""
        if position is None or position[0] is None:
            return
        x, y = position
        
        if self.start_position is None:
            self.start_position = (x, y)
        
        # 訪問セル
        cell = (int(x) // self.GRID_SIZE, int(y) // self.GRID_SIZE)
        self.visited_cells.add(cell)
        self.path_history.append((x, y, tic))
        self.last_position = (x, y)
        
        # スタートからの最大距離
        if self.start_position:
            d = ((x - self.start_position[0])**2 + (y - self.start_position[1])**2) ** 0.5
            self.max_distance = max(self.max_distance, d)
        
        # 鍵イベント
        if notifications:
            self._extract_keys(notifications, tic)
        
        # 行き止まり記録（スタック時）
        if front_blocked:
            self.stuck_events.append((x, y, tic))
            if len([e for e in self.stuck_events if e[0] == x and e[1] == y]) >= 3:
                self.dead_ends.add(cell)
    
    def _extract_keys(self, notifications, tic):
        """取得通知（picked up / you got / secured）の行だけから鍵色を拾う"""
        colors = ["blue", "red", "yellow"]
        for line in extract_key_events(notifications):
            words = re.findall(r"[a-z]+", line.lower())  # 単語一致（"secured" 内の "red" を拾わない）
            for c in colors:
                if c in words and not any(k.color == c for k in self.keys_obtained):
                    self.keys_obtained.append(KeyEvent(color=c, tic=tic))
    
    def get_summary(self) -> str:
        """Jev/System3 に渡す要約"""
        keys = ",".join(k.color for k in self.keys_obtained) or "none"
        return (
            f"visited={len(self.visited_cells)}cells, "
            f"keys={keys}, "
            f"max_dist={self.max_distance:.0f}, "
            f"dead_ends={len(self.dead_ends)}"
        )
    
    def is_dead_end(self, position) -> bool:
        if position is None or position[0] is None:
            return False
        cell = (int(position[0]) // self.GRID_SIZE, int(position[1]) // self.GRID_SIZE)
        return cell in self.dead_ends
    
    def reset(self):
        self.visited_cells.clear()
        self.path_history.clear()
        self.keys_obtained.clear()
        self.doors_seen.clear()
        self.stuck_events.clear()
        self.dead_ends.clear()
        self.start_position = None
        self.max_distance = 0.0
