# Google Classroom AI Assignment Assistant

A beginner-friendly Python project that:

1. Connects to your Google Classroom account via the official Google APIs (OAuth 2.0).
2. Reads your courses and fetches the assignments (coursework).
3. Detects new / pending assignments and tracks them in a local SQLite database.
4. Downloads attachments (PDF, DOCX, TXT, images), extracts their text.
5. Sends the assignment to an AI model and generates a structured answer.
6. Saves the answer as a `.docx` file and shows it to you.
7. **Only after you explicitly type `APPROVE` does it turn the assignment in** on Google Classroom.

> **Safety guarantee:** nothing is ever submitted automatically. The submission
> code lives in `app/classroom/submit.py` and can only be reached through the
> approval step in the review menu.

---

## Project structure

```
classroom_ai_agent/
├── app/
│   ├── main.py                 Phase 6: terminal menu + review/approval flow
│   ├── config.py               paths, OAuth scopes, AI settings (one place)
│   ├── classroom/
│   │   ├── auth.py            Phase 1: OAuth 2.0 login + token refresh
│   │   ├── client.py          Phase 1: Classroom + Drive service builders
│   │   ├── assignments.py     Phase 2: fetch + normalize coursework
│   │   └── submit.py          Phase 7: turnIn via the API (only after approval)
│   ├── files/
│   │   ├── downloader.py      Phase 3: download Drive attachments
│   │   ├── pdf_reader.py      Phase 3: PDF text (PyMuPDF)
│   │   ├── docx_reader.py     Phase 3: Word text (python-docx)
│   │   ├── image_reader.py    Phase 3: optional OCR
│   │   └── reader.py          Phase 3: picks the right reader by extension
│   ├── ai/
│   │   ├── client.py          Phase 4: OpenAI-compatible HTTP client
│   │   ├── prompts.py         Phase 4: system prompt + assignment packing
│   │   └── solver.py          Phase 4: solve_assignment() orchestrator
│   ├── output/
│   │   └── document_generator.py  Phase 5: builds the .docx
│   └── database/
│       └── db.py              Phase 2: SQLite storage + status tracking
├── data/
│   ├── downloads/             raw attachment files
│   ├── generated/             your answer .docx files
│   └── app.db                 SQLite database (created on first run)
├── credentials/               place credentials.json here (NEVER commit)
├── .env.example               copy to .env and fill in your AI key
├── .gitignore
├── requirements.txt
└── README.md
```

The idea behind the layout: **each phase of the spec maps to one folder**.
Classroom (read side), Files (input side), AI (thinking), Output (document),
Database (memory). `main.py` is the only file that knows about *all* of them —
that is the "agent" wiring, and you can see it all in one place.

---

## Architecture (why it's built this way)

```
Google Classroom  ──►  classroom/ (auth, client, assignments)
        │  raw API data
        ▼
database/db.py  ──────►  remembers what is NEW (status = pending)
        │
        ▼
files/ (downloader + readers)  ──►  "materials" text
        │
        ▼
ai/ (prompts + client + solver) ──►  solution text
        │
        ▼
output/document_generator.py ──►  answer.docx  (status = ready)
        │
        ▼
main.py review menu ──►  [view] [regenerate] [edit] [APPROVE] [cancel]
        │
        ▼
classroom/submit.py ──►  turnIn  (ONLY after you typed APPROVE)
```

**Why no LangChain?** A "reagent agent" adds abstractions that hide exactly the
part you are trying to learn. Here the whole pipeline is just functions calling
functions. When you understand this, adding an agent loop later is trivial —
and you'll know what it's actually doing under the hood.

---

## Phase 1 — Setup & authentication

### 1. Create the virtual environment and install dependencies

```powershell
# from the project root (classroom_ai_agent)
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
```

What's in `requirements.txt` and why:

| Package | Used for |
|---|---|
| `google-api-python-client` | The official Google client. Builds Classroom/Drive service objects. |
| `google-auth-oauthlib` | The `InstalledAppFlow` that opens the browser login page. |
| `google-auth` / `google-auth-httplib2` | Token handling + refresh. |
| `python-dotenv` | Reads `.env` so your API key is never in code. |
| `pymupdf` | PDF text extraction. |
| `python-docx` | Read .docx attachments AND write the final answer document. |
| `Pillow` | Open image attachments (used with optional OCR). |
| `requests` | The AI API call — plain HTTP on purpose, so you can see it. |

### 2. Set up the Google Cloud project (do this once ~10 min)

1. Go to <https://console.cloud.google.com/> → **New Project** → name it
   (e.g. `classroom-assistant`).
2. **Enable APIs**:
   - <https://console.cloud.google.com/apis/library/classroom.googleapis.com> → Enable
   - <https://console.cloud.google.com/apis/library/drive.googleapis.com> → Enable
   - The Drive API is only needed to *download the files attached* to assignments.
