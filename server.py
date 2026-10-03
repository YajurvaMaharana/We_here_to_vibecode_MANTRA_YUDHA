"""
NovaMart Sentinel-Governor Local Server
Serves the UI Dashboard and provides REST endpoints for agent execution.
"""

import http.server
import socketserver
import json
import os
import urllib.parse
from core.governor import SentinelGovernor
from tools.registry import ToolRegistry
from tools.db import MOCK_DB

PORT = 8080
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UI_DIR = os.path.join(BASE_DIR, "ui")

tool_registry = ToolRegistry()
governor = SentinelGovernor(tool_registry=tool_registry)


class SentinelRequestHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=UI_DIR, **kwargs)

    def do_GET(self):
        parsed_url = urllib.parse.urlparse(self.path)
        
        if parsed_url.path == "/api/database":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(json.dumps(MOCK_DB, default=str).encode("utf-8"))
            return

        if parsed_url.path == "/api/health":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(json.dumps({"status": "healthy", "service": "Sentinel-Governor"}).encode("utf-8"))
            return

        # Default static file serving
        return super().do_GET()

    def do_POST(self):
        parsed_url = urllib.parse.urlparse(self.path)
        
        if parsed_url.path == "/api/chat":
            content_length = int(self.headers.get("Content-Length", 0))
            post_data = self.rfile.read(content_length)
            
            try:
                payload = json.loads(post_data.decode("utf-8"))
                message = payload.get("message", "")
                customer_id = payload.get("customer_id", "CUST-9812")
                session_id = payload.get("session_id")
                
                result = governor.process_turn(
                    raw_customer_message=message,
                    customer_id=customer_id,
                    session_id=session_id
                )
                
                response_data = {
                    "decision": result.decision,
                    "customer_response": result.customer_response,
                    "audit_trail": result.audit_trail,
                    "steps_trace": result.steps_trace
                }
                
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(json.dumps(response_data, default=str).encode("utf-8"))
            except Exception as e:
                self.send_response(500)
                self.send_header("Content-Type", "application/json")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(json.dumps({"error": str(e)}).encode("utf-8"))
            return

        self.send_response(404)
        self.end_headers()

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()


def run_server():
    print(f"Starting Sentinel-Governor Server on http://localhost:{PORT}")
    with socketserver.TCPServer(("", PORT), SentinelRequestHandler) as httpd:
        httpd.serve_forever()


if __name__ == "__main__":
    run_server()
