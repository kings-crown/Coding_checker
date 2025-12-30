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
