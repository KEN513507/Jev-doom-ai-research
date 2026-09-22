"""赤強度のキャリブレーション（state_utils と定義を共用）。"""
import vizdoom as vzd
import numpy as np

try:
    from train.state_utils import compute_red_metrics, USE_RESOLUTION, ACTIVE_REGION
except ImportError:
    from state_utils import compute_red_metrics, USE_RESOLUTION, ACTIVE_REGION

g = vzd.DoomGame()
g.load_config(f"{vzd.scenarios_path}/deadly_corridor.cfg")

# 解像度を state_utils と揃える
if USE_RESOLUTION == "RES_160X120":
    g.set_screen_resolution(vzd.ScreenResolution.RES_160X120)
else:
    g.set_screen_resolution(vzd.ScreenResolution.RES_320X240)

g.set_window_visible(False)
g.init()

print(f"Resolution: {USE_RESOLUTION}, Region: {ACTIVE_REGION}")

for ep in range(3):
    g.new_episode()
    reds = []
    while not g.is_episode_finished():
        s = g.get_state()
        if s is None:
            break
        red_mean, _ = compute_red_metrics(s.screen_buffer)
        reds.append(red_mean)
        g.make_action([0, 0, 0, 0, 1, 0, 0])  # 前進のみ
    reds = np.array(reds)
    print(f"Episode {ep}: n={len(reds)} "
          f"min={reds.min():.1f}, median={np.median(reds):.1f}, max={reds.max():.1f}")

g.close()
