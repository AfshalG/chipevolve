const vscode = require("vscode");
const http = require("http");
const https = require("https");
const path = require("path");
const fs = require("fs");
const { spawn } = require("child_process");

const RTL_LANGUAGES = new Set(["systemverilog", "verilog"]);
const RTL_EXTENSIONS = new Set([".sv", ".v", ".svh", ".vh"]);

const MODE_LABEL = { generate: "Generate", review: "Review", optimize: "Optimize" };

let backendProcess;
let dashboardPanel;
let stream;
let output;
let statusItem;
let diagnostics;
let chatView;

/** Everything about the task currently in flight. */
let task = null;

// --------------------------------------------------------------------- config

function configuration() {
  const config = vscode.workspace.getConfiguration("chipevolve");
  return {
    backendUrl: config.get("backendUrl", "http://127.0.0.1:8000").replace(/\/$/, ""),
    distro: config.get("wslDistro", "Ubuntu"),
    projectPath: config.get("projectPath", "examples/alu"),
    model: config.get("model", "claude-opus-5"),
    apiKey: config.get("anthropicApiKey", ""),
    autoApprove: config.get("autoApprove", ["read", "run"]),
  };
}

/**
 * Where generated and edited files land. Priority:
 *   1. an absolute chipevolve.projectPath, if the user pinned one
 *   2. the nearest folder with a project.yaml, walking up from the active file
 *   3. the workspace folder that owns the active file
 *   4. the first workspace folder
 *   5. the bundled demo, only when no folder is open at all
 */
function resolveProjectRoot(context) {
  const configured = configuration().projectPath;
  if (configured && path.isAbsolute(configured)) return configured;

  const editor = vscode.window.activeTextEditor;
  const folders = vscode.workspace.workspaceFolders || [];

  if (editor && editor.document.uri.scheme === "file") {
    const owner = vscode.workspace.getWorkspaceFolder(editor.document.uri);
    const stop = owner ? path.resolve(owner.uri.fsPath) : null;
    let dir = path.dirname(editor.document.fileName);
    for (let hops = 0; hops < 24; hops += 1) {
      if (fs.existsSync(path.join(dir, "project.yaml"))) return dir;
      if (stop && path.resolve(dir) === stop) break;
      const parent = path.dirname(dir);
      if (parent === dir) break;
      dir = parent;
    }
    if (owner) return owner.uri.fsPath;
  }

  if (folders.length) {
    const withProject = folders.find((folder) => fs.existsSync(path.join(folder.uri.fsPath, "project.yaml")));
    if (withProject) return withProject.uri.fsPath;
    // A repo often keeps its RTL in a subdirectory. Prefer the nearest
    // project.yaml below the root over scattering generated files at the top.
    const nested = findProjectBelow(folders[0].uri.fsPath, 3);
    if (nested) return nested;
    return folders[0].uri.fsPath;
  }
  return path.join(context.extensionPath, configured || "examples/alu");
}

const PRUNED_DIRS = new Set([
  "node_modules", ".git", ".venv", "venv", "env", "__pycache__", "dist", "build",
  "target", "out", "obj_dir", ".chipevolve", ".vscode", ".idea", "site-packages",
]);

/** Shallow breadth-first hunt for a project.yaml, skipping vendor trees. */
function findProjectBelow(root, maxDepth) {
  let level = [root];
  for (let depth = 0; depth < maxDepth && level.length; depth += 1) {
    const next = [];
    for (const dir of level) {
      let entries;
      try { entries = fs.readdirSync(dir, { withFileTypes: true }); } catch { continue; }
      for (const entry of entries) {
        if (!entry.isDirectory() || PRUNED_DIRS.has(entry.name) || entry.name.startsWith(".")) continue;
        const child = path.join(dir, entry.name);
        if (fs.existsSync(path.join(child, "project.yaml"))) return child;
        next.push(child);
      }
    }
    level = next;
  }
  return null;
}

/** The root the backend is currently pointed at. */
let activeRoot;

function projectRoot(context) {
  return activeRoot || resolveProjectRoot(context);
}

/** Point the backend at the right directory before running anything. */
async function ensureProject(context) {
  const desired = resolveProjectRoot(context);
  const result = await requestJson(
    "POST", `${configuration().backendUrl}/api/project/open`, { root: desired }, 30000);
  activeRoot = result.root || desired;
  if (result.changed) output.appendLine(`[extension] project: ${activeRoot}`);
  return activeRoot;
}

function toWslPath(windowsPath) {
  const resolved = path.resolve(windowsPath).replaceAll("\\", "/");
  const match = resolved.match(/^([A-Za-z]):\/(.*)$/);
  return match ? `/mnt/${match[1].toLowerCase()}/${match[2]}` : resolved;
}

