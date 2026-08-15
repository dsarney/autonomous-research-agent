# Autonomous Research Agent

An AI research app that plans an investigation, searches the web, evaluates coverage, fills gaps, and writes a cited report with confidence levels.

## Setup

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Set `OPENAI_API_KEY` in `.env`. Optional settings:

- `OPENAI_MODEL` (default `gpt-4o-mini`)
- `MAX_ITERATIONS` (default `3`)
- `MAX_SEARCHES_PER_RUN` (default `8`)
- `OPENAI_TIMEOUT_SECONDS` (default `120`)
- `RELEVANCE_THRESHOLD` (default `0.35`)

## Run

```bash
source venv/bin/activate
uvicorn app.main:app --reload
```

Open http://127.0.0.1:8000

Enter a research question and click **Run research**. The page shows each stage as it happens (plan, search, evaluate, write), including the live activity log and the research plan.

**Stop** cancels an in-progress run so you can edit the question and send it again. When a report is complete, download it as **Word** (editable `.docx`) or **PDF**.

API:

- `GET /health` — process is up
- `POST /research/plan` — question to research plan
- `POST /research/search` — web search for a query or sub-questions
- `POST /research/run` — full loop (`wait: true` to block until complete)
- `POST /research/{id}/stop` — cancel an in-progress run (drops the OpenAI request)
- `GET /research/{id}` — poll a run
- `GET /research/{id}/export.docx` — editable Word report
- `GET /research/{id}/export.pdf` — PDF for sharing

## Tests

```bash
pytest
```

Tests mock OpenAI. Live runs use OpenAI web search and incur API usage; keep iteration and search caps low while developing.
