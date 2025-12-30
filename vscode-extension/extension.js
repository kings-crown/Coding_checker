const fs = require("fs")
const path = require("path")
const vscode = require("vscode")

const SCHEME = "coding-checker"
const SIGNAL_FILE = ".coding_checker/ui.signal.json"

function activate(context) {
  const contentByUri = new Map()
  const emitter = new vscode.EventEmitter()
  context.subscriptions.push(emitter)

  const provider = {
    onDidChange: emitter.event,
    provideTextDocumentContent(uri) {
      return contentByUri.get(uri.toString()) ?? ""
    },
  }
  context.subscriptions.push(vscode.workspace.registerTextDocumentContentProvider(SCHEME, provider))

  let latestPayload = null

  const openDiffFromPayload = async (payload) => {
    if (!payload) {
      vscode.window.showInformationMessage("No Coding Checker diff available yet.")
      return
    }

    const fileLabel = payload.path || payload.abs_path || "unknown"
    const beforeUri = buildVirtualUri(fileLabel, "before")
    contentByUri.set(beforeUri.toString(), payload.before || "")
    emitter.fire(beforeUri)

    let rightUri
    if (payload.abs_path && fs.existsSync(payload.abs_path)) {
      rightUri = vscode.Uri.file(payload.abs_path)
    } else {
      rightUri = buildVirtualUri(fileLabel, "after")
      contentByUri.set(rightUri.toString(), payload.after || "")
      emitter.fire(rightUri)
    }

    const title = `Coding Checker: ${path.basename(fileLabel)}`
    await vscode.commands.executeCommand("vscode.diff", beforeUri, rightUri, title)
  }

  const handleSignal = async (signalUri) => {
    let payload
    try {
      const raw = await fs.promises.readFile(signalUri.fsPath, "utf8")
      payload = JSON.parse(raw)
    } catch (error) {
      return
    }

    if (!payload || payload.event !== "file_diff") {
      return
    }

    latestPayload = payload
    openDiffFromPayload(payload)
  }

  const signalRoots = getSignalRoots(context)
  for (const root of signalRoots) {
    const pattern = new vscode.RelativePattern(vscode.Uri.file(root), SIGNAL_FILE)
    const watcher = vscode.workspace.createFileSystemWatcher(pattern)
    watcher.onDidCreate(handleSignal)
    watcher.onDidChange(handleSignal)
    context.subscriptions.push(watcher)
  }

  const command = vscode.commands.registerCommand("codingChecker.openPatchUI", () =>
    openDiffFromPayload(latestPayload),
  )
  context.subscriptions.push(command)
}

function buildVirtualUri(filePath, tag) {
  const normalized = filePath.replace(/\\/g, "/")
  const encoded = encodeURIComponent(normalized)
  return vscode.Uri.parse(`${SCHEME}:/${tag}/${encoded}`)
}

function getSignalRoots(context) {
  const roots = new Set()
  const workspaceFolders = vscode.workspace.workspaceFolders ?? []

  for (const folder of workspaceFolders) {
    roots.add(folder.uri.fsPath)
    roots.add(path.join(folder.uri.fsPath, "Coding_checker"))
  }

  roots.add(path.resolve(context.extensionPath, ".."))

  return Array.from(roots)
}

function deactivate() {}

module.exports = { activate, deactivate }