function shellQuote(value) {
  return `'${String(value).replaceAll("'", `'"'"'`)}'`;
}

// ---------------------------------------------------------------- editor view

function isRtlDocument(document) {
  if (!document || document.uri.scheme !== "file") return false;
  return RTL_LANGUAGES.has(document.languageId) || RTL_EXTENSIONS.has(path.extname(document.fileName).toLowerCase());
}

/** Make a path relative to the project root, or null when it lives outside it. */
function relativeToProject(context, absolute) {
  const root = path.resolve(projectRoot(context));
  const relative = path.relative(root, path.resolve(absolute));
  if (!relative || relative.startsWith("..") || path.isAbsolute(relative)) return null;
  return relative.split(path.sep).join("/");
}

/**
 * What the user is looking at right now: the active RTL file, any selection in
 * it, and every other RTL file they have open.
 */
function editorContext(context) {
  const editor = vscode.window.activeTextEditor;
  const focus = editor && isRtlDocument(editor.document) ? relativeToProject(context, editor.document.fileName) : null;

  const open = [];
  for (const group of vscode.window.tabGroups.all) {
    for (const tab of group.tabs) {
      const uri = tab.input && tab.input.uri;
      if (!uri || uri.scheme !== "file") continue;
      if (!RTL_EXTENSIONS.has(path.extname(uri.fsPath).toLowerCase())) continue;
      const relative = relativeToProject(context, uri.fsPath);
      if (relative && !open.includes(relative)) open.push(relative);
    }
  }

  let selection = null;
  if (focus && editor && !editor.selection.isEmpty) {
    selection = [editor.selection.start.line + 1, editor.selection.end.line + 1];
  } else if (focus && editor) {
    selection = [editor.selection.active.line + 1, editor.selection.active.line + 1];
  }
  return { focus, open, selection, editor };
}

// -------------------------------------------------------------------- backend

function requestJson(method, target, body, timeout = 10000) {
  return new Promise((resolve, reject) => {
    const url = new URL(target);
    const transport = url.protocol === "https:" ? https : http;
    const payload = body === undefined ? undefined : JSON.stringify(body);
    const request = transport.request(
      url,
      {
        method,
        headers: payload
          ? { "content-type": "application/json", "content-length": Buffer.byteLength(payload) }
          : {},
        timeout,
      },
      (response) => {
        let data = "";
        response.setEncoding("utf8");
        response.on("data", (chunk) => { data += chunk; });
        response.on("end", () => {
          if ((response.statusCode ?? 500) >= 400) {
            let detail = data;
            try { detail = JSON.parse(data).detail || data; } catch { /* keep raw body */ }
            reject(new Error(detail || `Backend returned ${response.statusCode}`));
            return;
          }
          try { resolve(data ? JSON.parse(data) : {}); }
          catch (error) { reject(error); }
        });
      },
    );
    request.on("timeout", () => request.destroy(new Error("Backend request timed out")));
    request.on("error", reject);
    if (payload) request.write(payload);
    request.end();
  });
}

async function backendReady() {
  try {
    await requestJson("GET", `${configuration().backendUrl}/api/health`, undefined, 3000);
    return true;
  } catch {
    return false;
  }
}

async function startBackend(context, showProgress = true) {
  if (await backendReady()) return true;
  if (backendProcess && backendProcess.exitCode === null) return waitForBackend();

  const backend = toWslPath(path.join(context.extensionPath, "backend"));
  const project = toWslPath(projectRoot(context));
  const { distro, apiKey } = configuration();
  const key = apiKey || process.env.ANTHROPIC_API_KEY || "";
  const command = [
    `cd ${shellQuote(backend)}`,
    `export CHIPEVOLVE_PROJECT=${shellQuote(project)}`,
    `export CHIPEVOLVE_WSL_DISTRO=${shellQuote(distro)}`,
    ...(key ? [`export ANTHROPIC_API_KEY=${shellQuote(key)}`] : []),
    "PYTHONPATH=. .venv/bin/python -m uvicorn chipevolve.api.main:app --host 127.0.0.1 --port 8000",
  ].join(" && ");

  output.appendLine(`[extension] starting backend in WSL distribution ${distro}`);
  backendProcess = spawn("wsl.exe", ["-d", distro, "--", "bash", "-lc", command], { windowsHide: true });
  backendProcess.stdout.on("data", (chunk) => output.append(chunk.toString()));
  backendProcess.stderr.on("data", (chunk) => output.append(chunk.toString()));
  backendProcess.on("exit", (code) => output.appendLine(`[extension] backend exited with code ${code}`));

  const wait = waitForBackend();
  if (!showProgress) return wait;
  return vscode.window.withProgress(
    { location: vscode.ProgressLocation.Notification, title: "Starting ChipEvolve backend…" },
    () => wait,
  );
}

