//! A library on this computer (docs/apps.md): a paperus for one person,
//! without a server. Its parts (app/local/build.sh: Python with the server,
//! PostgreSQL with pgvector, the website) are downloaded once per version
//! from the release, checked against their SHA-256; its data (database,
//! files, backups) stay in the app's data folder. The app starts them, all
//! on 127.0.0.1 only, logs itself in as the library's only person (a
//! random password, kept with the data) and stops them when it ends.

use std::{
    fs,
    io::{Read, Write},
    net::TcpListener,
    path::{Path, PathBuf},
    process::{Child, Command, Stdio},
    sync::Mutex,
    thread,
    time::{Duration, Instant},
};

use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use tauri::{AppHandle, Manager, Url};

use crate::libraries;

/// What the start page shows while the library gets ready.
pub static PROGRESS: Mutex<String> = Mutex::new(String::new());
/// The library's processes while it runs.
static RUNNING: Mutex<Option<Running>> = Mutex::new(None);

/// The username of the library's only person.
const USER: &str = "me";
const RELEASES: &str = "https://github.com/qcode-uni-a/paperus/releases/download";

struct Running {
    url: Url,
    password: String,
    children: Vec<Child>,
    postgres: PathBuf,
    database: PathBuf,
}

/// Kept with the library's data: the passwords and ports, made once.
#[derive(Deserialize, Serialize)]
struct Secrets {
    database_password: String,
    password: String,
    database_port: u16,
    port: u16,
    /// Where the PDFs are kept, if not with the rest (`pdf_folder`).
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pdf_folder: Option<PathBuf>,
}

fn progress(text: &str) {
    *PROGRESS.lock().expect("progress") = text.to_owned();
}

/// The platform's bundle name, as the release's files are named.
fn target() -> Option<&'static str> {
    if cfg!(all(target_os = "linux", target_arch = "x86_64")) {
        Some("x86_64-unknown-linux-gnu")
    } else if cfg!(all(target_os = "macos", target_arch = "aarch64")) {
        Some("aarch64-apple-darwin")
    } else if cfg!(all(target_os = "macos", target_arch = "x86_64")) {
        Some("x86_64-apple-darwin")
    } else if cfg!(all(target_os = "windows", target_arch = "x86_64")) {
        Some("x86_64-pc-windows-msvc")
    } else {
        None
    }
}

fn version() -> &'static str {
    env!("CARGO_PKG_VERSION")
}

/// Where the library's data are.
pub fn data_folder(app: &AppHandle) -> Result<PathBuf, String> {
    app.path()
        .app_data_dir()
        .map(|folder| folder.join("library"))
        .map_err(|_| "The app has no folder for its data.".into())
}

/// The bundle for this version: there already, given (`PAPERUS_LOCAL_BUNDLE`,
/// a folder or a .tar.gz, for tests and development), or downloaded.
fn bundle(app: &AppHandle) -> Result<PathBuf, String> {
    if let Ok(given) = std::env::var("PAPERUS_LOCAL_BUNDLE") {
        let given = PathBuf::from(given);
        if given.is_dir() {
            return Ok(given);
        }
    }
    let folder = app
        .path()
        .app_local_data_dir()
        .map_err(|_| "The app has no folder for its data.")?
        .join("local")
        .join(version());
    if folder.join("VERSION").exists() {
        return Ok(folder);
    }
    let archive = match std::env::var("PAPERUS_LOCAL_BUNDLE") {
        Ok(given) => fs::read(given).map_err(|error| format!("The bundle: {error}"))?,
        Err(_) => download()?,
    };
    progress("Unpacking…");
    let partial = folder.with_extension("partial");
    let _ = fs::remove_dir_all(&partial);
    fs::create_dir_all(&partial).map_err(|error| error.to_string())?;
    tar::Archive::new(flate2::read::GzDecoder::new(archive.as_slice()))
        .unpack(&partial)
        .map_err(|error| format!("The library's parts could not be unpacked: {error}"))?;
    let _ = fs::remove_dir_all(&folder);
    fs::rename(&partial, &folder).map_err(|error| error.to_string())?;
    Ok(folder)
}

