# Interactive Storytelling Generator with Voice & Visuals

## Project Overview

The **Interactive Storytelling Generator** is a web application that creates immersive, AI‑driven stories enriched with synthesized voice narration and dynamic visual scenes. Users can:

- Provide a story prompt or let the system generate a story from a theme.
- Choose a narrator voice (male/female, language, style).
- Generate accompanying images or short video clips for each scene.
- Interact with the story in real‑time (pause, skip, replay).

The backend is powered by **FastAPI** and the **OpenAI API** (GPT‑4o for text generation, Whisper for speech synthesis, DALL·E for images). Media processing (audio concatenation, video assembly) is handled by **FFmpeg**. The frontend is built with **React** and communicates with the API via a clean OpenAPI contract.

## Tech Stack

| Layer | Technology |
|-------|------------|
| **Backend** | Python 3.11, FastAPI, Pydantic, OpenAI SDK, FFmpeg (via `ffmpeg-python`) |
| **Frontend** | React 18, TypeScript, Vite, Axios |
| **AI Services** | OpenAI GPT‑4o (text), OpenAI TTS (audio), DALL·E (images) |
| **Deployment** | Docker, Docker‑Compose, Uvicorn (ASGI server) |
| **Testing** | Pytest, HTTPX, React Testing Library |
| **CI/CD** | GitHub Actions (lint, test, build) |

## Repository Structure

```
interactive-storytelling/
├── backend/
│   ├── app/
│   │   ├── api/                # FastAPI routers
│   │   ├── core/               # Settings, logging
│   │   ├── models/             # Pydantic schemas
│   │   ├── services/           # OpenAI, FFmpeg wrappers
│   │   └── main.py             # FastAPI entry point
│   ├── tests/                  # Pytest suite
│   ├── Dockerfile
│   └── requirements.txt
├── frontend/
│   ├── src/
│   │   ├── components/
│   │   ├── pages/
│   │   └── api/                # Axios wrappers
│   ├── public/
│   ├── index.html
│   ├── vite.config.ts
│   ├── tsconfig.json
│   └── package.json
├── docker-compose.yml
├── .github/workflows/ci.yml
└── README.md
```

## Prerequisites

- **Docker** & **Docker‑Compose** (recommended for a one‑click dev environment)
- **Python 3.11+** (if you prefer a local virtual environment)
- **Node.js 20+** & **npm** (for the frontend)
- An **OpenAI API key** with access to GPT‑4o, Whisper, and DALL·E.

## Setup

### 1. Clone the repository

```bash
git clone https://github.com/yourusername/interactive-storytelling.git
cd interactive-storytelling
```

### 2. Environment variables

Create a `.env` file in the project root (Docker will automatically load it). Required variables:

```dotenv
# OpenAI
OPENAI_API_KEY=sk-...

# FastAPI
HOST=0.0.0.0
PORT=8000

# FFmpeg (optional custom path)
FFMPEG_PATH=/usr/bin/ffmpeg
```

### 3. Development (Docker)

The quickest way to start everything:

```bash
docker compose up --build
```

- Backend API will be reachable at `http://localhost:8000`.
- Frontend will be served at `http://localhost:5173`.

### 4. Development (Local Python & Node)

#### Backend

```bash
# Create and activate a virtual environment
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate

# Install dependencies
pip install -r backend/requirements.txt

# Run the API
uvicorn backend/app.main:app --host 0.0.0.0 --port 8000 --reload
```

#### Frontend

```bash
cd frontend
npm install
npm run dev
```

### 5. Running Tests

```bash
# Backend tests
pytest backend/tests

# Frontend tests
cd frontend
npm run test
```

## Usage

### API Endpoints (selected)

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/v1/story/generate` | Accepts a prompt or theme, returns story JSON with scene texts. |
| `POST` | `/api/v1/voice/synthesize` | Takes a text snippet and voice settings, returns an MP3 file. |
| `POST` | `/api/v1/visual/create` | Generates an image for a scene using DALL·E. |
| `GET`  | `/api/v1/media/assemble` | Combines audio and images into a short video (MP4). |
| `GET`  | `/api/v1/health` | Simple health check. |

Full OpenAPI docs are available at `http://localhost:8000/docs`.

### Example Workflow (via Frontend)

1. **Enter a prompt** – “A lost kitten finds its way home through a magical forest.”
2. **Select narrator** – Female, calm, English US.
3. **Press “Generate”** – The backend returns a structured story with 5 scenes.
4. **Generate media** – For each scene the UI triggers voice synthesis and image creation.
5. **Assemble** – The backend stitches audio + images into a video per scene; the UI streams them sequentially.
6. **Interact** – Users can pause, replay, or request alternative visual styles.

## Architecture Highlights

- **FastAPI** provides async endpoints, automatic validation via Pydantic, and OpenAPI schema generation.
- **OpenAIService** abstracts all calls to the OpenAI SDK, handling retries and rate‑limit back‑off.
- **MediaService** uses `ffmpeg-python` to:
  - Concatenate multiple audio fragments.
  - Overlay images on a silent video track.
  - Export MP4 with H.264/AAC for web compatibility.
- **React** consumes the API with a thin Axios wrapper, maintains story state in a Redux store, and uses the HTML5 `<video>` element for playback.
- **Docker** isolates dependencies (Python, Node, FFmpeg) and simplifies deployment to any cloud provider.

## Production Deployment

A typical production stack uses:

- **Docker Swarm** or **Kubernetes** for container orchestration.
- **NGINX** as a reverse proxy, handling TLS termination.
- **Redis** for caching generated media (keyed by hash of prompt + voice settings) to reduce API costs.
- **Celery** (or FastAPI background tasks) for long‑running media assembly jobs, with a RabbitMQ/Redis broker.

Example `docker-compose.prod.yml` (excerpt):

```yaml
services:
  api:
    image: ghcr.io/yourusername/interactive-storytelling-api:latest
    environment:
      - OPENAI_API_KEY=${OPENAI_API_KEY}
      - REDIS_URL=redis://redis:6379/0
    depends_on:
      - redis
    restart: always

  frontend:
    image: ghcr.io/yourusername/interactive-storytelling-frontend:latest
    ports:
      - "80:80"
    restart: always

  redis:
    image: redis:7-alpine
    restart: always
```

## Security Considerations

- **API keys** are never committed; they are injected via environment variables or secret managers.
- **Input validation**: Pydantic schemas enforce length limits and sanitize user‑provided text.
- **Rate limiting**: Implemented with a FastAPI middleware (e.g., `slowapi`) to protect OpenAI usage.
- **CORS**: Configured to allow only the frontend origin in production.

## Contributing

1. Fork the repository.
2. Create a feature branch (`git checkout -b feature/awesome-idea`).
3. Write tests for new functionality.
4. Ensure `pytest` and `npm test` both pass.
5. Submit a Pull Request with a clear description.

Please follow the **PEP 8** style guide for Python and **Airbnb** style guide for TypeScript/JavaScript.

## License

This project is licensed under the **MIT License** – see the `LICENSE` file for details.

---

*Happy storytelling!*