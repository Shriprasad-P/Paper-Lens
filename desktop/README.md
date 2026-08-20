# PaperLens macOS desktop shell

This directory contains the Tauri v2 shell for local end-to-end validation. It
does not replace the Next.js UI or FastAPI backend. The shell resolves a
per-user Application Support directory, runs an explicit Alembic migration,
starts standalone backend and Next.js resources on loopback ports, waits for
readiness, and opens the existing PaperLens reader in a native window.

Run from the repository root:

```bash
cd desktop
npm install
npm run desktop:dev
npm run desktop:build
```

The production-like local bundle is written to
`desktop/src-tauri/target/release/bundle/macos/PaperLens.app`. It is ad-hoc/
unsigned local validation output, not a notarized distribution artifact.