/// The release's bundle for this platform, checked against its SHA-256.
fn download() -> Result<Vec<u8>, String> {
    let target = target().ok_or("A library on this computer is not there for this system yet.")?;
    let name = format!("paperus-local-{}-{target}.tar.gz", version());
    let base = format!("{RELEASES}/v{}/{name}", version());
    let agent = libraries::agent_for_downloads();
    let fetch = |url: &str| -> Result<ureq::http::Response<ureq::Body>, String> {
        let response = agent
            .get(url)
            .call()
            .map_err(|error| format!("The library's parts could not be downloaded: {error}."))?;
        if !response.status().is_success() {
            return Err(format!(
                "The library's parts could not be downloaded ({}).",
                response.status()
            ));
        }
        Ok(response)
    };
    let expected = fetch(&format!("{base}.sha256"))?
        .body_mut()
        .read_to_string()
        .map_err(|error| error.to_string())?
        .split_whitespace()
        .next()
        .unwrap_or_default()
        .to_lowercase();
    let mut response = fetch(&base)?;
    let total = response
        .headers()
        .get("content-length")
        .and_then(|length| length.to_str().ok()?.parse::<u64>().ok());
    let mut reader = response.body_mut().with_config().limit(2 << 30).reader();
    let mut data = Vec::new();
    let mut buffer = vec![0; 1 << 16];
    loop {
        let read = reader
            .read(&mut buffer)
            .map_err(|error| error.to_string())?;
        if read == 0 {
            break;
        }
        data.extend_from_slice(&buffer[..read]);
        progress(&match total {
            Some(total) => format!(
                "Downloading the library's parts… {} of {} MB",
                data.len() >> 20,
                total >> 20
            ),
            None => format!("Downloading the library's parts… {} MB", data.len() >> 20),
        });
    }
    let got = format!("{:x}", Sha256::digest(&data));
    if got != expected {
        return Err("The downloaded parts are not the release's (their SHA-256 differs).".into());
    }
    Ok(data)
}

fn executable(folder: &Path, name: &str) -> PathBuf {
    folder.join(format!("{name}{}", std::env::consts::EXE_SUFFIX))
}

fn python(bundle: &Path) -> PathBuf {
    let unix = bundle.join("python/bin/python3");
    if unix.exists() {
        unix
    } else {
        bundle.join("python/python.exe")
    }
}

/// A command without a console window (Windows).
#[cfg_attr(not(windows), allow(unused_mut))]
fn command(program: &Path) -> Command {
    let mut command = Command::new(program);
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        const CREATE_NO_WINDOW: u32 = 0x0800_0000;
        command.creation_flags(CREATE_NO_WINDOW);
    }
    command
}

/// Runs to the end; what it said if it failed.
fn run(mut command: Command, what: &str, input: Option<&str>) -> Result<(), String> {
    command.stdout(Stdio::piped()).stderr(Stdio::piped());
    if input.is_some() {
        command.stdin(Stdio::piped());
    }
    let mut child = command
        .spawn()
        .map_err(|error| format!("{what} could not start: {error}"))?;
    if let (Some(input), Some(mut stdin)) = (input, child.stdin.take()) {
        let _ = writeln!(stdin, "{input}");
    }
    let output = child
        .wait_with_output()
        .map_err(|error| format!("{what}: {error}"))?;
    if output.status.success() {
        Ok(())
    } else {
        let said = String::from_utf8_lossy(&output.stderr);
        let last = said.lines().rev().find(|line| !line.trim().is_empty());
        Err(format!("{what} failed: {}", last.unwrap_or("no message")))
    }
}

/// A port free on 127.0.0.1: ``wanted`` if it is.
fn free_port(wanted: u16) -> u16 {
    if wanted != 0 && TcpListener::bind(("127.0.0.1", wanted)).is_ok() {
        return wanted;
    }
    TcpListener::bind(("127.0.0.1", 0))
        .and_then(|listener| listener.local_addr())
        .map(|address| address.port())
        .unwrap_or(wanted)
}

fn secrets(data: &Path) -> Result<(Secrets, bool), String> {
    let path = data.join("secrets.json");
    if let Ok(bytes) = fs::read(&path) {
        return serde_json::from_slice(&bytes)
            .map(|secrets| (secrets, false))
            .map_err(|_| "The library's settings are damaged.".into());
    }
    let secrets = Secrets {
        database_password: crate::login::random(24),
        password: crate::login::random(24),
        database_port: free_port(0),
        port: free_port(0),
        pdf_folder: None,
    };
    save_secrets(data, &secrets)?;
    Ok((secrets, true))
}

