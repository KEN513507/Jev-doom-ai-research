"""Jev API connection test.

Reads TYPESAFE_API_KEY from environment only (never hardcode).
"""
import os
import sys

import requests

JEV_API_URL = "https://api.typesafe.ai/v1/systemone"


def main() -> int:
    api_key = os.environ.get("TYPESAFE_API_KEY")
    if not api_key:
        raise EnvironmentError("TYPESAFE_API_KEY is not set")

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": "jev-latest",
        "state": "The agent is at full health (100), facing a single enemy at medium range.",
        "questions": {
            "next_action": {
                "type": "choice",
                "instructions": "Which action should the agent take next?",
                "criteria": {
                    "attack": "Fire at the visible enemy.",
                    "take_cover": "Hide to avoid incoming damage.",
                    "move_closer": "Advance toward the enemy.",
                    "retreat": "Fall back to a safer position.",
                },
            }
        },
    }

    try:
        response = requests.post(JEV_API_URL, headers=headers, json=payload, timeout=10)
        response.raise_for_status()
        print("API Response:")
        print(response.json())
        return 0
    except requests.exceptions.RequestException as e:
        print(f"Error calling Jev API: {e}")
        if getattr(e, "response", None) is not None:
            print(f"Status Code: {e.response.status_code}")
            print(f"Response Body: {e.response.text}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