async function waitForBackend() {
  for (let attempt = 0; attempt < 30; attempt += 1) {
    if (await backendReady()) return true;
    await new Promise((resolve) => setTimeout(resolve, 500));
  }
  vscode.window.showErrorMessage(
    "ChipEvolve backend did not start. Check the ChipEvolve output channel and install backend dependencies.",
  );
  return false;
}

// ------------------------------------------------------------------ native UI

function setStatus(text, busy = false) {
  if (!statusItem) return;
  statusItem.text = busy ? `$(sync~spin) ChipEvolve: ${text}` : `$(circuit-board) ChipEvolve: ${text}`;
  statusItem.show();
}

const SEVERITY = {
  critical: vscode.DiagnosticSeverity.Error,
  high: vscode.DiagnosticSeverity.Error,
  medium: vscode.DiagnosticSeverity.Warning,
  low: vscode.DiagnosticSeverity.Information,
};

/** Review findings become squiggles on the real file and rows in Problems. */
function publishFindings(context, findings) {
  diagnostics.clear();
  const byFile = new Map();
  for (const finding of findings) {
    const absolute = path.join(projectRoot(context), finding.path);
    const line = Math.max(0, (finding.line || 1) - 1);
    const range = new vscode.Range(line, 0, line, Number.MAX_SAFE_INTEGER);
    const diagnostic = new vscode.Diagnostic(
      range,
      `${finding.title}\n\n${finding.detail || ""}${finding.suggestion ? `\n\nFix: ${finding.suggestion}` : ""}`.trim(),
      SEVERITY[finding.severity] ?? vscode.DiagnosticSeverity.Information,
    );
    diagnostic.source = "ChipEvolve";
    diagnostic.code = finding.severity;
    const key = absolute;
    if (!byFile.has(key)) byFile.set(key, []);
    byFile.get(key).push(diagnostic);
  }
  for (const [file, items] of byFile) {
    diagnostics.set(vscode.Uri.file(file), items);
  }
  return byFile.size;
}

/** Show the pending edit as a real diff editor, backed by a temp file. */
async function showPendingDiff(context, preview) {
  if (!preview || !preview.path) return;
  const original = vscode.Uri.file(path.join(projectRoot(context), preview.path));
  const scratch = path.join(context.globalStorageUri.fsPath, "proposed");
  fs.mkdirSync(scratch, { recursive: true });
  const proposed = path.join(scratch, path.basename(preview.path));
  const before = fs.existsSync(original.fsPath) ? fs.readFileSync(original.fsPath, "utf8") : "";
  fs.writeFileSync(proposed, applyUnifiedDiff(before, preview.diff), "utf8");
  await vscode.commands.executeCommand(
    "vscode.diff",
    original,
    vscode.Uri.file(proposed),
    `ChipEvolve · ${preview.path} (proposed)`,
    { preview: true },
  );
}

/** Reconstruct the proposed file from the unified diff the backend previewed. */
function applyUnifiedDiff(before, diff) {
  const lines = String(diff || "").split("\n");
  const source = before.split("\n");
  const out = [];
  let cursor = 0;
  for (let index = 0; index < lines.length; index += 1) {
    const line = lines[index];
    const hunk = /^@@ -(\d+)(?:,(\d+))? \+\d+(?:,\d+)? @@/.exec(line);
    if (!hunk) continue;
    const start = Number(hunk[1]) - 1;
    while (cursor < start) out.push(source[cursor++]);
    for (index += 1; index < lines.length && !lines[index].startsWith("@@"); index += 1) {
      const body = lines[index];
      if (body.startsWith("+")) out.push(body.slice(1));
      else if (body.startsWith("-")) cursor += 1;
      else if (body.startsWith(" ")) out.push(source[cursor++]);
    }
    index -= 1;
  }
  while (cursor < source.length) out.push(source[cursor++]);
  return out.join("\n");
}

async function askApproval(context, payload) {
  const preview = payload.preview || {};
  const target = preview.path || (payload.input && payload.input.path) || payload.name;
  const churn = preview.added != null ? ` (+${preview.added} −${preview.removed})` : "";
  const detail = `ChipEvolve wants to edit ${target}${churn}`;

  const choice = await vscode.window.showInformationMessage(detail, "Approve", "Show diff", "Reject");
  if (choice === "Show diff") {
    await showPendingDiff(context, preview);
    const second = await vscode.window.showInformationMessage(detail, "Approve", "Reject");
    return second === "Approve";
  }
  return choice === "Approve";
}

