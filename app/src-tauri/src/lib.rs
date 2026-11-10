//! paperus as an app (docs/apps.md): a paperus server's website in a
//! window of its own. The app's own page (`start/`) lists the libraries
//! and adds one; a library's website is a remote address and gets no
//! access to the app (no capability names it).

mod libraries;
mod login;

use std::{
    path::{Path, PathBuf},
    sync::atomic::{AtomicUsize, Ordering},
};

use libraries::Library;
use tauri::{
    AppHandle, Manager, Url, WebviewUrl, WebviewWindow, WebviewWindowBuilder,
    menu::{Menu, MenuItem, PredefinedMenuItem, Submenu},
    webview::{DownloadEvent, NewWindowResponse},
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
fn open_library(app: AppHandle, url: String) -> Result<(), String> {
    let mut saved = libraries::load(&app);
    if !saved.libraries.iter().any(|library| library.url == url) {
        return Err("No such library.".into());
    }
    saved.last = Some(url.clone());
    libraries::save(&app, &saved)?;
    let window = app.get_webview_window(MAIN).ok_or("The window is gone.")?;
    let to = Url::parse(&url).map_err(|error| error.to_string())?;
    window.navigate(to).map_err(|error| error.to_string())
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
        // browser's then: web/src/routes/login).
        .initialization_script("window.paperusApp = {};")
        .inner_size(1280.0, 860.0)
        .min_inner_size(420.0, 520.0)
        .on_navigation(move |url| match url.scheme() {
            // The page, a library, its login (its OIDC provider's pages).
            "http" | "https" | "tauri" => true,
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
        .plugin(tauri_plugin_opener::init())
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
            open_library
        ])
        .setup(|app| {
            let saved = libraries::load(app.handle());
            // The library open last, else the app's page.
            let url = saved
                .last
                .filter(|last| saved.libraries.iter().any(|library| &library.url == last))
                .and_then(|last| Url::parse(&last).ok())
                .map_or(WebviewUrl::App("index.html".into()), WebviewUrl::External);
            window(app.handle(), MAIN, url)?;
            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("paperus failed to start");
}
