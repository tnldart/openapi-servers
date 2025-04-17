# [Previous imports and setup remain the same...]
import os
import httpx
import inspect
from typing import Optional, List, Dict, Any, Type, Callable
from fastapi import FastAPI, HTTPException, Body, Depends
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# --- Environment Variable Checks ---
SLACK_BOT_TOKEN = os.getenv("SLACK_BOT_TOKEN")
SLACK_TEAM_ID = os.getenv("SLACK_TEAM_ID")
SLACK_CHANNEL_IDS_STR = os.getenv("SLACK_CHANNEL_IDS") # Optional

if not SLACK_BOT_TOKEN:
    raise ValueError("SLACK_BOT_TOKEN environment variable not set.")
if not SLACK_TEAM_ID:
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

origins = ["*"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

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
                    print(f"Slack API Error for {method} {endpoint}: {error_msg}")
                    raise HTTPException(status_code=400, detail={"slack_error": error_msg, "message": f"Slack API Error: {error_msg}"})
                return data
            except httpx.HTTPStatusError as e:
                print(f"HTTP Error: {e.response.status_code} - {e.response.text}")
                raise HTTPException(status_code=e.response.status_code, detail=f"Slack API HTTP Error: {e.response.text}")
            except httpx.RequestError as e:
                print(f"Request Error: {e}")
                raise HTTPException(status_code=503, detail=f"Error connecting to Slack API: {e}")
            except Exception as e:
                print(f"Unexpected Error during Slack request: {e}")
                raise HTTPException(status_code=500, detail=f"An internal error occurred during the Slack request: {e}")

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
                        "limit": 10  # Get last 10 messages by default
                    }
                )
                # Add history to channel data
                if history.get("ok"):
                    channel_data["history"] = history.get("messages", [])
            except Exception as e:
                print(f"Error fetching history for channel {channel_id}: {e}")
                channel_data["history"] = []
                
            return channel_data

        if PREDEFINED_CHANNEL_IDS:
            channels_info = []
            for channel_id in PREDEFINED_CHANNEL_IDS:
                try:
                    if channel_data := await fetch_channel_with_history(channel_id):
                        channels_info.append(channel_data)
                except Exception as e:
                    print(f"Could not fetch info for predefined channel {channel_id}: {e}")
            
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
                except Exception as e:
                    print(f"Error fetching history for channel {channel['id']}: {e}")
                    channels_with_history.append(channel)  # Fall back to channel info without history
                    
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

# Define a function factory to create endpoint handlers
def create_endpoint_handler(tool_name: str, method: Callable, args_model: Type[BaseModel]):
    async def endpoint_handler(args: args_model = Body(...)) -> ToolResponse:
        try:
            result = await method(args=args)
            return {"content": result}
        except HTTPException as e:
            raise e
        except Exception as e:
            print(f"Error executing tool {tool_name}: {e}")
            raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")
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
