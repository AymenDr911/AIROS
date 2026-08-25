# 🚀 AIROS V2 — GitHub Commit & Push Guide

A simple, **secure-by-default** walkthrough to commit and push the current
version of AIROS V2 to GitHub. Follow it top to bottom.

> ⚠️ **Security already handled for you (do NOT undo):**
> - Sensitive files are **ignored** and can never be committed:
>   `secrets.toml` (GEMINI API key), `data/users_db.json`, `data/uploads/`,
>   `app/generated/`, `airos.db` (all `.db`).
> - The two previously-tracked files `data/users_db.json` and the uploaded CV
>   were **untracked** (`git rm --cached`) — they still exist locally but are
>   now out of version control.

---

## 0. Prerequisites

- Git installed → `git --version` (this repo uses an older Git 2.15, that's fine).
- A GitHub repo. Yours: `https://github.com/AymenDr911/AIROS.git`
- Here, Git identity (for commit author):
  - name: `Votre Nom`   ·   email: `aymen911@gmail.com`  (already set ✔)

**Fix/verify your identity once** (if the commit shows a wrong author):

```bash
git config user.name "Your Name"
git config user.email "you@example.com"
```

---

## 1. See what's changed

```bash
# From inside the project
cd "/Users/macbook/Documents/Careers folder/AIROS"

# Current branch, uncommitted files, and your remote URL
git status
git remote -v
git branch --show-current          # (old git: use `git branch` and look for *)
```

**Current state:** branch is `feature/foundation`, remote is set, and there are
modified + new source files ready to commit.

> 🛡️ **Safety check before you commit anything:**
> ```bash
> git add -n -A . | grep -iE 'secrets|users_db|uploads|generated|airos\.db|\.env'
> ```
> If this prints **anything**, stop and check `.gitignore`.
> You should see **no output** (already verified ✔).

---

## 2. Stage the files

```bash
# Stage ALL the (safe) source changes:
git add -A
```

> Prefer the explicit list if you want a tighter commit:
> ```bash
> git add V2.0/app V2.0/_smoke_stage3.py
> ```

Verify only intended files are staged:

```bash
git status
# or, what's about to be committed:
git diff --cached --stat
```

---

## 3. Commit

```bash
git commit -m "feat(tracker): recruiter-response + interview scheduling; secure .gitignore"
```

> A good commit message: a short summary, optionally a body.
> ```bash
> git commit -m "feat: AIROS V2 - ATS + tracking workflow" \
>            -m "ATS analyzer, document generation, job application, lifecycle tracker, recruiter-response & interview scheduling. Ignore secrets/user-data/db."
> ```

---

## 4. Push

**Push your current branch** (`feature/foundation`) to GitHub and link the remote:

```bash
git push -u origin feature/foundation
```
- `-u` sets the upstream so later pushes are just `git push`.

**If you'd rather publish on `main`:**
```bash
git checkout main
git pull origin main                    # get any remote changes first
git push origin feature/foundation:main # optional: push your branch as main
```

---

## 5. First time on a *new* machine / clone

```bash
git clone https://github.com/AyouDr911/AIROS.git
cd AIROS
# recreate the secrets file locally (it is NOT in the repo by design):
mkdir -p .streamlit
# create .streamlit/secrets.toml with your GEMINI_API_KEY, e.g.:
#   GEMINI_API_KEY = "your-key-here"
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

---

## 6. Verify

- GitHub → open your repo → branch `feature/foundation` → you should see your
  commit and the source tree **without** `secrets.*`, `users_db.json`,
  `uploads/`, `generated/`, or `*.db`.
- Local sanity: `git status` should say *"working tree clean"*.

---

## 7. Troubleshooting & rollback

| Problem | Fix |
|---|---|
| `git push` rejected (remote ahead) | `git pull --rebase` then `git push` |
| Pushed a secret by mistake | Rotate the key + `git rm --cached <file>`; push a follow-up commit |
| Wrong commit message | `git commit --amend -m "new message"` |
| Want to undo a pushed commit | `git revert <commit-hash>` (safest) |
| Auth fails (HTTPS) | Use a **Personal Access Token** (not your password): GitHub → Settings → Developer settings → PAT |
| SSH preferred | `git remote set-url origin git@github.com:AyouDr911/AIROS.git` |

### Recommended branch flow
```
main          ← stable, tagged releases (V2.0)
feature/*     ← work in progress (currently: feature/foundation)
```
Fork a branch for each feature (`git checkout -b feature/tracking`),
then merge back to `main` when stable.

---

*Generated for the AIROS V2.0 close-out. Secrets and personal data are
intentionally excluded from version control.*