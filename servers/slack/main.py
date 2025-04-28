"""Slack MCP Server – high‑performance version
------------------------------------------------
Showcase‑level code quality and pythonic clarity.
"""

import os
import asyncio
import logging
import json  # For JSONDecodeError
from typing import Optional, List, Dict, Any, Type, Callable

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Body, Depends, Security
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import APIKeyHeader
from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Environment variables
# ---------------------------------------------------------------------------
load_dotenv()

SLACK_BOT_TOKEN = os.getenv("SLACK_BOT_TOKEN")
SLACK_TEAM_ID = os.getenv("SLACK_TEAM_ID")
SLACK_CHANNEL_IDS_STR = os.getenv("SLACK_CHANNEL_IDS")  # Optional
ALLOWED_ORIGINS_STR = os.getenv("ALLOWED_ORIGINS", "*")
SERVER_API_KEY = os.getenv("SERVER_API_KEY")  # Optional API key for security

if not SLACK_BOT_TOKEN:
    logger.critical("SLACK_BOT_TOKEN environment variable not set.")
    raise ValueError("SLACK_BOT_TOKEN environment variable not set.")
if not SLACK_TEAM_ID:
    logger.critical("SLACK_TEAM_ID environment variable not set.")
    raise ValueError("SLACK_TEAM_ID environment variable not set.")

PREDEFINED_CHANNEL_IDS: Optional[List[str]] = (
    [cid.strip() for cid in SLACK_CHANNEL_IDS_STR.split(",")] if SLACK_CHANNEL_IDS_STR else None
)

# ---------------------------------------------------------------------------
# FastAPI app setup
# ---------------------------------------------------------------------------
app = FastAPI(
    title="Slack API Server",
    version="1.0.0",
    description="FastAPI server providing Slack functionalities via specific, dynamically generated tool endpoints.",
)

# CORS
allow_origins = [origin.strip() for origin in ALLOWED_ORIGINS_STR.split(",")]
if allow_origins == ["*"]:
    logger.warning("CORS allow_origins is set to '*' which is insecure for production. Consider setting ALLOWED_ORIGINS environment variable.")

