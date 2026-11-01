# Lorebook

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
- `uv run alembic revision --autogenerate -m "..."` - after changing `models.py`; migrations
  run on startup

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
  auth.py            accounts (e-mail + password, registration only for ALLOWED_EMAILS, mailed
                     reset), owner check on every API call; off when ALLOWED_EMAILS is empty
  importing/         file -> paragraphs -> chapters, no AI
  services/versions.py  whole-book commits and rollback
  llm/registry.py    the only place that builds chat models and lists provider models
  llm/calls.py       TextModel: the configured text model, JSON output, usage journal
  analysis/          LangGraph loop that finds characters and locations, its prompts,
                     the background runner
  llm/provision.py   the Hubris connection created from HUBRIS_API_KEY at startup
  rag/               local embeddings, chunk index and hybrid search, chat with citations
  images/            project style, image prompt from a card, image generation client
  scenes/            scene split, references for a scene, video prompt, archive
  api/               REST routes
frontend/src/
  api.ts             typed client
  i18n.tsx           every UI string, Russian and English
  pages/, components/
data/                runtime, gitignored: PostgreSQL cluster, uploads, secret.key
_private/, _reference/  gitignored: the owner's test book and the earlier Node prototype
demo/                a short original story used for demos and end-to-end checks
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
- Every model call goes through `TextModel` so it lands in the usage journal. Raw model
  answers are stored per chapter (`chapter_extractions`) keyed by text hash and
  `PROMPT_VERSION`; bump the version when the extraction prompt changes.
- Quotes shown as sources are verified against the chapter text; an unverified quote is
  dropped, never displayed.
- Cards are read-only, with one exception: the user may merge two cards or split a name
  into its own card (`pinned_names`, `standalone`). Later runs must keep those decisions.
- Embeddings are local (fastembed). Chunks are a few sentences because the model reads
  about 128 tokens; search returns each hit with its neighbours.
- Pictures are never deleted as a side effect, only by the user's own action. Each one
  carries the `style_key` it was made in; only pictures in the project's current style are
  offered as references.
- Every UI string goes through `i18n.tsx` in both languages. The server returns error
  codes (`reader_mode_readonly`), the frontend translates them.
- Book text and anything from `_private/` never goes into the repository.
- The hosted pool is tiny (4 connections). Never touch the database on the event loop
  (async code goes through `run_in_threadpool`), and call `db.release_connection(session)`
  before any wait on a model or provider; `TextModel` and `ImageModel` already do. It can
  only give back a transaction that has not written, so add rows after the model has
  answered, not before (as the chat does with the question). The
  healthcheck is `/api/health` and must not use the database.

## Build order

1. Projects, import, chapters, reader, connections - done
2. Characters and locations on demand (LangGraph, per chapter, resumable), usage journal - done
3. Chat over the book with citations (RAG, pgvector) - done
4. Project style, images of characters and locations, looks by chapter - done, except
   that image generation has only been exercised against a mocked HTTP endpoint
5. Scenes, first frame, video prompt, reference archive - done; the first frame, like
   all image generation, has not been run against a real provider yet
6. Writer extras: refresh of stale cards, plot suggestions - done
7. Docker, shared password for hosting, Alembic migrations, README - written; the Docker
   setup has not been run (no Docker on the development machine). Opening the repository
   is the owner's call.