// -------------------------------------------------------------- event handling

async function onEvent(context, event) {
  const payload = event.payload || {};
  // The backend broadcasts one bus to every listener, so a second VS Code window
  // (or a CLI client) would otherwise stream its transcript into this one.
  // Once we know our own session id, ignore everybody else's chat events.
  if (payload.session && task && task.sessionId && payload.session !== task.sessionId) return;
  // The sidebar is the primary surface; it renders the transcript, the tool
  // cards and the approval buttons. Everything below is the native half:
  // the log, the status bar, Problems, and the diff editor.
  chatView?.webview.postMessage({ type: "event", event });
  if (task && event.seq) {
    if (task.seen.has(event.seq)) return;
    task.seen.add(event.seq);
  }

  switch (event.type) {
    case "chat.started":
      if (task) {
        task.workspacePath = payload.workspace_path || null;
        task.detached = Boolean(task.workspacePath) && path.resolve(task.workspacePath) !== path.resolve(projectRoot(context));
      }
      output.appendLine(`\n── ${MODE_LABEL[payload.mode] || payload.mode} · ${payload.workspace} ──`);
      break;

    case "chat.text":
      output.append(payload.text);
      break;

    case "chat.tool_start":
      output.appendLine(`\n  → ${payload.name} ${compactArgs(payload.input)}`);
      setStatus(payload.name.replace(/_/g, " "), true);
      task?.progress?.report({ message: payload.name.replace(/_/g, " ") });
      break;

    case "chat.approval_required": {
      setStatus("waiting for approval");
      // The sidebar shows Approve/Reject inline, so only fall back to a modal
      // notification when the view is not open.
      if (payload.preview && payload.preview.path) previews.set(payload.preview.path, payload.preview);
      if (chatView) break;
      const approved = await askApproval(context, payload);
      try {
        await requestJson("POST", `${configuration().backendUrl}/api/agent/approve`, {
          tool_use_id: payload.tool_use_id,
          approved,
        });
      } catch (error) {
        output.appendLine(`  ! approval failed: ${error.message}`);
      }
      break;
    }

    case "chat.tool_result":
      output.appendLine(`    ${payload.ok ? "✓" : "✗"} ${payload.summary || ""}`);
      // A file the agent just wrote into the working tree should appear straight
      // away, the way it would if you had typed it yourself.
      if (payload.ok && payload.meta && payload.meta.path && !task?.detached) {
        if (payload.name === "write_file" || payload.name === "replace_in_file") {
          task && task.touched.add(payload.meta.path);
          openFile(context, payload.meta.path).catch(() => { /* editor may be busy */ });
        }
      }
      if (payload.name === "report_findings" && payload.meta && payload.meta.findings) {
        const files = publishFindings(context, payload.meta.findings);
        task && (task.findings = payload.meta.findings.length);
        output.appendLine(`    ${payload.meta.findings.length} findings across ${files} file(s) → Problems panel`);
      }
      if (payload.name === "score_candidate" && payload.meta) {
        task && (task.verdict = payload.meta);
      }
      break;

    case "chat.integrity_violation":
      output.appendLine(`  ⚠ BLOCKED: ${event.message}`);
      vscode.window.showWarningMessage(`ChipEvolve blocked a protected-path edit: ${event.message}`);
      break;

    case "chat.usage":
      task && (task.usage = payload);
      break;

    case "chat.error":
      output.appendLine(`\n  ! ${event.message}`);
      vscode.window.showErrorMessage(`ChipEvolve: ${event.message}`);
      break;

    case "chat.done":
      await finishTask(context, payload);
      break;

    default:
      break;
  }
}

function compactArgs(input) {
  if (!input) return "";
  const text = JSON.stringify(input);
  return text.length > 120 ? `${text.slice(0, 117)}…` : text;
}

