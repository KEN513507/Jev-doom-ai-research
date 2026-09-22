"""Measure Jev API latency with connection reuse (requests.Session)."""
import os
import statistics
import time

import requests

JEV_API_URL = "https://api.typesafe.ai/v1/systemone"

session = requests.Session()  # ★ 接続を再利用
session.headers.update({
    "Authorization": f"Bearer {os.environ['TYPESAFE_API_KEY']}",
    "Content-Type": "application/json",
})


def build_payload(state_text):
    return {
        "model": "jev-latest",
        "state": state_text,
        "questions": {
            "act": {"type": "choice", "instructions": "Next action.",
                    "criteria": {"fwd": "Forward", "atk": "Attack"}}
        },
    }


def one_call(state_text, timeout=15):
    t0 = time.perf_counter()
    r = session.post(JEV_API_URL, json=build_payload(state_text), timeout=timeout)
    r.raise_for_status()
    return (time.perf_counter() - t0) * 1000


def measure(state_text, n=30):
    latencies = []
    for i in range(n):
        dt = one_call(state_text)
        latencies.append(dt)
        print(f"{i + 1:3d}: {dt:7.1f} ms", flush=True)
    print(f"\nmin={min(latencies):.1f}  median={statistics.median(latencies):.1f}  "
          f"mean={statistics.mean(latencies):.1f}  p95={statistics.quantiles(latencies, n=20)[18]:.1f}  "
          f"max={max(latencies):.1f}")
    return latencies


if __name__ == "__main__":
    state = ("health=100, enemy_visible=true, enemy_distance=400, "
             "ammo=50, wall_ahead=false")
    measure(state)
