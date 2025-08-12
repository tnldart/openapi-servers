# 🧠 Memory Tool Server

A plug-and-play server for memory tools using FastAPI.  

## 🚀 Quickstart

Clone the repo and start the memory server:

```bash
git clone https://github.com/open-webui/openapi-servers
cd openapi-servers/servers/memory
pip install -r requirements.txt
uvicorn main:app --host 0.0.0.0 --reload
```

That's it – you're live! 🟢

or to live dangerously(you should really use Docker)...

## UV run invocation:

```bash
uv run https://raw.githubusercontent.com/tnldart/openapi-servers/refs/heads/main/servers/memory/oneshot.py https://raw.githubusercontent.com/tnldart/openapi-servers/refs/heads/main/servers/memory/main.py --host 0.0.0.0 --port 8000
```