fn save_secrets(data: &Path, secrets: &Secrets) -> Result<(), String> {
    fs::create_dir_all(data).map_err(|error| error.to_string())?;
    let path = data.join("secrets.json");
    let bytes = serde_json::to_vec_pretty(secrets).map_err(|error| error.to_string())?;
    fs::write(&path, bytes).map_err(|error| error.to_string())?;
    // Only for the person themselves.
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        let _ = fs::set_permissions(&path, fs::Permissions::from_mode(0o600));
    }
    Ok(())
}

/// The library's address, started if it is not running: its parts
/// downloaded if needed, a new database the first time. Blocks.
pub fn start(app: &AppHandle) -> Result<(Url, String), String> {
    if let Some(running) = RUNNING.lock().expect("running").as_ref() {
        return Ok((running.url.clone(), running.password.clone()));
    }
    progress("Getting the library ready…");
    let bundle = bundle(app)?;
    let data = data_folder(app)?;
    let (mut secrets, new) = secrets(&data)?;
    let postgres = bundle.join("postgres/bin");
    let database = data.join("database");

    if !database.exists() {
        progress("Making the library's database…");
        let password_file = data.join("database-password");
        fs::write(&password_file, &secrets.database_password).map_err(|e| e.to_string())?;
        let mut initdb = command(&executable(&postgres, "initdb"));
        initdb
            .arg("-D")
            .arg(&database)
            .args(["-U", "paperus", "-E", "UTF8", "--auth=scram-sha-256"])
            .arg(format!("--pwfile={}", password_file.display()));
        let made = run(initdb, "The database", None);
        let _ = fs::remove_file(&password_file);
        made?;
    }

    progress("Starting the library…");
    // Still running after the app ended without stopping it (a crash): used,
    // on its port.
    let mut status = command(&executable(&postgres, "pg_ctl"));
    status.arg("-D").arg(&database).arg("status");
    let running = run(status, "The database", None).is_ok();
    // The ports of last time, unless something else took them meanwhile.
    let database_port = if running {
        secrets.database_port
    } else {
        free_port(secrets.database_port)
    };
    let port = free_port(secrets.port);
    if (database_port, port) != (secrets.database_port, secrets.port) {
        secrets.database_port = database_port;
        secrets.port = port;
        save_secrets(&data, &secrets)?;
    }
    let mut pg_ctl = command(&executable(&postgres, "pg_ctl"));
    pg_ctl
        .arg("-D")
        .arg(&database)
        .arg("-l")
        .arg(data.join("postgres.log"))
        .args(["-w", "-o"])
        .arg(format!(
            "-p {database_port} -c listen_addresses=127.0.0.1 -c unix_socket_directories="
        ))
        .arg("start");
    if !running {
        run(pg_ctl, "The database", None)?;
    }
    if new {
        let mut createdb = command(&executable(&postgres, "createdb"));
        createdb
            .args([
                "-h",
                "127.0.0.1",
                "-p",
                &database_port.to_string(),
                "-U",
                "paperus",
            ])
            .arg("paperus")
            .env("PGPASSWORD", &secrets.database_password);
        run(createdb, "The database", None)?;
    }

    let server = |arguments: &[&str]| {
        let mut command = command(&python(&bundle));
        command
            .args(["-m", "paperus"])
            .args(arguments)
            // Its own Python only, whatever the computer's is set up with.
            .env_remove("PYTHONPATH")
            .env_remove("PYTHONHOME")
            .env("PYTHONNOUSERSITE", "1")
            .env(
                "PAPERUS_DATABASE_URL",
                format!(
                    "postgresql+psycopg://paperus:{}@127.0.0.1:{database_port}/paperus",
                    secrets.database_password
                ),
            )
            .env("PAPERUS_STORAGE_PATH", pdf_folder(&data, &secrets))
            // New files wait here while the PDFs' folder (a network share,
            // say) is out of reach.
            .env("PAPERUS_INCOMING_PATH", data.join("incoming"))
            .env("PAPERUS_BACKUP_PATH", data.join("backups"))
            .env("PAPERUS_COPY_PATH", data.join("library-copy"))
            .env("PAPERUS_WEB_PATH", bundle.join("web"))
            // Plain http on 127.0.0.1, no ML service (yet): words only.
            .env("PAPERUS_COOKIE_SECURE", "false")
            .env("PAPERUS_ML_URLS", "[\"http://127.0.0.1:9\"]");
        command
    };
    run(server(&["migrate"]), "Updating the library", None)?;
    if new {
        run(
            server(&["user", "create", USER, "--admin", "--password-stdin"]),
            "The library's login",
            Some(&secrets.password),
        )?;
    }
    let log = |name: &str| {
        fs::File::create(data.join(name))
            .map(Stdio::from)
            .unwrap_or_else(|_| Stdio::null())
    };
    // Their input stays open while the app runs: when it ends, however it
    // ends, they do too (--stop-with-stdin).
    let mut serve = server(&[
        "serve",
        "--host",
        "127.0.0.1",
        "--port",
        &port.to_string(),
        "--stop-with-stdin",
    ]);
    serve
        .stdin(Stdio::piped())
        .stdout(log("server.log"))
        .stderr(log("server-errors.log"));
    let mut worker = server(&["worker", "--stop-with-stdin"]);
    worker
        .stdin(Stdio::piped())
        .stdout(log("worker.log"))
        .stderr(log("worker-errors.log"));
    let children = vec![
        serve.spawn().map_err(|error| error.to_string())?,
        worker.spawn().map_err(|error| error.to_string())?,
    ];
    let url = Url::parse(&format!("http://127.0.0.1:{port}")).expect("an address");
    *RUNNING.lock().expect("running") = Some(Running {
        url: url.clone(),
        password: secrets.password.clone(),
        children,
        postgres,
        database,
    });

    // Until it answers.
    let started = Instant::now();
    let health = format!("{url}api/health");
    while libraries::agent()
        .get(&health)
        .call()
        .map_or(true, |response| !response.status().is_success())
    {
        if started.elapsed() > Duration::from_secs(60) {
            stop();
            return Err("The library did not start (see server-errors.log in its folder).".into());
        }
        thread::sleep(Duration::from_millis(250));
    }
    progress("");
    Ok((url, secrets.password))
}

