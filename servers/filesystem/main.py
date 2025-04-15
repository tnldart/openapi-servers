from fastapi import FastAPI, HTTPException, Body
from fastapi.responses import PlainTextResponse
from fastapi.middleware.cors import CORSMiddleware


from pydantic import BaseModel, Field
import os
import pathlib
import asyncio
from typing import List, Optional, Union, Dict, Tuple
import difflib
import shutil
from datetime import datetime, timezone, timedelta
import uuid
from config import ALLOWED_DIRECTORIES
app = FastAPI(
    title="Secure Filesystem API",
    version="0.1.0",
    description="A secure file manipulation server for reading, editing, writing, listing, and searching files with access restrictions.",
)

origins = ["*"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# In-memory store for pending confirmations. Use Redis/DB in production.
# Format: {token: (DeletePathRequest_data, expiry_datetime)}
pending_confirmations: Dict[str, Tuple['DeletePathRequest', datetime]] = {}

# ------------------------------------------------------------------------------
# Utility functions
# ------------------------------------------------------------------------------


def normalize_path(requested_path: str) -> pathlib.Path:
    requested = pathlib.Path(os.path.expanduser(requested_path)).resolve()
    for allowed in ALLOWED_DIRECTORIES:
        if str(requested).lower().startswith(allowed.lower()): # Case-insensitive path comparison
            return requested
    raise HTTPException(
        status_code=403,
        detail={
            "error": "Access Denied",
            "requested_path": str(requested),
            "message": "Requested path is outside allowed directories.",
            "allowed_directories": ALLOWED_DIRECTORIES,
        },
    )


# ------------------------------------------------------------------------------
# Pydantic Schemas
# ------------------------------------------------------------------------------


class ReadFileRequest(BaseModel):
    path: str = Field(..., description="Path to the file to read")


class WriteFileRequest(BaseModel):
    path: str = Field(
        ..., description="Path to write to. Existing file will be overwritten."
    )
    content: str = Field(..., description="UTF-8 encoded text content to write.")


class EditOperation(BaseModel):
    oldText: str = Field(
        ..., description="Text to find and replace (exact match required)"
    )
    newText: str = Field(..., description="Replacement text")


class EditFileRequest(BaseModel):
    path: str = Field(..., description="Path to the file to edit.")
    edits: List[EditOperation] = Field(..., description="List of edits to apply.")
    dryRun: bool = Field(
        False, description="If true, only return diff without modifying file."
    )


class CreateDirectoryRequest(BaseModel):
    path: str = Field(
        ...,
        description="Directory path to create. Intermediate dirs are created automatically.",
    )


class ListDirectoryRequest(BaseModel):
    path: str = Field(..., description="Directory path to list contents for.")


class DirectoryTreeRequest(BaseModel):
    path: str = Field(
        ..., description="Directory path for which to return recursive tree."
    )


class SearchFilesRequest(BaseModel):
    path: str = Field(..., description="Base directory to search in.")
    pattern: str = Field(
        ..., description="Filename pattern (case-insensitive substring match)."
    )
    excludePatterns: Optional[List[str]] = Field(
        default=[], description="Patterns to exclude."
    )


class SearchContentRequest(BaseModel):
    path: str = Field(..., description="Base directory to search within.")
    search_query: str = Field(..., description="Text content to search for (case-insensitive).")
    recursive: bool = Field(
        default=True, description="Whether to search recursively in subdirectories."
    )
    file_pattern: Optional[str] = Field(
        default="*", description="Glob pattern to filter files to search within (e.g., '*.py')."
    )


class DeletePathRequest(BaseModel):
    path: str = Field(..., description="Path to the file or directory to delete.")
    recursive: bool = Field(
        default=False, description="If true and path is a directory, delete recursively. Required if directory is not empty."
    )
    # confirmation_token replaces the old confirm_delete flag
    confirmation_token: Optional[str] = Field(
        default=None, description="A confirmation token obtained from a prior request, required to execute deletion."
    )


class MovePathRequest(BaseModel):
    source_path: str = Field(..., description="The current path of the file or directory.")
    destination_path: str = Field(..., description="The new path for the file or directory.")


class GetMetadataRequest(BaseModel):
    path: str = Field(..., description="Path to the file or directory to get metadata for.")


# ------------------------------------------------------------------------------
# Routes
# ------------------------------------------------------------------------------


class SuccessResponse(BaseModel):
    message: str = Field(..., description="Success message indicating the operation was completed.")

# Response model for when confirmation is required for deletion
class ConfirmationRequiredResponse(BaseModel):
    message: str = Field(default="Confirmation required to proceed with deletion.")
    confirmation_token: str = Field(..., description="Token needed for the confirmation step.")
    expires_at: str = Field(..., description="UTC timestamp when the token expires (ISO format).")


class ReadFileResponse(BaseModel):
    content: str = Field(..., description="UTF-8 encoded text content of the file.")


class DiffResponse(BaseModel):
    diff: str = Field(..., description="Unified diff output comparing original and modified content.")


@app.post("/read_file", response_model=ReadFileResponse, summary="Read a file")
async def read_file(data: ReadFileRequest = Body(...)):
    """
    Read the entire contents of a file and return as JSON.
    """
    path = normalize_path(data.path)
    try:
        file_content = path.read_text(encoding="utf-8")
        return ReadFileResponse(content=file_content)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"File not found: {data.path}")
    except PermissionError:
         raise HTTPException(status_code=403, detail=f"Permission denied for file: {data.path}")
    except Exception as e:
        # Catch potential read errors
        raise HTTPException(status_code=500, detail=f"Failed to read file {data.path}: {str(e)}")


