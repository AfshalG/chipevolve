const vscode = require("vscode");
const http = require("http");
const https = require("https");
const path = require("path");
const fs = require("fs");
const { spawn } = require("child_process");

let dashboardPanel;
let backendProcess;

function configuration() {
  const config = vscode.workspace.getConfiguration("chipevolve");
  return {
    backendUrl: config.get("backendUrl", "http://127.0.0.1:8000").replace(/\/$/, ""),
    port: config.get("port", 8000),
    distro: config.get("wslDistro", "Ubuntu"),
    // WSL is opt-in and Windows-only. macOS/Linux spawn Python directly.
    useWsl: config.get("useWsl", false),
    pythonPath: config.get("pythonPath", ""),
    backendPath: config.get("backendPath", ""),
    projectPath: config.get("projectPath", "examples/alu"),
  };
}

function projectRoot(context) {
  const configured = configuration().projectPath;
  return path.isAbsolute(configured) ? configured : path.join(context.extensionPath, configured);
}

function toWslPath(windowsPath) {
  const resolved = path.resolve(windowsPath).replaceAll("\\", "/");
  const match = resolved.match(/^([A-Za-z]):\/(.*)$/);
  return match ? `/mnt/${match[1].toLowerCase()}/${match[2]}` : resolved;
}

function shellQuote(value) {
  return `'${String(value).replaceAll("'", `'"'"'`)}'`;
}

function requestJson(method, target, body) {
  return new Promise((resolve, reject) => {
    const url = new URL(target);
    const transport = url.protocol === "https:" ? https : http;
    const payload = body === undefined ? undefined : JSON.stringify(body);
    const request = transport.request(url, {
      method,
      headers: payload ? { "content-type": "application/json", "content-length": Buffer.byteLength(payload) } : {},
      timeout: 5000,
    }, (response) => {
      let data = "";
      response.setEncoding("utf8");
      response.on("data", (chunk) => { data += chunk; });
      response.on("end", () => {
        if ((response.statusCode ?? 500) >= 400) {
          reject(new Error(data || `Backend returned ${response.statusCode}`));
          return;
        }
        try { resolve(data ? JSON.parse(data) : {}); }
        catch (error) { reject(error); }
      });
    });
    request.on("timeout", () => request.destroy(new Error("Backend request timed out")));
    request.on("error", reject);
    if (payload) request.write(payload);
    request.end();
  });
}

async function backendReady() {
  try {
    await requestJson("GET", `${configuration().backendUrl}/api/health`);
    return true;
  } catch {
    return false;
  }
}

/**
 * Locate the Python backend and the interpreter to run it with.
 *
 * The repo layout is: <repoRoot>/chipevolve/  (package)
 *                     <repoRoot>/.venv/       (interpreter)
 * The extension lives at <repoRoot>/extension/, so the backend is one level up.
 * A configured backendPath overrides this entirely.
 */
function resolveBackend(context) {
  const configured = configuration().backendPath;
  if (configured) return path.resolve(configured);
  const repoRoot = path.resolve(context.extensionPath, "..");
  if (fs.existsSync(path.join(repoRoot, "chipevolve", "api", "main.py"))) return repoRoot;
  // Fallback: a bundled copy shipped inside the extension.
  return path.join(context.extensionPath, "backend");
}

function resolvePython(backendDir) {
  const configured = configuration().pythonPath;
  if (configured) return configured;
  const candidates = process.platform === "win32"
    ? [path.join(backendDir, ".venv", "Scripts", "python.exe")]
    : [path.join(backendDir, ".venv", "bin", "python")];
  for (const candidate of candidates) {
    if (fs.existsSync(candidate)) return candidate;
  }
  return process.platform === "win32" ? "python" : "python3";
}

