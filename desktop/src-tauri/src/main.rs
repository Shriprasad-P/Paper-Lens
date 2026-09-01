#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::fs::{self, File, OpenOptions};
use std::io::{Read, Write};
use std::net::{TcpListener, TcpStream};
use std::path::Path;
use std::process::{Child, Command, Stdio};
use std::sync::{Arc, Mutex};
use std::thread;
use std::time::{Duration, Instant};
#[cfg(unix)]
use std::os::unix::process::CommandExt;
use tauri::{AppHandle, Manager, RunEvent, WebviewUrl, WebviewWindow, WebviewWindowBuilder, WindowEvent};
use uuid::Uuid;

const APP_NAME: &str = "PaperLens";
const VERSION: &str = "0.1.0";

struct RuntimeState {
    backend: Mutex<Option<Child>>,
    frontend: Mutex<Option<Child>>,
    ollama: Mutex<Option<Child>>,
    shutting_down: Mutex<bool>,
}

impl RuntimeState {
    fn new() -> Self {
        Self { backend: Mutex::new(None), frontend: Mutex::new(None), ollama: Mutex::new(None), shutting_down: Mutex::new(false) }
    }

    fn shutdown(&self) {
        if let Ok(mut shutting_down) = self.shutting_down.lock() {
            if *shutting_down {
                return;
            }
            *shutting_down = true;
        }
        for process in [&self.frontend, &self.backend, &self.ollama] {
            if let Ok(mut child) = process.lock() {
                if let Some(mut process) = child.take() {
                    #[cfg(unix)]
                    unsafe {
                        let _ = libc::kill(-(process.id() as i32), libc::SIGTERM);
                    }
                    let _ = process.kill();
                    let _ = process.wait();
                }
            }
        }
    }
}

fn main() {
    tauri::Builder::default()
        .plugin(tauri_plugin_single_instance::init(|app, _argv, _cwd| {
            if let Some(window) = app.get_webview_window("main") {
                let _ = window.show();
                let _ = window.set_focus();
            }
        }))
        .setup(|app| {
            let state = Arc::new(RuntimeState::new());
            app.manage(state.clone());
            let window = WebviewWindowBuilder::new(app, "main", WebviewUrl::External("about:blank".parse().unwrap()))
                .title(APP_NAME)
                .inner_size(1440.0, 920.0)
                .min_inner_size(1024.0, 700.0)
                .resizable(true)
                .build()?;
            let _ = window.show();
            let _ = window.set_focus();
            let app_handle = app.handle().clone();
            thread::spawn(move || boot_runtime(app_handle, window, state));
            Ok(())
        })
        .on_window_event(|window, event| {
            if matches!(event, WindowEvent::CloseRequested { .. }) {
                if let Some(state) = window.app_handle().try_state::<Arc<RuntimeState>>() {
                    state.shutdown();
                }
            }
        })
        .build(tauri::generate_context!())
        .expect("error while running PaperLens")
        .run(|app, event| {
            if matches!(event, RunEvent::Exit) {
                if let Some(state) = app.try_state::<Arc<RuntimeState>>() {
                    state.shutdown();
                }
            }
        });
}

fn boot_runtime(app: AppHandle, window: WebviewWindow, state: Arc<RuntimeState>) {
    if let Err(error) = boot_runtime_inner(&app, &window, &state) {
        write_runtime_log(&app, &format!("desktop_startup_failed: {error}"));
        show_runtime_error(&window, &format!("PaperLens could not start: {error}"));
    }
}