async function finishTask(context, payload) {
  const finished = task;
  task = null;
  setStatus("idle");
  finished?.resolve?.();
  if (!finished) return;

  const cost = finished.usage ? ` · $${(finished.usage.cost_usd || 0).toFixed(3)}` : "";

  if (payload.reason === "cancelled") {
    vscode.window.showInformationMessage("ChipEvolve task cancelled.");
    return;
  }
  if (finished.mode === "review") {
    const count = finished.findings || 0;
    const action = count
      ? await vscode.window.showInformationMessage(
          `ChipEvolve review: ${count} finding(s)${cost}`, "Show Problems", "Show log")
      : await vscode.window.showInformationMessage(`ChipEvolve review: no findings${cost}`, "Show log");
    if (action === "Show Problems") vscode.commands.executeCommand("workbench.actions.view.problems");
    if (action === "Show log") output.show(true);
    return;
  }

  const edited = payload.edited || [];
  if (payload.detached && edited.length && chatView) {
    // The sidebar renders its own "Keep this candidate?" card.
    return;
  }
  if (payload.detached && edited.length) {
    const verdict = finished.verdict;
    const headline = verdict
      ? `${verdict.accepted ? "ACCEPTED" : "REJECTED"} ${
          verdict.fitness && verdict.fitness.improvement_percent != null
            ? `${verdict.fitness.improvement_percent > 0 ? "+" : ""}${verdict.fitness.improvement_percent.toFixed(2)}%`
            : ""
        }`
      : "Candidate ready";
    const action = await vscode.window.showInformationMessage(
      `ChipEvolve · ${headline}${cost} — ${edited.join(", ")}`,
      "Apply to project",
      "Show diff",
      "Discard",
    );
    if (action === "Show diff") {
      await openCandidateDiff(context, finished.workspacePath, edited[0]);
      const second = await vscode.window.showInformationMessage(
        `Apply ${edited.join(", ")} to the project?`, "Apply to project", "Discard");
      if (second !== "Apply to project") return;
    } else if (action !== "Apply to project") {
      return;
    }
    await applyEdits(context);
    return;
  }

  if (edited.length) {
    vscode.window.showInformationMessage(`ChipEvolve updated ${edited.join(", ")}${cost}`);
    await openFile(context, edited[0]);
  } else {
    const action = await vscode.window.showInformationMessage(`ChipEvolve finished${cost}`, "Show log");
    if (action === "Show log") output.show(true);
  }
}

async function openCandidateDiff(context, workspacePath, relative) {
  if (!workspacePath || !relative) return;
  const baseline = vscode.Uri.file(path.join(projectRoot(context), relative));
  const candidate = vscode.Uri.file(path.join(workspacePath, relative));
  if (!fs.existsSync(candidate.fsPath)) return;
  await vscode.commands.executeCommand("vscode.diff", baseline, candidate, `ChipEvolve · ${relative} (candidate)`);
}

async function openFile(context, relative, line = 0) {
  const uri = vscode.Uri.file(path.join(projectRoot(context), relative));
  if (!fs.existsSync(uri.fsPath)) return;
  const editor = await vscode.window.showTextDocument(uri, { preview: false });
  if (line > 0) {
    const position = new vscode.Position(Math.max(0, line - 1), 0);
    editor.selection = new vscode.Selection(position, position);
    editor.revealRange(new vscode.Range(position, position), vscode.TextEditorRevealType.InCenter);
  }
}

async function applyEdits(context) {
  try {
    const result = await requestJson("POST", `${configuration().backendUrl}/api/agent/apply`, undefined, 30000);
    const applied = result.applied || [];
    if (!applied.length) {
      vscode.window.showInformationMessage("ChipEvolve had no edits to apply.");
      return [];
    }
    vscode.window.showInformationMessage(`ChipEvolve applied ${applied.join(", ")}`);
    await openFile(context, applied[0]);
    return applied;
  } catch (error) {
    vscode.window.showErrorMessage(`ChipEvolve could not apply the edits: ${error.message}`);
  }
  return [];
}

// --------------------------------------------------------------- event stream

function attachEventStream(context) {
  let request;
  let timer;
  let closed = false;
  let epoch = 0;

  const reconnect = (mine) => {
    if (closed || mine !== epoch) return;
    epoch += 1;
    request?.destroy();
    request = undefined;
    clearTimeout(timer);
    timer = setTimeout(connect, 2000);
  };

  const connect = () => {
    if (closed) return;
    const mine = epoch;
    request?.destroy();
    const target = new URL(`${configuration().backendUrl}/api/events`);
    request = http.get(target, { headers: { accept: "text/event-stream" } }, (response) => {
      response.setEncoding("utf8");
      let buffer = "";
      response.on("data", (chunk) => {
        if (closed || mine !== epoch) return;
        buffer += chunk;
        let boundary;
        while ((boundary = buffer.indexOf("\n\n")) >= 0) {
          const block = buffer.slice(0, boundary);
          buffer = buffer.slice(boundary + 2);
          const data = block.split("\n").find((line) => line.startsWith("data: "));
          if (!data) continue;
          try {
            onEvent(context, JSON.parse(data.slice(6)));
          } catch { /* ignore malformed SSE frames */ }
        }
      });
      response.on("end", () => reconnect(mine));
    });
    request.on("error", () => reconnect(mine));
  };

  connect();
  return { destroy() { closed = true; epoch += 1; clearTimeout(timer); request?.destroy(); } };
}

