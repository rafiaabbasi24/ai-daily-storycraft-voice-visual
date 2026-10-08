import os
import uuid
import shutil
import subprocess
import logging
from pathlib import Path
from typing import List, Optional

import openai
from fastapi import FastAPI, HTTPException, BackgroundTasks, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, BaseSettings, Field, validator

# --------------------------------------------------------------------------- #
# Configuration
# --------------------------------------------------------------------------- #


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    openai_api_key: str = Field(..., env="OPENAI_API_KEY")
    # Directory where generated assets are stored (served as static files)
    assets_dir: Path = Path("assets")
    # Path to ffmpeg executable (assumed to be in PATH if not provided)
    ffmpeg_path: str = "ffmpeg"
    # Default voice for TTS (OpenAI supported voice identifiers)
    default_voice: str = "alloy"
    # Maximum length of generated story (tokens)
    max_story_tokens: int = 500

    class Config:
        env_file = ".env"
        case_sensitive = False


settings = Settings()
openai.api_key = settings.openai_api_key

# Ensure assets directory exists
settings.assets_dir.mkdir(parents=True, exist_ok=True)

# --------------------------------------------------------------------------- #
# Logging
# --------------------------------------------------------------------------- #

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("storytelling_app")

# --------------------------------------------------------------------------- #
# Pydantic models
# --------------------------------------------------------------------------- #


class StoryRequest(BaseModel):
    """Payload for story generation."""

    prompt: str = Field(..., description="User supplied story prompt.")
    voice: Optional[str] = Field(
        None,
        description="Voice identifier for TTS. If omitted, default voice is used.",
    )
    image_style: Optional[str] = Field(
        None,
        description="Optional style hint for image generation (e.g., 'oil painting').",
    )
    num_images: int = Field(
        5,
        ge=1,
        le=10,
        description="Number of images to generate for the visual story.",
    )

    @validator("prompt")
    def non_empty_prompt(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Prompt must not be empty")
        return v


class StoryResponse(BaseModel):
    """Response returned after generation completes."""

    story_text: str = Field(..., description="Generated story text.")
    audio_url: str = Field(..., description="URL to the generated narration audio.")
    video_url: str = Field(..., description="URL to the generated video montage.")
    asset_id: str = Field(..., description="Unique identifier for the generated assets.")


# --------------------------------------------------------------------------- #
# Helper functions
# --------------------------------------------------------------------------- #


def _run_ffmpeg(command: List[str]) -> None:
    """Execute an ffmpeg command, raising on failure."""
    logger.debug("Running ffmpeg command: %s", " ".join(command))
    result = subprocess.run(
        command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False, text=True
    )
    if result.returncode != 0:
        logger.error("ffmpeg error: %s", result.stderr)
        raise RuntimeError(f"ffmpeg failed: {result.stderr}")


def generate_story_text(prompt: str, max_tokens: int) -> str:
    """Generate story text using OpenAI's ChatCompletion API."""
    logger.info("Generating story text for prompt: %s", prompt)
    response = openai.ChatCompletion.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": "You are a creative storyteller."},
            {"role": "user", "content": prompt},
        ],
        max_tokens=max_tokens,
        temperature=0.8,
    )
    story = response.choices[0].message.content.strip()
    logger.debug("Generated story text: %s", story)
    return story


def generate_voice narration(text: str, voice: str, output_path: Path) -> None:
    """Generate speech audio using OpenAI's audio speech endpoint."""
    logger.info("Generating voice audio (voice=%s) to %s", voice, output_path)
    # OpenAI's TTS endpoint (as of 2024) is `audio.speech`
    response = openai.audio.speech.create(
        model="tts-1",
        voice=voice,
        input=text,
    )
    # The response is a streaming binary; write to file
    with open(output_path, "wb") as f:
        for chunk in response.iter_bytes():
            f.write(chunk)
    logger.debug("Audio saved to %s", output_path)


def generate_images(prompt: str, style: Optional[str], count: int, output_dir: Path) -> List[Path]:
    """Generate a list of images using OpenAI's image generation API."""
    logger.info("Generating %d images for prompt: %s", count, prompt)
    images: List[Path] = []
    for i in range(count):
        full_prompt = f"{prompt}. {style}" if style else prompt
        response = openai.images.generate(
            model="dall-e-3",
            prompt=full_prompt,
            n=1,
            size="1024x1024",
        )
        image_url = response.data[0].url
        # Download the image
        image_path = output_dir / f"image_{i + 1}.png"
        with open(image_path, "wb") as f:
            f.write(openai.File.download(image_url).content)  # type: ignore
        images.append(image_path)
        logger.debug("Saved image %d to %s", i + 1, image_path)
    return images


