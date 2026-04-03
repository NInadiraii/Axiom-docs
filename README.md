# DocMind — Micro-SaaS MVP

> Ask questions about your PDFs. Contextual retrieval powered by FAISS + LangChain v2.

---

## Architecture

```
┌─────────────────────────────────────────────────┐
│  Browser (templates/index.html)                 │
│  ┌──────────┐  ┌────────────────────────────┐   │
│  │  Upload   │  │   Chat Window              │   │
│  │  Sidebar  │  │   (query → answer + cite)  │   │
│  └──────────┘  └────────────────────────────┘   │
└──────────────────┬──────────────────────────────┘
                   │  REST API
┌──────────────────▼──────────────────────────────┐
│  Flask Backend (app.py)                         │
│                                                 │
│  POST /api/upload  → save PDF, rebuild FAISS    │
│  POST /api/query   → similarity search → answer │
│  GET  /api/usage   → return tier + counts       │
│  POST /api/upgrade → switch to tier_2           │
│                                                 │
│  ┌─────────────┐  ┌──────────────────────────┐  │
│  │ UsageTracker │  │  FAISS VectorStore       │  │
│  │ (JSON file)  │  │  (per-user index)        │  │
│  └─────────────┘  └──────────────────────────┘  │
└─────────────────────────────────────────────────┘
```

## Contextual Retrieval

When a user uploads a PDF:
1. `PyPDFLoader` extracts text page-by-page
2. `RecursiveCharacterTextSplitter` chunks each page (800 chars, 150 overlap)
3. Each chunk retains `source_file` and `page` metadata
4. All chunks are embedded with `all-MiniLM-L6-v2` and stored in a **per-user FAISS index**

When a user asks a question:
1. The query is embedded and matched against **only their documents** (contextual)
2. Top-4 chunks are retrieved with source citations
3. The answer is returned with file + page references

## Usage Tiers

| Feature              | Starter (free) | Pro           |
|----------------------|-----------------|---------------|
| Documents            | 2               | 50            |
| Queries / month      | 50              | Unlimited     |

Usage is tracked in `usage_data.json`. In production, replace with a database.

## Quick Start

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Run the server
python app.py

# 3. Open http://localhost:5000
```

## Adding a Real LLM

The MVP returns raw retrieved chunks. To get synthesized AI answers, add one
of these to your environment and update the `_answer_from_context()` function:

```bash
# Option A: OpenAI
export OPENAI_API_KEY="sk-..."

# Option B: Anthropic
export ANTHROPIC_API_KEY="sk-ant-..."
```

Then swap in `ChatOpenAI` or `ChatAnthropic` from LangChain in `app.py`.

## Project Structure

```
docmind/
├── app.py              # Flask backend + all logic
├── requirements.txt    # Python dependencies
├── templates/
│   └── index.html      # Single-page frontend
├── uploads/            # Per-user PDF storage (auto-created)
├── vectorstores/       # Per-user FAISS indexes (auto-created)
└── usage_data.json     # Usage tracking (auto-created)
```

## Production Checklist

- [ ] Replace JSON usage store with PostgreSQL / Redis
- [ ] Add authentication (e.g., Flask-Login + OAuth)
- [ ] Connect Stripe for tier upgrades
- [ ] Plug in an LLM (OpenAI / Anthropic) for synthesized answers
- [ ] Add rate limiting (Flask-Limiter)
- [ ] Deploy with Gunicorn + nginx
- [ ] Move FAISS indexes to cloud storage (S3)
