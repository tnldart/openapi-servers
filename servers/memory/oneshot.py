# /// script
# dependencies = ["httpx", "fastapi[standard]"]
# ///
# meant to be run with uv run - inspired by https://github.com/ivanfioravanti/qwen-image-mps/blob/main/qwen-image-mps.py
import sys, tempfile, pathlib, httpx, subprocess, os, shutil, socket

def _next_free_port(start=8000, end=9000):
    for port in range(start, end):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                s.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    raise RuntimeError(f"No free port found in range {start}-{end-1}")

def main():
    if len(sys.argv) < 2:
        print("Usage: oneshot.py <raw-main.py-url> [extra fastapi dev args]", file=sys.stderr)
        sys.exit(2)

    url = sys.argv[1]
    extra = sys.argv[2:]

    # Respect explicit port flags; otherwise choose the next free port ≥8000
    has_port_flag = any(a in ("--port", "-p") for a in extra)
    if not has_port_flag:
        try:
            port = _next_free_port(8000, 9000)
            extra = [*extra, "--port", str(port)]
        except Exception as e:
            print(f"Warning: could not find free port automatically ({e}); falling back to FastAPI default", file=sys.stderr)

    td = tempfile.mkdtemp(prefix="fastapi-url-")
    try:
        dst = pathlib.Path(td, "main.py")
        r = httpx.get(url, follow_redirects=True, timeout=60)
        r.raise_for_status()
        dst.write_text(r.text, encoding="utf-8")

        os.chdir(td)
        cmd = [sys.executable, "-m", "fastapi", "dev", "main.py", *extra]
        subprocess.run(cmd, check=True)
    finally:
        shutil.rmtree(td, ignore_errors=True)

if __name__ == "__main__":
    main()