// ------------------------------------------------------------------- commands

async function runMode(context, mode) {
  if (chatView) {
    await vscode.commands.executeCommand("chipevolve.chat.focus");
    chatView.webview.postMessage({ type: "setMode", mode });
    await pushStatus(context);
    return;
  }
  if (task) {
    const action = await vscode.window.showWarningMessage(
      "A ChipEvolve task is already running.", "Cancel it", "Keep waiting");
    if (action === "Cancel it") await cancelTask();
    return;
  }
  if (!(await startBackend(context))) return;
  try {
    await ensureProject(context);
  } catch (error) {
    vscode.window.showErrorMessage(`ChipEvolve could not open the project: ${error.message}`);
    return;
  }

  const view = editorContext(context);
  if (mode !== "generate" && !view.focus) {
    const proceed = await vscode.window.showWarningMessage(
      "No Verilog file from the ChipEvolve project is active. Continue against the whole project?",
      "Continue", "Cancel");
    if (proceed !== "Continue") return;
  }

  const placeholder = {
    generate: "Describe the module to write — ports, behaviour, timing",
    review: view.focus ? `What should the review of ${view.focus} focus on?` : "What should the review focus on?",
    optimize: view.focus ? `What should this generation improve in ${view.focus}?` : "What should this generation improve?",
  }[mode];

  const message = await vscode.window.showInputBox({
    title: `ChipEvolve · ${MODE_LABEL[mode]} RTL`,
    prompt: view.focus ? `Context: ${view.focus}` : "Context: whole project",
    placeHolder: placeholder,
    ignoreFocusOut: true,
  });
  if (!message || !message.trim()) return;

  diagnostics.clear();
  output.clear();
  output.show(true);

  await vscode.window.withProgress(
    {
      location: vscode.ProgressLocation.Notification,
      title: `ChipEvolve · ${MODE_LABEL[mode]}`,
      cancellable: true,
    },
    (progress, token) =>
      new Promise(async (resolve) => {
        task = {
          mode,
          seen: new Set(),
          progress,
          resolve,
          usage: null,
          findings: 0,
          verdict: null,
          workspacePath: null,
          sessionId: null,
          detached: false,
          touched: new Set(),
        };
        token.onCancellationRequested(() => cancelTask());
        setStatus(`${MODE_LABEL[mode].toLowerCase()}…`, true);
        try {
          const started = await requestJson(
            "POST",
            `${configuration().backendUrl}/api/agent/task`,
            {
              mode,
              message,
              model: configuration().model,
              auto_approve: configuration().autoApprove,
              focus_path: view.focus,
              open_files: view.open,
              selection: view.selection,
            },
            60000,
          );
          if (task) task.sessionId = started.session;
        } catch (error) {
          task = null;
          setStatus("idle");
          vscode.window.showErrorMessage(`ChipEvolve: ${error.message}`);
          resolve();
        }
      }),
  );
}

async function cancelTask() {
  try {
    await requestJson("POST", `${configuration().backendUrl}/api/agent/cancel`);
  } catch { /* the task may already have finished */ }
}

// ------------------------------------------------------------ chat sidebar

function chatHtml(webview, context) {
  const media = vscode.Uri.joinPath(context.extensionUri, "apps", "extension", "media");
  const styleUri = webview.asWebviewUri(vscode.Uri.joinPath(media, "chat.css"));
  const scriptUri = webview.asWebviewUri(vscode.Uri.joinPath(media, "chat.js"));
  const nonce = Math.random().toString(36).slice(2);
  return `<!doctype html>
  <html lang="en"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
  <meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src ${webview.cspSource}; script-src 'nonce-${nonce}';">
  <link rel="stylesheet" href="${styleUri}"><title>ChipEvolve</title></head>
  <body><div id="app"></div><script nonce="${nonce}" src="${scriptUri}"></script></body></html>`;
}

/** Tell the sidebar whether the backend is reachable and what file is focused. */
async function pushStatus(context) {
  if (!chatView) return;
  const view = editorContext(context);
  try {
    const health = await requestJson("GET", `${configuration().backendUrl}/api/health`, undefined, 3000);
    chatView.webview.postMessage({
      type: "status",
      online: true,
      project: health.project,
      focus: view.focus,
    });
  } catch (error) {
    chatView.webview.postMessage({
      type: "status",
      online: false,
      reason: "Backend offline",
      focus: view.focus,
    });
  }
}