3. **OAuth consent screen** → create it:
   - User type: **External** (or Internal if you have a Workspace domain).
   - Audience: in some setups you must click **Add users** and add your own
     Google account as a test user (only matters if Google warns
     "app is not verified" in a browser).
4. **Credentials** →
   - **Create Credentials → OAuth client ID**
   - Application type: **Desktop App**
   - Download the JSON → save it exactly as `credentials/credentials.json`.

### 3. Explain the OAuth scopes (what we ask permission for)

`app/config.py` defines three scopes. Always use the *minimum* you need:

| Scope | Why |
|---|---|
| `classroom.courses.readonly` | Read the list of courses you belong to. |
| `classroom.coursework.me` | Read your assignments **and** turn in your own submissions. This is the exact scope Google requires for `studentSubmissions.turnIn`. |
| `drive.readonly` | Download the files a teacher attached to an assignment. Read-only — we never modify your Drive. |

No password is ever given to this program. The flow (in `auth.py`):

```text
token.json exists?
 ├─ yes, not expired                       -> use it
 ├─ yes, expired, has refresh token        -> refresh silently (no browser)
 └─ no (first run)                         -> open browser -> you approve
                                                 -> Google gives an access token
                                                    -> saved to credentials/token.json
```

### 4. Run Phase 1

```powershell
.\venv\Scripts\python.exe -m app.main
```

Choose:
- `[1] Authenticate with Google` → a browser opens, sign in, approve.
- `[2] List my courses` → you should see each course name and id.

Expected output for `[2]`:

```
  * Introduction to Statistics — Section B   (id: 123456789)
  * Artificial Intelligence 101              (id: 987654321)
```

### 5. Common Phase 1 errors