def create_video_from_images(
    image_paths: List[Path], audio_path: Path, output_path: Path, fps: int = 1
) -> None:
    """
    Combine images and audio into a video using ffmpeg.

    Each image is shown for ``1/fps`` seconds.
    """
    logger.info("Creating video %s from %d images and audio %s", output_path, len(image_paths), audio_path)

    # Create a temporary text file listing the images for ffmpeg concat demuxer
    list_file = output_path.parent / f"{output_path.stem}_images.txt"
    with open(list_file, "w", encoding="utf-8") as f:
        for img_path in image_paths:
            f.write(f"file '{img_path.resolve()}'\n")
            f.write(f"duration {1 / fps}\n")
        # Repeat last frame to ensure video length matches audio
        f.write(f"file '{image_paths[-1].resolve()}'\n")

    # Build ffmpeg command
    command = [
        settings.ffmpeg_path,
        "-y",  # overwrite output
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        str(list_file),
        "-i",
        str(audio_path),
        "-c:v",
        "libx264",
        "-r",
        str(fps),
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-shortest",
        str(output_path),
    ]
    _run_ffmpeg(command)

    # Cleanup temporary list file
    list_file.unlink(missing_ok=True)
    logger.debug("Video creation complete: %s", output_path)


def clean_up_temp_dir(temp_dir: Path) -> None:
    """Recursively delete a temporary directory."""
    logger.debug("Cleaning up temporary directory %s", temp_dir)
    shutil.rmtree(temp_dir, ignore_errors=True)


# --------------------------------------------------------------------------- #
# FastAPI application
# --------------------------------------------------------------------------- #

app = FastAPI(
    title="Interactive Storytelling Generator",
    description="Generate stories with AI-generated narration and visual slides.",
    version="1.0.0",
)


# Allow browsers to call the API from any origin (adjust in production)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve generated assets
app.mount("/assets", StaticFiles(directory=str(settings.assets_dir)), name="assets")


@app.post("/generate", response_model=StoryResponse, summary="Generate story, audio, and video")
async def generate_story(request: StoryRequest, background_tasks: BackgroundTasks):
    """
    Generate a story based on the supplied prompt, synthesize narration,
    create illustrative images, and combine everything into a video.
    The heavy lifting is performed in a background task so the request returns
    only after all assets are ready.
    """
    asset_id = uuid.uuid4().hex
    asset_dir = settings.assets_dir / asset_id
    asset_dir.mkdir(parents=True, exist_ok=True)

    # Paths for generated assets
    audio_path = asset_dir / "narration.mp3"
    video_path = asset_dir / "story.mp4"
    images_dir = asset_dir / "images"
    images_dir.mkdir(parents=True, exist_ok=True)

    # Determine voice
    voice = request.voice or settings.default_voice

    # Generate story text (blocking but fast)
    try:
        story_text = generate_story_text(request.prompt, settings.max_story_tokens)
    except Exception as exc:
        logger.exception("Failed to generate story text")
        raise HTTPException(status_code=500, detail="Story generation failed") from exc

    # Schedule heavy tasks in background to avoid blocking the event loop
    def heavy_workflow():
        try:
            # 1. Generate narration audio
            generate_voice narration(story_text, voice, audio_path)

            # 2. Generate images
            image_paths = generate_images(
                request.prompt,
                request.image_style,
                request.num_images,
                images_dir,
            )

            # 3. Assemble video
            create_video_from_images(image_paths, audio_path, video_path, fps=1)

        except Exception as exc:
            logger.exception("Error during asset generation for %s", asset_id)
        finally:
            # Clean up temporary images (keep audio & video)
            clean_up_temp_dir(images_dir)

    background_tasks.add_task(heavy_workflow)

    # Build URLs that clients can use to retrieve assets
    audio_url = app.url_path_for("static", path=f"{asset_id}/narration.mp3")
    video_url = app.url_path_for("static", path=f"{asset_id}/story.mp4")

    # Return response immediately; assets will be ready shortly.
    return StoryResponse(
        story_text=story_text,
        audio_url=audio_url,
        video_url=video_url,
        asset_id=asset_id,
    )


@app.get("/health", summary="Health check")
def health_check():
    """Simple health endpoint used by orchestration tools."""
    return {"status": "ok"}


# --------------------------------------------------------------------------- #
# Entry point for local development
# --------------------------------------------------------------------------- #

if __name__ == "__main__":
    import uvicorn

    uvicorn.run("src.main:app", host="0.0.0.0", port=8000, reload=True)