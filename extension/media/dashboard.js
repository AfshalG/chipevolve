const vscode = acquireVsCodeApi();

const state = {
  snapshot: null,
  online: false,
  error: null,
  events: [],
  running: false,
  selectedGeneration: null,
};

const stages = ["analyzing", "recalling_memory", "planning_mutation", "editing", "reviewing", "linting", "simulating", "synthesizing", "physical_analysis", "scoring"];

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>'"]/g, (character) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;" })[character]);
}

function metric(value, unit = "") {
  return value == null ? "N/A" : `${Number(value).toLocaleString(undefined, { maximumFractionDigits: 2 })}${unit ? ` ${unit}` : ""}`;
}

function percent(base, best, lower = true) {
  if (base == null || best == null || base === 0) return { label: "Awaiting measured data", className: "muted" };
  const value = ((best - base) / base) * 100;
  const good = lower ? value < 0 : value > 0;
  return { label: `${good ? "IMPROVED" : "REGRESSED"} ${value > 0 ? "+" : ""}${value.toFixed(1)}%`, className: good ? "good" : "bad" };
}

function statusIcon(status) {
  if (status === "connected") return "✓";
  if (status === "optional") return "○";
  return "×";
}

function renderSidebar(snapshot) {
  const tools = Object.entries(snapshot?.tool_status ?? {});
  const generations = snapshot?.generations ?? [];
  const latest = generations.at(-1);
  const baseline = snapshot?.baseline;
  return `<section class="side-shell">
    <div class="side-brand"><span class="chip-glyph">CE</span><div><strong>ChipEvolve</strong><small>Your chip gets better every generation.</small></div></div>
    <div class="side-status ${state.online ? "online" : "offline"}"><span></span>${state.online ? "BACKEND CONNECTED" : "BACKEND OFFLINE"}</div>
    <button class="primary wide" data-command="openDashboard">OPEN DASHBOARD <kbd>↗</kbd></button>
    ${!state.online ? `<button class="secondary wide" data-command="startBackend">START WSL BACKEND</button>` : ""}
    <div class="side-section"><header><span>CURRENT PROJECT</span></header>
      <button class="project-file" data-command="openFile" data-path="rtl/alu.sv"><span class="file-icon">SV</span><div><strong>${escapeHtml(snapshot?.config?.name ?? "demo-alu")}</strong><small>rtl/alu.sv</small></div><span>›</span></button>
      <div class="micro-grid"><div><strong>${baseline?.cell_count ?? "N/A"}</strong><span>BASE CELLS</span></div><div><strong>${generations.length}</strong><span>GENERATIONS</span></div></div>
    </div>
    <div class="side-section tools"><header><span>TOOLCHAIN</span></header>${tools.length ? tools.map(([name, status]) => `<div class="tool"><span class="dot ${status}">${statusIcon(status)}</span><strong>${escapeHtml(name.replaceAll("_", " "))}</strong><small>${status}</small></div>`).join("") : `<p class="empty-copy">Start the backend to inspect WSL tools.</p>`}</div>
    <div class="side-section"><header><span>LATEST GENERATION</span></header>${latest ? `<button class="latest-card" data-command="openDiff" data-generation="${latest.generation_number}" data-path="rtl/alu.sv"><span>GEN ${String(latest.generation_number).padStart(2, "0")}</span><strong>${escapeHtml(latest.mutation_type.replaceAll("_", " "))}</strong><small class="${latest.status}">${latest.status} · view native diff</small></button>` : `<p class="empty-copy">No experiments yet. Establish a baseline, then evolve.</p>`}</div>
    <div class="side-actions"><button class="secondary" data-command="baseline">BASELINE</button><button class="primary" data-command="evolve" ${!state.online ? "disabled" : ""}>EVOLVE</button></div>
  </section>`;
}

function stageRail(active) {
  const activeIndex = stages.indexOf(active);
  return stages.map((stage, index) => `<div class="stage ${index < activeIndex ? "done" : index === activeIndex ? "active" : ""}"><span>${index < activeIndex ? "✓" : index === activeIndex ? "●" : ""}</span><strong>${stage.replaceAll("_", " ")}</strong></div>`).join("");
}

function lineage(generations) {
  return `<div class="line-node baseline"><span class="node">◆</span><div><strong>BASELINE</strong><small>Generation 0 · real EDA</small></div></div>${generations.map((generation) => `<button class="line-node ${generation.status}" data-command="selectGeneration" data-id="${generation.id}"><span class="node">${generation.status === "accepted" ? "✓" : generation.status === "rejected" ? "×" : "●"}</span><div><strong>GEN ${String(generation.generation_number).padStart(2, "0")}</strong><small>${escapeHtml(generation.mutation_type.replaceAll("_", " "))}</small></div><em>${generation.status}</em></button>`).join("") || `<p class="empty-copy lineage-empty">Measured generations will branch from the baseline.</p>`}`;
}