class ChatViewProvider {
  constructor(context) { this.context = context; }

  resolveWebviewView(view) {
    chatView = view;
    view.webview.options = {
      enableScripts: true,
      localResourceRoots: [vscode.Uri.file(path.join(this.context.extensionPath, "apps", "extension", "media"))],
    };
    view.webview.html = chatHtml(view.webview, this.context);
    view.webview.onDidReceiveMessage((message) => onChatMessage(this.context, message));
    view.onDidDispose(() => { chatView = undefined; });
  }
}

async function onChatMessage(context, message) {
  const base = configuration().backendUrl;
  switch (message.command) {
    case "ready":
      await pushStatus(context);
      return;

    case "startBackend":
      await startBackend(context);
      await pushStatus(context);
      return;

    case "openFile":
      await openFile(context, message.path, message.line || 0);
      return;

    case "openDiff":
      if (task && task.detached) await openCandidateDiff(context, task.workspacePath, message.path);
      else await showPendingDiff(context, pendingPreview(message.path));
      return;

    case "approve":
      try {
        await requestJson("POST", `${base}/api/agent/approve`, {
          tool_use_id: message.toolUseId,
          approved: Boolean(message.approved),
        });
      } catch (error) {
        chatView?.webview.postMessage({ type: "taskFailed", message: error.message });
      }
      return;

    case "cancel":
      await cancelTask();
      return;

    case "applyEdits": {
      const applied = await applyEdits(context);
      chatView?.webview.postMessage({ type: "applied", files: applied });
      return;
    }

    case "startTask":
      await startTaskFromSidebar(context, message);
      return;

    default:
      return;
  }
}

/** Remember the last edit preview per path so "Open diff" can rebuild it. */
const previews = new Map();
function pendingPreview(relative) {
  return previews.get(relative);
}

async function startTaskFromSidebar(context, message) {
  if (!(await startBackend(context))) {
    chatView?.webview.postMessage({ type: "taskFailed", message: "The backend is not running." });
    return;
  }
  try {
    await ensureProject(context);
  } catch (error) {
    chatView?.webview.postMessage({ type: "taskFailed", message: error.message });
    return;
  }

  const view = editorContext(context);
  diagnostics.clear();
  previews.clear();
  output.clear();

  task = {
    mode: message.mode,
    seen: new Set(),
    progress: null,
    resolve: null,
    usage: null,
    findings: 0,
    verdict: null,
    workspacePath: null,
    sessionId: null,
    detached: false,
    touched: new Set(),
  };
  setStatus(`${MODE_LABEL[message.mode].toLowerCase()}…`, true);

  try {
    const started = await requestJson(
      "POST",
      `${configuration().backendUrl}/api/agent/task`,
      {
        mode: message.mode,
        message: message.message,
        model: configuration().model,
        auto_approve: message.autoApprove || [],
        focus_path: view.focus,
        open_files: view.open,
        selection: view.selection,
      },
      60000,
    );
    if (task) task.sessionId = started.session;
    await pushStatus(context);
  } catch (error) {
    task = null;
    setStatus("idle");
    chatView?.webview.postMessage({ type: "taskFailed", message: error.message });
  }
}

// ------------------------------------------------------------------ dashboard

function dashboardHtml(webview, context) {
  const media = vscode.Uri.joinPath(context.extensionUri, "apps", "extension", "media");
  const styleUri = webview.asWebviewUri(vscode.Uri.joinPath(media, "dashboard.css"));
  const scriptUri = webview.asWebviewUri(vscode.Uri.joinPath(media, "dashboard.js"));
  const nonce = Math.random().toString(36).slice(2);
  return `<!doctype html>
  <html lang="en"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
  <meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src ${webview.cspSource}; script-src 'nonce-${nonce}';">
  <link rel="stylesheet" href="${styleUri}"><title>ChipEvolve</title></head>
  <body data-mode="dashboard"><div id="app"></div><script nonce="${nonce}" src="${scriptUri}"></script></body></html>`;
}

function postSnapshot(webview) {
  requestJson("GET", `${configuration().backendUrl}/api/project`)
    .then((snapshot) => webview.postMessage({ type: "snapshot", snapshot }))
    .catch((error) => webview.postMessage({ type: "offline", message: error.message }));
}

