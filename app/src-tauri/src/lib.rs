//! paperus as an app (docs/apps.md): a paperus server's website in a
//! window of its own. The app's own page (`start/`) lists the libraries
//! and adds one; a library's website is a remote address and gets no
//! access to the app (no capability names it).

mod libraries;
mod local;
mod login;
mod notices;
mod offline;
mod open_with;

use std::{
    path::{Path, PathBuf},
    sync::atomic::{AtomicUsize, Ordering},
};

use libraries::Library;
use tauri::{
    AppHandle, Manager, Url, WebviewUrl, WebviewWindow, WebviewWindowBuilder,
    menu::{Menu, MenuItem, PredefinedMenuItem, Submenu},
    webview::{DownloadEvent, NewWindowResponse, PageLoadEvent},
};
use tauri_plugin_opener::OpenerExt;

const MAIN: &str = "main";

/// Where the app's own page is served (the scheme differs by system).
fn start_page() -> Url {
    let base = if cfg!(any(windows, target_os = "android")) {
        "http://tauri.localhost/"
    } else {
        "tauri://localhost/"
    };
    Url::parse(base).expect("a valid address")
}

#[tauri::command]
fn libraries(app: AppHandle) -> Vec<Library> {
    libraries::load(&app).libraries
}

#[tauri::command]
async fn add_library(app: AppHandle, address: String) -> Result<Library, String> {
    let url = libraries::address(&address)?;
    let checked = url.clone();
    tauri::async_runtime::spawn_blocking(move || libraries::check(&checked))
        .await
        .map_err(|error| error.to_string())??;
    let library = Library {
        url: libraries::key(&url),
        name: url.host_str().unwrap_or_default().to_owned(),
        local: false,
    };
    let mut saved = libraries::load(&app);
    if !saved.libraries.contains(&library) {
        saved.libraries.push(library.clone());
        libraries::save(&app, &saved)?;
    }
    Ok(library)
}

#[tauri::command]
fn forget_library(app: AppHandle, url: String) -> Result<(), String> {
    let mut saved = libraries::load(&app);
    saved.libraries.retain(|library| library.url != url);
    if saved.last.as_deref() == Some(&url) {
        saved.last = None;
    }
    libraries::save(&app, &saved)
}

#[tauri::command]
async fn open_library(app: AppHandle, url: String) -> Result<(), String> {
    let mut saved = libraries::load(&app);
    let library = saved
        .libraries
        .iter()
        .find(|library| library.url == url)
        .cloned()
        .ok_or("No such library.")?;
    if library.local {
        return open_local(app).await;
    }
    saved.last = Some(url.clone());
    libraries::save(&app, &saved)?;
    let window = app.get_webview_window(MAIN).ok_or("The window is gone.")?;
    // Out of reach: its copy, if there is one (offline.rs).
    let checked = url.clone();
    let reachable = tauri::async_runtime::spawn_blocking(move || offline::reachable(&checked))
        .await
        .unwrap_or(true);
    if !reachable && offline::has_copy(&app, &url) {
        return offline::open(&window, &url).map_err(|error| error.to_string());
    }
    let to = Url::parse(&url).map_err(|error| error.to_string())?;
    window.navigate(to).map_err(|error| error.to_string())
}

/// The library of the copy open in ``window`` again, if it answers.
fn back_online(app: &AppHandle, label: &str) {
    let app = app.clone();
    let label = label.to_owned();
    std::thread::spawn(move || {
        let Some(window) = app.get_webview_window(&label) else {
            return;
        };
        let library = offline::open_library();
        match library.filter(|url| offline::reachable(url)) {
            Some(url) => {
                if let Ok(to) = Url::parse(&url) {
                    let _ = window.navigate(to);
                }
            }
            None => {
                let _ = window.eval("alert('The library still cannot be reached.')");
            }
        }
    });
}

/// Makes the library on this computer (its parts downloaded, a database
/// made) and opens it.
#[tauri::command]
async fn make_local_library(app: AppHandle) -> Result<(), String> {
    open_local(app).await
}

/// What the library on this computer is doing while it gets ready.
#[tauri::command]
fn local_progress() -> String {
    local::PROGRESS
        .lock()
        .map(|text| text.clone())
        .unwrap_or_default()
}

/// Changes made offline that libraries refused (changed or gone meanwhile).
#[tauri::command]
fn unsaved_changes(app: AppHandle) -> Vec<offline::Unsaved> {
    offline::unsaved(&app)
}

/// The person has seen one of them.
#[tauri::command]
fn dismiss_unsaved(app: AppHandle, library: String, seq: i64) -> Result<(), String> {
    offline::dismiss(&app, &library, seq)
}

