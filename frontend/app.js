const api = {
  health: "/api/health",
  config: "/api/config",
  volumes: "/api/volumes",
  instructions: "/api/instructions",
  cardStatus: "/api/card/status",
  cardInit: "/api/card/init",
  folders: "/api/folders",
  samples: "/api/samples",
  upload: "/api/samples/upload",
  audio: "/api/samples/audio",
};

const els = {
  appTitle: document.getElementById("app-title"),
  appAuthor: document.getElementById("app-author"),
  ffmpegStatus: document.getElementById("ffmpeg-status"),
  cardStatus: document.getElementById("card-status"),
  waveStatus: document.getElementById("wave-status"),
  fileCount: document.getElementById("file-count"),
  volumeSelect: document.getElementById("volume-select"),
  cardPath: document.getElementById("card-path"),
  refreshVolumes: document.getElementById("refresh-volumes"),
  initCard: document.getElementById("init-card"),
  cardNote: document.getElementById("card-note"),
  folderSelect: document.getElementById("folder-select"),
  channelSelect: document.getElementById("channel-select"),
  newFolder: document.getElementById("new-folder"),
  createFolder: document.getElementById("create-folder"),
  fileInput: document.getElementById("file-input"),
  dropzone: document.getElementById("dropzone"),
  jobStatus: document.getElementById("job-status"),
  folderGrid: document.getElementById("folder-grid"),
  sampleRows: document.getElementById("sample-rows"),
  preview: document.getElementById("preview"),
  formatRules: document.getElementById("format-rules"),
  instructionSections: document.getElementById("instruction-sections"),
  errorCodes: document.getElementById("error-codes"),
};

const state = {
  config: null,
  cardPath: "",
  busy: false,
};

function selectedFolder() {
  return els.folderSelect.value || "";
}

async function readJson(response) {
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = payload.detail;
    const message = Array.isArray(detail)
      ? detail.map((item) => item.msg || JSON.stringify(item)).join(" ")
      : detail || response.statusText;
    throw new Error(message);
  }
  return payload;
}

async function loadConfig() {
  const [health, config, instructions] = await Promise.all([
    readJson(await fetch(api.health)),
    readJson(await fetch(api.config)),
    readJson(await fetch(api.instructions)),
  ]);

  state.config = config;
  document.title = config.app_name;
  els.appTitle.textContent = config.app_name;
  els.appAuthor.textContent = config.author;
  els.channelSelect.value = config.default_channels;
  setBadge(els.ffmpegStatus, health.ffmpeg_available ? "READY" : "MISSING", health.ffmpeg_available);

  if (!health.ffmpeg_available) {
    els.jobStatus.textContent = `Install ${health.ffmpeg_binary} before converting files.`;
  }

  if (config.sdcard_path) {
    els.cardPath.value = config.sdcard_path;
    state.cardPath = config.sdcard_path;
  }

  renderInstructions(instructions);
}