async function startBackend(context, showProgress = true) {
  if (await backendReady()) return true;
  if (backendProcess && backendProcess.exitCode === null) return waitForBackend();

  const output = vscode.window.createOutputChannel("ChipEvolve");
  context.subscriptions.push(output);
  output.show(true);

  const backend = resolveBackend(context);
  const project = projectRoot(context);
  const useWsl = process.platform === "win32" && configuration().useWsl;

  const args = [
    "-m", "uvicorn", "chipevolve.api.main:app",
    "--host", "127.0.0.1", "--port", String(configuration().port),
  ];

  if (useWsl) {
    // Windows + WSL: run inside the distro, translating paths.
    const distro = configuration().distro;
    const command = [
      `cd ${shellQuote(toWslPath(backend))}`,
      `export CHIPEVOLVE_PROJECT=${shellQuote(toWslPath(project))}`,
      `PYTHONPATH=. .venv/bin/python ${args.join(" ")}`,
    ].join(" && ");
    output.appendLine(`[extension] Starting backend in WSL (${distro})`);
    backendProcess = spawn("wsl.exe", ["-d", distro, "--", "bash", "-lc", command], { windowsHide: true });
  } else {
    // macOS, Linux, and native Windows all take this path.
    const python = resolvePython(backend);
    output.appendLine(`[extension] Starting backend: ${python} ${args.join(" ")}`);
    output.appendLine(`[extension] cwd=${backend}  project=${project}`);
    backendProcess = spawn(python, args, {
      cwd: backend,
      env: { ...process.env, PYTHONPATH: backend, CHIPEVOLVE_PROJECT: project },
      windowsHide: true,
    });
  }

  backendProcess.stdout.on("data", (chunk) => output.append(chunk.toString()));
  backendProcess.stderr.on("data", (chunk) => output.append(chunk.toString()));
  backendProcess.on("error", (error) => {
    output.appendLine(`[extension] Failed to spawn backend: ${error.message}`);
    vscode.window.showErrorMessage(`ChipEvolve could not start the backend: ${error.message}`);
  });
  backendProcess.on("exit", (code) => output.appendLine(`[extension] Backend exited with code ${code}`));

  const wait = waitForBackend();
  if (!showProgress) return wait;
  return vscode.window.withProgress(
    { location: vscode.ProgressLocation.Notification, title: "Starting ChipEvolve\u2026" },
    () => wait,
  );
}

async function waitForBackend() {
  for (let attempt = 0; attempt < 30; attempt += 1) {
    if (await backendReady()) return true;
    await new Promise((resolve) => setTimeout(resolve, 500));
  }
  vscode.window.showErrorMessage("ChipEvolve backend did not start. Check the ChipEvolve output channel — the usual cause is a missing .venv.");
  return false;
}

function webviewHtml(webview, context, mode = "dashboard") {
  const media = vscode.Uri.joinPath(context.extensionUri, "apps", "extension", "media");
  const styleUri = webview.asWebviewUri(vscode.Uri.joinPath(media, "dashboard.css"));
  const scriptUri = webview.asWebviewUri(vscode.Uri.joinPath(media, "dashboard.js"));
  const nonce = Math.random().toString(36).slice(2);
  return `<!doctype html>
  <html lang="en"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
  <meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src ${webview.cspSource}; script-src 'nonce-${nonce}';">
  <link rel="stylesheet" href="${styleUri}"><title>ChipEvolve</title></head>
  <body data-mode="${mode}"><div id="app"></div><script nonce="${nonce}" src="${scriptUri}"></script></body></html>`;
}

function postSnapshot(webview) {
  const base = configuration().backendUrl;
  requestJson("GET", `${base}/api/project`)
    .then((snapshot) => webview.postMessage({ type: "snapshot", snapshot }))
    .catch((error) => webview.postMessage({ type: "offline", message: error.message }));
}

function attachEventStream(webview) {
  const target = new URL(`${configuration().backendUrl}/api/events`);
  const request = http.get(target, { headers: { accept: "text/event-stream" } }, (response) => {
    response.setEncoding("utf8");
    let buffer = "";
    response.on("data", (chunk) => {
      buffer += chunk;
      let boundary;
      while ((boundary = buffer.indexOf("\n\n")) >= 0) {
        const block = buffer.slice(0, boundary);
        buffer = buffer.slice(boundary + 2);
        const data = block.split("\n").find((line) => line.startsWith("data: "));
        if (!data) continue;
        try {
          const event = JSON.parse(data.slice(6));
          webview.postMessage({ type: "event", event });
          if (["generation.decision", "baseline.completed", "baseline.failed"].includes(event.type)) postSnapshot(webview);
        } catch { /* Ignore malformed SSE frames. */ }
      }
    });
  });
  request.on("error", () => {});
  return request;
}

async function openRtl(context, relative = "rtl/alu.sv") {
  const uri = vscode.Uri.file(path.join(projectRoot(context), relative));
  await vscode.window.showTextDocument(uri, { preview: false });
}

