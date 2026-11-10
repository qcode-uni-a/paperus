fn main() {
    tauri_build::try_build(tauri_build::Attributes::new().app_manifest(
        tauri_build::AppManifest::new().commands(&[
            "libraries",
            "add_library",
            "forget_library",
            "open_library",
        ]),
    ))
    .expect("failed to build the app");
}
