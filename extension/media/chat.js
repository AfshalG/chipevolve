const vscode = acquireVsCodeApi();

const MODES = [
  { id: "generate", label: "Generate" },
  { id: "review", label: "Review" },
  { id: "optimize", label: "Optimize" },
];

const PLACEHOLDER = {
  generate: "Describe the module to write — ports, behaviour, timing…",
  review: "Which file or concern should the review focus on?",
  optimize: "What should this generation try to improve?",
};

const SUGGESTIONS = {
  generate: [
    ["Write a 4-stage pipelined 8-bit multiplier", "Synchronous reset, valid/ready handshake"],
    ["Add a parameterised FIFO next to the ALU", "Depth and width as parameters, full/empty flags"],
  ],
  review: [
    ["Review rtl/alu.sv for correctness and synthesis quality", "Lint and synthesis run as evidence"],
    ["Check every case statement for latch inference", "Reports findings by severity"],
  ],
  optimize: [
    ["Reduce ALU area without breaking the testbench", "One measured transformation per generation"],
    ["Shorten the critical path through the operation decode", "Recalls prior experiments before mutating"],
  ],
};

// How each tool call is announced in the timeline.
const TOOL_UI = {
  list_files: { verb: "List", target: () => "project files" },
  read_file: { verb: "Read", target: (i) => i.path },
  search_rtl: { verb: "Search", target: (i) => `/${i.pattern}/` },
  get_metrics: { verb: "Load", target: () => "measured metrics" },
  recall_memories: { verb: "Recall", target: (i) => i.mutation_type || "all experiments" },
  write_file: { verb: "Write", target: (i) => i.path, edit: true },
  replace_in_file: { verb: "Edit", target: (i) => i.path, edit: true },
  run_lint: { verb: "Run", target: () => "Verilator lint" },
  run_simulation: { verb: "Run", target: () => "testbench" },
  run_synthesis: { verb: "Run", target: () => "Yosys synthesis" },
  score_candidate: { verb: "Score", target: () => "candidate vs baseline" },
  record_experiment: { verb: "Remember", target: (i) => i.mutation_type || "experiment" },
  report_findings: { verb: "Report", target: () => "review findings" },
};

const persisted = vscode.getState() || {};

const state = {
  online: false,
  busy: false,
  mode: persisted.mode || "optimize",
  draft: persisted.draft || "",
  autoApprove: persisted.autoApprove || { read: true, edit: false, run: true },
  snapshot: null,
  task: null,
  rows: [],
  usage: null,
  offlineReason: null,
  pendingApply: null,
};

// ------------------------------------------------------------------ helpers

function escapeHtml(value) {
  return String(value ?? "").replace(
    /[&<>"']/g,
    (character) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[character],
  );
}

function attr(value) {
  return escapeHtml(value).replace(/\n/g, "&#10;");
}

/** Small markdown subset: fences, inline code, bold, bullets, headings. */
function markdown(source) {
  const blocks = String(source).split(/```/);
  return blocks
    .map((block, index) => {
      if (index % 2 === 1) {
        const [first, ...rest] = block.split("\n");
        const body = rest.length ? rest.join("\n") : first;
        return `<pre><code>${escapeHtml(body.replace(/\n$/, ""))}</code></pre>`;
      }
      return block
        .split(/\n{2,}/)
        .filter((paragraph) => paragraph.trim())
        .map((paragraph) => {
          const lines = paragraph.split("\n");
          if (lines.every((line) => /^\s*[-*]\s+/.test(line))) {
            const items = lines.map((line) => `<li>${inline(line.replace(/^\s*[-*]\s+/, ""))}</li>`).join("");
            return `<ul>${items}</ul>`;
          }
          if (/^#{1,6}\s+/.test(paragraph)) {
            return `<h4>${inline(paragraph.replace(/^#{1,6}\s+/, ""))}</h4>`;
          }
          return `<p>${lines.map(inline).join("<br>")}</p>`;
        })
        .join("");
    })
    .join("");
}