fn boot_runtime_inner(app: &AppHandle, window: &WebviewWindow, state: &Arc<RuntimeState>) -> Result<(), String> {
    let data_dir = app.path().app_data_dir().map_err(|error| error.to_string())?;
    let logs_dir = data_dir.join("logs");
    let database_dir = data_dir.join("database");
    let papers_dir = data_dir.join("papers");
    let artifacts_dir = data_dir.join("artifacts");
    let cache_dir = data_dir.join("cache");
    for directory in [&logs_dir, &database_dir, &papers_dir, &artifacts_dir, &cache_dir] {
        fs::create_dir_all(directory).map_err(|error| format!("cannot create {}: {error}", directory.display()))?;
    }
    write_runtime_log(app, &format!("desktop_started version={VERSION} data_dir={}", data_dir.display()));

    // The packaged app uses Ollama for all local AI. Reuse an existing daemon
    // when present; otherwise start the installed binary if one is discoverable.
    // Ollama itself selects Metal or CPU, so this also covers machines without
    // a usable Metal device. Failure is non-fatal: lexical reader features can
    // still start and the backend will return a safe local-provider error.
    ensure_ollama(&logs_dir, state);

    let backend_port = free_port()?;
    let frontend_port = free_port()?;
    let token = std::env::var("PAPERLENS_DESKTOP_TOKEN")
        .ok()
        .filter(|value| value.len() >= 16)
        .unwrap_or_else(|| Uuid::new_v4().to_string().replace('-', ""));
    let backend_url = format!("http://127.0.0.1:{backend_port}");
    let frontend_url = format!("http://127.0.0.1:{frontend_port}");

    if std::env::var("PAPERLENS_DESKTOP_DEV").as_deref() == Ok("1") {
        let configured_backend = std::env::var("PAPERLENS_DESKTOP_BACKEND_URL").map_err(|_| "desktop dev backend URL is missing".to_string())?;
        let configured_frontend = std::env::var("PAPERLENS_DESKTOP_FRONTEND_URL").map_err(|_| "desktop dev frontend URL is missing".to_string())?;
        wait_for_http(&format!("{configured_backend}/health/ready"), Duration::from_secs(30))?;
        wait_for_http(&format!("{configured_frontend}/"), Duration::from_secs(30))?;
        write_runtime_log(app, "backend_ready frontend_ready desktop_ready (development services)");
        navigate_to_app(window, &configured_frontend, &configured_backend, &token);
        return Ok(());
    }

    let resources = app.path().resource_dir().map_err(|error| error.to_string())?;
    let backend_binary = resources.join("resources/paperlens-backend");
    let node_binary = resources.join("resources/node");
    let frontend_dir = resources.join("resources/frontend");
    for required in [&backend_binary, &node_binary, &frontend_dir] {
        if !required.exists() {
            return Err(format!("packaged runtime resource is missing: {}", required.display()));
        }
    }

    let common_env = [
        ("PAPERLENS_ENVIRONMENT", "development".to_string()),
        ("PAPERLENS_DATABASE_URL", format!("sqlite:///{}", database_dir.join("paperlens.db").display())),
        ("PAPERLENS_STORAGE_PATH", papers_dir.display().to_string()),
        ("PAPERLENS_STORAGE_PROVIDER", "local".to_string()),
        ("PAPERLENS_AUTO_CREATE_SCHEMA", "false".to_string()),
        ("PAPERLENS_FRONTEND_ORIGINS", frontend_url.clone()),
        ("PAPERLENS_FRONTEND_ORIGIN", frontend_url.clone()),
        ("PAPERLENS_BACKEND_PUBLIC_URL", backend_url.clone()),
        // Use the user's local Ollama daemon; no hosted API credential is
        // required.  Ollama falls back to CPU execution when Metal is absent.
        ("AI_PROVIDER", "ollama".to_string()),
        ("AI_MODEL", "qwen3:4b".to_string()),
        ("AI_BASE_URL", "http://127.0.0.1:11434/v1".to_string()),
        ("EMBEDDING_PROVIDER", "ollama".to_string()),
        ("EMBEDDING_MODEL", "nomic-embed-text".to_string()),
        ("EMBEDDING_DIMENSION", "768".to_string()),
        ("EMBEDDING_VERSION", "ollama-nomic-embed-text-v1".to_string()),
        ("EMBEDDING_BASE_URL", "http://127.0.0.1:11434".to_string()),
        ("HYBRID_RETRIEVAL_ENABLED", "true".to_string()),
        ("RETRIEVAL_MODE", "HYBRID".to_string()),
        ("PAPERLENS_RATE_LIMITS_ENABLED", "true".to_string()),
        ("PAPERLENS_DESKTOP_TOKEN", token.clone()),
        ("PAPERLENS_RELEASE_VERSION", VERSION.to_string()),
        ("PAPERLENS_BUILD_SHA", "desktop-local".to_string()),
        ("PAPERLENS_BACKEND_PORT", backend_port.to_string()),
    ];
    let backend_log = logs_dir.join("backend.log");
    let frontend_log = logs_dir.join("frontend.log");
    let mut backend_command = Command::new(&backend_binary);
    backend_command.envs(common_env.iter().cloned()).current_dir(&resources);
    let backend = spawn_logged(backend_command, &backend_log)?;
    if let Ok(mut slot) = state.backend.lock() {
        *slot = Some(backend);
    }
    write_runtime_log(app, &format!("backend_started port={backend_port}"));
    wait_for_http_with_process(&format!("{backend_url}/health/ready"), Duration::from_secs(45), &state.backend)?;
    write_runtime_log(app, "database_ready backend_ready");

    let mut frontend_command = Command::new(&node_binary);
    frontend_command
        .arg(frontend_dir.join("server.js"))
        .current_dir(&frontend_dir)
        .env("PORT", frontend_port.to_string())
        .env("HOSTNAME", "127.0.0.1")
        .env("NODE_ENV", "production")
        .env("NEXT_TELEMETRY_DISABLED", "1");
    let frontend = spawn_logged(frontend_command, &frontend_log)?;
    if let Ok(mut slot) = state.frontend.lock() {
        *slot = Some(frontend);
    }
    write_runtime_log(app, &format!("frontend_started port={frontend_port}"));
    wait_for_http_with_process(&format!("{frontend_url}/"), Duration::from_secs(30), &state.frontend)?;
    write_runtime_log(app, "frontend_ready desktop_ready");
    navigate_to_app(window, &frontend_url, &backend_url, &token);
    monitor_children(app.clone(), window.clone(), state.clone());
    Ok(())
}