function renderInstructions(instructions) {
  els.formatRules.innerHTML = "";
  instructions.format_rules.forEach((rule) => {
    const item = document.createElement("li");
    item.textContent = rule;
    els.formatRules.appendChild(item);
  });

  els.instructionSections.innerHTML = "";
  instructions.sections.forEach((section) => {
    const wrap = document.createElement("section");
    const heading = document.createElement("h3");
    heading.textContent = section.heading;
    const list = document.createElement("ol");
    section.steps.forEach((step) => {
      const item = document.createElement("li");
      item.innerHTML = `<strong>${escapeHtml(step.title)}.</strong> ${escapeHtml(step.detail)}`;
      list.appendChild(item);
    });
    wrap.appendChild(heading);
    wrap.appendChild(list);
    els.instructionSections.appendChild(wrap);
  });

  els.errorCodes.innerHTML = "";
  instructions.error_codes.forEach((code) => {
    const row = document.createElement("div");
    row.innerHTML = `<dt>${escapeHtml(code.title)}</dt><dd>${escapeHtml(code.detail)}</dd>`;
    els.errorCodes.appendChild(row);
  });
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function setBadge(node, label, ok) {
  node.textContent = label;
  node.classList.toggle("is-ok", Boolean(ok));
  node.classList.toggle("is-bad", ok === false);
}

async function loadVolumes() {
  const volumes = await readJson(await fetch(api.volumes));
  els.volumeSelect.innerHTML = "";
  const placeholder = document.createElement("option");
  placeholder.value = "";
  placeholder.textContent = volumes.length ? "Select a mounted volume" : "No extra volumes found";
  els.volumeSelect.appendChild(placeholder);

  volumes.forEach((volume) => {
    const option = document.createElement("option");
    option.value = volume.path;
    const flags = [
      volume.looks_like_sd ? "TM-2?" : null,
      volume.has_wave_root ? "WAVE" : null,
      volume.writable ? "RW" : "LOCKED",
    ]
      .filter(Boolean)
      .join(" / ");
    option.textContent = `${volume.name} — ${flags}`;
    els.volumeSelect.appendChild(option);
  });

  const preferred =
    volumes.find((volume) => volume.path === state.cardPath) ||
    volumes.find((volume) => volume.has_wave_root) ||
    volumes.find((volume) => volume.looks_like_sd);

  if (preferred) {
    els.volumeSelect.value = preferred.path;
    els.cardPath.value = preferred.path;
    state.cardPath = preferred.path;
    await refreshCard();
  }
}

async function refreshCard() {
  if (!state.cardPath) {
    setBadge(els.cardStatus, "NONE", false);
    els.waveStatus.textContent = "—";
    els.fileCount.textContent = "0";
    els.cardNote.textContent = "No card selected.";
    return;
  }

  const status = await readJson(
    await fetch(`${api.cardStatus}?${new URLSearchParams({ card_path: state.cardPath })}`)
  );

  setBadge(els.cardStatus, status.writable ? "MOUNTED" : "LOCKED", status.writable);
  els.waveStatus.textContent = status.wave_ready ? status.wave_root : "MISSING";
  els.waveStatus.classList.toggle("is-ok", status.wave_ready);
  els.waveStatus.classList.toggle("is-bad", !status.wave_ready);
  els.fileCount.textContent = String(status.file_count);

  const missing = status.missing_recommended.length
    ? ` Missing recommended folders: ${status.missing_recommended.join(", ")}.`
    : "";
  els.cardNote.textContent = status.wave_ready
    ? `${status.wave_path} · ${status.folder_count} folders · ${status.file_count} files.${missing}`
    : `${status.selected_path} has no ${status.wave_root} yet. Press Init WAVE tree.`;

  renderFolders(status);
  await loadSamples();
}

function renderFolders(status) {
  const current = selectedFolder();
  els.folderSelect.innerHTML = "";
  els.folderGrid.innerHTML = "";

  status.folders.forEach((folder) => {
    const option = document.createElement("option");
    option.value = folder.name === state.config.root_folder_label ? "" : folder.name;
    option.textContent = `${folder.name} (${folder.file_count}/${folder.file_count + folder.remaining_slots})`;
    els.folderSelect.appendChild(option);

    const tile = document.createElement("button");
    tile.type = "button";
    tile.className = "folder-tile";
    tile.dataset.folder = option.value;
    tile.innerHTML = `<strong>${escapeHtml(folder.name)}</strong><span>${folder.file_count} files · ${folder.remaining_slots} open</span>`;
    tile.addEventListener("click", () => {
      els.folderSelect.value = tile.dataset.folder;
      highlightSelectedFolder();
    });
    bindDropTarget(tile, tile.dataset.folder);
    els.folderGrid.appendChild(tile);
  });

  if ([...els.folderSelect.options].some((option) => option.value === current)) {
    els.folderSelect.value = current;
  }
  highlightSelectedFolder();
}

function highlightSelectedFolder() {
  const current = selectedFolder();
  els.folderGrid.querySelectorAll(".folder-tile").forEach((tile) => {
    tile.classList.toggle("is-selected", tile.dataset.folder === current);
  });
}

async function loadSamples() {
  if (!state.cardPath) {
    return;
  }
  const samples = await readJson(
    await fetch(`${api.samples}?${new URLSearchParams({ card_path: state.cardPath })}`)
  );
  els.sampleRows.innerHTML = "";
  if (!samples.length) {
    els.sampleRows.innerHTML = `<tr><td colspan="5">WAVE tree is empty. Drop files onto a folder.</td></tr>`;
    return;
  }

  samples.forEach((sample) => {
    const row = document.createElement("tr");
    const format = [sample.sample_rate, sample.bit_depth ? `${sample.bit_depth}-bit` : null, sample.channels ? `${sample.channels}ch` : null]
      .filter(Boolean)
      .join(" / ");
    row.innerHTML = `
      <td>${escapeHtml(sample.folder)}</td>
      <td>${escapeHtml(sample.name)}</td>
      <td>${escapeHtml(format || "WAV")}</td>
      <td>${sample.duration_seconds != null ? `${sample.duration_seconds.toFixed(2)}s` : "—"}</td>
      <td></td>
    `;
    const actions = row.lastElementChild;
    const play = document.createElement("button");
    play.type = "button";
    play.className = "btn";
    play.textContent = "Play";
    play.addEventListener("click", () => previewSample(sample));
    const remove = document.createElement("button");
    remove.type = "button";
    remove.className = "btn btn--signal";
    remove.textContent = "Delete";
    remove.addEventListener("click", () => removeSample(sample));
    actions.append(play, remove);
    els.sampleRows.appendChild(row);
  });
}

function previewSample(sample) {
  const folder = sample.folder === state.config.root_folder_label ? "" : sample.folder;
  const params = new URLSearchParams({
    card_path: state.cardPath,
    folder,
    filename: sample.name,
  });
  els.preview.src = `${api.audio}?${params}`;
  els.preview.play().catch(() => {
    els.jobStatus.textContent = "Browser blocked autoplay. Use the audio bar.";
  });
}

async function removeSample(sample) {
  if (!window.confirm(`Delete ${sample.name} from the card?`)) {
    return;
  }
  const folder = sample.folder === state.config.root_folder_label ? "" : sample.folder;
  await readJson(
    await fetch(api.samples, {
      method: "DELETE",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        card_path: state.cardPath,
        folder,
        filename: sample.name,
      }),
    })
  );
  els.jobStatus.textContent = `Deleted ${sample.name}. Reassign any pad that used it or the TM-2 will show NO WAVE.`;
  await refreshCard();
}

