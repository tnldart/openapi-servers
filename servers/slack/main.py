import os
import httpx
import inspect
import logging
import json # For JSONDecodeError
from typing import Optional, List, Dict, Any, Type, Callable
from fastapi import FastAPI, HTTPException, Body, Depends, Security
from fastapi.security import APIKeyHeader
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from dotenv import load_dotenv

# --- Logging Setup ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Load environment variables from .env file
load_dotenv()

# --- Environment Variable Checks ---
SLACK_BOT_TOKEN = os.getenv("SLACK_BOT_TOKEN")
SLACK_TEAM_ID = os.getenv("SLACK_TEAM_ID")
SLACK_CHANNEL_IDS_STR = os.getenv("SLACK_CHANNEL_IDS") # Optional
ALLOWED_ORIGINS_STR = os.getenv("ALLOWED_ORIGINS", "*") # Default to allow all
SERVER_API_KEY = os.getenv("SERVER_API_KEY") # Optional API key for security

if not SLACK_BOT_TOKEN:
    # Fail fast if essential config is missing
    logger.critical("SLACK_BOT_TOKEN environment variable not set.")
    raise ValueError("SLACK_BOT_TOKEN environment variable not set.")
if not SLACK_TEAM_ID:
    logger.critical("SLACK_TEAM_ID environment variable not set.")
    raise ValueError("SLACK_TEAM_ID environment variable not set.")

PREDEFINED_CHANNEL_IDS = [
    channel_id.strip()
    for channel_id in SLACK_CHANNEL_IDS_STR.split(',')
] if SLACK_CHANNEL_IDS_STR else None

# --- FastAPI App Setup ---
app = FastAPI(
    title="Slack API Server",
    version="1.0.0",
    description="FastAPI server providing Slack functionalities via specific, dynamically generated tool endpoints.",
)

# Configure CORS
allow_origins = [origin.strip() for origin in ALLOWED_ORIGINS_STR.split(',')]
if allow_origins == ["*"]:
    logger.warning("CORS allow_origins is set to '*' which is insecure for production. Consider setting ALLOWED_ORIGINS environment variable.")

app.add_middleware(
    CORSMiddleware,
    allow_origins=allow_origins,
    allow_credentials=True, # Allow credentials if origins are specific, adjust if needed
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- API Key Security ---
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False) # auto_error=False to handle optional key

async def get_api_key(key: str = Security(api_key_header)):
    if SERVER_API_KEY: # Only enforce key if it's set in the environment
        if not key:
            logger.warning("API Key required but not provided in X-API-Key header.")
            raise HTTPException(status_code=401, detail="X-API-Key header required")
        if key != SERVER_API_KEY:
            logger.warning("Invalid API Key provided.")
            raise HTTPException(status_code=401, detail="Invalid API Key")
        # If key is valid and required, proceed
    # If SERVER_API_KEY is not set, allow access without a key
    # logger.info("API Key check passed (or not required).") # Optional: Log successful checks
    return key # Return the key or None if not required/provided

if not SERVER_API_KEY:
    logger.warning("SERVER_API_KEY environment variable is not set. Server will allow unauthenticated requests.")

# [Previous Pydantic models remain the same...]
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

