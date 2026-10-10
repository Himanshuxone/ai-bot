# Deploying FinRAG on Vercel (public demo)

This deploys the web app and API as one Python serverless function. It is a **demo
deployment**: every visitor gets a private, temporary workspace with synthetic sample
documents. It is not a production setup for real financial or personal data.

## What you get

- The web UI at `/` (redirects to `/ui/`) and the API under `/v1/*`.
- A **Try the demo with sample documents** button. Each click creates a new isolated
  workspace (`demo-<random>`) containing `sample_financials.csv`, `board_notes.md` and
  `quarterly_budget.xlsx`, signed for 2 hours.
- Offline answers only: nothing is sent to an AI provider, so there is no API cost and no
  visitor data leaves Vercel.

## Files that make it work

| File | Purpose |
|---|---|
| `api/index.py` | Entry point: exposes the ASGI `app` to the Vercel Python runtime |
| `vercel.json` | Routes every path to the function and bundles `finrag/**` (UI and sample files) |
| `requirements.txt`, `.python-version` | Dependencies and Python 3.12 |
| `.vercelignore` | Keeps tests, docs and local data out of the upload |
| `finrag/demo.py`, `finrag/demo_data/` | Demo sessions, workspace pruning, bundled samples |

## Environment variables

| Variable | Value | Why |
|---|---|---|
| `FINRAG_ENVIRONMENT` | `production` | Fail-closed checks; interactive API docs off |
| `FINRAG_DEMO_MODE` | `true` | Per-visitor workspaces and the demo button |
| `FINRAG_MASTER_KEY` | random 32-byte key (`python -m finrag.cli keygen`), marked **sensitive** | Encrypts stores and signs demo tokens. **All instances must share it** |
| `FINRAG_DATA_DIR` | `/tmp/finrag` | Vercel's only writable location |
| `FINRAG_DEFAULT_RETENTION_DAYS` | `1` | Uploaded demo files are short-lived |
| `FINRAG_MAX_UPLOAD_BYTES` | `2097152` | 2 MiB cap (Vercel also limits request bodies to about 4.5 MB) |

Do **not** set `FINRAG_LLM_PROVIDER=anthropic`: demo mode refuses to start with an
external provider.

## Deploy

1. Import the repository in Vercel (Framework preset: Other), or run `vercel deploy`.
2. Add the environment variables above for Production.
3. Deploy. Open the URL and click **Try the demo**.

Vercel's *Deployment Protection* is on by default; turn it off for this project if the
link should be public.

## Windows (PowerShell) quick path

```powershell
git clone https://github.com/Himanshuxone/ai-bot.git; cd ai-bot
npx vercel login
npx vercel link
npx vercel env add FINRAG_ENVIRONMENT production            # type: production
npx vercel env add FINRAG_DEMO_MODE production              # type: true
npx vercel env add FINRAG_DATA_DIR production               # type: /tmp/finrag
npx vercel env add FINRAG_DEFAULT_RETENTION_DAYS production # type: 1
npx vercel env add FINRAG_MAX_UPLOAD_BYTES production       # type: 2097152
npx vercel env add FINRAG_MASTER_KEY production --sensitive # paste your key
npx vercel env ls                                           # all six must be listed
npx vercel deploy --prod
```

Generate the key in PowerShell with:

```powershell
$b = New-Object byte[] 32
[Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($b)
[Convert]::ToBase64String($b).Replace('+','-').Replace('/','_')
```

If `npx` is blocked by PowerShell's script policy, use Command Prompt or `npx.cmd`.

## Troubleshooting

| Symptom | Cause and fix |
|---|---|
| Vercel page "A function needed by this page temporarily failed" (older builds of this repo) | The app crashed while starting, usually because `FINRAG_MASTER_KEY` or another variable was missing for the **Production** environment. Run `npx vercel env ls`, add what is missing, then redeploy |
| JSON `{"detail": "FinRAG failed to start", "reason": ...}` with HTTP 503 | The same problem, now explained. The `reason` names the missing or invalid setting. Fix it and redeploy (variables only apply to **new** deployments) |
| Page asks you to log in to Vercel | Deployment Protection is on. Turn off Vercel Authentication for the project |
| "Try the demo" button missing | `FINRAG_DEMO_MODE` is not `true` in Production |
| Sample documents vanish or uploads disappear | Expected on serverless: storage is temporary per instance; the samples reload automatically |
| Need the real error | `npx vercel logs <your-production-url>` or the project's **Logs** tab; the full traceback is printed there |

## Limits of this deployment

- **Storage is temporary.** Functions use a per-instance `/tmp`. A visitor routed to a
  different or recycled instance loses uploaded files; the sample documents are restored
  automatically. Do not rely on uploads surviving.
- **Not for real data.** There is no persistent encrypted store, no backup and no
  audit-log retention. For production use a container host with a persistent volume (see
  the `Dockerfile`) or replace the file stores with a database.
- **Rate limits are per instance.** Demo-session creation is limited to 20 per minute per
  instance, and at most 40 workspaces are kept per instance. A determined abuser could
  still consume resources; put a firewall rule or Vercel's WAF in front for a long-lived
  public demo.
- **Cold starts** add a second or two to the first request.
- **Scanned PDFs** are not read (no OCR). A PDF sample is not bundled.
