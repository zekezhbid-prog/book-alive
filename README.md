# Book Alive

Turn a book into chapters, characters, locations and scenes, and get ready-to-use prompts
and reference images for AI video. Built with FastAPI, LangChain, LangGraph, PostgreSQL
with pgvector, and React.

> Work in progress. What exists today is listed under "Status".

## Two kinds of projects

- **Finished book.** Upload a text; it is read-only. You pick out characters, locations
  and scenes and prepare them for animation.
- **Writing a book.** Write and edit chapters in the app. One commit saves a version of the
  whole book, and any version can be restored. The illustrator tools work here too.

## Principles

- **No surprise spending.** Import splits the book into chapters without any AI. Every
  model call starts from a button, and expensive ones show an estimate first.
- **Bring your own models.** A connection is an address and a key for any OpenAI-compatible
  API (OpenRouter, OmniRoute, ...). Text and image models are chosen separately.
- **Use a Claude subscription for text.** On your own machine the app can call the local
  Claude Code CLI, so text work is covered by the subscription.

## Status

- [x] Projects, import (TXT, EPUB, FB2, DOCX, text PDF), chapter detection, manual fixes
- [x] Reader with search; writer mode with autosave, versions and rollback
- [x] Connections, model list with a free-only filter, connection test
- [ ] Characters and locations on demand, with source quotes
- [ ] Chat over the book with citations
- [ ] Images of characters and locations in one project style
- [ ] Scenes, first frame, video prompt, reference archive
- [ ] Docker and hosting

## Run locally

Requires [uv](https://docs.astral.sh/uv/) and Node.js 22+. No database to install: with
`DATABASE_URL` empty, an embedded PostgreSQL with pgvector starts in `data/`.

```bash
cd frontend && npm install && npm run build && cd ..
cd backend && uv sync && uv run uvicorn app.main:app --port 8000
```

Open http://127.0.0.1:8000, then add a connection in Settings.

For development run the API with `--reload` and `npm run dev` in `frontend/` (port 5173).

## Tests

```bash
cd backend && uv run pytest -q
```
