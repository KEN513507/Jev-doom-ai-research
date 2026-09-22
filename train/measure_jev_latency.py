"""Measure Jev API latency for realistic DOOM states."""
import os
import statistics
import time

import requests

JEV_API_URL = "https://api.typesafe.ai/v1/systemone"


def build_payload(state_text):
    return {
        "model": "jev-latest",
        "state": state_text,
        "questions": {
            "next_action": {
                "type": "choice",
                "instructions": "Choose the best next action.",
                "criteria": {
                    "move_forward": "Advance.",
                    "move_backward": "Retreat.",
                    "turn_left": "Scan left.",
                    "turn_right": "Scan right.",
                    "attack": "Fire.",
                },
            }
        },
    }


def measure(api_key, state_text, n=30):
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    latencies = []
    for i in range(n):
        t0 = time.perf_counter()
        r = requests.post(JEV_API_URL, headers=headers,
                          json=build_payload(state_text), timeout=15)
        r.raise_for_status()
        dt = (time.perf_counter() - t0) * 1000
        latencies.append(dt)
        print(f"{i + 1:3d}: {dt:7.1f} ms", flush=True)
    print(f"\nmin={min(latencies):.1f}  median={statistics.median(latencies):.1f}  "
          f"mean={statistics.mean(latencies):.1f}  p95={statistics.quantiles(latencies, n=20)[18]:.1f}  "
          f"max={max(latencies):.1f}")
    return latencies


if __name__ == "__main__":
    key = os.environ["TYPESAFE_API_KEY"]
    state = ("health=100, enemy_visible=true, enemy_distance=400, "
             "ammo=50, wall_ahead=false")
    measure(key, state)