/// Starts the library on this computer if needed, logs the window in and
/// opens it; kept in the list (its address follows its port).
async fn open_local(app: AppHandle) -> Result<(), String> {
    let started = app.clone();
    let (url, password) = tauri::async_runtime::spawn_blocking(move || local::start(&started))
        .await
        .map_err(|error| error.to_string())??;
    let login = url.clone();
    let (token, max_age) =
        tauri::async_runtime::spawn_blocking(move || local::log_in(&login, &password))
            .await
            .map_err(|error| error.to_string())??;
    let mut saved = libraries::load(&app);
    saved.libraries.retain(|library| !library.local);
    let library = Library {
        url: libraries::key(&url),
        name: "This computer".into(),
        local: true,
    };
    saved.last = Some(library.url.clone());
    saved.libraries.insert(0, library);
    libraries::save(&app, &saved)?;
    let window = app.get_webview_window(MAIN).ok_or("The window is gone.")?;
    window
        .set_cookie(login::cookie(&url, token, max_age))
        .map_err(|error| error.to_string())?;
    window.navigate(url).map_err(|error| error.to_string())
}

/// A window for the app's page or a library, with what the app does
/// around the website: other sites' links in the system's browser, the
/// library's own in another window, downloads into Downloads.
fn window(app: &AppHandle, label: &str, url: WebviewUrl) -> tauri::Result<WebviewWindow> {
    let opener = app.clone();
    let windows = app.clone();
    let own = label.to_owned();
    WebviewWindowBuilder::new(app, label, url)
        .title("paperus")
        // The website knows it is in the app (its login page offers the
        // browser's then: web/src/routes/login), which version, and what
        // it can do (web/src/lib/app.ts).
        .initialization_script(format!(
            "window.paperusApp = {};",
            serde_json::json!({
                "version": env!("CARGO_PKG_VERSION"),
                "features": {"offline": offline::SYNC},
            })
        ))
        .inner_size(1280.0, 860.0)
        .min_inner_size(420.0, 520.0)
        .on_navigation(move |url| match url.scheme() {
            // The page, a library, its login (its OIDC provider's pages),
            // a library's copy offline.
            "http" | "https" | "tauri" | offline::SCHEME => true,
            "about" | "blob" | "data" => true,
            // The website asking the app: log in in the system's browser.
            "paperus-app" => {
                if url.path() == "login" {
                    let next = url
                        .query_pairs()
                        .find(|(key, _)| key == "next")
                        .map(|(_, path)| path.into_owned())
                        .filter(|path| path.starts_with('/') && !path.starts_with("//"))
                        .unwrap_or_else(|| "/".into());
                    login::start(opener.clone(), own.clone(), next);
                }
                // The copy's "Go online" (web/src/lib/OfflineBanner.svelte).
                if url.path() == "online" {
                    back_online(&opener, &own);
                }
                false
            }
            // mailto: and the like: the system's programs.
            _ => {
                let _ = opener.opener().open_url(url.as_str(), None::<&str>);
                false
            }
        })
        .on_new_window(move |url, _features| {
            if libraries::of(&windows, &url).is_some() {
                static OPENED: AtomicUsize = AtomicUsize::new(0);
                let label = format!("library-{}", OPENED.fetch_add(1, Ordering::Relaxed));
                let _ = window(&windows, &label, WebviewUrl::External(url));
            } else if matches!(url.scheme(), "http" | "https" | "mailto") {
                let _ = windows.opener().open_url(url.as_str(), None::<&str>);
            }
            NewWindowResponse::Deny
        })
        // Files dropped on the window are the website's (its drop zone).
        .disable_drag_drop_handler()
        .on_page_load(|window, payload| {
            if window.label() == MAIN && payload.event() == PageLoadEvent::Finished {
                open_with::loaded(window.app_handle());
                offline::nudge();
            }
        })
        .on_document_title_changed(|window, title| {
            let _ = window.set_title(if title.is_empty() { "paperus" } else { &title });
        })
        .on_download(|webview, event| {
            if let DownloadEvent::Requested { url, destination } = event {
                let Some(folder) = webview.app_handle().path().download_dir().ok() else {
                    return false;
                };
                let name = destination
                    .file_name()
                    .map(|name| name.to_string_lossy().into_owned())
                    .or_else(|| url.path_segments()?.next_back().map(str::to_owned))
                    .filter(|name| !name.is_empty())
                    .unwrap_or_else(|| "download".into());
                *destination = unused(&folder, &name);
            }
            true
        })
        .build()
}

