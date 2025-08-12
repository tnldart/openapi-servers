# /// script
# dependencies = ["httpx", "fastapi[standard]"]
# ///
# meant to be run with uv run
import sys, tempfile, pathlib, httpx, subprocess, os, shutil

def main():
    if len(sys.argv) < 2:
        print("Usage: oneshot.py <raw-main.py-url> [extra fastapi dev args]", file=sys.stderr)
        sys.exit(2)

    url = sys.argv[1]
    extra = sys.argv[2:]

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