fn spawn_logged(mut command: Command, path: &Path) -> Result<Child, String> {
    let file = OpenOptions::new().create(true).append(true).open(path).map_err(|error| format!("cannot open {}: {error}", path.display()))?;
    let stderr = file.try_clone().map_err(|error| error.to_string())?;
    #[cfg(unix)]
    unsafe {
        command.pre_exec(|| {
            if libc::setpgid(0, 0) != 0 {
                return Err(std::io::Error::last_os_error());
            }
            Ok(())
        });
    }
    command.stdout(Stdio::from(file)).stderr(Stdio::from(stderr)).spawn().map_err(|error| format!("cannot launch sidecar: {error}"))
}

fn ensure_ollama(logs_dir: &Path, state: &Arc<RuntimeState>) {
    let endpoint = "http://127.0.0.1:11434/api/tags";
    if http_ok(endpoint) {
        return;
    }
    let Some(binary) = find_ollama_binary() else {
        return;
    };
    let log_path = logs_dir.join("ollama.log");
    let mut command = Command::new(binary);
    command.arg("serve");
    let child = match spawn_logged(command, &log_path) {
        Ok(child) => child,
        Err(_) => return,
    };
    if let Ok(mut slot) = state.ollama.lock() {
        *slot = Some(child);
    }
    let _ = wait_for_http_with_process(endpoint, Duration::from_secs(20), &state.ollama);
}

fn find_ollama_binary() -> Option<std::path::PathBuf> {
    if let Some(path) = std::env::var_os("PATH") {
        for directory in std::env::split_paths(&path) {
            let candidate = directory.join("ollama");
            if candidate.is_file() {
                return Some(candidate);
            }
        }
    }
    for candidate in ["/usr/local/bin/ollama", "/opt/homebrew/bin/ollama"] {
        let path = std::path::PathBuf::from(candidate);
        if path.is_file() {
            return Some(path);
        }
    }
    None
}