async function openGenerationDiff(context, generation, relative = "rtl/alu.sv") {
  const baseline = vscode.Uri.file(path.join(projectRoot(context), relative));
  const candidate = vscode.Uri.file(path.join(projectRoot(context), ".chipevolve", "generations", `gen-${String(generation).padStart(3, "0")}`, relative));
  if (!fs.existsSync(candidate.fsPath)) {
    vscode.window.showWarningMessage(`Generation ${generation} workspace is not available.`);
    return;
  }
  await vscode.commands.executeCommand("vscode.diff", baseline, candidate, `ChipEvolve · Baseline ↔ Gen ${String(generation).padStart(2, "0")}`);
}

function bindMessages(webview, context) {
  return webview.onDidReceiveMessage(async (message) => {
    if (message.command === "refresh") postSnapshot(webview);
    if (message.command === "openDashboard") vscode.commands.executeCommand("chipevolve.openDashboard");
    if (message.command === "openFile") await openRtl(context, message.path);
    if (message.command === "openDiff") await openGenerationDiff(context, message.generation, message.path);
    if (message.command === "startBackend") {
      await startBackend(context);
      postSnapshot(webview);
      attachEventStream(webview);
    }
    if (message.command === "baseline") vscode.commands.executeCommand("chipevolve.establishBaseline");
    if (message.command === "evolve") vscode.commands.executeCommand("chipevolve.evolve");
  });
}

class ControlCenterProvider {
  constructor(context) { this.context = context; }
  resolveWebviewView(view) {
    view.webview.options = { enableScripts: true, localResourceRoots: [vscode.Uri.file(path.join(this.context.extensionPath, "apps", "extension", "media"))] };
    view.webview.html = webviewHtml(view.webview, this.context, "sidebar");
    bindMessages(view.webview, this.context);
    postSnapshot(view.webview);
  }
}

function openDashboard(context) {
  if (dashboardPanel) {
    dashboardPanel.reveal(vscode.ViewColumn.One);
    postSnapshot(dashboardPanel.webview);
    return;
  }
  dashboardPanel = vscode.window.createWebviewPanel("chipevolve.dashboard", "ChipEvolve · Evolution", vscode.ViewColumn.One, {
    enableScripts: true,
    retainContextWhenHidden: true,
    localResourceRoots: [vscode.Uri.file(path.join(context.extensionPath, "apps", "extension", "media"))],
  });
  dashboardPanel.iconPath = vscode.Uri.file(path.join(context.extensionPath, "apps", "extension", "media", "chip.svg"));
  dashboardPanel.webview.html = webviewHtml(dashboardPanel.webview, context);
  bindMessages(dashboardPanel.webview, context);
  let stream;
  if (backendProcess || configuration()) stream = attachEventStream(dashboardPanel.webview);
  postSnapshot(dashboardPanel.webview);
  dashboardPanel.onDidDispose(() => { stream?.destroy(); dashboardPanel = undefined; });
}

async function activate(context) {
  context.subscriptions.push(vscode.window.registerWebviewViewProvider("chipevolve.controlCenter", new ControlCenterProvider(context)));
  context.subscriptions.push(vscode.commands.registerCommand("chipevolve.openDashboard", () => openDashboard(context)));
  context.subscriptions.push(vscode.commands.registerCommand("chipevolve.startBackend", () => startBackend(context)));
  context.subscriptions.push(vscode.commands.registerCommand("chipevolve.openDemoProject", () => openRtl(context)));
  context.subscriptions.push(vscode.commands.registerCommand("chipevolve.establishBaseline", async () => {
    if (!await startBackend(context)) return;
    await vscode.window.withProgress({ location: vscode.ProgressLocation.Notification, title: "ChipEvolve · Establishing real EDA baseline…" }, async () => {
      await requestJson("POST", `${configuration().backendUrl}/api/baseline`);
    });
    vscode.window.showInformationMessage("ChipEvolve baseline complete. Open the dashboard to inspect measured metrics.");
    if (dashboardPanel) postSnapshot(dashboardPanel.webview);
  }));
  context.subscriptions.push(vscode.commands.registerCommand("chipevolve.evolve", async () => {
    if (!await startBackend(context)) return;
    openDashboard(context);
    await requestJson("POST", `${configuration().backendUrl}/api/evolve`);
    vscode.window.showInformationMessage("ChipEvolve started a focused RTL generation.");
  }));
}

function deactivate() {
  if (backendProcess && backendProcess.exitCode === null) backendProcess.kill();
}

module.exports = { activate, deactivate, toWslPath };