# --- Slack Client Class ---
class SlackClient:
    BASE_URL = "https://slack.com/api/"

    def __init__(self, token: str, team_id: str):
        self.headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json; charset=utf-8",
        }
        self.team_id = team_id

    async def _request(self, method: str, endpoint: str, params: Optional[Dict] = None, json_data: Optional[Dict] = None) -> Dict[str, Any]:
        async with httpx.AsyncClient(base_url=self.BASE_URL, headers=self.headers) as client:
            try:
                response = await client.request(method, endpoint, params=params, json=json_data)
                response.raise_for_status()
                data = response.json()
                if not data.get("ok"):
                    error_msg = data.get("error", "Unknown Slack API error")
                    # Return the specific Slack error in the response
                    logger.warning(f"Slack API Error for {method} {endpoint}: {error_msg}")
                    raise HTTPException(status_code=400, detail={"slack_error": error_msg, "message": f"Slack API returned an error: {error_msg}"})
                return data
            except httpx.HTTPStatusError as e:
                # Handle specific HTTP errors like rate limiting (429)
                if e.response.status_code == 429:
                    retry_after = e.response.headers.get("Retry-After")
                    detail = f"Slack API rate limit exceeded. Retry after {retry_after} seconds." if retry_after else "Slack API rate limit exceeded."
                    logger.warning(f"Rate limit hit for {method} {endpoint}. Retry-After: {retry_after}")
                    raise HTTPException(status_code=429, detail=detail, headers={"Retry-After": retry_after} if retry_after else {})
                else:
                    logger.error(f"HTTP Error: {e.response.status_code} - {e.response.text}", exc_info=True)
                    raise HTTPException(status_code=e.response.status_code, detail=f"Slack API HTTP Error: Status {e.response.status_code}")
            except httpx.RequestError as e:
                logger.error(f"Request Error connecting to Slack API: {e}", exc_info=True)
                raise HTTPException(status_code=503, detail=f"Could not connect to Slack API: {e}")
            except json.JSONDecodeError as e:
                 logger.error(f"Failed to decode JSON response from Slack API for {method} {endpoint}: {e}", exc_info=True)
                 raise HTTPException(status_code=502, detail="Invalid response received from Slack API.")
            except Exception as e: # Catch other unexpected errors
                logger.exception(f"Unexpected error during Slack request for {method} {endpoint}: {e}") # Use logger.exception to include traceback
                raise HTTPException(status_code=500, detail=f"An internal server error occurred: {type(e).__name__}")

    async def get_channel_history(self, args: GetChannelHistoryArgs) -> Dict[str, Any]:
        params = {"channel": args.channel_id, "limit": args.limit}
        return await self._request("GET", "conversations.history", params=params)

    async def get_channels(self, args: ListChannelsArgs) -> Dict[str, Any]:
        limit = args.limit
        cursor = args.cursor

        async def fetch_channel_with_history(channel_id: str) -> Dict[str, Any]:
            # First get channel info
            channel_info = await self._request("GET", "conversations.info", params={"channel": channel_id})
            if not channel_info.get("ok") or channel_info.get("channel", {}).get("is_archived"):
                return None

            channel_data = channel_info["channel"]

            # Then get channel history
            try:
                history = await self._request(
                    "GET",
                    "conversations.history",
                    params={
                        "channel": channel_id,
                        "limit": 1 # Fetch minimal history by default to speed up get_channels. Consider asyncio.gather for concurrency.
                    }
                )
                # Add history to channel data
                if history.get("ok"):
                    channel_data["history"] = history.get("messages", [])
            except Exception as e: # Catch errors during history fetch but don't fail the whole channel list
                logger.warning(f"Error fetching history for channel {channel_id}: {e}", exc_info=True)
                channel_data["history"] = [] # Ensure history key exists even if fetch fails

            return channel_data

        if PREDEFINED_CHANNEL_IDS:
            channels_info = []
            for channel_id in PREDEFINED_CHANNEL_IDS:
                try:
                    if channel_data := await fetch_channel_with_history(channel_id):
                        channels_info.append(channel_data)
                except Exception as e: # Catch errors fetching predefined channels
                    logger.warning(f"Could not fetch info for predefined channel {channel_id}: {e}", exc_info=True)

            return {
                "ok": True,
                "channels": channels_info,
                "response_metadata": {"next_cursor": ""}
            }
        else:
            # First get list of channels
            params = {
                "types": "public_channel",
                "exclude_archived": "true",
                "limit": min(limit, 200),
                "team_id": self.team_id,
            }
            if cursor:
                params["cursor"] = cursor

            channels_list = await self._request("GET", "conversations.list", params=params)

            if not channels_list.get("ok"):
                return channels_list

            # Then fetch history for each channel
            channels_with_history = []
            for channel in channels_list["channels"]:
                try:
                    if channel_data := await fetch_channel_with_history(channel["id"]):
                        channels_with_history.append(channel_data)
                except Exception as e: # Catch errors during history fetch but don't fail the whole channel list
                    logger.warning(f"Error fetching history for channel {channel['id']}: {e}", exc_info=True)
                    channel["history"] = [] # Add empty history on error
                    channels_with_history.append(channel)

            return {
                "ok": True,
                "channels": channels_with_history,
                "response_metadata": channels_list.get("response_metadata", {"next_cursor": ""})
            }

    async def post_message(self, args: PostMessageArgs) -> Dict[str, Any]:
        payload = {"channel": args.channel_id, "text": args.text}
        return await self._request("POST", "chat.postMessage", json_data=payload)

    async def post_reply(self, args: ReplyToThreadArgs) -> Dict[str, Any]:
        payload = {"channel": args.channel_id, "thread_ts": args.thread_ts, "text": args.text}
        return await self._request("POST", "chat.postMessage", json_data=payload)

    async def add_reaction(self, args: AddReactionArgs) -> Dict[str, Any]:
        payload = {"channel": args.channel_id, "timestamp": args.timestamp, "name": args.reaction}
        return await self._request("POST", "reactions.add", json_data=payload)

    async def get_thread_replies(self, args: GetThreadRepliesArgs) -> Dict[str, Any]:
        params = {"channel": args.channel_id, "ts": args.thread_ts}
        return await self._request("GET", "conversations.replies", params=params)

    async def get_users(self, args: GetUsersArgs) -> Dict[str, Any]:
        params = {
            "limit": min(args.limit, 200),
            "team_id": self.team_id,
        }
        if args.cursor:
            params["cursor"] = args.cursor
        return await self._request("GET", "users.list", params=params)

    async def get_user_profile(self, args: GetUserProfileArgs) -> Dict[str, Any]:
        params = {"user": args.user_id, "include_labels": "true"}
        return await self._request("GET", "users.profile.get", params=params)

# --- Instantiate Slack Client ---
slack_client = SlackClient(token=SLACK_BOT_TOKEN, team_id=SLACK_TEAM_ID)

# --- Tool Definitions & Endpoint Generation ---
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

# Define a function factory to create endpoint handlers, including API key dependency
def create_endpoint_handler(tool_name: str, method: Callable, args_model: Type[BaseModel]):
    async def endpoint_handler(
        args: args_model = Body(...),
        api_key: str = Depends(get_api_key) # Add API key dependency here
    ) -> ToolResponse:
        try:
            result = await method(args=args)
            return {"content": result}
        except HTTPException as e:
            raise e
        except Exception as e:
            logger.exception(f"Error executing tool {tool_name}: {e}") # Use logger.exception here too
            raise HTTPException(status_code=500, detail=f"Internal server error: {type(e).__name__}")
    return endpoint_handler

# Register endpoints for each tool
for tool_name, config in TOOL_MAPPING.items():
    handler = create_endpoint_handler(
        tool_name=tool_name,
        method=config["method"],
        args_model=config["args_model"]
    )

    app.post(
        f"/{tool_name}",
        response_model=ToolResponse,
        summary=config["description"],
        description=f"Executes the {tool_name} tool. Arguments are passed in the request body.",
        tags=["Slack Tools"],
        name=tool_name
    )(handler)

# --- Root Endpoint ---
@app.get("/", summary="Root endpoint", include_in_schema=False)
async def read_root():
    return {"message": "Slack API Server is running. See /docs for available tool endpoints."}
