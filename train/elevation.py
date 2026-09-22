"""Elevation: Z軸（高低差）の認識と待機処理"""
from collections import deque


class ElevationTracker:
    """Z座標の変化を監視し、リフト/段差を検出する"""
    
    def __init__(self, window=8):
        self.window = window
        self.z_history = deque(maxlen=window)
        self.last_z = None
        self.elevation_changing = False
        self.stationary_tic = 0
    
    def update(self, position_z):
        """Returns: True if elevation is changing (lift/stairs in progress)"""
        if position_z is None:
            return False
        
        self.z_history.append(position_z)
        
        # 直近window内のZ変化量
        if len(self.z_history) >= 3:
            z_min = min(self.z_history)
            z_max = max(self.z_history)
            delta = z_max - z_min
            # 8 units（0.5m）以上の変化 = リフト/段差
            self.elevation_changing = delta > 8.0
        else:
            self.elevation_changing = False
        
        # 静止判定（Zが変わらない）
        if self.last_z is not None and abs(position_z - self.last_z) < 1.0:
            self.stationary_tic += 1
        else:
            self.stationary_tic = 0
        self.last_z = position_z
        
        return self.elevation_changing
    
    def reset(self):
        self.z_history.clear()
        self.last_z = None
        self.elevation_changing = False
        self.stationary_tic = 0


class DoorWaiter:
    """ドア opening 待機用
    
    use を押した後、ドアが開き切るまで（約30tic）待つ。
    """
    
    def __init__(self, wait_tic=30):
        self.wait_remaining = 0
        self.total_wait = wait_tic
    
    def start(self):
        self.wait_remaining = self.total_wait
    
    def tick(self, frame_skip=4) -> bool:
        """Returns: True if still waiting (should not act)"""
        if self.wait_remaining <= 0:
            return False
        self.wait_remaining -= frame_skip
        return True
    
    def is_waiting(self) -> bool:
        return self.wait_remaining > 0
    
    def reset(self):
        self.wait_remaining = 0
