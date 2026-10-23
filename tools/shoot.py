#!/usr/bin/env python3
"""Headless GPU screenshots of the Pearl St viewer, with the app's own frame stats and console.

  tools/shoot.py --views mall_e,mall_w,orbit                  # .work/shots/<view>.png, one per view
  tools/shoot.py --params "facade=f61c4184&fov=40" --out x.png
  tools/shoot.py --views mall_e --eval "JSON.stringify(window.__app.stats())"
  tools/shoot.py --url https://zephr-xyz.github.io/pearl-st-3d/ --views orbit   # the deployed page

Starts a private static server on viewer/ (unless --url), launches Chrome headless on the GPU,
opens the page with capture=1 added, waits for window.__ready, settles, saves a PNG and prints
the `stats:` line (frame ms, draw calls, triangles, camera) and any console errors. Chrome and
the server are killed at the end, however the run ends. Exit codes: 0 done, 1 never ready,
2 Chrome did not start, 3 console errors.

The DevTools transport (a stdlib websocket client) follows tools/shoot.py of
github.com/vladi21k/3DSceneRenderer (MIT).
"""
import argparse, atexit, base64, json, os, platform, shutil, signal, socket, struct, subprocess, sys, tempfile, time
import urllib.parse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VIEWER = os.path.join(ROOT, "viewer")
WORK = os.path.join(ROOT, ".work")
CHROME_CANDIDATES = [
    os.environ.get("SHOOT_CHROME", ""),
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    shutil.which("google-chrome") or "", shutil.which("chromium") or "", shutil.which("chromium-browser") or "",
]
GPU_FLAGS = "--enable-gpu --ignore-gpu-blocklist" + (" --use-angle=metal" if platform.system() == "Darwin" else " --use-angle=gl")

_procs = []


def cleanup():
    for p in _procs:
        if p.poll() is None:
            try:
                p.terminate(); p.wait(5)
            except Exception:
                try: p.kill()
                except Exception: pass


atexit.register(cleanup)
for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
    signal.signal(sig, lambda *_: sys.exit(130))


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def port_open(port):
    with socket.socket() as s:
        s.settimeout(0.3)
        return s.connect_ex(("127.0.0.1", port)) == 0


def start_server():
    port = free_port()
    p = subprocess.Popen([sys.executable, "-m", "http.server", str(port), "--bind", "127.0.0.1", "--directory", VIEWER],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    _procs.append(p)
    for _ in range(100):
        if port_open(port):
            return f"http://127.0.0.1:{port}/"
        time.sleep(0.05)
    sys.exit("static server did not start")


def chrome_path():
    for c in CHROME_CANDIDATES:
        if c and os.path.exists(c):
            return c
    sys.exit("Chrome not found: set SHOOT_CHROME=/path/to/chrome")


def start_chrome(profile, width, height):
    args = [chrome_path(), "--headless=new", "--remote-debugging-port=0", f"--user-data-dir={profile}",
            f"--window-size={width},{height}", "--hide-scrollbars", "--mute-audio", "--no-first-run",
            "--no-default-browser-check", "--disable-extensions", "--disable-gpu-sandbox",
            *os.environ.get("SHOOT_GPU_FLAGS", GPU_FLAGS).split(), *os.environ.get("SHOOT_CHROME_FLAGS", "").split(),
            "about:blank"]
    err = open(os.environ["SHOOT_STDERR"], "w") if os.environ.get("SHOOT_STDERR") else subprocess.DEVNULL
    p = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=err)
    _procs.append(p)
    path = os.path.join(profile, "DevToolsActivePort")
    end = time.time() + 30
    while time.time() < end:
        if p.poll() is not None:
            sys.exit(2)
        try:
            lines = open(path).read().split()
            if len(lines) >= 2 and lines[0].isdigit():
                return f"ws://127.0.0.1:{lines[0]}{lines[1]}"
        except OSError:
            pass
        time.sleep(0.05)
    print("Chrome did not open its DevTools port", file=sys.stderr)
    sys.exit(2)