app.add_middleware(
    CORSMiddleware,
    allow_origins=allow_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# API key security
# ---------------------------------------------------------------------------
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


async def get_api_key(key: str = Security(api_key_header)):
    if SERVER_API_KEY:
        if not key:
            logger.warning("API Key required but not provided in X-API-Key header.")
            raise HTTPException(status_code=401, detail="X-API-Key header required")
        if key != SERVER_API_KEY:
            logger.warning("Invalid API Key provided.")
            raise HTTPException(status_code=401, detail="Invalid API Key")
    return key  # May be None when not required


if not SERVER_API_KEY:
    logger.warning("SERVER_API_KEY environment variable is not set. Server will allow unauthenticated requests.")

# ---------------------------------------------------------------------------
# Pydantic models (arguments & responses)
# ---------------------------------------------------------------------------

class ListChannelsArgs(BaseModel):
    limit: Optional[int] = Field(100, description="Maximum number of channels to return (default 100, max 200)")
    cursor: Optional[str] = Field(None, description="Pagination cursor for next page of results")


class PostMessageArgs(BaseModel):
    channel_id: str = Field(..., description="The ID of the channel to post to")
    text: str = Field(..., description="The message text to post")


class ReplyToThreadArgs(BaseModel):
    channel_id: str = Field(..., description="The ID of the channel containing the thread")
    thread_ts: str = Field(..., description="The timestamp of the parent message (e.g., '1234567890.123456')")
    text: str = Field(..., description="The reply text")


class AddReactionArgs(BaseModel):
    channel_id: str = Field(..., description="The ID of the channel containing the message")
    timestamp: str = Field(..., description="The timestamp of the message to react to")
    reaction: str = Field(..., description="The name of the emoji reaction (without colons)")


class GetChannelHistoryArgs(BaseModel):
    channel_id: str = Field(..., description="The ID of the channel")
    limit: Optional[int] = Field(10, description="Number of messages to retrieve (default 10)")


class GetThreadRepliesArgs(BaseModel):
    channel_id: str = Field(..., description="The ID of the channel containing the thread")
    thread_ts: str = Field(..., description="The timestamp of the parent message (e.g., '1234567890.123456')")


class GetUsersArgs(BaseModel):
    cursor: Optional[str] = Field(None, description="Pagination cursor for next page of results")
    limit: Optional[int] = Field(100, description="Maximum number of users to return (default 100, max 200)")


class GetUserProfileArgs(BaseModel):
    user_id: str = Field(..., description="The ID of the user")


class ToolResponse(BaseModel):
    content: Dict[str, Any] = Field(..., description="The JSON response from the Slack API call")


# ---------------------------------------------------------------------------
# Slack client (high‑performance)
# ---------------------------------------------------------------------------

class SlackClient:
    """Thin async wrapper over Slack Web API with connection‑pool reuse."""

    BASE_URL = "https://slack.com/api/"

    def __init__(self, token: str, team_id: str, *, max_connections: int = 20):
        self.team_id = team_id
        self.headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json; charset=utf-8",
        }
        limits = httpx.Limits(max_connections=max_connections, max_keepalive_connections=max_connections)
        self._client = httpx.AsyncClient(
            base_url=self.BASE_URL,
            headers=self.headers,
            limits=limits,
            http2=True,
            timeout=10,
        )

    # ---------------- private helpers ---------------- #
    async def _request(
        self,
        method: str,
        endpoint: str,
        *,
        params: Optional[Dict] = None,
        json_data: Optional[Dict] = None,
    ) -> Dict[str, Any]:
        try:
            response = await self._client.request(method, endpoint, params=params, json=json_data)
            response.raise_for_status()
            data = response.json()
            if not data.get("ok"):
                error_msg = data.get("error", "Unknown Slack API error")
                raise HTTPException(status_code=400, detail={"slack_error": error_msg})
            return data
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 429:
                retry_after = e.response.headers.get("Retry-After")
                detail = (
                    f"Slack API rate limit exceeded. Retry after {retry_after} seconds."
                    if retry_after
                    else "Slack API rate limit exceeded."
                )
                logger.warning("Rate limit hit: %s", detail)
                raise HTTPException(status_code=429, detail=detail, headers={"Retry-After": retry_after} if retry_after else {})
            logger.error("HTTP Error %s - %s", e.response.status_code, e.response.text, exc_info=True)
            raise HTTPException(status_code=e.response.status_code, detail="Slack API HTTP Error")
        except httpx.RequestError as e:
            logger.error("Request Error connecting to Slack API: %s", e, exc_info=True)
            raise HTTPException(status_code=503, detail=f"Could not connect to Slack API: {e}")
        except json.JSONDecodeError as e:
            logger.error("Failed to decode JSON: %s", e, exc_info=True)
            raise HTTPException(status_code=502, detail="Invalid JSON from Slack API")
        except Exception as e:  # noqa: BLE001
            logger.exception("Unexpected error during Slack request: %s", e)
            raise HTTPException(status_code=500, detail=f"Internal error: {type(e).__name__}")

    # ---------------- public helpers ---------------- #
    async def channel_with_history(self, channel_id: str, *, history_limit: int = 1) -> Optional[Dict[str, Any]]:
        """Return channel metadata plus ≤ ``history_limit`` recent messages, or None."""
        try:
            info = await self._request("GET", "conversations.info", params={"channel": channel_id})
            chan = info["channel"]
            if chan.get("is_archived"):
                return None
            hist = await self._request(
                "GET",
                "conversations.history",
                params={"channel": channel_id, "limit": history_limit},
            )
            chan["history"] = hist.get("messages", [])
            return chan
        except Exception as exc:  # noqa: BLE001
            logger.warning("Skipping channel %s – %s", channel_id, exc, exc_info=True)
            return None

    # ---------------- API surface ---------------- #
    async def get_channel_history(self, args: GetChannelHistoryArgs) -> Dict[str, Any]:
        return await self._request("GET", "conversations.history", params={"channel": args.channel_id, "limit": args.limit})

    async def get_channels(self, args: ListChannelsArgs) -> Dict[str, Any]:  # noqa: C901 – keep cohesive
        # 1. decide which ids to fetch
        if PREDEFINED_CHANNEL_IDS:
            ids = PREDEFINED_CHANNEL_IDS
            next_cursor = ""
        else:
            params: Dict[str, Any] = {
                "types": "public_channel",
                "exclude_archived": "true",
                "limit": min(args.limit, 200),
                "team_id": self.team_id,
            }
            if args.cursor:
                params["cursor"] = args.cursor
            clist = await self._request("GET", "conversations.list", params=params)
            ids = [c["id"] for c in clist["channels"]]
            next_cursor = clist.get("response_metadata", {}).get("next_cursor", "")

        # 2. fetch metadata + history concurrently under a semaphore
        sem = asyncio.Semaphore(10)  # adjust parallelism as desired

        async def guarded(cid: str):
            async with sem:
                return await self.channel_with_history(cid)

        channels = [c for c in await asyncio.gather(*(guarded(cid) for cid in ids)) if c]
        return {"ok": True, "channels": channels, "response_metadata": {"next_cursor": next_cursor}}

    async def post_message(self, args: PostMessageArgs) -> Dict[str, Any]:
        return await self._request("POST", "chat.postMessage", json_data={"channel": args.channel_id, "text": args.text})

    async def post_reply(self, args: ReplyToThreadArgs) -> Dict[str, Any]:
        return await self._request(
            "POST",
            "chat.postMessage",
            json_data={"channel": args.channel_id, "thread_ts": args.thread_ts, "text": args.text},
        )

    async def add_reaction(self, args: AddReactionArgs) -> Dict[str, Any]:
        return await self._request(
            "POST",
            "reactions.add",
            json_data={"channel": args.channel_id, "timestamp": args.timestamp, "name": args.reaction},
        )

    async def get_thread_replies(self, args: GetThreadRepliesArgs) -> Dict[str, Any]:
        return await self._request("GET", "conversations.replies", params={"channel": args.channel_id, "ts": args.thread_ts})

    async def get_users(self, args: GetUsersArgs) -> Dict[str, Any]:
        params = {"limit": min(args.limit, 200), "team_id": self.team_id}
        if args.cursor:
            params["cursor"] = args.cursor
        return await self._request("GET", "users.list", params=params)

    async def get_user_profile(self, args: GetUserProfileArgs) -> Dict[str, Any]:
        return await self._request("GET", "users.profile.get", params={"user": args.user_id, "include_labels": "true"})

    # ---------------- lifecycle ---------------- #
    async def aclose(self) -> None:  # call on app shutdown
        await self._client.aclose()