function metricCard(label, value, unit, change) {
  return `<article class="metric-card"><header>${label}</header><strong>${metric(value, unit)}</strong><small class="${change.className}">${change.label}</small><div class="spark"><i></i><i></i><i></i><i></i><i></i><i></i></div></article>`;
}

function renderDashboard(snapshot) {
  const baseline = snapshot?.baseline ?? {};
  const best = snapshot?.best ?? {};
  const generations = snapshot?.generations ?? [];
  const accepted = generations.filter((generation) => generation.status === "accepted").length;
  const rejected = generations.filter((generation) => generation.status === "rejected").length;
  const selected = generations.find((generation) => generation.id === state.selectedGeneration) ?? generations.at(-1);
  const latestEvent = state.events[0];
  const activeStage = state.running ? (state.events.find((event) => event.stage)?.stage ?? "analyzing") : null;
  const tools = Object.entries(snapshot?.tool_status ?? {});
  return `<main class="dashboard">
    <header class="topbar">
      <div class="brand"><span class="brand-chip">CE</span><div><strong>ChipEvolve</strong><small>Your chip gets better every generation.</small></div></div>
      <div class="crumb"><span>${escapeHtml(snapshot?.config?.name ?? "demo-alu")}</span><b>›</b><span>${selected ? `gen-${String(selected.generation_number).padStart(3, "0")}` : "baseline"}</span></div>
      <div class="top-actions"><span class="system ${state.online ? "online" : "offline"}"><i></i>${state.online ? "SYSTEM READY" : "BACKEND OFFLINE"}</span><button class="icon" data-command="refresh" title="Refresh">↻</button><button class="primary evolve" data-command="evolve" ${!state.online || state.running ? "disabled" : ""}>${state.running ? "● EVOLVING" : "▶ EVOLVE"}</button></div>
    </header>
    <aside class="left-panel">
      <div class="panel-title"><span>PROJECT</span></div>
      <button class="file-row" data-command="openFile" data-path="rtl/alu.sv"><span class="folder">⌄</span><strong>rtl</strong></button>
      <button class="file-row nested" data-command="openFile" data-path="rtl/alu.sv"><span class="sv">SV</span><strong>alu.sv</strong><em>OPEN ↗</em></button>
      <div class="panel-title border"><span>EVOLUTION LINEAGE</span><b>${generations.length}</b></div>
      <div class="lineage">${lineage(generations)}</div>
    </aside>
    <section class="content">
      ${!state.online ? `<div class="offline-banner"><div><strong>WSL backend is not connected</strong><span>Start the Python service to inspect EDA tools and establish a real baseline.</span></div><button class="secondary" data-command="startBackend">START BACKEND</button></div>` : ""}
      <div class="hero"><div><span class="eyebrow">${selected ? `GENERATION ${String(selected.generation_number).padStart(2, "0")}` : "GENERATION 00 · BASELINE"}</span><h1>${selected ? escapeHtml(selected.mutation_type.replaceAll("_", " ")) : "RTL evolution control center"}</h1><p>${escapeHtml(selected?.hypothesis ?? "Real EDA tools decide which mutations survive.")}</p></div><div class="run-count"><strong>${generations.length}</strong><span>GENERATIONS</span></div></div>
      <div class="metrics">
        ${metricCard("POWER", best.power_mw, "mW", percent(baseline.power_mw, best.power_mw))}
        ${metricCard("PERFORMANCE", best.fmax_mhz, "MHz", percent(baseline.fmax_mhz, best.fmax_mhz, false))}
        ${metricCard("CELL COUNT", best.cell_count, "cells", percent(baseline.cell_count, best.cell_count))}
        ${metricCard("CONGESTION", best.congestion, "", percent(baseline.congestion, best.congestion))}
      </div>
      <div class="evidence-grid">
        <article class="experiment-card"><header><span>MUTATION EVIDENCE</span>${selected ? `<b class="decision ${selected.status}">${selected.status}</b>` : ""}</header>
          ${selected ? `<div class="hypothesis"><span>HYPOTHESIS</span><p>${escapeHtml(selected.hypothesis)}</p></div><div class="checks"><div class="${selected.verification.protected_files_intact ? "pass" : "fail"}"><i>${selected.verification.protected_files_intact ? "✓" : "×"}</i><span>Protected integrity</span></div><div class="${selected.verification.simulation_passed ? "pass" : "fail"}"><i>${selected.verification.simulation_passed ? "✓" : "×"}</i><span>Simulation</span></div><div class="${selected.verification.synthesis_passed ? "pass" : "fail"}"><i>${selected.verification.synthesis_passed ? "✓" : "×"}</i><span>Synthesis</span></div></div><button class="secondary diff-button" data-command="openDiff" data-generation="${selected.generation_number}" data-path="rtl/alu.sv">OPEN NATIVE VS CODE DIFF ↗</button>` : `<div class="large-empty"><strong>No generation evidence yet</strong><span>Establish a baseline, then run one focused mutation.</span></div>`}
        </article>
        <article class="memory-card"><header><span>ENGINEERING MEMORY</span><b>${generations.reduce((sum, generation) => sum + generation.memory_refs.length, 0)} RECALLS</b></header>${generations.slice().reverse().slice(0, 3).map((generation) => `<div class="memory-row"><span>GEN ${String(generation.generation_number).padStart(2, "0")}</span><div><strong>${escapeHtml(generation.mutation_type.replaceAll("_", " "))}</strong><small>${escapeHtml(generation.decision_reason ?? "Experiment recorded")}</small></div><em class="${generation.status}">${generation.status}</em></div>`).join("") || `<div class="large-empty"><strong>Memory is empty</strong><span>Experiments—not chat messages—will be stored here.</span></div>`}</article>
      </div>
      <footer class="summary"><div><strong>${generations.length}</strong><span>GENERATIONS</span></div><div><strong>${accepted}</strong><span>ACCEPTED</span></div><div><strong>${rejected}</strong><span>REJECTED</span></div><div><strong>${generations.reduce((sum, generation) => sum + generation.memory_refs.length, 0)}</strong><span>MEMORY RECALLS</span></div></footer>
    </section>
    <aside class="right-panel">
      <div class="panel-title"><span>EVOLUTION</span><b class="live ${state.running ? "running" : ""}">${state.running ? "● LIVE" : "IDLE"}</b></div>
      <div class="current-gen"><div><span>CURRENT</span><strong>${state.running ? `GEN ${String(generations.length + 1).padStart(2, "0")}` : selected ? `GEN ${String(selected.generation_number).padStart(2, "0")}` : "BASELINE"}</strong></div><em>${escapeHtml(snapshot?.config?.objective?.toUpperCase() ?? "BALANCED")}</em></div>
      <div class="stages">${stageRail(activeStage)}</div>
      <div class="panel-title border"><span>AGENT ACTIVITY</span><b>◌</b></div>
      <div class="activity">${state.events.slice(0, 10).map((event) => `<div><time>${new Date(event.timestamp).toLocaleTimeString([], { hour12: false })}</time><span>${escapeHtml(event.message)}</span></div>`).join("") || `<p class="empty-copy">Deterministic stage events stream here.</p>`}</div>
      <div class="panel-title border"><span>TOOLCHAIN</span></div><div class="tool-list">${tools.map(([name, status]) => `<div><span class="dot ${status}">${statusIcon(status)}</span><strong>${escapeHtml(name.replaceAll("_", " "))}</strong><em>${status}</em></div>`).join("")}</div>
      <div class="integrity"><span>✓</span><div><strong>Protected evaluation</strong><small>INTEGRITY ENFORCED</small></div></div>
    </aside>
  </main>`;
}

function render() {
  const sidebar = document.body.dataset.mode === "sidebar";
  document.getElementById("app").innerHTML = sidebar ? renderSidebar(state.snapshot) : renderDashboard(state.snapshot);
}

document.addEventListener("click", (event) => {
  const button = event.target.closest("[data-command]");
  if (!button) return;
  const command = button.dataset.command;
  if (command === "selectGeneration") {
    state.selectedGeneration = button.dataset.id;
    render();
    return;
  }
  if (command === "evolve") state.running = true;
  vscode.postMessage({ command, path: button.dataset.path, generation: Number(button.dataset.generation) || undefined });
  render();
});

window.addEventListener("message", ({ data }) => {
  if (data.type === "snapshot") {
    state.snapshot = data.snapshot;
    state.online = true;
    state.error = null;
  }
  if (data.type === "offline") {
    state.online = false;
    state.error = data.message;
  }
  if (data.type === "event") {
    state.events.unshift(data.event);
    state.events = state.events.slice(0, 60);
    if (data.event.type === "generation.stage_changed" || data.event.type === "baseline.started") state.running = true;
    if (["generation.decision", "baseline.failed"].includes(data.event.type)) state.running = false;
  }
  render();
});

vscode.postMessage({ command: "refresh" });
render();
