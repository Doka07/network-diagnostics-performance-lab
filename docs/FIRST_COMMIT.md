# First commit

Suggested repository name: `network-diagnostics-performance-lab`.

Create an empty GitHub repository with this name, initially private. Do not initialize it
with a README, license, or .gitignore: the local project already contains the first and
third, and a license has not yet been selected. The project owner alone commits and pushes.
An initial private push enables CI; making the repository public is a separate decision.

## Local review and commit

Run these commands yourself from an Ubuntu terminal. Initialization is for this currently
uninitialized project; if a Git repository already exists by then, skip `git init`.

```bash
cd /home/denis/Desktop/network-diagnostics-performance-lab
git init -b main
git add .gitignore .github AGENTS.md CLAUDE.md CODEX.md GEMINI.md README.md pyproject.toml configs diaglab docs scripts tests results/.gitkeep
git diff --cached --check
git diff --cached --stat
git diff --cached
git status --short
```

Inspect the staged files, then run:

```bash
git commit -m "feat: establish reviewed Phase 1 diagnostics contracts and offline CLI"
```

The explicit file list keeps private sibling planning/review files and local generated
artifacts out of the commit. The ignore rules also exclude virtual environments,
caches, build output, raw results, local inventory, and common credential files.

## Connect GitHub after the repository is created

Replace the example URL with the exact SSH or HTTPS URL from your new repository:

```bash
git remote add origin YOUR_REPOSITORY_URL
git remote -v
git push -u origin main
```

The push triggers the prepared GitHub Actions workflow for Python 3.12 and 3.14. Check
the repository's Actions tab for both jobs. Local checks already passed, but a remote
CI result can only be recorded after those jobs actually run.