async function initCard() {
  requireCard();
  const status = await readJson(
    await fetch(api.cardInit, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        card_path: state.cardPath,
        create_recommended: true,
      }),
    })
  );
  els.jobStatus.textContent = `Created ${status.wave_root} plus recommended folders.`;
  await refreshCard();
}

async function createFolder() {
  requireCard();
  const folderName = els.newFolder.value.trim();
  if (!folderName) {
    throw new Error("Enter a folder name. ASCII only, one level under WAVE.");
  }
  await readJson(
    await fetch(api.folders, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        card_path: state.cardPath,
        folder_name: folderName,
      }),
    })
  );
  els.newFolder.value = "";
  els.jobStatus.textContent = `Created folder ${folderName}.`;
  await refreshCard();
}

function requireCard() {
  state.cardPath = els.cardPath.value.trim();
  if (!state.cardPath) {
    throw new Error("Select or paste the mounted SD card path.");
  }
}

async function uploadFiles(fileList, folderName) {
  requireCard();
  const files = [...fileList];
  if (!files.length) {
    return;
  }
  if (state.busy) {
    throw new Error("A conversion is already running.");
  }

  const body = new FormData();
  body.append("card_path", state.cardPath);
  body.append("folder", folderName ?? selectedFolder());
  body.append("channels", els.channelSelect.value);
  files.forEach((file) => body.append("files", file));

  state.busy = true;
  els.jobStatus.textContent = `Converting ${files.length} file(s) to TM-2 WAV…`;
  try {
    const result = await readJson(
      await fetch(api.upload, {
        method: "POST",
        body,
      })
    );
    const saved = result.results.map((item) => item.saved_name).join(", ");
    const extra = result.errors.length ? ` Errors: ${result.errors.join(" ")}` : "";
    els.jobStatus.textContent = saved
      ? `Wrote ${saved}.${extra} Eject the card, insert it with the TM-2 off, then assign pads with INST.`
      : extra;
    await refreshCard();
  } finally {
    state.busy = false;
  }
}

function bindDropTarget(node, folderName) {
  node.addEventListener("dragover", (event) => {
    event.preventDefault();
    node.classList.add("is-hot");
  });
  node.addEventListener("dragleave", () => node.classList.remove("is-hot"));
  node.addEventListener("drop", async (event) => {
    event.preventDefault();
    event.stopPropagation();
    node.classList.remove("is-hot");
    if (folderName !== undefined) {
      els.folderSelect.value = folderName;
      highlightSelectedFolder();
    }
    try {
      await uploadFiles(event.dataTransfer.files, folderName);
    } catch (error) {
      els.jobStatus.textContent = error.message;
    }
  });
}

function bindUi() {
  els.volumeSelect.addEventListener("change", async () => {
    if (!els.volumeSelect.value) {
      return;
    }
    els.cardPath.value = els.volumeSelect.value;
    state.cardPath = els.volumeSelect.value;
    try {
      await refreshCard();
    } catch (error) {
      els.cardNote.textContent = error.message;
    }
  });

  els.cardPath.addEventListener("change", async () => {
    state.cardPath = els.cardPath.value.trim();
    try {
      await refreshCard();
    } catch (error) {
      els.cardNote.textContent = error.message;
    }
  });

  els.refreshVolumes.addEventListener("click", () => run(loadVolumes));
  els.initCard.addEventListener("click", () => run(initCard));
  els.createFolder.addEventListener("click", () => run(createFolder));
  els.folderSelect.addEventListener("change", highlightSelectedFolder);
  els.fileInput.addEventListener("change", async () => {
    try {
      await uploadFiles(els.fileInput.files);
    } catch (error) {
      els.jobStatus.textContent = error.message;
    } finally {
      els.fileInput.value = "";
    }
  });

  bindDropTarget(els.dropzone);
}

async function run(task) {
  try {
    await task();
  } catch (error) {
    els.jobStatus.textContent = error.message;
  }
}

bindUi();
run(async () => {
  await loadConfig();
  await loadVolumes();
});
