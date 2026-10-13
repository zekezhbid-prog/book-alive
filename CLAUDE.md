# Book Alive

Web app that turns a book into chapters, characters, locations, scenes and prompts for
AI video. Two goals, in this order: a portfolio project showing Python + LangChain/LangGraph
+ RAG, and a useful tool for illustrators and writers. When features and code quality
compete, code quality wins.

The agreed product decisions are in `docs/decisions.md` (Russian). Read it before changing
behaviour; it records what the owner chose and what was deliberately left out.

## Commands

Backend (from `backend/`, Python 3.12 via uv):
- `uv run uvicorn app.main:app --reload --port 8000` - API; also serves `frontend/dist` if built
- `uv run pytest -q` - tests (start their own throwaway embedded PostgreSQL)
- `uv run ruff check . && uv run ruff format .`

Frontend (from `frontend/`):
- `npm run dev` - Vite on :5173, proxies `/api` to :8000
- `npm run build` - type-check and build into `dist/`
- `npm run lint`

## Layout

```
backend/app/
  main.py            FastAPI app, serves the built frontend
  config.py          settings from environment / .env
  db.py              engine, session, embedded PostgreSQL when DATABASE_URL is empty
  models.py          SQLAlchemy models
  crypto.py          encryption of stored API keys
  importing/         file -> paragraphs -> chapters, no AI
  services/versions.py  whole-book commits and rollback
  llm/registry.py    the only place that builds chat models and lists provider models
  llm/claude_cli.py  LangChain chat model over the local Claude Code CLI (subscription)
  api/               REST routes
frontend/src/
  api.ts             typed client
  i18n.tsx           every UI string, Russian and English
  pages/, components/
data/                runtime, gitignored: PostgreSQL cluster, uploads, secret.key
_private/, _reference/  gitignored: the owner's test book and the earlier Node prototype
```

## Rules that hold everywhere

- Nothing calls an AI model unless the user pressed a button for it. Import only splits
  the book into chapters, deterministically.
- All model access goes through `llm/registry.py`. No provider SDK calls elsewhere.
- API keys are stored encrypted and never returned to the browser, only the last 4 characters.
- A "finished book" project (`reader`) has read-only text and no versions. A "writing"
  project (`writer`) has the editor and whole-book versions. Chapter boundaries can be
  fixed by hand in both.
- Derived data (characters, locations, scenes) is read-only for the user and records the
  `content_hash` of the chapter text it was computed from. Different hash means stale.
  Nothing is recomputed automatically.
- Every UI string goes through `i18n.tsx` in both languages. The server returns error
  codes (`reader_mode_readonly`), the frontend translates them.
- Book text and anything from `_private/` never goes into the repository.

## Build order

1. Projects, import, chapters, reader, connections - done
2. Characters and locations on demand (LangGraph, per chapter, resumable), usage journal
3. Chat over the book with citations (RAG, pgvector)
4. Project style, images of characters and locations, looks by chapter
5. Scenes, first frame, video prompt, reference archive
6. Writer extras: stale markers, plot suggestions
7. Docker, shared password for hosting, README, opening the repository
