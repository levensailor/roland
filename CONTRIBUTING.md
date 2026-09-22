# Contributing

This repository uses feature branches and pull requests. Do not commit directly to `main` unless you are the maintainer applying a reviewed change.

## Create a feature branch

1. Fork the repository if you do not have write access.
2. Clone your copy and create a branch named for the change:

```bash
git checkout main
git pull
git checkout -b feature/short-description
```

Examples: `feature/add-aiff-preview`, `fix/locked-sd-detection`.

3. Keep configuration in environment variables. Do not hardcode product names, paths, ports, or folder labels in new code.

## Describe why the change belongs here

In the pull request body, explain:

- Why the TM-2 workflow needs this change
- What a reviewer should try (drop a file, init a card path, assign reminders still accurate)
- Any official Roland manual or support note you used

## Open a pull request

```bash
git add -A
git commit -m "Explain why this change exists."
git push -u origin HEAD
```

Then open a pull request against `main` and fill in:

```markdown
## Why
What problem this solves for loading samples onto the TM-2.

## How to test
- [ ] App starts with `python -m app.main` from `backend/`
- [ ] Drag-and-drop converts a non-WAV file
- [ ] Files land under Roland/TM-2/WAVE
- [ ] In-app TM-2 reminders still match the hardware steps
```

Wait for review before merging.
