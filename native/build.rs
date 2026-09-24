// The module's __version__ is the release placemat builds on: the last v*
// tag of this checkout (git describe), the same tag placemat's own version
// comes from. Built outside a git checkout, the crate's placeholder version
// stands in - placemat then declines the module, the safe answer for a
// build it cannot vouch for.
use std::process::Command;

fn main() {
    println!("cargo:rerun-if-changed=../.git/HEAD");
    println!("cargo:rerun-if-changed=../.git/refs/tags");
    println!("cargo:rerun-if-changed=../.git/packed-refs");
    let tag = Command::new("git")
        .args(["describe", "--tags", "--abbrev=0", "--match", "v*"])
        .output()
        .ok()
        .filter(|o| o.status.success())
        .and_then(|o| String::from_utf8(o.stdout).ok())
        .map(|s| s.trim().trim_start_matches('v').to_owned());
    let version = tag.unwrap_or_else(|| env!("CARGO_PKG_VERSION").to_owned());
    println!("cargo:rustc-env=PLACEMAT_VERSION={version}");
}
