# 💬 Slack Tool Server

A powerful FastAPI-based server providing Slack workspace interactions using OpenAPI standards.

📦 Built with:
⚡️ FastAPI • 📜 OpenAPI • 🐍 Python • 💬 Slack API

---

## 🚀 Quickstart

Clone the repo and get started:

```bash
git clone https://github.com/open-webui/openapi-servers
cd openapi-servers/servers/slack

# Install dependencies
pip install -r requirements.txt

# Set up environment variables
export SLACK_BOT_TOKEN="xoxb-your-bot-token"
export SLACK_TEAM_ID="your-team-id"
export SLACK_CHANNEL_IDS="comma,separated,channel,ids" # Optional: restrict to specific channels

# Run the server
uvicorn main:app --host 0.0.0.0 --reload
```

---

## 🔍 About

This server is part of the OpenAPI Tools Collection. It provides a comprehensive interface to Slack workspace operations, including:

- 📋 List channels with message history
- 📤 Post messages and replies
- 👥 User information and profiles
- 👋 Add reactions to messages
- 📜 View message threads and history

All functionality is wrapped in a developer-friendly OpenAPI interface, making it perfect for integration with AI agents, automation tools, or custom Slack applications.

---

## 🔑 Prerequisites
Most of this is pulled straight from the Slack Python SDK so the barebones readme can easily be supplemented by reading the official one. Setup looks like:
1. **Slack Bot Token**: Create a Slack App and get a Bot User OAuth Token
   - Visit [Slack API Apps](https://api.slack.com/apps)
   - Create a new app or select existing
   - Add necessary bot scopes:
     - `channels:history`
     - `channels:read`
     - `chat:write`
     - `reactions:write`
     - `users:read`
     - `users:read.email`
   - Install the app to your workspace
   - You'll get the bot token on the last screen. 

2. **Team ID**: Your Slack workspace/team ID
   - Found in workspace settings or URL (go to your slack instance via web and it'll be after the slash)

3. **Channel IDs** (Optional):
   - Restrict the server to specific channels
   - Comma-separated list of channel IDs

---

## 🛠️ Available Tools

The server provides the following Slack tools:

- `slack_list_channels`: List channels with recent message history
- `slack_post_message`: Send messages to channels
- `slack_reply_to_thread`: Reply to message threads
- `slack_add_reaction`: Add emoji reactions to messages
- `slack_get_channel_history`: Get channel message history
- `slack_get_thread_replies`: Get replies in a thread
- `slack_get_users`: List workspace users
- `slack_get_user_profile`: Get detailed user profiles

Each tool is available as a dedicated endpoint with full OpenAPI documentation.

---

## 🌐 API Documentation

Once running, explore the interactive API documentation:

🖥️ Swagger UI: http://localhost:8000/docs
📄 OpenAPI JSON: http://localhost:8000/openapi.json

The documentation includes detailed schemas, example requests, and response formats for all available tools.

---

## 🔒 Security Notes

- Keep your `SLACK_BOT_TOKEN` secure
- Use environment variables for sensitive credentials
- Consider implementing additional authentication for the API server in production
- Review Slack's [security best practices](https://api.slack.com/authentication/best-practices)

---

Made with ❤️ by the Open WebUI community 🌍
Explore more tools ➡️ https://github.com/open-webui/openapi-servers
