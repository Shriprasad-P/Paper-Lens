# PaperLens macOS local app

PaperLens has a local-first macOS shell built with Tauri 2. The existing
Next.js reader and FastAPI API remain authoritative; the shell only owns
startup, process supervision, local paths, and the webview boundary.

## Architecture

```text
PaperLens.app (Tauri, com.paperlens.app)
  ├─ bundled Next.js standalone server + bundled Node.js
  ├─ bundled PyInstaller FastAPI/Alembic sidecar
  └─ webview → 127.0.0.1:<dynamic frontend port>
                    └─ API → 127.0.0.1:<dynamic backend port>
```

At each launch the shell binds two free loopback ports, creates a fresh
per-launch token, runs Alembic against the local SQLite database, waits for
`/health/ready` and the Next.js root, and then navigates the webview with the
API URL/token in the session URL. The frontend stores those values only in
`sessionStorage`; the backend accepts the token through
`X-PaperLens-Desktop-Token`. CORS preflight remains unauthenticated so the
browser can make the authenticated request.

The backend is a standalone PyInstaller executable and the frontend uses the
bundled Node executable, so the packaged app does not require a system Python
or Node installation. Child processes are put in their own Unix process
groups. Closing the window or receiving a Tauri exit event terminates both
groups and waits for them; a monitor replaces the page with a diagnostic if a
child exits unexpectedly. The single-instance plugin focuses the existing
window when another copy is opened.

## Build and run

Prerequisites are macOS 13+, Xcode Command Line Tools, Rust/Cargo, Python 3.11 or newer for the build environment, and Node/npm. Install the desktop CLI once:

```bash
cd desktop
npm install
```

The one-button entry point required by the local Codex environment is:

```bash
./script/build_and_run.sh                 # build and open the app
./script/build_and_run.sh --verify        # build, open, wait for desktop_ready
./script/build_and_run.sh --logs          # build, open, tail desktop.log
./script/build_and_run.sh --telemetry     # build, open, print size/process sample
./script/build_and_run.sh --debug         # build and run the Tauri binary directly
```

Equivalent lower-level commands are `cd desktop && npm run desktop:dev` for development services, `npm run desktop:build` for a release bundle, and `npm run desktop:check` for toolchain/backend checks. The release artifact is:

```text
desktop/src-tauri/target/release/bundle/macos/PaperLens.app
```

The app is ad-hoc/unsigned for local use. It has bundle identifier
`com.paperlens.app`, version `0.1.0`, a generated PaperLens icon, a restrictive
loopback-aware CSP, and no external network permission in the shell itself.

## Local data and logs

Tauri resolves `app_data_dir()` to:

```text
~/Library/Application Support/com.paperlens.app/
  database/paperlens.db
  papers/<paper-id>/source.pdf
  artifacts/
  cache/
  logs/desktop.log
  logs/backend.log
  logs/frontend.log
```

The directory is created on first launch and survives app restarts. Runtime
data, generated resources, build output, and logs are ignored by Git. AI
credentials are not copied into the bundle or written to these logs; the
packaged default is the no-AI local mode.

## Validation plan

The local validation covers a real `.app` launch, migration on a fresh data
directory, readiness, token rejection/acceptance, dynamic-port startup,
landing-page rendering, arXiv ingestion, persistence after reopen, PDF/source
and evidence navigation, process-group shutdown, crash messaging, and the
single-instance focus path. Existing backend, frontend, Playwright, evaluation,
and deployment checks remain required gates. External AI generation and visual
PDF-region highlighting remain intentionally out of scope when no credentials
or reliable coordinate mapping are available.