@app.post("/write_file", response_model=SuccessResponse, summary="Write to a file")
async def write_file(data: WriteFileRequest = Body(...)):
    """
    Write content to a file, overwriting if it exists. Returns JSON success message.
    """
    path = normalize_path(data.path)
    try:
        path.write_text(data.content, encoding="utf-8")
        return SuccessResponse(message=f"Successfully wrote to {data.path}")
    except PermissionError:
        raise HTTPException(status_code=403, detail=f"Permission denied to write to {data.path}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to write to {data.path}: {str(e)}")


# Note: Union was already imported earlier

@app.post(
    "/edit_file",
    response_model=Union[SuccessResponse, DiffResponse],
    summary="Edit a file with diff"
)
async def edit_file(data: EditFileRequest = Body(...)):
    """
    Apply a list of edits to a text file.
    Returns JSON success message or JSON diff on dry-run.
    """
    path = normalize_path(data.path)
    try:
        original = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"File not found: {data.path}")
    except PermissionError:
        raise HTTPException(status_code=403, detail=f"Permission denied to read file: {data.path}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to read file {data.path} for editing: {str(e)}")

    modified = original
    try:
        for edit in data.edits:
            if edit.oldText not in modified:
                raise HTTPException(
                    status_code=400,
                    detail=f"Edit failed: oldText not found in content: '{edit.oldText[:50]}...'",
                )
            modified = modified.replace(edit.oldText, edit.newText, 1)

        if data.dryRun:
            diff_output = difflib.unified_diff(
                original.splitlines(keepends=True),
                modified.splitlines(keepends=True),
                fromfile=f"a/{data.path}",
                tofile=f"b/{data.path}",
            )
            return DiffResponse(diff="".join(diff_output))

        # Apply changes if not a dry run
        path.write_text(modified, encoding="utf-8")
        return SuccessResponse(message=f"Successfully edited file {data.path}")

    except PermissionError:
        raise HTTPException(status_code=403, detail=f"Permission denied to write edited file: {data.path}")
    except Exception as e:
        # Catch potential write errors after modification
        raise HTTPException(status_code=500, detail=f"Failed to write edited file {data.path}: {str(e)}")


@app.post(
    "/create_directory", response_model=SuccessResponse, summary="Create a directory"
)
async def create_directory(data: CreateDirectoryRequest = Body(...)):
    """
    Create a new directory recursively. Returns JSON success message.
    """
    dir_path = normalize_path(data.path)
    try:
        dir_path.mkdir(parents=True, exist_ok=True)
        return SuccessResponse(message=f"Successfully created directory {data.path}")
    except PermissionError:
        raise HTTPException(status_code=403, detail=f"Permission denied to create directory {data.path}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to create directory {data.path}: {str(e)}")


@app.post(
    "/list_directory", summary="List a directory"
)
async def list_directory(data: ListDirectoryRequest = Body(...)):
    """
    List contents of a directory.
    """
    dir_path = normalize_path(data.path)
    if not dir_path.is_dir():
        raise HTTPException(status_code=400, detail="Provided path is not a directory")

    listing = []
    for entry in dir_path.iterdir():
        entry_type = "directory" if entry.is_dir() else "file"
        listing.append({"name": entry.name, "type": entry_type})

    # FastAPI automatically serializes the list to JSON
    return listing


