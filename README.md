# Profile Adaptor

Local-first tool that crawls a hiring job description (JD), parses your resume, runs section checkers, collects human-in-the-loop confirmations (salary / work years / work base / template), rewrites the resume with **Ollama** or a **web OpenAI-compatible LLM**, audits fidelity, and exports **Word** (and optional **PDF**).

## Features

- **JD crawl** from URL or local `--jd-file` / pasted text
- **Resume parse** for `.docx` and `.pdf` (document-skills aligned: `python-docx`, `pdfplumber`/`pypdf`)
- **Dual LLM**: local Ollama **or** configurable web endpoint
- **Checkers**: primary job content, job requirements, education, work experience
- **HITL gates**: salary, work years, work base, template selector
- **Surfaces**: Textual **TUI**, local **browser UI**, and one-shot **CLI**

## Setup

```bash
cd Profile_Adaptor
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

### Ollama (default)

```bash
ollama serve
ollama pull qwen3.5:9b
```

### Web LLM endpoint

Edit `.env`:

```env
PROVIDER=web
WEB_LLM_BASE_URL=https://api.openai.com/v1
WEB_LLM_API_KEY=sk-...
WEB_LLM_MODEL=gpt-4o-mini
```

Any OpenAI-compatible `/v1/chat/completions` server works (including local gateways).

## Usage

### One-shot CLI

```bash
python -m profile_adaptor run \
  --jd-file ./samples/sample_jd.txt \
  --resume ./samples/sample_resume.docx \
  --salary "40-50k" \
  --years 5 \
  --base "Shanghai" \
  --provider ollama \
  --pdf
```

HITL fields `--salary`, `--years`, and `--base` are **required** (no silent defaults).

Template:

- omit `--template` → reuse source resume DOCX layout
- `--template ./templates/foo.docx` or a filename under `templates/`

### TUI

```bash
python -m profile_adaptor tui
```

### Browser UI (localhost)

```bash
python -m profile_adaptor web --port 8765
```

Open http://127.0.0.1:8765 — upload resume, paste/URL JD, confirm HITL fields, select template, download outputs.

## Outputs

Written under `output/`:

| File | Purpose |
|------|---------|
| `*_adapted.docx` | Adapted resume |
| `*_adapted.pdf` | Optional PDF |
| `*_context.json` | HITL + checker + run metadata |
| `*_audit.json` | Fidelity audit flags |

## Pipeline

1. Load JD (URL or file) + parse resume  
2. Run checkers (job content / requirements / education / work experience)  
3. Require HITL: salary, work years, work base, template  
4. Rewrite via LLM (facts preserved; skills expanded only when implied)  
5. Fidelity audit (rules + optional LLM)  
6. Fill template or source DOCX → export  

## Notes

- PDF resumes need a DOCX `--template` (source-layout reuse requires DOCX).
- SPA-heavy job boards may need paste / `--jd-file`.
- `--strict` fails the run on high-severity audit flags.
- `--override-checkers` continues despite checker errors (TUI enables this by default after you review fields).