/// The session for the library's only person: its login cookie's value and
/// how long it lasts.
pub fn log_in(url: &Url, password: &str) -> Result<(String, i64), String> {
    let response = libraries::agent()
        .post(format!("{url}api/auth/login"))
        .send_json(serde_json::json!({ "username": USER, "password": password }))
        .map_err(|error| format!("Logging in to the library did not work: {error}."))?;
    if !response.status().is_success() {
        return Err(format!(
            "Logging in to the library did not work ({}).",
            response.status()
        ));
    }
    response
        .headers()
        .get_all("set-cookie")
        .iter()
        .filter_map(|header| header.to_str().ok())
        .find_map(session_of)
        .ok_or_else(|| "The library gave no login.".into())
}

/// The session in a Set-Cookie header for the login cookie.
fn session_of(header: &str) -> Option<(String, i64)> {
    let mut parts = header.split(';').map(str::trim);
    let (name, value) = parts.next()?.split_once('=')?;
    if name != libraries::SESSION_COOKIE || value.is_empty() {
        return None;
    }
    let max_age = parts
        .find_map(|part| {
            let (key, value) = part.split_once('=')?;
            key.eq_ignore_ascii_case("max-age")
                .then(|| value.parse().ok())?
        })
        .unwrap_or(30 * 24 * 3600);
    Some((value.to_owned(), max_age))
}

/// Where the library's PDFs are kept: a folder chosen (a network share,
/// another disk), else beside its database.
fn pdf_folder(data: &Path, secrets: &Secrets) -> PathBuf {
    secrets
        .pdf_folder
        .clone()
        .unwrap_or_else(|| data.join("files"))
}

/// Where the PDFs of the library on this computer are, if there is one.
pub fn current_pdf_folder(app: &AppHandle) -> Option<PathBuf> {
    let data = data_folder(app).ok()?;
    let bytes = fs::read(data.join("secrets.json")).ok()?;
    let secrets: Secrets = serde_json::from_slice(&bytes).ok()?;
    Some(pdf_folder(&data, &secrets))
}

