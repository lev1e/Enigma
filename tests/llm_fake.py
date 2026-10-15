"""Fake local provider server for the AI chat tests. Speaks the five wire protocols, records every request
(path, headers, body) and can stream a scripted answer in chosen chunks. Test key is a made-up string."""
from __future__ import annotations

import http.server
import json
import threading

TEST_KEY = "test-key-NOT-REAL-0000000000"


class FakeProvider:
    def __init__(self, chunks=None, status=200, usage=(7, 3), models=("m-one", "m-two"), finish=None, tail_error=False):
        self.chunks = list(chunks if chunks is not None else ["Hello ", "world"])
        self.status = status
        self.usage = usage
        self.models = list(models)
        self.finish = finish
        self.tail_error = tail_error
        self.requests: list[dict] = []
        self.reply = None                      # optional callable(body: dict) -> list[str] chunks
        owner = self

        class Handler(http.server.BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.0"

            def log_message(self, *args):
                pass

            def _record(self):
                length = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(length) if length else b""
                owner.requests.append({"path": self.path, "headers": {k.lower(): v for k, v in self.headers.items()},
                                       "raw": raw, "body": json.loads(raw) if raw else None})
                return owner.requests[-1]

            def do_GET(self):
                self._record()
                if owner.status != 200:
                    return self._fail()
                if self.path.startswith("/v1beta/models"):
                    payload = {"models": [{"name": "models/" + m} for m in owner.models]}
                else:
                    payload = {"data": [{"id": m} for m in owner.models]}
                self._json(payload)

            def _json(self, payload, code=200):
                data = json.dumps(payload).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def _fail(self):
                self._json({"error": {"message": "boom with key " + TEST_KEY}}, owner.status)

            def do_POST(self):
                req = self._record()
                if owner.status != 200:
                    return self._fail()
                body = req["body"]
                chunks = owner.reply(body) if owner.reply else owner.chunks
                path = self.path
                stream = bool(body.get("stream")) or "streamGenerateContent" in path
                kind = ("anthropic" if path.startswith("/v1/messages") else
                        "gemini" if "/v1beta/models/" in path else "openai")
                if not stream:
                    return self._json(self._whole(kind, "".join(chunks)))
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.end_headers()
                try:
                    self._stream(kind, chunks)
                except (BrokenPipeError, ConnectionResetError):
                    pass

            def _whole(self, kind, text):
                i, o = owner.usage
                if kind == "anthropic":
                    return {"content": [{"type": "text", "text": text}], "usage": {"input_tokens": i, "output_tokens": o},
                            "stop_reason": "end_turn"}
                if kind == "gemini":
                    return {"candidates": [{"content": {"parts": [{"text": text}]}, "finishReason": owner.finish or "STOP"}],
                            "usageMetadata": {"promptTokenCount": i, "candidatesTokenCount": o}}
                return {"choices": [{"message": {"content": text}, "finish_reason": owner.finish or "stop"}],
                        "usage": {"prompt_tokens": i, "completion_tokens": o}}

            def _send(self, event, data):
                line = (f"event: {event}\n" if event else "") + "data: " + (data if isinstance(data, str) else json.dumps(data)) + "\n\n"
                self.wfile.write(line.encode())
                self.wfile.flush()

            def _stream(self, kind, chunks):
                i, o = owner.usage
                if kind == "anthropic":
                    self._send("message_start", {"type": "message_start", "message": {"usage": {"input_tokens": i}}})
                    for c in chunks:
                        self._send("content_block_delta", {"type": "content_block_delta", "delta": {"type": "text_delta", "text": c}})
                    if owner.tail_error:
                        return self._send("error", {"type": "error", "error": {"message": "overloaded"}})
                    self._send("message_delta", {"type": "message_delta", "delta": {"stop_reason": owner.finish or "end_turn"},
                                                 "usage": {"output_tokens": o}})
                elif kind == "gemini":
                    for c in chunks:
                        self._send("", {"candidates": [{"content": {"parts": [{"text": c}]}}]})
                    self._send("", {"candidates": [{"content": {"parts": [{"text": ""}]}, "finishReason": owner.finish or "STOP"}],
                                    "usageMetadata": {"promptTokenCount": i, "candidatesTokenCount": o}})
                else:
                    for c in chunks:
                        self._send("", {"choices": [{"delta": {"content": c}}]})
                    self._send("", {"choices": [{"delta": {}, "finish_reason": owner.finish or "stop"}]})
                    self._send("", {"choices": [], "usage": {"prompt_tokens": i, "completion_tokens": o}})
                    self._send("", "[DONE]")

        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        self.thread = threading.Thread(target=lambda: self.server.serve_forever(poll_interval=0.02), daemon=True)

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *exc):
        self.server.shutdown()
        self.server.server_close()

    def bodies(self) -> list[bytes]:
        return [r["raw"] for r in self.requests if r["raw"]]
