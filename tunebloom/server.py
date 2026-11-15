"""Serveur local (bibliothèque standard) : sert l'interface web et l'API JSON. Aucune dépendance."""
import json, mimetypes, os, sys, threading, time, traceback, webbrowser
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

from .webapi import Project

WEB = os.path.join(os.path.dirname(__file__), "web")
P = Project()
LAST_PING = [0.0]


def listdir(path):
    path = os.path.abspath(path or os.path.expanduser("~"))
    ents = []
    try:
        for n in sorted(os.listdir(path), key=str.lower):
            if n.startswith("."):
                continue
            full = os.path.join(path, n)
            ents.append(dict(name=n, dir=os.path.isdir(full)))
    except OSError as e:
        return dict(path=path, parent=os.path.dirname(path), entries=[], error=str(e))
    ents.sort(key=lambda e: (not e["dir"], e["name"].lower()))
    return dict(path=path, parent=os.path.dirname(path), entries=ents)


class H(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype="application/json"):
        if isinstance(body, (dict, list)):
            body = json.dumps(body).encode()
        elif isinstance(body, str):
            body = body.encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        return self.rfile.read(n) if n else b""

    def do_GET(self):
        u = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        if u.path.startswith("/api/"):
            return self._api(u.path[5:], q, None)
        name = "index.html" if u.path in ("/", "") else u.path.lstrip("/")
        full = os.path.normpath(os.path.join(WEB, name))
        if not full.startswith(WEB) or not os.path.isfile(full):
            return self._send(404, "not found", "text/plain")
        with open(full, "rb") as f:
            self._send(200, f.read(), mimetypes.guess_type(full)[0] or "application/octet-stream")

    def do_POST(self):
        u = urlparse(self.path)
        self._api(u.path[5:], {}, self._body())

    def _api(self, route, q, body):
        try:
            with P.lock:
                self._route(route, q, json.loads(body) if body else {})
        except LookupError as e:
            self._send(404, dict(error=str(e)))
        except NotImplementedError as e:
            self._send(501, dict(error=str(e)))
        except Exception as e:
            traceback.print_exc()
            self._send(500, dict(error=f"{type(e).__name__}: {e}"))

    def _route(self, r, q, b):
        i = int(q["i"]) if "i" in q else None
        if r == "ping":
            LAST_PING[0] = time.time()
            return self._send(200, dict(ok=True))
        if r == "state":
            return self._send(200, dict(open=P.arc is not None, path=P.path, dirty=P.dirty,
                                        version=P.arc.version if P.arc else 0))
        if r == "fs":
            return self._send(200, listdir(q.get("path")))
        if r == "open":
            P.open(b["path"], b.get("grps", []))
            return self._send(200, dict(ok=True))
        if r == "close":
            P.close()
            return self._send(200, dict(ok=True))
        if P.arc is None:
            return self._send(409, dict(error="Aucun projet ouvert"))
        if r == "list":
            return self._send(200, P.list(q["cat"]))
        if r == "item":
            return self._send(200, P.item(q["cat"], i))
        if r == "set":
            P.set_value(b["cat"], b["i"], b["key"], b["value"])
            return self._send(200, dict(ok=True, dirty=True))
        if r == "save":
            P.arc.save(b.get("path") or P.path)
            if b.get("path"):
                P.path = b["path"]
            P.dirty = False
            return self._send(200, dict(ok=True))
        if r == "audio":
            data, au = P.audio_wav(q["kind"], i, int(q.get("j", 0)))
            return self._send(200, data, "audio/wav")
        if r == "seq":
            return self._send(200, P.seq_view(q["kind"], i))
        if r == "bank":
            return self._send(200, P.bank_view(i))
        if r == "addgrp":
            with open(b["path"], "rb") as f:
                n = P.arc.attach_group(f.read())
            return self._send(200, dict(ok=True, files=n))
        self._send(404, dict(error="route inconnue"))


def main(path=None, port=0, open_browser=True):
    srv = ThreadingHTTPServer(("127.0.0.1", port), H)
    port = srv.server_address[1]
    if path:
        P.open(path)
    url = f"http://127.0.0.1:{port}/"
    try:
        print(f"TuneBloom-Py : {url}   (Ctrl+C pour quitter)")
    except Exception:
        pass                                  # exécutable « windowed » : pas de console
    if open_browser:
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()

        def watchdog():                       # quitte quand l'onglet du navigateur est fermé
            time.sleep(20)
            while True:
                time.sleep(3)
                if LAST_PING[0] and time.time() - LAST_PING[0] > 20:
                    srv.shutdown()
                    return
        threading.Thread(target=watchdog, daemon=True).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