/// The marker naming the library a folder of stored files belongs to
/// (`server/src/paperus/storage.py`).
const MARKER: &str = ".paperus-library";

/// Keep the PDFs in ``to`` from now on: the library stopped, what is in
/// the old folder copied over, checked, and removed there. Refused for a
/// folder another library owns. Start the library again afterwards.
pub fn move_pdf_folder(app: &AppHandle, to: &Path) -> Result<(), String> {
    let data = data_folder(app)?;
    let (mut secrets, _) = secrets(&data)?;
    let from = pdf_folder(&data, &secrets);
    if from == to {
        return Ok(());
    }
    let ours = fs::read_to_string(from.join(MARKER)).ok();
    if let Ok(theirs) = fs::read_to_string(to.join(MARKER))
        && Some(&theirs) != ours.as_ref()
    {
        return Err("That folder holds another library's files.".into());
    }
    progress("Moving the PDFs");
    stop();
    copy_tree(&from, &from, to)?;
    secrets.pdf_folder = (to != data.join("files")).then(|| to.to_path_buf());
    save_secrets(&data, &secrets)?;
    // Only once all is over and the setting saved.
    let _ = fs::remove_dir_all(&from);
    progress("");
    Ok(())
}

/// Copy everything under ``folder`` (inside ``root``) to the same place
/// under ``to``, each file checked by its size.
fn copy_tree(root: &Path, folder: &Path, to: &Path) -> Result<(), String> {
    let Ok(entries) = fs::read_dir(folder) else {
        return Ok(());
    };
    for entry in entries.flatten() {
        let path = entry.path();
        if path.is_dir() {
            copy_tree(root, &path, to)?;
            continue;
        }
        let relative = path.strip_prefix(root).map_err(|error| error.to_string())?;
        let target = to.join(relative);
        if let Some(parent) = target.parent() {
            fs::create_dir_all(parent).map_err(|error| error.to_string())?;
        }
        let copied = fs::copy(&path, &target).map_err(|error| error.to_string())?;
        let size = entry.metadata().map(|meta| meta.len()).unwrap_or(copied);
        if copied != size {
            return Err(format!("{} was not copied whole.", relative.display()));
        }
    }
    Ok(())
}

/// Ends the library's processes (when the app ends).
pub fn stop() {
    let Some(mut running) = RUNNING.lock().expect("running").take() else {
        return;
    };
    for child in &mut running.children {
        let _ = child.kill();
        let _ = child.wait();
    }
    let mut pg_ctl = command(&executable(&running.postgres, "pg_ctl"));
    pg_ctl
        .arg("-D")
        .arg(&running.database)
        .args(["-m", "fast", "-w", "stop"]);
    let _ = run(pg_ctl, "The database", None);
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn the_pdfs_copied_whole() {
        let root = std::env::temp_dir().join(format!("paperus-move-{}", std::process::id()));
        let (from, to) = (root.join("from"), root.join("to"));
        fs::create_dir_all(from.join("blobs/ab/cd")).unwrap();
        fs::write(from.join("blobs/ab/cd/abcd"), "a PDF").unwrap();
        fs::write(from.join(MARKER), "us\n").unwrap();
        copy_tree(&from, &from, &to).unwrap();
        assert_eq!(
            fs::read_to_string(to.join("blobs/ab/cd/abcd")).unwrap(),
            "a PDF"
        );
        assert_eq!(fs::read_to_string(to.join(MARKER)).unwrap(), "us\n");
        fs::remove_dir_all(&root).unwrap();
    }

    #[test]
    fn the_login_cookie_is_read_from_its_header() {
        let header = "paperus_session=abc123; HttpOnly; Max-Age=2592000; Path=/; SameSite=lax";
        assert_eq!(session_of(header), Some(("abc123".into(), 2_592_000)));
        assert_eq!(session_of("other=1; Path=/"), None);
        assert_eq!(session_of("paperus_session=; Max-Age=0"), None);
    }

    #[test]
    fn a_wanted_port_is_kept_while_free() {
        let port = free_port(0);
        assert_ne!(port, 0);
        assert_eq!(free_port(port), port);
        let taken = TcpListener::bind(("127.0.0.1", 0)).unwrap();
        let busy = taken.local_addr().unwrap().port();
        assert_ne!(free_port(busy), busy);
    }
}