@app.post("/directory_tree", summary="Recursive directory tree")
async def directory_tree(data: DirectoryTreeRequest = Body(...)):
    """
    Recursively return a tree structure of a directory.
    """
    base_path = normalize_path(data.path)

    def build_tree(current: pathlib.Path):
        entries = []
        for item in current.iterdir():
            entry = {
                "name": item.name,
                "type": "directory" if item.is_dir() else "file",
            }
            if item.is_dir():
                entry["children"] = build_tree(item)
            entries.append(entry)
        return entries

    return build_tree(base_path)


@app.post("/search_files", summary="Search for files")
async def search_files(data: SearchFilesRequest = Body(...)):
    """
    Search files and directories matching a pattern.
    """
    base_path = normalize_path(data.path)
    results = []

    for root, dirs, files in os.walk(base_path):
        root_path = pathlib.Path(root)
        # Check if the current root directory should be excluded
        excluded = False
        for pattern in data.excludePatterns:
            if pathlib.Path(root).match(pattern):
                excluded = True
                break
        if excluded:
            continue
        for item in files + dirs:
            if data.pattern.lower() in item.lower():
                result_path = root_path / item
                if any(str(result_path).startswith(alt) for alt in ALLOWED_DIRECTORIES):
                    results.append(str(result_path))

    return {"matches": results or ["No matches found"]}


@app.post(
    "/delete_path",
    response_model=Union[SuccessResponse, ConfirmationRequiredResponse],
    summary="Delete a file or directory (two-step confirmation)"
)
async def delete_path(data: DeletePathRequest = Body(...)):
    """
    Initiate or confirm deletion of a file or directory.

    1.  **First Request:** Call without `confirmation_token`. Returns a `confirmation_token`.
    2.  **Second Request:** Call again with the *exact same* `path` and `recursive` parameters,
        plus the `confirmation_token` received from the first request.

    Use `recursive=True` to delete non-empty directories (requires confirmation).
    Returns `ConfirmationRequiredResponse` on first step, `SuccessResponse` on completion.
    """
    path = normalize_path(data.path)
    token = data.confirmation_token

    if token is None:
        # Step 1: No token provided, generate one and request confirmation
        if not path.exists():
             # Check existence before generating a token
             raise HTTPException(status_code=404, detail=f"Path not found: {data.path}")

        confirmation_token = str(uuid.uuid4())
        expiry_time = datetime.now(timezone.utc) + timedelta(minutes=2) # Token valid for 2 minutes

        # Store the original request data and expiry time associated with the token
        # Important: Store data *before* normalization for validation later
        pending_confirmations[confirmation_token] = (data, expiry_time)

        return ConfirmationRequiredResponse(
            confirmation_token=confirmation_token,
            expires_at=expiry_time.isoformat()
        )

    else:
        # Step 2: Token provided, validate and attempt deletion
        if token not in pending_confirmations:
            raise HTTPException(status_code=400, detail="Invalid or expired confirmation token.")

        stored_request_data, expiry_time = pending_confirmations[token]

        # Validate expiry
        if datetime.now(timezone.utc) > expiry_time:
            del pending_confirmations[token] # Remove expired token
            raise HTTPException(status_code=400, detail="Confirmation token has expired.")

        # Validate consistency: path and recursive flag must match the original request
        if stored_request_data.path != data.path or stored_request_data.recursive != data.recursive:
             del pending_confirmations[token] # Remove token due to mismatch
             raise HTTPException(status_code=400, detail="Request parameters do not match the original confirmation request.")

        # --- Proceed with Deletion ---
        try:
            if not path.exists():
                # Re-check existence in case it was deleted between steps
                raise HTTPException(status_code=404, detail=f"Path not found (may have been deleted after confirmation): {data.path}")

            if path.is_file():
                path.unlink()
                message = f"Successfully deleted file: {data.path}"
            elif path.is_dir():
                if data.recursive:
                    shutil.rmtree(path)
                    message = f"Successfully deleted directory recursively: {data.path}"
                else:
                    try:
                        path.rmdir()
                        message = f"Successfully deleted empty directory: {data.path}"
                    except OSError as e:
                        raise HTTPException(
                            status_code=400,
                            detail=f"Directory not empty. Use 'recursive=True' to delete non-empty directories. Original error: {e}"
                        )
            else:
                 raise HTTPException(status_code=400, detail=f"Path is not a file or directory: {data.path}")

            # Deletion successful, remove the used token
            del pending_confirmations[token]
            return SuccessResponse(message=message)

        except PermissionError:
            # Don't remove token on permission error; user might fix permissions and retry
            raise HTTPException(status_code=403, detail=f"Permission denied to delete {data.path}")
        except HTTPException as http_exc:
             # If an expected HTTP error occurred during deletion (e.g., dir not empty), remove the token
             del pending_confirmations[token]
             raise http_exc # Re-raise the specific HTTP exception
        except Exception as e:
            # Catch unexpected errors during deletion, remove the token
            del pending_confirmations[token]
            raise HTTPException(status_code=500, detail=f"Failed to delete {data.path}: {e}")