class WS:
    """Minimal websocket client for the DevTools protocol."""

    def __init__(self, url):
        hostport, path = url[5:].split("/", 1)
        host, port = hostport.split(":")
        self.sock = socket.create_connection((host, int(port)), timeout=30)
        key = base64.b64encode(os.urandom(16)).decode()
        req = (f"GET /{path} HTTP/1.1\r\nHost: {hostport}\r\nUpgrade: websocket\r\n"
               f"Connection: Upgrade\r\nSec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n")
        self.sock.sendall(req.encode())
        buf = b""
        while b"\r\n\r\n" not in buf:
            buf += self.sock.recv(4096)
        self.extra = buf.split(b"\r\n\r\n", 1)[1]
        self.next_id = 0
        self.events = []

    def _recv_exact(self, n):
        while len(self.extra) < n:
            chunk = self.sock.recv(1 << 20)
            if not chunk:
                raise ConnectionError("websocket closed")
            self.extra += chunk
        out, self.extra = self.extra[:n], self.extra[n:]
        return out

    def recv(self):
        msg = b""
        while True:
            b1, b2 = self._recv_exact(2)
            fin, op = b1 & 0x80, b1 & 0x0F
            ln = b2 & 0x7F
            if ln == 126:
                ln = struct.unpack(">H", self._recv_exact(2))[0]
            elif ln == 127:
                ln = struct.unpack(">Q", self._recv_exact(8))[0]
            data = self._recv_exact(ln)
            if op == 8:
                raise ConnectionError("websocket closed by peer")
            if op in (0, 1, 2):
                msg += data
                if fin:
                    return json.loads(msg.decode("utf-8", "replace"))

    def send(self, method, params=None, session=None):
        self.next_id += 1
        payload = {"id": self.next_id, "method": method, "params": params or {}}
        if session:
            payload["sessionId"] = session
        data = json.dumps(payload).encode()
        hdr = bytearray([0x81])
        mask = os.urandom(4)
        if len(data) < 126:
            hdr.append(0x80 | len(data))
        elif len(data) < 65536:
            hdr.append(0x80 | 126); hdr += struct.pack(">H", len(data))
        else:
            hdr.append(0x80 | 127); hdr += struct.pack(">Q", len(data))
        hdr += mask
        self.sock.sendall(bytes(hdr) + bytes(b ^ mask[i % 4] for i, b in enumerate(data)))
        return self.next_id

    def call(self, method, params=None, session=None, timeout=120):
        mid = self.send(method, params, session)
        t0 = time.time()
        while time.time() - t0 < timeout:
            m = self.recv()
            if m.get("id") == mid:
                if "error" in m:
                    raise RuntimeError(f"{method}: {m['error']}")
                return m.get("result", {})
            self.events.append(m)
        raise TimeoutError(method)


