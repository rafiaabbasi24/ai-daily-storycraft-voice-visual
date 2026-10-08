import os
import json
from pathlib import Path
from typing import Any, Dict

import pytest
from fastapi.testclient import TestClient
from unittest.mock import AsyncMock, MagicMock, patch

# Import the FastAPI app from the project entry point.
# Adjust the import path if the app is defined elsewhere.
from main import app  # type: ignore

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def client() -> TestClient:
    """
    Provides a TestClient instance for the FastAPI app.
    """
    return TestClient(app)


# ---------------------------------------------------------------------------
# Helper functions for mocking external services
# ---------------------------------------------------------------------------

def mock_openai_chat_completion_create(*args: Any, **kwargs: Any) -> Dict[str, Any]:
    """
    Mock for openai.ChatCompletion.create that returns a predictable response.
    The real implementation returns a dict with a 'choices' list containing
    a 'message' dict with a 'content' key.
    """
    return {
        "choices": [
            {
                "message": {
                    "content": "Once upon a time in a magical forest..."
                }
            }
        ]
    }


def mock_ffmpeg_run(*args: Any, **kwargs: Any) -> MagicMock:
    """
    Mock for subprocess.run that simulates successful FFmpeg execution.
    """
    mock_process = MagicMock()
    mock_process.returncode = 0
    mock_process.stdout = b"ffmpeg output"
    mock_process.stderr = b""
    return mock_process


def mock_save_file(*args: Any, **kwargs: Any) -> str:
    """
    Mock for any function that saves a temporary file and returns its path.
    Returns a deterministic path inside the test directory.
    """
    return str(Path(__file__).parent / "temp_mock_file.txt")


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_root_endpoint(client: TestClient) -> None:
    """
    Verify that the root endpoint ("/") returns a 200 status code and a JSON
    payload containing a welcome message.
    """
    response = client.get("/")
    assert response.status_code == 200, "Root endpoint should respond with HTTP 200"
    data = response.json()
    assert isinstance(data, dict), "Response JSON should be a dictionary"
    assert "message" in data, "Root response must contain a 'message' key"
    assert "Interactive Storytelling" in data["message"], "Welcome message should reference the project"


def test_generate_story_success(client: TestClient) -> None:
    """
    Test the `/generate` endpoint with a valid prompt.
    The test patches external dependencies (OpenAI API, FFmpeg, file I/O) to
    ensure deterministic behavior without network or heavy processing.
    """
    test_prompt = "A brave knight embarks on a quest."

    # Patch the OpenAI call, FFmpeg execution, and any file-saving utilities.
    with patch("openai.ChatCompletion.create", side_effect=mock_openai_chat_completion_create), \
         patch("subprocess.run", side_effect=mock_ffmpeg_run), \
         patch("main.save_temp_file", side_effect=mock_save_file), \
         patch("main.upload_to_storage", return_value="https://example.com/mock_asset.mp4"):

        response = client.post(
            "/generate",
            json={"prompt": test_prompt},
            headers={"Content-Type": "application/json"},
        )

    # Basic response checks
    assert response.status_code == 200, f"Expected 200 OK, got {response.status_code}"
    payload = response.json()
    assert isinstance(payload, dict), "Response payload must be a JSON object"

    # Verify that the expected keys are present
    expected_keys = {"story", "audio_url", "image_url"}
    missing = expected_keys - payload.keys()
    assert not missing, f"Response is missing keys: {missing}"

    # Verify that the mocked story content is returned
    assert payload["story"] == "Once upon a time in a magical forest...", \
        "The story content should match the mocked OpenAI response"

    # Verify that the mocked URLs are returned
    assert payload["audio_url"] == "https://example.com/mock_asset.mp4", \
        "Audio URL should be the mocked storage URL"
    assert payload["image_url"] == "https://example.com/mock_asset.mp4", \
        "Image URL should be the mocked storage URL"


def test_generate_story_missing_prompt(client: TestClient) -> None:
    """
    Ensure that the `/generate` endpoint returns a 422 error when the required
    `prompt` field is omitted from the request body.
    """
    response = client.post(
        "/generate",
        json={},  # No prompt provided
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 422, "Missing prompt should result in HTTP 422 Unprocessable Entity"
    error_detail = response.json().get("detail")
    assert isinstance(error_detail, list), "Error detail should be a list of validation errors"
    assert any(err.get("loc") == ["body", "prompt"] for err in error_detail), \
        "Validation error should point to missing 'prompt' field"


def test_generate_story_openai_failure(client: TestClient) -> None:
    """
    Simulate an OpenAI API failure and verify that the endpoint returns a
    502 Bad Gateway error with a helpful message.
    """
    test_prompt = "A dragon guards a treasure."

    def mock_failure(*args: Any, **kwargs: Any) -> None:
        raise Exception("OpenAI service unavailable")

    with patch("openai.ChatCompletion.create", side_effect=mock_failure):
        response = client.post(
            "/generate",
            json={"prompt": test_prompt},
            headers={"Content-Type": "application/json"},
        )

    assert response.status_code == 502, "OpenAI failure should map to HTTP 502 Bad Gateway"
    payload = response.json()
    assert "error" in payload, "Error response must contain an 'error' key"
    assert "OpenAI" in payload["error"], "Error message should reference OpenAI"


def test_generate_story_ffmpeg_failure(client: TestClient) -> None:
    """
    Simulate a failure in the FFmpeg subprocess and verify that the endpoint
    returns a 500 Internal Server Error.
    """
    test_prompt = "A spaceship lands on a distant planet."

    with patch("openai.ChatCompletion.create", side_effect=mock_openai_chat_completion_create), \
         patch("subprocess.run", side_effect=lambda *a, **kw: MagicMock(returncode=1, stderr=b"ffmpeg error")), \
         patch("main.save_temp_file", side_effect=mock_save_file):

        response = client.post(
            "/generate",
            json={"prompt": test_prompt},
            headers={"Content-Type": "application/json"},
        )

    assert response.status_code == 500, "FFmpeg failure should result in HTTP 500 Internal Server Error"
    payload = response.json()
    assert "error" in payload, "Error response must contain an 'error' key"
    assert "FFmpeg" in payload["error"], "Error message should reference FFmpeg"


# ---------------------------------------------------------------------------
# End of file
# ---------------------------------------------------------------------------