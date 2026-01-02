# Coding Checker VS Code Extension

Opens native VS Code diff views when `basic_rust.py` writes files.

## Install (local workspace)
1) Open the `Coding_checker` folder in VS Code.
2) Run the command palette action: `Developer: Install Extension from Location...`
3) Select the `Coding_checker/vscode-extension` folder.
4) Reload VS Code when prompted.

## Use
- Run `basic_rust.py` from the integrated terminal.  
  The extension watches `.coding_checker/ui.signal.json` and opens VS Code diff views.
- You can also run the command `Coding Checker: Open Latest Diff`.

## Example workflow
1) Open the `Coding_checker` folder in VS Code and install the extension.
2) Start the agent from the integrated terminal:
   ```bash
   python3 basic_rust.py
   ```
3) Enter a concrete prompt, for example:
   ```text
   Create a Rust library crate in project_dir "demo2".
   Implement fn clamp_i32(x: i32, lo: i32, hi: i32) -> i32 where lo <= hi.
   Add a Kani proof that:
     1) result is always within [lo, hi]
     2) clamp is idempotent: clamp(clamp(x, lo, hi), lo, hi) == clamp(x, lo, hi)
   Use kani::assume(lo <= hi).
   Run kani and fix if needed.
   ```
4) When the agent writes `workspace/demo2/src/lib.rs`, the extension opens a diff view
   showing the before/after changes immediately.
