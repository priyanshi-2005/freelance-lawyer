"""Run the local browser prototype with python3 app.py --offline."""

import argparse
import base64
import binascii
from copy import deepcopy
from http import HTTPStatus
from http.cookies import CookieError, SimpleCookie
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
from pathlib import Path
from secrets import token_urlsafe
import time
from urllib.parse import quote

from case_documents import MAX_FILE_BYTES
from intake import Conversation, WELCOME
from model import DEFAULT_MODEL, LocalModel

UI = Path(__file__).with_name("chat.html")
SESSION_TIMEOUT = 3600


class Handler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass

    def send_body(self, status, content, media_type, session=None, filename=None):
        self.send_response(status)
        self.send_header("Content-Type", media_type + ("; charset=utf-8" if filename is None else ""))
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", "frame-ancestors 'none'; base-uri 'none'")
        if session is not None:
            self.send_header("Set-Cookie", f"case={session}; Path=/; HttpOnly; SameSite=Strict")
        if filename is not None:
            self.send_header("Content-Disposition", "attachment; filename*=UTF-8''" + quote(filename, safe=""))
        self.end_headers()
        self.wfile.write(content)

    def send_json(self, status, body, session=None):
        self.send_body(status, json.dumps(body).encode(), "application/json", session)

    def allowed_origin(self):
        host = self.server.origin.removeprefix("http://")
        return self.headers.get("Host") == host and self.headers.get("Origin", self.server.origin) == self.server.origin

    def do_GET(self):
        if not self.allowed_origin():
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        if self.path == "/":
            self.send_body(HTTPStatus.OK, UI.read_bytes(), "text/html")
            return
        if self.path == "/case.pdf" or self.path.startswith("/files/"):
            session = self.read_session()
            if session in self.server.sessions:
                case, _, used = self.server.sessions[session]
                if time.monotonic() - used <= SESSION_TIMEOUT:
                    if self.path == "/case.pdf":
                        details = case.case_text()
                        file = case.build_pdf("Case file", details) if details else None
                    else:
                        file = case.find_attachment(self.path.removeprefix("/files/"))
                    if file is not None:
                        self.send_body(HTTPStatus.OK, file.content, file.media_type, filename=file.name)
                        return
        self.send_error(HTTPStatus.NOT_FOUND)

    def read_session(self):
        cookie = SimpleCookie()
        try:
            cookie.load(self.headers.get("Cookie", ""))
        except CookieError:
            return None
        return cookie["case"].value if "case" in cookie else None

    def do_POST(self):
        if self.path != "/chat" or not self.allowed_origin():
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        try:
            size = int(self.headers.get("Content-Length", "0"))
            if not 0 < size <= (MAX_FILE_BYTES * 4 // 3 + 12000) or self.headers.get_content_type() != "application/json":
                raise ValueError
            payload = json.loads(self.rfile.read(size))
            action = payload.get("action") if isinstance(payload, dict) else None
            if action not in ("message", "open", "reset", "legal", "draft", "choose", "upload"):
                raise ValueError
            upload = payload.get("attachment") if action == "message" else None
            if action == "upload":
                upload = payload
            if upload is None and size > 12000:
                raise ValueError
            if action == "message":
                raw = payload.get("message")
                message = " ".join(raw.split()) if isinstance(raw, str) else ""
                if len(message) > 2500 or (not message and upload is None):
                    raise ValueError
            if action == "choose" and not isinstance(payload.get("choice"), str):
                raise ValueError
            if upload is not None:
                if not isinstance(upload, dict) or not all(isinstance(upload.get(key), str) for key in ("name", "purpose", "content")):
                    raise ValueError
                content = base64.b64decode(upload["content"], validate=True)
        except (ValueError, UnicodeError, binascii.Error):
            self.send_json(HTTPStatus.BAD_REQUEST, {"error": "Send a message up to 2,500 characters or a PDF, PNG, or JPG up to 5 MB."})
            return

        now = time.monotonic()
        sessions = self.server.sessions
        for expired in [key for key, (_, _, used) in sessions.items() if now - used > SESSION_TIMEOUT]:
            del sessions[expired]
        session = self.read_session()
        if action == "reset" and session in sessions:
            del sessions[session]
        if session not in sessions:
            session = token_urlsafe(24)
            sessions[session] = (Conversation(), [], now)
        case, transcript, _ = sessions[session]
        sessions[session] = (case, transcript, now)

        body = {}
        attachment = None
        if action == "message":
            if upload is not None:
                case = deepcopy(case)
                try:
                    attachment = case.attach(upload["name"], content, upload["purpose"])
                except ValueError as error:
                    self.send_json(HTTPStatus.BAD_REQUEST, {"error": str(error)}, session)
                    return
            try:
                body = case.respond(message, self.server.model, attachment=attachment) if message else case.describe_upload(attachment)
            except (RuntimeError, ValueError):
                self.send_json(HTTPStatus.SERVICE_UNAVAILABLE, {
                    "error": "The local model couldn’t process that message. Please try again."
                }, session)
                return
        elif action == "draft":
            body["draft"], body["reply"] = case.draft()
        elif action == "choose":
            body = case.choose(payload["choice"])
        elif action == "upload":
            try:
                body = case.upload(payload["name"], content, payload["purpose"])
            except ValueError as error:
                self.send_json(HTTPStatus.BAD_REQUEST, {"error": str(error)}, session)
                return
        elif action == "legal":
            body = case.legal()
        else:
            body["reply"] = WELCOME
        body["case"] = case.view()
        body["payment_flow"] = case.payment is not None and case.fraud is None
        if body.get("draft"):
            title = body.get("draft_title") or ("Payment demand draft" if body["payment_flow"] else "Case file")
            body["download"] = case.save_pdf(title, body["draft"])
        if action == "open":
            body["transcript"] = transcript
        elif action != "reset":
            user_text = message if action == "message" else payload.get("message")
            if action == "upload":
                user_text = ("Form: " if payload["purpose"] == "form" else "Evidence: ") + payload["name"]
            entry = {key: body[key] for key in ("reply", "sources", "source", "choices", "download") if key in body}
            if isinstance(user_text, str):
                entry["user"] = user_text
            if attachment is not None:
                label = ("Form: " if attachment.purpose == "form" else "Evidence: ") + attachment.name
                body["attachment_label"] = entry["attachment_label"] = label
            transcript.append(entry)
            del transcript[:-100]
        sessions[session] = (case, transcript, now)
        self.send_json(HTTPStatus.OK, body, session)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default=DEFAULT_MODEL, help="Hugging Face model ID or local model folder")
    parser.add_argument("--offline", action="store_true", help="Use model files already available locally")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    try:
        with HTTPServer(("127.0.0.1", args.port), Handler) as server:
            print(f"Loading {args.model}…", flush=True)
            server.model = LocalModel(args.model, args.offline)
            server.sessions = {}
            server.origin = f"http://127.0.0.1:{server.server_port}"
            print(f"Open {server.origin} in your browser. Press Ctrl+C to stop.", flush=True)
            server.serve_forever()
    except KeyboardInterrupt:
        pass
    except (ImportError, OSError, ValueError) as error:
        parser.exit(1, f"Startup failed: {error}\nSee README.md for setup and model download instructions.\n")


if __name__ == "__main__":
    main()