function openDashboard(context) {
  if (dashboardPanel) {
    dashboardPanel.reveal(vscode.ViewColumn.One);
    postSnapshot(dashboardPanel.webview);
    return;
  }
  dashboardPanel = vscode.window.createWebviewPanel(
    "chipevolve.dashboard",
    "ChipEvolve · Evolution",
    vscode.ViewColumn.One,
    {
      enableScripts: true,
      retainContextWhenHidden: true,
      localResourceRoots: [vscode.Uri.file(path.join(context.extensionPath, "apps", "extension", "media"))],
    },
  );
  dashboardPanel.webview.html = dashboardHtml(dashboardPanel.webview, context);
  dashboardPanel.webview.onDidReceiveMessage(async (message) => {
    if (message.command === "refresh" || message.command === "ready") postSnapshot(dashboardPanel.webview);
    if (message.command === "openFile") await openFile(context, message.path);
    if (message.command === "evolve") vscode.commands.executeCommand("chipevolve.optimizeRtl");
    if (message.command === "baseline") vscode.commands.executeCommand("chipevolve.establishBaseline");
  });
  postSnapshot(dashboardPanel.webview);
  dashboardPanel.onDidDispose(() => { dashboardPanel = undefined; });
}

// ------------------------------------------------------------------- activate

async function activate(context) {
  output = vscode.window.createOutputChannel("ChipEvolve");
  diagnostics = vscode.languages.createDiagnosticCollection("chipevolve");
  statusItem = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Right, 100);
  statusItem.command = "chipevolve.showActions";
  setStatus("idle");
  context.subscriptions.push(output, diagnostics, statusItem);

  context.subscriptions.push(
    vscode.window.registerWebviewViewProvider("chipevolve.chat", new ChatViewProvider(context), {
      webviewOptions: { retainContextWhenHidden: true },
    }),
  );
  context.subscriptions.push(
    vscode.window.onDidChangeActiveTextEditor(() => pushStatus(context).catch(() => {})),
  );

  stream = attachEventStream(context);
  context.subscriptions.push({ dispose: () => stream?.destroy() });

  const register = (name, handler) =>
    context.subscriptions.push(vscode.commands.registerCommand(name, handler));

  register("chipevolve.generateRtl", () => runMode(context, "generate"));
  register("chipevolve.reviewRtl", () => runMode(context, "review"));
  register("chipevolve.optimizeRtl", () => runMode(context, "optimize"));
  register("chipevolve.cancelTask", () => cancelTask());
  register("chipevolve.applyEdits", () => applyEdits(context));
  register("chipevolve.showLog", () => output.show(true));
  register("chipevolve.newTask", async () => {
    await vscode.commands.executeCommand("chipevolve.chat.focus");
    chatView?.webview.postMessage({ type: "newTask" });
  });
  register("chipevolve.clearFindings", () => diagnostics.clear());
  register("chipevolve.openDashboard", () => openDashboard(context));
  register("chipevolve.startBackend", () => startBackend(context));

  register("chipevolve.establishBaseline", async () => {
    if (!(await startBackend(context))) return;
    await vscode.window.withProgress(
      { location: vscode.ProgressLocation.Notification, title: "ChipEvolve · measuring baseline…" },
      async () => {
        const result = await requestJson(
          "POST", `${configuration().backendUrl}/api/baseline?force=true`, undefined, 900000);
        const cells = result.metrics && result.metrics.cell_count;
        vscode.window.showInformationMessage(
          cells != null
            ? `ChipEvolve baseline: ${cells} cells`
            : "ChipEvolve could not measure a baseline — see the log.",
        );
        if (cells == null) output.show(true);
      },
    );
  });

  register("chipevolve.showActions", async () => {
    const items = task
      ? [{ label: "$(stop) Cancel running task", command: "chipevolve.cancelTask" },
         { label: "$(output) Show log", command: "chipevolve.showLog" }]
      : [
          { label: "$(sparkle) Generate RTL", command: "chipevolve.generateRtl" },
          { label: "$(checklist) Review RTL", command: "chipevolve.reviewRtl" },
          { label: "$(rocket) Optimize RTL", command: "chipevolve.optimizeRtl" },
          { label: "$(dashboard) Measure baseline", command: "chipevolve.establishBaseline" },
          { label: "$(pulse) Open dashboard", command: "chipevolve.openDashboard" },
          { label: "$(output) Show log", command: "chipevolve.showLog" },
          { label: "$(clear-all) Clear findings", command: "chipevolve.clearFindings" },
        ];
    const picked = await vscode.window.showQuickPick(items, { title: "ChipEvolve" });
    if (picked) vscode.commands.executeCommand(picked.command);
  });

  startBackend(context, false).catch(() => { /* surfaced on first use */ });
}

function deactivate() {
  stream?.destroy();
  if (backendProcess && backendProcess.exitCode === null) backendProcess.kill();
}

module.exports = { activate, deactivate, toWslPath, applyUnifiedDiff, isRtlDocument };
