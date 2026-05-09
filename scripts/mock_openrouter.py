"""Minimal OpenRouter-compatible mock for structured OCR validation."""

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        if self.path != "/api/v1/chat/completions":
            self.send_response(404)
            self.end_headers()
            return

        length = int(self.headers.get("content-length", "0"))
        if length:
            self.rfile.read(length)

        structured = {
            "title": "Mock OpenRouter Invoice",
            "originalNumber": "MOCK-001",
            "inputCostType": "1. invoice",
            "issueDate": None,
            "paymentDate": None,
            "vendorName": "Mock Vendor",
            "paymentMethod": None,
            "description": "Validated by local OpenRouter-compatible mock",
            "totalAmount": 1234,
            "taxes": [],
            "inputCostItems": [],
        }
        payload = {
            "id": "mock-chatcmpl",
            "object": "chat.completion",
            "choices": [
                {
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": json.dumps(structured),
                    },
                    "finish_reason": "stop",
                }
            ],
        }
        body = json.dumps(payload).encode("utf-8")
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        return


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", 8081), Handler).serve_forever()
