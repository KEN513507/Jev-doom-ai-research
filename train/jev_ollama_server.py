"""Jev-compatible decision server backed by local Ollama.

Exposes POST /v1/systemone with the same interface as the TypeSafe AI
cloud API, so train/jev_agent.py works unchanged apart from the URL.

    OLLAMA_URL=http://127.0.0.1:11434 OLLAMA_MODEL=qwen2.5:1.5b \
        python train/jev_ollama_server.py [--port 8081]

Only stdlib is used (http.server + urllib). No API keys needed locally.
"""
import argparse
import json
import os
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "qwen2.5:1.5b")
OLLAMA_TIMEOUT = float(os.environ.get("OLLAMA_TIMEOUT", "120"))


def build_choice_prompt(state, instructions, criteria):
    """Build a JSON-only decision prompt for a choice question."""
    options = "\n".join(f'- "{k}": {v}' for k, v in criteria.items())
    keys = ", ".join(f'"{k}"' for k in criteria)
    return (
        f"Game state: {state}\n"
        f"Task: {instructions}\n"
        f"Options:\n{options}\n"
        f"Reply with JSON only, no other text, in exactly this shape:\n"
        f'{{"choice": <one of {keys}>, '
        f'"confidence": <0.0-1.0>, '
        f'"probabilities": {{<each option key>: <probability>}}}}'
    )


def extract_json_object(text):
    """Return the first JSON object found in text, or None."""
    decoder = json.JSONDecoder()
    idx = text.find("{")
    while idx != -1:
        try:
            obj, _ = decoder.raw_decode(text[idx:])
            if isinstance(obj, dict):
                return obj
        except json.JSONDecodeError:
            pass
        idx = text.find("{", idx + 1)
    return None


def normalize_probs(raw, keys):
    """Coerce a raw probabilities mapping to a distribution over keys."""
    probs = {}
    total = 0.0
    for k in keys:
        try:
            v = float((raw or {}).get(k, 0.0))
        except (TypeError, ValueError):
            v = 0.0
        v = max(0.0, v)
        probs[k] = v
        total += v
    if total <= 0:
        return None
    return {k: v / total for k, v in probs.items()}


def decide_choice(state, instructions, criteria):
    """Ask Ollama for a choice decision. Returns (choice, confidence, probs)."""
    keys = list(criteria)
    payload = json.dumps({
        "model": OLLAMA_MODEL,
        "prompt": build_choice_prompt(state, instructions, criteria),
        "stream": False,
    }).encode()
    req = urllib.request.Request(
        f"{OLLAMA_URL}/api/generate", data=payload,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=OLLAMA_TIMEOUT) as resp:
        body = json.load(resp)
    obj = extract_json_object(body.get("response", "")) or {}

    probs = normalize_probs(obj.get("probabilities"), keys)
    choice = obj.get("choice")
    if choice not in keys:
        # Fall back to the highest-probability option, else the first key.
        choice = max(probs, key=probs.get) if probs else keys[0]
    if not probs:
        # Model gave a choice but no usable distribution: confident fallback.
        share = (1.0 - 0.9) / max(len(keys) - 1, 1)
        probs = {k: (0.9 if k == choice else share) for k in keys}
    try:
        confidence = float(obj.get("confidence", max(probs.values())))
    except (TypeError, ValueError):
        confidence = max(probs.values())
    confidence = min(1.0, max(0.0, confidence))
    return choice, confidence, probs


class Handler(BaseHTTPRequestHandler):
    server_version = "JevOllama/1.0"

    def log_message(self, *args):
        pass  # keep game logs clean; use print below sparingly

    def _send(self, code, obj):
        data = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self):
        if self.path != "/v1/systemone":
            return self._send(404, {"detail": "not found"})
        try:
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length) or b"{}")
        except (ValueError, OSError):
            return self._send(400, {"detail": "invalid JSON"})
        questions = body.get("questions")
        if not isinstance(questions, dict) or not questions:
            return self._send(400, {"detail": "questions must be a non-empty map"})
        state = body.get("state", "")
        answers = {}
        try:
            for qid, q in questions.items():
                if not isinstance(q, dict) or q.get("type") != "choice":
                    return self._send(400, {"detail": f"question {qid!r}: only type=choice is supported"})
                criteria = q.get("criteria")
                if not isinstance(criteria, dict) or len(criteria) < 2:
                    return self._send(400, {"detail": f"question {qid!r}: criteria needs >=2 options"})
                choice, confidence, probs = decide_choice(
                    state, q.get("instructions", "Choose one."), criteria
                )
                answers[qid] = {
                    "type": "choice",
                    "choice": choice,
                    "confidence": confidence,
                    "probabilities": probs,
                }
        except Exception as e:  # noqa: BLE001 - report backend errors as 502
            return self._send(502, {"detail": f"ollama backend error: {e}"})
        return self._send(200, {"model": OLLAMA_MODEL, "answers": answers})


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", "8081")))
    args = parser.parse_args()
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print(f"jev_ollama_server on http://127.0.0.1:{args.port}/v1/systemone "
          f"(ollama={OLLAMA_URL}, model={OLLAMA_MODEL})", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
