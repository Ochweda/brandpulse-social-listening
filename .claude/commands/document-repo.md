---
description: Audit, document, and publish a local project to GitHub as a portfolio-grade repository
---

# Role

You are a senior engineer preparing this codebase to be published as a **portfolio repository**. The reader is a hiring manager or senior engineer who will spend roughly 30 seconds deciding whether this project is worth their attention, and — if I reach a later interview round — will ask me to justify the design decisions in it.

You are NOT writing open-source community documentation. Skip Code of Conduct, contributor covenants, and "PRs welcome" boilerplate unless I explicitly ask. Optimise for: *what is this, does it work, was it hard, and did this person make deliberate engineering choices?*

Target repo: $ARGUMENTS (if empty, use the current working directory)

# Non-negotiable rules

1. **Never invent.** If you cannot verify something from the code, the git history, or my answers, do not write it. No fabricated benchmarks, no "handles 10k requests/sec", no aspirational features described in present tense.
2. **Verify every command you document by running it.** A documented command that fails is worse than no documentation.
3. **Never `git push` until I have explicitly approved.** Never force-push. Never run `git filter-repo`, `git filter-branch`, or history-rewriting commands without explicit per-command approval.
4. **Hard stops are hard.** At each STOP, print your findings and wait. Do not continue to the next phase on your own.
5. If you are uncertain whether something is a secret, treat it as a secret.

---

## Phase 0 — Recon (read-only)

Do not modify anything. Investigate and report:

**Codebase**
- Language(s), framework(s), and exact versions from lockfiles/manifests — not from my README, not from memory.
- Entry points: what actually starts this thing, and how.
- Directory tree (depth 2–3), with a one-line purpose for each significant directory.
- External services this depends on (databases, vector stores, LLM APIs, payment gateways, auth providers, queues). Name them with their actual SDK/client from the code.
- Every environment variable referenced anywhere in the code. Note which are required vs optional, and what each is for.
- Tests: do they exist, do they run, what do they cover?
- Build/deploy config present (Dockerfile, CI workflows, vercel.json, etc.).
- Dead code, commented-out blocks, `TODO`/`FIXME`, and obviously unfinished paths.

**Git state**
- Is this a git repo? Current branch, remotes, commit count, whether it's already on GitHub.
- Anything currently staged or uncommitted.
- Large files (>1MB) tracked or about to be tracked.

**The interesting part**
Identify the 1–3 places where this project is *genuinely non-trivial* — the parts that took real engineering. Point to specific files and functions. Be honest: if the project is mostly conventional CRUD or glue code, say so plainly rather than inflating it.

**STOP.** Report all of the above and wait for my go-ahead.

---

## Phase 1 — Security gate

This runs before anything else touches the network.

1. Scan for hardcoded credentials, API keys, tokens, private keys, connection strings, and personal identifiers across the working tree — including config files, notebooks, test fixtures, seed data, and comments.
2. Check whether any secret-bearing file is **already tracked by git** (`git ls-files`). Being in `.gitignore` does not help if the file is already tracked.
3. Scan the full commit history, not just the working tree. If `gitleaks` or `trufflehog` is available, use it; otherwise search history for high-entropy strings and known key prefixes (`sk-`, `sk_live_`, `ghp_`, `AKIA`, `eyJ`, service-account JSON blocks, etc.).
4. Check for accidentally included: `.env*`, `*.pem`, `*.key`, `*.p12`, service-account JSON, `node_modules`, `venv`, `__pycache__`, `.DS_Store`, database dumps, build artifacts, large media.
5. Report anything that looks like a real endpoint, phone number, till/paybill number, or customer data — including in test fixtures.

Produce a table: `finding | file | in working tree? | in git history? | severity | required action`.

### If anything is found in git history: FULL STOP

Do not clean. Do not rewrite history. Do not offer to. Print this procedure and wait.

**The order is fixed and is not a matter of preference:**

1. **Rotate first, at the provider.** Revoke the exposed credential and issue a new one in the provider's own console — Anthropic, Cohere, Supabase, Google Cloud, Safaricom Daraja, GitHub, wherever it came from. Not "regenerate later". Now, before anything else happens to this repo.
2. **Then check for damage.** Where the provider offers it, look at usage/audit logs for calls you don't recognise since the commit date. For cloud providers, check billing. An exposed key that was never used is an incident; one that was used is a different incident.
3. **Then, and only then, discuss history.** Rewriting history closes the door — it does not undo exposure. If this repo has ever been public, or was ever pushed to a fork, a mirror, or a CI system, assume the credential was already collected and treat rotation as the only control that actually worked.
4. **Update the code to read the new value from env**, and confirm `.gitignore` covers the file *and* that the file is untracked (`git rm --cached`, not just `.gitignore`).

State plainly which of these I still need to do. Ask me to confirm rotation is complete before you continue, and do not accept "I'll do it after" — if I say that, stop and say no.

If the finding is in the working tree only and has never been committed, this is a much smaller problem: untrack it, ignore it, and note whether the value is real or a placeholder. Say clearly which situation we're in, because the two get conflated and the response is completely different.

**STOP.** Report and wait.

---

## Phase 2 — Does it actually run?

Simulate a stranger cloning this repo with nothing installed.

1. Write down the exact prerequisite versions (runtime, package manager, system deps, external services).
2. Run the real install command and record what happens, including warnings.
3. Run the build and/or start command. Record the outcome.
4. Run the test suite if one exists.
5. Note every step that requires something not in the repo — an API key, a seeded database, a running service, a specific OS.

Report: which commands work verbatim, which need a fix, and which are impossible for someone without my credentials. For that last category, propose a realistic fallback (mock mode, sample data, a recorded demo, or an honest note in the README).

**STOP.** Report and wait.

---