class Page:
    def __init__(self, ws_url, width, height):
        self.ws = WS(ws_url)
        self.tid = self.ws.call("Target.createTarget", {"url": "about:blank"})["targetId"]
        self.sid = self.ws.call("Target.attachToTarget", {"targetId": self.tid, "flatten": True})["sessionId"]
        # the exact viewport, whatever the window frame takes (headless gives 1920x993 for a 1080 window)
        self.ws.call("Emulation.setDeviceMetricsOverride",
                     {"width": width, "height": height, "deviceScaleFactor": 1, "mobile": False}, session=self.sid)
        self.ws.call("Page.enable", session=self.sid)
        self.ws.call("Runtime.enable", session=self.sid)
        self.ws.call("Log.enable", session=self.sid)

    def eval(self, js, timeout=120):
        r = self.ws.call("Runtime.evaluate", {"expression": js, "returnByValue": True, "awaitPromise": True},
                         session=self.sid, timeout=timeout)
        if "exceptionDetails" in r:
            d = r["exceptionDetails"]
            return {"exception": d.get("exception", {}).get("description") or d.get("text")}
        return r.get("result", {}).get("value")

    def navigate(self, url):
        self.ws.events.clear()
        self.ws.call("Page.navigate", {"url": url}, session=self.sid)

    def close(self):
        try:
            self.ws.call("Target.closeTarget", {"targetId": self.tid}, timeout=10)
        except Exception:
            pass
        try:
            self.ws.sock.close()
        except Exception:
            pass

    def console(self):
        """Console errors, warnings and exceptions seen so far (and clear them)."""
        out = []
        for e in self.ws.events:
            m, p = e.get("method"), e.get("params", {})
            if m == "Runtime.consoleAPICalled" and p.get("type") in ("error", "warning", "assert"):
                out.append(p["type"] + ": " + " ".join(str(a.get("value", a.get("description", ""))) for a in p.get("args", [])))
            elif m == "Runtime.exceptionThrown":
                d = p.get("exceptionDetails", {})
                out.append("exception: " + (d.get("exception", {}).get("description") or d.get("text", "")))
            elif m == "Log.entryAdded" and p.get("entry", {}).get("level") in ("error", "warning"):
                en = p["entry"]
                if "favicon.ico" in en.get("url", ""):
                    continue
                out.append(f"{en['level']}: {en.get('text', '')} {en.get('url', '')}")
        self.ws.events.clear()
        return out

    def screenshot(self, path):
        r = self.ws.call("Page.captureScreenshot", {"format": "png"}, session=self.sid)
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        with open(path, "wb") as f:
            f.write(base64.b64decode(r["data"]))


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0], formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    ap.add_argument("--views", default="", help="comma-separated view names (view=) to shoot, one file each")
    ap.add_argument("--params", default="", help="extra URL query without '?', e.g. facade=f61c4184&fov=40")
    ap.add_argument("--out", default="", help="screenshot path (single shot) or directory (with --views); default .work/shots/")
    ap.add_argument("--url", default="", help="page to open instead of the private server on viewer/")
    ap.add_argument("--width", type=int, default=1920)
    ap.add_argument("--height", type=int, default=1080)
    ap.add_argument("--settle", type=float, default=1.5, help="seconds to wait after ready before the shot")
    ap.add_argument("--timeout", type=float, default=120, help="seconds to wait for window.__ready")
    ap.add_argument("--eval", default="", help="JS evaluated after each shot, result printed")
    ap.add_argument("--no-shot", action="store_true", help="stats and console only")
    a = ap.parse_args()

    os.makedirs(WORK, exist_ok=True)
    profile = tempfile.mkdtemp(prefix="shoot-", dir=WORK)
    atexit.register(lambda: shutil.rmtree(profile, ignore_errors=True))
    base = a.url or start_server()
    ws_url = start_chrome(profile, a.width, a.height)

    views = [v for v in a.views.split(",") if v] or [None]
    outdir = a.out if (a.out and (len(views) > 1 or os.path.isdir(a.out) or not a.out.endswith(".png"))) else os.path.join(WORK, "shots")
    worst = 0
    for view in views:
        q = {"capture": "1"}
        if view:
            q["view"] = view
        qs = urllib.parse.urlencode(q) + (("&" + a.params) if a.params else "")
        url = base + ("&" if "?" in base else "?") + qs if "?" in base else base + "?" + qs
        label = view or (a.params.replace("&", "_").replace("=", "-") or "shot")
        # a fresh tab per view: a tab reused across full scene rebuilds answered slower each
        # time (32 s, then 105 s, then not at all within 2 minutes)
        page = Page(ws_url, a.width, a.height)
        t0 = time.time()
        page.navigate(url)
        ready = False
        while time.time() - t0 < a.timeout:
            try:
                if page.eval("window.__ready === true") is True:
                    ready = True
                    break
            except (socket.timeout, TimeoutError):
                print(f"{label}: page busy for 30 s at {time.time() - t0:.0f} s, still waiting")
                continue
            time.sleep(0.25)
        if not ready:
            print(f"{label}: WARNING never ready after {a.timeout:.0f} s; console: {page.console()}")
            worst = max(worst, 1)
            page.close()
            continue
        time.sleep(a.settle)
        if not a.no_shot:
            path = a.out if (a.out and a.out.endswith(".png") and len(views) == 1) else os.path.join(outdir, f"{label}.png")
            page.screenshot(path)
            print(f"{label}: wrote {path} (ready in {time.time() - t0:.1f} s)")
        stats = page.eval("JSON.stringify(window.__app.stats())")
        print(f"{label}: stats: {stats}")
        if a.eval:
            print(f"{label}: eval: {page.eval(a.eval)}")
        errs = page.console()
        for e in errs:
            print(f"{label}: console {e}")
        if errs:
            worst = max(worst, 3)
        page.close()
    return worst


if __name__ == "__main__":
    sys.exit(main())