| Symptom | Fix |
|---|---|
| `Missing credentials/credentials.json` | Create the Desktop App OAuth client and download the JSON to that exact path. |
| Browser says "app not verified" | Click *Advanced → Go to unsafe* (it's your own app), or add yourself as a test user on the consent screen. |
| `invalid_grant` on refresh | Revoked access or changed client → delete `credentials/token.json`, run `[1]` again. |
| `409` on Drive | The user blocked Drive access; delete token and re-auth, approving all three scopes. |

---

## Phase 2 — Fetch assignments + SQLite tracking

**Where:** `app/classroom/assignments.py`, `app/database/db.py`.

- `assignments.py` calls `courses().courseWork().list()`, handles pagination
  (results come in pages of 100, so we loop until `nextPageToken` is gone), and
  converts the raw nested response into a flat dict.
- `db.py` stores one row per assignment. `(coursework_id, course_id)` is a
  `UNIQUE` key, so re-syncing **never duplicates**. Rows carry a `status`:

| status | meaning |
|---|---|
| `pending` | seen by the app for the first time — the "new assignment" detector |
| `ready` | AI solution generated, saved to `data/generated/`, awaiting your review |
| `approved` | you approved; turn-in was attempted but failed |
| `submitted` | turned in successfully |
| `cancelled` | you chose not to submit |

Run `[3] Sync assignments`, then `[4] Show pending assignments`.

---

## Phase 3 — Attachments: download + extract

**Where:** `app/files/*`.

- `downloader.py`: for each `driveFile` material, `files().get()` gives the
  MIME type; native Google Docs are **exported** to text (they aren't stored as
  files), everything else is streamed with `MediaIoBaseDownload`. Files over
  50 MB are skipped for safety. Links / YouTube have nothing to download and are
  kept as notes so the AI still knows they exist.
- `reader.py` is a dispatcher: `.pdf → pdf_reader`, `.docx → docx_reader`,
  `.png/.jpg → image_reader`, `.txt/.md → plain text`. Unknown extensions raise
  `UnsupportedFileTypeError`, which `main.py` catches and turns into
  "[unsupported file]" in the AI prompt — a failure never kills the app.
- `pdf_reader.py` uses PyMuPDF page text. A *scanned* PDF has no text layer, so
  it returns an honest message about OCR instead of fake content.
- `image_reader.py` does OCR **only if** you install Tesseract + `pytesseract`
  (optional). Without it, the image is reported as requiring a vision model.
  This keeps the default install 100% dependency-free.

---

## Phase 4 — The AI module

**Where:** `app/ai/*`.

The AI receives exactly the structured info from the spec:

```json
{
  "course": "Introduction to Statistics",
  "assignment_title": "Homework 3",
  "description": "Compute the mean of the dataset.",
  "due_date": "2026-10-01 23:59",
  "materials": "...text extracted from attachments...",
  "assignment_id": "abc123",
  "course_id": "123"
}
```

- `prompts.py` sets the standing rules (system prompt): identify the tasks,
  keep reasoning vs final answer separate (`## Reasoning` / `## Final Answer`),
  never invent data, explicitly list **missing information**, structured output.
- `client.py` is deliberately just `requests.post()`. An "AI call" is a POST
  with a JSON body (`model`, `messages`, `temperature`) to
  `{base_url}/chat/completions`. Because it follows the OpenAI-compatible
  format, switching providers = editing `.env` only:

| Provider | `AI_BASE_URL` | `AI_API_KEY` | `AI_MODEL` |
|---|---|---|---|
| OpenAI | `https://api.openai.com/v1` | `sk-...` | `gpt-4o-mini` |
| Groq (free tier) | `https://api.groq.com/openai/v1` | `gsk_...` | `llama3-70b-8192` |
| Ollama (local, free) | `http://localhost:11434/v1` | *(empty)* | `llama3.1` |

Copy `.env.example` → `.env` and fill in one provider. `client.py` raises
`AIError` with a readable reason on network failure, non-200 responses or a
malformed response — all caught in `main.py`.

---

## Phase 5 — Answer document

**Where:** `app/output/document_generator.py`.

Builds the `.docx` with `python-docx`:

```
Classroom AI Assistant — Solution
Course / Generated / Due date / IDs      (cover block)
Question / Task                          (your teacher's description)
Solution                                 (the AI text, page-break separated)
```

The AI reply uses a tiny Markdown subset, so `## Final Answer` becomes a real
Word heading, `- ` lines become bullets, and numbered lines become a numbered
list — the file reads like a professional write-up, not raw chat text.

---

## Phase 6 — Review interface (the safety gate)

**Where:** `app/main.py` → `review_loop()`.

After processing, you see:

```
Assignment: Introduction to Statistics
Status:      ready (awaiting your approval)
Answer file: data/generated/..._2026-09-24.docx

[1] View solution
[2] Regenerate solution
[3] Edit output
[4] Approve and submit
[5] Cancel (keep draft, do not submit)
```

- `[1]` prints the generated document content in the terminal.
- `[2]` asks the AI for a second, differently structured attempt.
- `[3]` lets you paste a corrected version (finish with a line `DONE`).
- `[4]` prompts `Type APPROVE (all caps) to submit:` — anything else returns
  you to the menu. Submission is *structurally impossible* without this step.
- `[5]` archives the draft (`cancelled`) without submitting.

---

## Phase 7 — Submission (verified against current API docs)

**Where:** `app/classroom/submit.py`.

Verified facts (checked against Google's official reference):

- The endpoint is
  `POST courses/{courseId}/courseWork/{courseWorkId}/studentSubmissions/{id}:turnIn`.
- It requires the scope `classroom.coursework.me` (already in our scope list)
  and **may only be called by the student who owns the submission**.
- It flips your submission state to `TURNED_IN` (equivalent of clicking
  "Turn in") and may transfer Drive attachment ownership to the teacher.
- The **public API cannot attach files** the way the UI does. `.docs`
  attachments are added through Classroom's UI or Google Drive. There is a
  `studentSubmissions.modifyAttachments` endpoint, but it requires the same
  OAuth client project as the one that created the coursework and an extra
  Drive-write scope, and it only supports `workType == ASSIGNMENT`. That is
  intentionally left out to keep permissions minimal — it's a good extension
  exercise (see "Extending" below).
- Some organisations disallow API turn-in; then Google returns `403
  PERMISSION_DENIED`. The app reports exactly that and tells you to submit in
  the web UI. It never hides the failure.

So: submission = find your `studentSubmissions` for the assignment, call
`turnIn` on it, record the result in the `submissions` table, mark status
`submitted`. Repeatedly calling it is safe (turning in an already-turned-in
submission is a no-op).

---

## Security

- API keys live only in `.env` (git-ignored).
- `credentials/credentials.json` and `credentials/token.json` are git-ignored.
- We request the minimum scopes (read courses, own coursework, read-only Drive).
- No access token is ever printed or logged.
- The `.gitignore` covers `__pycache__`, `.env`, secrets, and local data.

## Extending the project (ideas)

- **Attach the answer**: add a `drive.file` scope, upload the generated `.docx`
  to Drive, then call `studentSubmissions.modifyAttachments.addAttachments`
  before `turnIn`.
- **Watch mode**: a loop that runs "sync" every N minutes and prints new
  pending assignments.
- **Multi-file answers**: an `agent` loop that plans the solution and calls the
  model per sub-task before assembling the final document.
- **Scanned PDFs**: install Tesseract and wire `pdf_reader` to OCR when a page
  has no text.
- **Question templates**: store past assignments in SQLite to detect repeated
  question types.

## Common errors (all phases)

| Error | Cause / fix |
|---|---|
| `AI_API_KEY` missing | Copy `.env.example` to `.env`, set a key, or point `AI_BASE_URL` at Ollama. |
| `choices` key / unexpected response shape | Provider not OpenAI-compatible at that URL; check `AI_BASE_URL` ends in `/v1`. |
| `Rate limit reached` (429) | Wait 30-60s; Google throttles Classroom/Drive calls. |
| `PERMISSION_DENIED` on submit | Organisation blocked API turn-in → submit from the Classroom website. |
| Duplicate assignment rows | Can't happen — unique key. Status is never reset on refresh. |
| `Unsupported file type` | The reader dispatcher tells you which extensions are supported. |