# ---------------------------------------------------------------------------
# Instantiate Slack client
# ---------------------------------------------------------------------------
slack_client = SlackClient(token=SLACK_BOT_TOKEN, team_id=SLACK_TEAM_ID)


# ---------------------------------------------------------------------------
# Dynamic tool mapping / endpoint generation
# ---------------------------------------------------------------------------
TOOL_MAPPING = {
    "slack_list_channels": {
        "args_model": ListChannelsArgs,
        "method": slack_client.get_channels,
        "description": "List public or pre-defined channels in the workspace with pagination",
    },
    "slack_post_message": {
        "args_model": PostMessageArgs,
        "method": slack_client.post_message,
        "description": "Post a new message to a Slack channel",
    },
    "slack_reply_to_thread": {
        "args_model": ReplyToThreadArgs,
        "method": slack_client.post_reply,
        "description": "Reply to a specific message thread in Slack",
    },
    "slack_add_reaction": {
        "args_model": AddReactionArgs,
        "method": slack_client.add_reaction,
        "description": "Add a reaction emoji to a message",
    },
    "slack_get_channel_history": {
        "args_model": GetChannelHistoryArgs,
        "method": slack_client.get_channel_history,
        "description": "Get recent messages from a channel",
    },
    "slack_get_thread_replies": {
        "args_model": GetThreadRepliesArgs,
        "method": slack_client.get_thread_replies,
        "description": "Get all replies in a message thread",
    },
    "slack_get_users": {
        "args_model": GetUsersArgs,
        "method": slack_client.get_users,
        "description": "Get a list of all users in the workspace with their basic profile information",
    },
    "slack_get_user_profile": {
        "args_model": GetUserProfileArgs,
        "method": slack_client.get_user_profile,
        "description": "Get detailed profile information for a specific user",
    },
}


# ---------------- endpoint factory ---------------- #

def create_endpoint_handler(tool_name: str, method: Callable, args_model: Type[BaseModel]):
    async def handler(args: args_model = Body(...), api_key: str = Depends(get_api_key)) -> ToolResponse:  # noqa: ANN001
        try:
            result = await method(args=args)
            return {"content": result}
        except HTTPException:
            raise  # re‑raise untouched
        except Exception as exc:  # noqa: BLE001
            logger.exception("Error executing tool %s: %s", tool_name, exc)
            raise HTTPException(status_code=500, detail=f"Internal server error: {type(exc).__name__}")

    return handler


for name, cfg in TOOL_MAPPING.items():
    app.post(
        f"/{name}",
        response_model=ToolResponse,
        summary=cfg["description"],
        description=f"Executes the {name} tool. Arguments are passed in the request body.",
        tags=["Slack Tools"],
        name=name,
    )(create_endpoint_handler(name, cfg["method"], cfg["args_model"]))


# ---------------------------------------------------------------------------
# Lifecycle events
# ---------------------------------------------------------------------------
@app.on_event("shutdown")
async def _close_slack_client():
    await slack_client.aclose()


# ---------------------------------------------------------------------------
# Root endpoint
# ---------------------------------------------------------------------------
@app.get("/", summary="Root endpoint", include_in_schema=False)
async def read_root():
    return {"message": "Slack API Server is running. See /docs for available tool endpoints."}