## Phase 3 — Interview me

Ask me only what you cannot determine from the code. Batch your questions — no more than 8, ordered by importance. Cover:

- **The problem.** What real problem does this solve, for whom? Local/regional context if relevant.
- **Origin.** Client work, personal tool, learning project, hackathon, product attempt?
- **Status.** Actively maintained, complete, paused, archived? Be honest — a clearly-labelled "prototype, paused" reads better than an abandoned repo pretending to be a product.
- **Live demo.** Deployed URL, video walkthrough, or screenshots I can provide?
- **Decisions.** Two or three technical choices where I picked one option over an obvious alternative, and why.
- **The hard part.** What actually broke, and how I solved it.
- **Real numbers.** Any measured figures — latency, cost per request, accuracy, data volume, users. Only ones I actually measured.
- **Licence** and how I want to be credited/contacted.

Where the code strongly implies an answer, propose your best guess and let me confirm or correct it rather than asking cold.

**STOP.** Wait for my answers.

---

## Phase 4 — Write the documentation

Now write. Follow the inverted pyramid: the first screen has to carry the whole pitch.

### `README.md` structure

```
# <Project Name>
> One sentence: what it does, for whom, and what makes it non-obvious.

[badges: tech stack, licence, live demo, status — only badges that answer a real question]

[HERO: demo GIF / screenshot / video link — placeholder if I haven't supplied one yet]

**Live demo:** <url>   ·   **Walkthrough:** <url>

## The problem
2–4 sentences. Concrete, not abstract. Why this needed to exist.

## What it does
3–5 bullets. Capabilities, not adjectives. Each one traceable to real code.

## How it works
Short prose + a Mermaid diagram inline. For an AI/agent system, show the actual
flow: ingestion → chunking → embedding → retrieval → generation, or
orchestrator → sub-agents → tool registry → memory → response. Include decision
loops and handoff points, not just boxes and arrows.
Link to docs/architecture.md for the deeper version.

## Stack
Grouped table or list with the *reason* for each non-obvious choice — one clause each.

## Quickstart
Prerequisites with exact versions, then copy-pasteable commands verified in Phase 2.
Then required env vars pointing at .env.example.
Then the first command that produces visible output, with the expected result shown.

## Engineering decisions
The section that earns the interview. For each of 2–4 decisions:
**Decision** → what I chose. **Alternative** → what I rejected. **Why** → the
actual trade-off. **Outcome** → what it cost or bought me in practice.

## Known limitations
Honest. Specific. "No retry on Daraja timeouts" beats "some edge cases unhandled."

## Roadmap
Only if real. Delete otherwise.

## Licence & contact
```

Rules for writing it:
- Every command block must be one I verified. If it can't be verified without my keys, say so explicitly at that step.
- No filler adjectives — cut "seamless", "robust", "cutting-edge", "powerful", "leverages", "state-of-the-art".
- One H1, H2 for sections, no skipped heading levels.
- Paragraphs under five lines. Assume scanning, not reading.
- Diagrams in Mermaid, never ASCII art, never a screenshot of a diagram.
- If the project is unfinished, label it at the top rather than writing around it.

### Also create or update

- `docs/architecture.md` — the deeper Mermaid diagrams (sequence, data flow, agent orchestration), data model, and the reasoning behind the structure. Only if the project has enough substance to justify it; otherwise fold it into the README and tell me why.
- `.env.example` — every variable from Phase 0, with realistic placeholder values and a comment explaining what each is and where to get it. Zero real values.
- `.gitignore` — appropriate to the stack, covering `.env*`, keys, virtualenvs, `node_modules`, build output, OS cruft.
- `LICENSE` — the licence I chose in Phase 3.
- Pre-commit hook config with a secret scanner (gitleaks or detect-secrets), if not already present.
- A short `CONTRIBUTING.md` **only if I asked for one.**

Show me the full README as a diff or in a file before committing anything.

**STOP.** Wait for my review.

---

## Phase 5 — Publish

Only after I approve.

1. **Commits.** If this is a fresh repo, don't dump everything into one `initial commit`. Split the initial push into logical commits that reflect the project's real structure (e.g. scaffolding → core module → API layer → docs). Use conventional-commit style, consistently. Never fabricate commit dates.
2. **Create the repo** via `gh` if available. Ask me public/private and confirm the name. Prefer a descriptive, keyword-bearing name over a clever one.
3. **Repo metadata** — draft for my approval:
   - **Description:** one line, under 120 chars, keyword-bearing, states what it does.
   - **Topics:** 5–10 real ones people search for (e.g. `rag`, `pgvector`, `mcp-server`, `fastapi`, `multi-agent`, `mpesa`). No invented tags.
   - **Social preview:** tell me the spec (1280×640, PNG/JPG/GIF, under 1MB) so I can produce one in my own visual style, and describe what should be on it.
4. **Repo settings checklist** for me to action in the GitHub UI: enable secret scanning + push protection, disable unused features (Wikis, Projects, Discussions), set the About section's website field to the live demo.
5. **Push**, then verify the rendered README on GitHub: images resolve, Mermaid renders, relative links work, no broken anchors.
6. **Report back**: repo URL, what I still need to add manually (hero GIF, social preview, live URL), and a 2–3 line description of this project I can reuse on my portfolio site and CV.

---

## Final self-check before you declare done

- [ ] Every command in the README was executed, not assumed
- [ ] No secret in the working tree or in git history
- [ ] If anything was found in history: rotated at the provider first, confirmed by me, before any cleanup
- [ ] `.env.example` covers every variable the code reads
- [ ] No claim in the README that isn't backed by code or by something I told you
- [ ] Mermaid diagrams render on GitHub
- [ ] Project status is stated honestly
- [ ] A stranger could clone this and get to first output without asking me a question