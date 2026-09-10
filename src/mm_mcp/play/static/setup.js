"use strict";

// Setup remains usable before a native catalog or an editable project exists.
window.WorkshopSetup = class WorkshopSetup {
  constructor(request, onChanged = async () => {}) {
    this.request = request;
    this.onChanged = onChanged;
    this.model = null;
    this.job = null;
    this.busy = false;
    this.stopping = false;
    this.dialog = document.createElement("dialog");
    this.dialog.id = "setup-dialog";
    this.dialog.setAttribute("aria-labelledby", "setup-title");
    this.dialog.innerHTML = `
      <div class="setup-heading"><div><p class="eyebrow">Your local workshop</p>
        <h2 id="setup-title">Set up material rendering</h2></div>
        <button id="setup-close" type="button" aria-label="Close setup">Close</button></div>
      <p>Connect Godot and the Material Maker source folder. Your materials and edits stay in your workspace.</p>
      <div id="setup-state" class="setup-state"></div>
      <form id="setup-form">
        <label for="setup-godot">Godot executable or application</label>
        <input id="setup-godot" name="godot_binary" type="text" required autocomplete="off" spellcheck="false"
          placeholder="For example, /Applications/Godot.app">
        <select id="setup-godot-detected" aria-label="Detected Godot installations" hidden></select>
        <small id="setup-godot-source" class="hint"></small>
        <label for="setup-project">Material Maker source folder</label>
        <input id="setup-project" name="project_path" type="text" required autocomplete="off" spellcheck="false"
          placeholder="Folder containing project.godot and addons">
        <select id="setup-project-detected" aria-label="Detected Material Maker source folders" hidden></select>
        <small id="setup-project-source" class="hint"></small>
        <div class="toolbar setup-actions"><button id="setup-save" type="submit" class="primary">Save setup</button>
          <button id="setup-check" type="button">Find tools &amp; check setup</button></div>
      </form>
      <ul id="setup-checks" class="setup-checks"></ul>
      <div class="toolbar setup-actions"><button id="setup-verify" type="button">Test a small render</button>
        <button id="setup-cancel" type="button" disabled>Cancel test</button></div>
      <p id="setup-message" role="status" aria-live="polite"></p>
      <details id="setup-install"><summary>Need to install the native tools?</summary>
        <ol><li><a id="setup-godot-link" target="_blank" rel="noreferrer">Download Godot 4.7</a> and extract it.</li>
          <li><a id="setup-project-link" target="_blank" rel="noreferrer">Download the compatible Material Maker source</a> and extract it.</li>
          <li>Use <strong>Find tools &amp; check setup</strong>, or paste the two paths above, then save.</li></ol>
        <p class="hint">A packaged Material Maker application does not include the source folder this renderer needs.
          A successful test render confirms that the native tools can use your graphics hardware.</p>
      </details>
      <details><summary>Saved settings and repair</summary><p id="setup-settings-file" class="hint"></p>
        <p class="hint">Paths supplied by your launcher or .env file take priority. To repair a source checkout's
          .env paths, run <code>python scripts/configure.py</code> in its Python environment.</p></details>`;
    document.body.appendChild(this.dialog);
    this.field("close").onclick = () => this.dialog.close();
    this.field("form").onsubmit = event => {
      event.preventDefault();
      this.run(() => this.save());
    };
    this.field("check").onclick = () => this.run(() => this.check());
    this.field("verify").onclick = () => this.run(() => this.verify());
    this.field("cancel").onclick = () => this.run(() => this.cancel());
    this.dialog.addEventListener("click", event => {
      if (event.target !== this.dialog) return;
      const bounds = this.dialog.getBoundingClientRect();
      if (event.clientX < bounds.left || event.clientX > bounds.right ||
          event.clientY < bounds.top || event.clientY > bounds.bottom) this.dialog.close();
    });
  }

  field(name) { return this.dialog.querySelector("#setup-" + name); }

  message(text, error = false) {
    this.field("message").textContent = text;
    this.field("message").classList.toggle("error", error);
  }

  async run(fn) {
    try { await fn(); } catch (error) { this.message(error.message, true); }
  }

  async load(fillFields = true) {
    this.model = await this.request("/api/setup");
    this.draw(fillFields);
    await this.onChanged(this.model);
    return this.model;
  }

  show() {
    if (!this.dialog.open) this.dialog.showModal();
    if (!this.busy) this.run(() => this.load());
  }

  ready() {
    return !!this.model && (this.model.injected_test_renderer ||
      (this.model.native_render_configured && !(this.model.checks || []).some(check => check.ok === false && check.required !== false)));
  }

  label() {
    if (!this.model) return "Connecting…";
    if (this.model.injected_test_renderer) return "Test renderer";
    if (!this.model.native_render_configured) return "Setup needed";
    if (this.model.native_render_verified_this_session) return "Rendering verified";
    if (this.model.last_render_error) return "Render needs attention";
    if (!this.ready()) return "Check setup";
    return "Ready to test";
  }

  draw(fillFields = false) {
    const model = this.model;
    if (!model) return;
    this.field("state").textContent = this.label();
    this.field("state").classList.toggle("verified", !!model.native_render_verified_this_session);
    for (const [name, key, candidates] of [
      ["godot", "godot_binary", model.detected?.godot_binaries || []],
      ["project", "project_path", model.detected?.project_paths || []]
    ]) {
      const input = this.field(name), source = model.overrides?.[key];
      if (fillFields) input.value = model.settings?.[key] || "";
      input.readOnly = !!source;
      this.field(name + "-source").textContent = source ? "Set by " + source + ". Change this path there to override it." : "";
      const detected = this.field(name + "-detected");
      detected.replaceChildren(new Option("Choose a detected installation…", ""));
      candidates.forEach(path => detected.add(new Option(path, path)));
      detected.hidden = !candidates.length || !!source;
      detected.onchange = () => { if (detected.value) input.value = detected.value; };
      if (fillFields && !input.value && candidates.length === 1) input.value = candidates[0];
    }
    const list = this.field("checks");
    list.replaceChildren();
    for (const check of model.checks || []) {
      const row = document.createElement("li");
      row.className = check.ok ? "check-pass" : check.required === false ? "check-info" : "check-fail";
      const title = document.createElement("strong");
      title.textContent = (check.ok ? "✓ " : check.required === false ? "○ " : "! ") + check.name.replaceAll("_", " ");
      const detail = document.createElement("span");
      detail.textContent = check.detail;
      row.append(title, detail); list.appendChild(row);
    }
    this.field("settings-file").textContent = "Native defaults are saved in " + model.settings_file + ". Your workspace stays where it is.";
    this.field("godot-link").href = model.install.godot_url;
    this.field("project-link").href = model.install.material_maker_url;
    this.field("install").open = !model.native_render_configured;
    if (model.last_render_error && !this.busy) this.message("Last native render: " + model.last_render_error, true);
    this.buttons();
  }

  buttons() {
    this.field("save").disabled = this.busy || !!this.job || !!this.model?.busy;
    this.field("check").disabled = this.busy;
    this.field("verify").disabled = this.busy || !!this.job || !this.ready() || !!this.model?.injected_test_renderer;
    this.field("cancel").disabled = !this.job || this.stopping;
  }

  async save() {
    this.busy = true; this.buttons(); this.message("Saving native tool paths…");
    try {
      this.model = await this.request("/api/setup", {
        godot_binary: this.field("godot").value.trim(), project_path: this.field("project").value.trim()
      });
      this.draw(true);
      await this.onChanged(this.model);
      this.message(Object.keys(this.model.overrides || {}).length ?
        "Saved defaults. The launcher settings shown above still take priority." :
        "Setup saved. Test a small render or choose a recipe to begin.");
    } finally { this.busy = false; this.buttons(); }
  }

  async check() {
    this.busy = true; this.buttons(); this.message("Checking paths and looking for installed tools…");
    try {
      this.model = await this.request("/api/setup/check", {});
      this.draw(false);
      for (const [field, key] of [["godot", "godot_binaries"], ["project", "project_paths"]]) {
        const paths = this.model.detected?.[key] || [];
        if (!this.field(field).value && paths.length === 1) this.field(field).value = paths[0];
      }
      await this.onChanged(this.model);
      const count = (this.model.detected?.godot_binaries?.length || 0) + (this.model.detected?.project_paths?.length || 0);
      this.message(count ? "Detected installations are listed below each path. Choose yours and save setup." :
        "No installations were detected. Paste their paths or use the download links below.");
    } finally { this.busy = false; this.buttons(); }
  }

  async verify() {
    this.busy = true; this.stopping = false; this.buttons(); this.message("Starting a small native render…");
    try {
      this.job = await this.request("/api/setup/verify", {});
      this.buttons();
      for (;;) {
        const job = await this.request("/api/jobs/" + this.job.job_id);
        if (job.state === "complete") {
          await this.load(false);
          const verified = this.model.native_render_verified_this_session;
          this.message(verified ? "Test render completed. Native rendering is verified for this session." :
            "Test completed, but the current setup still needs a verified native render.", !verified);
          break;
        }
        if (job.state === "failed" || job.state === "cancelled") {
          await this.load(false);
          this.message(job.state === "cancelled" ? "Test cancelled. No incomplete build was selected." :
            job.result?.error || "The native render failed. Review the setup checks and try again.", job.state === "failed");
          break;
        }
        const elapsed = Math.max(0, Math.floor(Date.now() / 1000 - job.created));
        this.message(this.stopping ? "Stopping the native test…" :
          (job.state === "queued" ? "Test queued" : "Rendering a small material") + " · " + elapsed + "s");
        await new Promise(resolve => setTimeout(resolve, 500));
      }
    } catch (error) {
      // A failed polling request must not silently abandon a test in the queue.
      if (this.job) await this.request("/api/jobs/" + this.job.job_id + "/cancel", {}).catch(() => {});
      throw error;
    } finally { this.job = null; this.busy = false; this.stopping = false; this.buttons(); }
  }

  async cancel() {
    if (!this.job) return;
    this.stopping = true; this.buttons();
    try { await this.request("/api/jobs/" + this.job.job_id + "/cancel", {}); }
    catch (error) { this.stopping = false; this.buttons(); throw error; }
  }
};