@app.post("/move_path", response_model=SuccessResponse, summary="Move or rename a file or directory")
async def move_path(data: MovePathRequest = Body(...)):
    """
    Move or rename a file or directory from source_path to destination_path.
    Both paths must be within the allowed directories.
    Returns JSON success message.
    """
    source = normalize_path(data.source_path)
    destination = normalize_path(data.destination_path) # Normalize destination path too

    try:
        if not source.exists():
            raise HTTPException(status_code=404, detail=f"Source path not found: {data.source_path}")

        shutil.move(str(source), str(destination)) # Handles both file and directory moves
        return SuccessResponse(message=f"Successfully moved '{data.source_path}' to '{data.destination_path}'")

    except PermissionError:
        raise HTTPException(status_code=403, detail=f"Permission denied for move operation involving '{data.source_path}' or '{data.destination_path}'")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to move '{data.source_path}' to '{data.destination_path}': {e}")


@app.post("/get_metadata", summary="Get file or directory metadata")
async def get_metadata(data: GetMetadataRequest = Body(...)):
    """
    Retrieve metadata for a specified file or directory path.
    """
    path = normalize_path(data.path)

    try:
        if not path.exists():
            raise HTTPException(status_code=404, detail=f"Path not found: {data.path}")

        stat_result = path.stat()

        # Determine if it's a file or directory
        if path.is_file():
            file_type = "file"
        elif path.is_dir():
            file_type = "directory"
        else:
            file_type = "other" # Should generally not happen for existing, normalized paths

        # Format timestamps to ISO 8601 UTC for consistency
        mod_time = datetime.fromtimestamp(stat_result.st_mtime, tz=timezone.utc).isoformat()
        # Get creation time (st_birthtime on macOS/BSD, fallback to st_ctime on Linux)
        try:
            create_time = datetime.fromtimestamp(stat_result.st_birthtime, tz=timezone.utc).isoformat()
        except AttributeError:
            create_time = datetime.fromtimestamp(stat_result.st_ctime, tz=timezone.utc).isoformat()


        metadata = {
            "path": str(path),
            "type": file_type,
            "size_bytes": stat_result.st_size,
            "modification_time_utc": mod_time,
            "creation_time_utc": create_time, # Note: Definition varies by OS (birthtime vs. ctime)
            "last_metadata_change_time_utc": datetime.fromtimestamp(stat_result.st_ctime, tz=timezone.utc).isoformat(),
        }
        return metadata

    except PermissionError:
        raise HTTPException(status_code=403, detail=f"Permission denied to access metadata for {data.path}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get metadata for {data.path}: {e}")


@app.post("/search_content", summary="Search for content within files")
async def search_content(data: SearchContentRequest = Body(...)):
    """
    Search for text content within files in a specified directory.
    """
    base_path = normalize_path(data.path)
    results = []
    search_query_lower = data.search_query.lower()

    if not base_path.is_dir():
        raise HTTPException(status_code=400, detail="Provided path is not a directory")

    iterator = base_path.rglob(data.file_pattern) if data.recursive else base_path.glob(data.file_pattern)

    for item_path in iterator:
        if item_path.is_file():
            try:
                # Read file line by line to handle potentially large files and different encodings
                with item_path.open("r", encoding="utf-8", errors="ignore") as f:
                    for line_num, line in enumerate(f, 1):
                        if search_query_lower in line.lower():
                            results.append(
                                {
                                    "file_path": str(item_path),
                                    "line_number": line_num,
                                    "line_content": line.strip(),
                                }
                            )
            except Exception as e:
                # Log or handle files that cannot be read (e.g., permission errors, binary files)
                print(f"Could not read or search file {item_path}: {e}")
                continue

    return {"matches": results or ["No matches found"]}


@app.get("/list_allowed_directories", summary="List access-permitted directories")
async def list_allowed_directories():
    """
    Show all directories this server can access.
    """
    return {"allowed_directories": ALLOWED_DIRECTORIES}