/// ``name`` in ``folder``, or "name (2).ext" and on if taken.
fn unused(folder: &Path, name: &str) -> PathBuf {
    let path = folder.join(name);
    if !path.exists() {
        return path;
    }
    let (stem, extension) = match name.rsplit_once('.') {
        Some((stem, extension)) if !stem.is_empty() => (stem, format!(".{extension}")),
        _ => (name, String::new()),
    };
    (2..)
        .map(|n| folder.join(format!("{stem} ({n}){extension}")))
        .find(|path| !path.exists())
        .expect("a free name")
}

fn menu(app: &AppHandle) -> tauri::Result<Menu<tauri::Wry>> {
    let menu = Menu::default(app)?;
    let library = Submenu::with_items(
        app,
        "Library",
        true,
        &[
            &MenuItem::with_id(
                app,
                "libraries",
                "Libraries…",
                true,
                Some("CmdOrCtrl+Shift+L"),
            )?,
            &PredefinedMenuItem::separator(app)?,
            &MenuItem::with_id(app, "back", "Back", true, Some("Alt+Left"))?,
            &MenuItem::with_id(app, "forward", "Forward", true, Some("Alt+Right"))?,
            &MenuItem::with_id(app, "reload", "Reload", true, Some("CmdOrCtrl+R"))?,
        ],
    )?;
    menu.append(&library)?;
    Ok(menu)
}

fn focused(app: &AppHandle) -> Option<WebviewWindow> {
    let windows = app.webview_windows();
    windows
        .values()
        .find(|window| window.is_focused().unwrap_or(false))
        .or_else(|| windows.get(MAIN))
        .cloned()
}

pub fn run() {
    tauri::Builder::default()
        // One app: opening it again (or a file with it) goes to this one.
        .plugin(tauri_plugin_single_instance::init(|app, arguments, _| {
            if let Some(main) = app.get_webview_window(MAIN) {
                let _ = main.unminimize();
                let _ = main.set_focus();
            }
            open_with::open(app, open_with::files_in(&arguments));
        }))
        .plugin(tauri_plugin_opener::init())
        .plugin(tauri_plugin_notification::init())
        .register_asynchronous_uri_scheme_protocol(offline::SCHEME, offline::serve)
        .menu(menu)
        .on_menu_event(|app, event| {
            let Some(window) = focused(app) else { return };
            let _ = match event.id().as_ref() {
                "libraries" => app.get_webview_window(MAIN).map_or(Ok(()), |main| {
                    let _ = main.set_focus();
                    main.navigate(start_page())
                }),
                "back" => window.eval("history.back()"),
                "forward" => window.eval("history.forward()"),
                "reload" => window.eval("location.reload()"),
                _ => Ok(()),
            };
        })
        .invoke_handler(tauri::generate_handler![
            libraries,
            add_library,
            forget_library,
            open_library,
            make_local_library,
            local_progress,
            unsaved_changes,
            dismiss_unsaved
        ])
        .setup(|app| {
            let saved = libraries::load(app.handle());
            // The library open last, else the app's page; the one on this
            // computer from the app's page, which shows it starting.
            let last = saved
                .last
                .as_ref()
                .and_then(|last| saved.libraries.iter().find(|library| &library.url == last));
            let url = match last {
                Some(library) if !library.local => Url::parse(&library.url)
                    .map_or(WebviewUrl::App("index.html".into()), WebviewUrl::External),
                _ => WebviewUrl::App("index.html".into()),
            };
            let main = window(app.handle(), MAIN, url)?;
            // The library open last, out of reach: its copy.
            if let Some(library) = last.filter(|library| !library.local).cloned() {
                let opening = app.handle().clone();
                std::thread::spawn(move || {
                    if !offline::reachable(&library.url)
                        && offline::has_copy(&opening, &library.url)
                    {
                        let _ = offline::open(&main, &library.url);
                    }
                });
            }
            if last.is_some_and(|library| library.local) {
                let opening = app.handle().clone();
                tauri::async_runtime::spawn(async move {
                    if let Err(message) = open_local(opening.clone()).await
                        && let Some(main) = opening.get_webview_window(MAIN)
                    {
                        let _ = main.eval(format!(
                            "alert({})",
                            serde_json::to_string(&message).unwrap_or_default()
                        ));
                    }
                });
            }
            notices::start(app.handle().clone());
            offline::start(app.handle().clone());
            let arguments: Vec<String> = std::env::args().collect();
            open_with::open(app.handle(), open_with::files_in(&arguments));
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("paperus failed to start")
        .run(|_app, _event| {
            // The library on this computer ends with the app.
            if let tauri::RunEvent::Exit = _event {
                local::stop();
            }
            // macOS hands files over as an event, not as arguments.
            #[cfg(target_os = "macos")]
            if let tauri::RunEvent::Opened { urls } = _event {
                let files = urls
                    .iter()
                    .filter_map(|url| url.to_file_path().ok())
                    .collect();
                open_with::open(_app, files);
            }
        });
}