function inline(text) {
  return escapeHtml(text)
    .replace(/`([^`]+)`/g, "<code>$1</code>")
    .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
}

function renderDiff(diff) {
  const lines = String(diff).split("\n");
  const body = lines
    .filter((line) => !line.startsWith("---") && !line.startsWith("+++"))
    .map((line) => {
      let className = "";
      if (line.startsWith("+")) className = "add";
      else if (line.startsWith("-")) className = "del";
      else if (line.startsWith("@@")) className = "hunk";
      return `<div class="${className}">${escapeHtml(line) || "&nbsp;"}</div>`;
    })
    .join("");
  return `<div class="diff">${body}</div>`;
}

function compact(value) {
  if (value == null) return "N/A";
  return Number(value).toLocaleString(undefined, { maximumFractionDigits: 2 });
}

function tokens(count) {
  if (!count) return "0";
  return count >= 1000 ? `${(count / 1000).toFixed(1)}k` : String(count);
}

function save() {
  vscode.setState({ mode: state.mode, draft: state.draft, autoApprove: state.autoApprove });
}

// ------------------------------------------------------------------- render

function toolCard(row) {
  const ui = TOOL_UI[row.name] || { verb: row.name, target: () => "" };
  const target = ui.target(row.input || {}) || "";
  const awaiting = row.status === "awaiting";
  const running = row.status === "running";
  const failed = row.status === "error" || row.status === "rejected";

  let indicator = "";
  if (running) indicator = `<span class="spin"></span>`;
  else if (awaiting) indicator = `<span class="dot-warn">●</span>`;
  else if (row.status === "done") indicator = `<span class="dot-good">✓</span>`;
  else if (failed) indicator = `<span class="dot-bad">✕</span>`;

  const verb = awaiting && ui.edit ? "ChipEvolve wants to edit" : ui.verb;
  const summaryClass = failed ? "bad" : row.status === "done" ? "good" : "";
  const head = `<div class="head" data-toggle="${row.id}">
      ${indicator}
      <span class="verb">${escapeHtml(verb)}</span>
      <span class="target">${escapeHtml(target)}</span>
      <span class="summary ${summaryClass}">${escapeHtml(row.summary || "")}</span>
    </div>`;

  const body = row.open ? toolBody(row) : "";
  const approval = awaiting ? approvalRow(row) : "";
  const className = awaiting ? "awaiting" : failed ? "error" : "";
  return `<div class="tool ${className}">${head}${body}${approval}</div>`;
}

function approvalRow(row) {
  const path = (row.input && row.input.path) || "";
  const showDiff = TOOL_UI[row.name] && TOOL_UI[row.name].edit && path;
  return `<div class="approve">
      ${showDiff ? `<button class="open-diff" data-diff="${attr(path)}">Open diff</button>` : ""}
      <button data-reject="${row.id}">Reject</button>
      <button class="primary" data-approve="${row.id}">Approve</button>
    </div>`;
}

function toolBody(row) {
  const meta = row.meta || {};
  if (meta.diff || (row.preview && row.preview.diff)) {
    return `<div class="body">${renderDiff(meta.diff || row.preview.diff)}</div>`;
  }
  if (row.preview && row.preview.error) {
    return `<div class="body"><pre>${escapeHtml(row.preview.error)}</pre></div>`;
  }
  if (row.name === "score_candidate" && meta.fitness) {
    return scoreBody(meta);
  }
  if (row.name === "report_findings" && meta.findings) {
    return meta.findings.map(findingRow).join("");
  }
  if (row.name === "run_synthesis" && meta.metrics) {
    return metricsBody(meta);
  }
  if (row.name === "recall_memories" && meta.memories) {
    return `<div class="body"><pre>${escapeHtml(row.detail || "")}</pre></div>`;
  }
  if (row.detail) {
    return `<div class="body"><pre>${escapeHtml(row.detail)}</pre></div>`;
  }
  return "";
}

function metricsBody(meta) {
  const metrics = meta.metrics || {};
  const baseline = meta.baseline || {};
  const cells = metrics.cell_count;
  const before = baseline.cell_count;
  const change = before && cells ? ((cells - before) / before) * 100 : null;
  const changeClass = change == null ? "" : change < 0 ? "good" : change > 0 ? "bad" : "";
  return `<div class="metrics">
      <div><strong>${compact(cells)}</strong><span>Cells</span></div>
      <div><strong>${compact(before)}</strong><span>Baseline</span></div>
      <div class="${changeClass}"><strong>${change == null ? "—" : `${change > 0 ? "+" : ""}${change.toFixed(1)}%`}</strong><span>Delta</span></div>
      <div><strong>${compact(metrics.runtime_seconds)}s</strong><span>Runtime</span></div>
    </div>`;
}

function scoreBody(meta) {
  const fitness = meta.fitness || {};
  const verification = meta.verification || {};
  const improvement = fitness.improvement_percent;
  const accepted = meta.accepted;
  const gate = (label, value) =>
    `<div class="${value === true ? "good" : value === false ? "bad" : ""}"><strong>${
      value === true ? "PASS" : value === false ? "FAIL" : "—"
    }</strong><span>${label}</span></div>`;
  return `<div class="metrics">
      <div class="${accepted ? "good" : "bad"}"><strong>${accepted ? "ACCEPT" : "REJECT"}</strong><span>Decision</span></div>
      <div class="${improvement > 0 ? "good" : improvement < 0 ? "bad" : ""}"><strong>${
        improvement == null ? "—" : `${improvement > 0 ? "+" : ""}${improvement.toFixed(2)}%`
      }</strong><span>Fitness</span></div>
      ${gate("Lint", verification.lint_passed)}
      ${gate("Sim", verification.simulation_passed)}
      ${gate("Synth", verification.synthesis_passed)}
      ${gate("Integrity", verification.protected_files_intact)}
    </div>`;
}

function findingRow(finding) {
  const where = finding.line ? `${finding.path}:${finding.line}` : finding.path;
  return `<div class="finding">
      <div class="row">
        <span class="sev ${escapeHtml(finding.severity)}">${escapeHtml(finding.severity)}</span>
        <strong>${escapeHtml(finding.title)}</strong>
      </div>
      <div class="detail">${escapeHtml(finding.detail || "")}</div>
      ${finding.suggestion ? `<div class="detail"><em>Fix:</em> ${escapeHtml(finding.suggestion)}</div>` : ""}
      <div class="where" data-open="${attr(finding.path)}" data-line="${finding.line || 1}">${escapeHtml(where)}</div>
    </div>`;
}

function renderRow(row) {
  switch (row.kind) {
    case "user":
      return `<div class="bubble-user">${escapeHtml(row.text)}</div>`;
    case "text":
      return `<div class="assistant">${markdown(row.text)}</div>`;
    case "thinking":
      return `<div class="thinking"><div class="head" data-toggle="${row.id}">${
        row.open ? "▾" : "▸"
      } Thinking</div>${row.open ? `<div>${escapeHtml(row.text)}</div>` : ""}</div>`;
    case "tool":
      return toolCard(row);
    case "error":
      return `<div class="notice">${escapeHtml(row.text)}</div>`;
    case "done":
      return `<div class="notice info">${escapeHtml(row.text)}</div>`;
    default:
      return "";
  }
}

function renderTimeline() {
  if (!state.rows.length) {
    const cards = (SUGGESTIONS[state.mode] || [])
      .map(
        ([title, hint]) =>
          `<button class="suggestion" data-prompt="${attr(title)}">${escapeHtml(title)}<small>${escapeHtml(
            hint,
          )}</small></button>`,
      )
      .join("");
    const heading = { generate: "Generate RTL", review: "Review RTL", optimize: "Optimize RTL" }[state.mode];
    return `<div class="empty">
        <h3>${heading}</h3>
        <div>Every claim is checked by Verilator and Yosys before it reaches you.</div>
        <div class="suggestions">${cards}</div>
      </div>`;
  }
  const rows = state.rows.map(renderRow).join("");
  if (!state.pendingApply) return rows;
  const files = state.pendingApply.map((file) => `<code>${escapeHtml(file)}</code>`).join(", ");
  return `${rows}<div class="tool awaiting">
      <div class="head"><span class="dot-warn">●</span><span class="verb">Keep this candidate?</span>
      <span class="summary">${state.pendingApply.length} file(s)</span></div>
      <div class="body"><div class="finding"><div class="detail">
        The edits live in the generation workspace so your working tree stayed clean. Applying copies
        ${files} into the project.
      </div></div></div>
      <div class="approve">
        <button data-discard="1">Discard</button>
        <button class="primary" data-apply="1">Apply to project</button>
      </div>
    </div>`;
}

function renderTaskCard() {
  if (!state.task) return "";
  const usage = state.usage;
  const project = state.snapshot && state.snapshot.config;
  return `<div class="taskcard">
      <div class="label">${escapeHtml(state.task.mode)} · ${escapeHtml(state.task.workspace || "")}</div>
      <div class="text">${escapeHtml(state.task.message)}</div>
      <div class="meters">
        ${project ? `<span>${escapeHtml(project.name)}</span>` : ""}
        ${usage ? `<span>Tokens <b>↑${tokens(usage.input_tokens)} ↓${tokens(usage.output_tokens)}</b></span>` : ""}
        ${usage ? `<span>Cost <b>$${(usage.cost_usd || 0).toFixed(4)}</b></span>` : ""}
      </div>
    </div>`;
}

function renderComposer() {
  const modes = MODES.map(
    (mode) =>
      `<button data-mode="${mode.id}" class="${state.mode === mode.id ? "active" : ""}">${mode.label}</button>`,
  ).join("");
  const auto = ["read", "edit", "run"]
    .map(
      (kind) =>
        `<label><input type="checkbox" data-auto="${kind}" ${state.autoApprove[kind] ? "checked" : ""}>${kind}</label>`,
    )
    .join("");
  return `<div class="composer">
      <div class="autorow"><span>Auto-approve</span>${auto}</div>
      <div class="inputwrap">
        <textarea id="prompt" rows="2" placeholder="${attr(PLACEHOLDER[state.mode])}" ${
          state.busy ? "disabled" : ""
        }>${escapeHtml(state.draft)}</textarea>
      </div>
      <div class="controls">
        <div class="modes">${modes}</div>
        <div class="spacer"></div>
        ${
          state.busy
            ? `<button class="send stop" id="stop">Stop</button>`
            : `<button class="send" id="send" ${state.online ? "" : "disabled"}>Send</button>`
        }
      </div>
    </div>`;
}

function render() {
  const timeline = document.querySelector(".timeline");
  const pinned = !timeline || timeline.scrollHeight - timeline.scrollTop - timeline.clientHeight < 60;
  const focused = document.activeElement && document.activeElement.id === "prompt";
  const caret = focused ? document.activeElement.selectionStart : null;

  document.getElementById("app").innerHTML = `
    <div class="topbar">
      <div class="brand"><span class="glyph">CE</span>ChipEvolve</div>
      <span class="status-dot ${state.online ? "online" : ""}" title="${
        state.online ? "Backend connected" : "Backend offline"
      }"></span>
      <div class="spacer"></div>
      ${state.online ? "" : `<button class="icon-button" id="start-backend">Start backend</button>`}
      <button class="icon-button" id="dashboard">Dashboard</button>
      <button class="icon-button" id="new-task" ${state.busy ? "disabled" : ""}>+ New</button>
    </div>
    ${renderTaskCard()}
    ${
      state.offlineReason && !state.online
        ? `<div class="notice-wrap"><div class="notice info">${escapeHtml(state.offlineReason)}</div></div>`
        : ""
    }
    <div class="timeline">${renderTimeline()}</div>
    ${renderComposer()}
  `;

  const fresh = document.querySelector(".timeline");
  if (pinned && fresh) fresh.scrollTop = fresh.scrollHeight;
  const prompt = document.getElementById("prompt");
  if (focused && prompt) {
    prompt.focus();
    if (caret != null) prompt.setSelectionRange(caret, caret);
  }
  autosize();
}

let frame = null;
let lastPaint = 0;
function schedule() {
  if (frame) return;
  const wait = Math.max(0, 66 - (Date.now() - lastPaint));
  frame = setTimeout(() => {
    frame = null;
    lastPaint = Date.now();
    render();
  }, wait);
}

function autosize() {
  const prompt = document.getElementById("prompt");
  if (!prompt) return;
  prompt.style.height = "auto";
  prompt.style.height = `${Math.min(prompt.scrollHeight, 160)}px`;
}

// ------------------------------------------------------------------ actions

function send() {
  const message = state.draft.trim();
  if (!message || state.busy || !state.online) return;
  state.rows = [{ kind: "user", text: message }];
  state.pendingApply = null;
  state.task = { mode: state.mode, message, workspace: "" };
  state.usage = null;
  state.busy = true;
  state.draft = "";
  save();
  vscode.postMessage({
    command: "startTask",
    mode: state.mode,
    message,
    autoApprove: Object.keys(state.autoApprove).filter((key) => state.autoApprove[key]),
  });
  schedule();
}

function newTask() {
  state.rows = [];
  state.pendingApply = null;
  state.task = null;
  state.usage = null;
  schedule();
}

function findRow(id) {
  return state.rows.find((row) => row.kind === "tool" && row.id === id);
}

function lastOpen(kind) {
  for (let index = state.rows.length - 1; index >= 0; index -= 1) {
    const row = state.rows[index];
    if (row.kind === kind && !row.closed) return row;
    if (row.kind === "tool") break;
  }
  return null;
}

function onEvent(event) {
  const payload = event.payload || {};
  switch (event.type) {
    case "chat.started":
      if (state.task) state.task.workspace = payload.workspace || "";
      break;
    case "chat.text": {
      const row = lastOpen("text");
      if (row) row.text += payload.text;
      else state.rows.push({ kind: "text", text: payload.text });
      break;
    }
    case "chat.thinking": {
      const row = lastOpen("thinking");
      if (row) row.text += payload.text;
      else state.rows.push({ kind: "thinking", id: `t${state.rows.length}`, text: payload.text, open: false });
      break;
    }
    case "chat.block_end":
      state.rows.forEach((row) => {
        if (row.kind === "text" || row.kind === "thinking") row.closed = true;
      });
      break;
    case "chat.tool_start":
      state.rows.push({
        kind: "tool",
        id: payload.tool_use_id,
        name: payload.name,
        input: payload.input || {},
        status: "running",
        summary: "",
        open: false,
      });
      break;
    case "chat.approval_required": {
      const row = findRow(payload.tool_use_id);
      if (row) {
        row.status = "awaiting";
        row.preview = payload.preview || {};
        row.summary = row.preview.added != null ? `+${row.preview.added} −${row.preview.removed}` : "needs approval";
        row.open = Boolean(row.preview.diff);
      }
      break;
    }
    case "chat.tool_approved": {
      const row = findRow(payload.tool_use_id);
      if (row) row.status = "running";
      break;
    }
    case "chat.tool_result": {
      const row = findRow(payload.tool_use_id);
      if (row) {
        row.status = payload.ok ? "done" : payload.summary === "rejected by user" ? "rejected" : "error";
        row.summary = payload.summary || (payload.ok ? "done" : "failed");
        row.detail = payload.detail || "";
        row.meta = payload.meta || {};
        if (!payload.ok || row.name === "score_candidate" || row.name === "report_findings") row.open = true;
      }
      break;
    }
    case "chat.integrity_violation":
      state.rows.push({ kind: "error", text: `Blocked: ${event.message}` });
      break;
    case "chat.usage":
      state.usage = payload;
      break;
    case "chat.error":
      state.rows.push({ kind: "error", text: event.message || "The task failed." });
      break;
    case "chat.done":
      state.busy = false;
      if (payload.reason === "cancelled") {
        state.rows.push({ kind: "done", text: "Task cancelled." });
      } else if (payload.detached && (payload.edited || []).length) {
        state.pendingApply = payload.edited;
      }
      break;
    default:
      return;
  }
  schedule();
}

// ----------------------------------------------------------------- wiring

document.addEventListener("click", (nativeEvent) => {
  const target = nativeEvent.target.closest(
    "[data-toggle],[data-approve],[data-reject],[data-mode],[data-prompt],[data-diff],[data-open],[data-apply],[data-discard],button",
  );
  if (!target) return;

  if (target.dataset.toggle) {
    const row = state.rows.find((item) => item.id === target.dataset.toggle);
    if (row) row.open = !row.open;
    return schedule();
  }
  if (target.dataset.approve || target.dataset.reject) {
    const id = target.dataset.approve || target.dataset.reject;
    const approved = Boolean(target.dataset.approve);
    const row = findRow(id);
    if (row) row.status = approved ? "running" : "rejected";
    vscode.postMessage({ command: "approve", toolUseId: id, approved });
    return schedule();
  }
  if (target.dataset.mode) {
    state.mode = target.dataset.mode;
    save();
    return schedule();
  }
  if (target.dataset.prompt) {
    state.draft = target.dataset.prompt;
    save();
    schedule();
    return send();
  }
  if (target.dataset.apply) {
    state.pendingApply = null;
    vscode.postMessage({ command: "applyEdits" });
    return schedule();
  }
  if (target.dataset.discard) {
    state.pendingApply = null;
    state.rows.push({ kind: "done", text: "Candidate discarded; the project is unchanged." });
    return schedule();
  }
  if (target.dataset.diff) {
    return vscode.postMessage({ command: "openDiff", path: target.dataset.diff });
  }
  if (target.dataset.open) {
    return vscode.postMessage({
      command: "openFile",
      path: target.dataset.open,
      line: Number(target.dataset.line || 1),
    });
  }
  switch (target.id) {
    case "send":
      return send();
    case "stop":
      return vscode.postMessage({ command: "cancel" });
    case "new-task":
      return newTask();
    case "dashboard":
      return vscode.postMessage({ command: "openDashboard" });
    case "start-backend":
      return vscode.postMessage({ command: "startBackend" });
    default:
      break;
  }
});

document.addEventListener("input", (nativeEvent) => {
  if (nativeEvent.target.id === "prompt") {
    state.draft = nativeEvent.target.value;
    save();
    autosize();
  }
});

document.addEventListener("change", (nativeEvent) => {
  const kind = nativeEvent.target.dataset && nativeEvent.target.dataset.auto;
  if (!kind) return;
  state.autoApprove[kind] = nativeEvent.target.checked;
  save();
});

document.addEventListener("keydown", (nativeEvent) => {
  if (nativeEvent.target.id !== "prompt") return;
  if (nativeEvent.key === "Enter" && !nativeEvent.shiftKey) {
    nativeEvent.preventDefault();
    send();
  }
});

window.addEventListener("message", (nativeEvent) => {
  const message = nativeEvent.data;
  if (message.type === "snapshot") {
    state.snapshot = message.snapshot;
    state.online = true;
    state.offlineReason = null;
  } else if (message.type === "offline") {
    state.online = false;
    state.offlineReason = message.message || "Backend offline. Start it to run a task.";
    state.busy = false;
  } else if (message.type === "event") {
    onEvent(message.event);
  } else if (message.type === "taskStarted") {
    if (state.task) state.task.workspace = message.workspace || "";
  } else if (message.type === "taskFailed") {
    state.busy = false;
    state.rows.push({ kind: "error", text: message.message });
  } else if (message.type === "applied") {
    const files = (message.files || []).join(", ");
    state.rows.push({ kind: "done", text: files ? `Applied to the project: ${files}` : "No edits to apply." });
  } else if (message.type === "setMode") {
    state.mode = message.mode;
    save();
  } else if (message.type === "newTask") {
    newTask();
  }
  schedule();
});

render();
vscode.postMessage({ command: "ready" });
