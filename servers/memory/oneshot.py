# /// script
# dependencies = ["httpx", "fastapi", "uvicorn[standard]"]
# ///
import sys, tempfile, pathlib, httpx, subprocess, os
url = sys.argv
td = tempfile.mkdtemp()
p = pathlib.Path(td, "main.py")
p.write_text(httpx.get(url).text, encoding="utf-8")
os.chdir(td)
subprocess.run([sys.executable, "-m", "fastapi", "dev", "main.py"], check=True)
