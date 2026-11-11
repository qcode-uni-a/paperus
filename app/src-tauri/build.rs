fn main() {
    tauri_build::try_build(tauri_build::Attributes::new().app_manifest(
        tauri_build::AppManifest::new().commands(&[
            "libraries",
            "add_library",
            "forget_library",
            "open_library",
            "make_local_library",
            "local_progress",
            "unsaved_changes",
            "dismiss_unsaved",
            "logins_in_file",
            "logging_out",
            "local_pdf_folder",
            "choose_pdf_folder",
        ]),
    ))
    .expect("failed to build the app");
}