fn monitor_children(app: AppHandle, window: WebviewWindow, state: Arc<RuntimeState>) {
    thread::spawn(move || loop {
        thread::sleep(Duration::from_millis(500));
        if *state.shutting_down.lock().unwrap_or_else(|poisoned| poisoned.into_inner()) {
            break;
        }
        for (name, process) in [("backend", &state.backend), ("frontend", &state.frontend)] {
            let stopped = process.lock().ok().and_then(|mut child| child.as_mut().and_then(|item| item.try_wait().ok())).flatten();
            if let Some(status) = stopped {
                write_runtime_log(&app, &format!("{name}_stopped status={status}"));
                show_runtime_error(&window, &format!("PaperLens {name} stopped unexpectedly. Check ~/Library/Application Support/com.paperlens.app/logs/{name}.log and restart the app."));
                return;
            }
        }
    });
}

fn wait_for_http(url: &str, timeout: Duration) -> Result<(), String> {
    wait_for_http_with_process(url, timeout, &Mutex::new(None))
}

fn wait_for_http_with_process(url: &str, timeout: Duration, process: &Mutex<Option<Child>>) -> Result<(), String> {
    let started = Instant::now();
    while started.elapsed() < timeout {
        if let Ok(mut child) = process.lock() {
            if let Some(item) = child.as_mut() {
                if let Some(status) = item.try_wait().map_err(|error| error.to_string())? {
                    return Err(format!("child exited before {url} became ready ({status})"));
                }
            }
        }
        if http_ok(url) {
            return Ok(());
        }
        thread::sleep(Duration::from_millis(250));
    }
    Err(format!("timed out waiting for {url}"))
}

fn http_ok(url: &str) -> bool {
    let Some((host_port, path)) = url.strip_prefix("http://").and_then(|value| value.split_once('/')) else { return false };
    let Ok(mut stream) = TcpStream::connect(host_port) else { return false };
    let _ = stream.set_read_timeout(Some(Duration::from_secs(2)));
    let request = format!("GET /{path} HTTP/1.1\r\nHost: {host_port}\r\nConnection: close\r\n\r\n");
    if stream.write_all(request.as_bytes()).is_err() { return false; }
    let mut response = String::new();
    if stream.read_to_string(&mut response).is_err() { return false; }
    response.starts_with("HTTP/1.1 200") || response.starts_with("HTTP/1.0 200")
}

fn free_port() -> Result<u16, String> {
    TcpListener::bind(("127.0.0.1", 0)).map_err(|error| error.to_string()).and_then(|listener| listener.local_addr().map(|address| address.port()).map_err(|error| error.to_string()))
}

fn navigate_to_app(window: &WebviewWindow, frontend: &str, backend: &str, token: &str) {
    let url = format!("{frontend}/?paperlens_api={}&desktop_token={}", urlencoding(backend), urlencoding(token));
    if let Ok(parsed) = url.parse() {
        let _ = window.navigate(parsed);
    }
    let _ = backend;
}

fn urlencoding(value: &str) -> String {
    value.replace(':', "%3A").replace('/', "%2F")
}

fn show_runtime_error(window: &WebviewWindow, message: &str) {
    let escaped = serde_json::to_string(message).unwrap_or_else(|_| "\"PaperLens startup failed.\"".to_string());
    let script = format!("document.body.innerHTML='<main style=\"font-family:-apple-system,sans-serif;padding:48px;max-width:720px\"><h1>PaperLens could not start</h1><p>'+{escaped}+'</p></main>';", escaped = escaped);
    let _ = window.eval(&script);
}

fn write_runtime_log(app: &AppHandle, message: &str) {
    let Ok(data_dir) = app.path().app_data_dir() else { return };
    let path = data_dir.join("logs").join("desktop.log");
    if let Some(parent) = path.parent() { let _ = fs::create_dir_all(parent); }
    if let Ok(mut file) = File::options().create(true).append(true).open(path) {
        let _ = writeln!(file, "{message}");
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn urlencoding_keeps_desktop_query_values_safe() {
        assert_eq!(urlencoding("http://127.0.0.1:8000"), "http%3A%2F%2F127.0.0.1%3A8000");
        assert_eq!(urlencoding("desktop-token/with:separator"), "desktop-token%2Fwith%3Aseparator");
    }

    #[test]
    fn free_port_binds_loopback_only() {
        let port = free_port().expect("a free loopback port");
        assert!(port > 0);
    }
}
