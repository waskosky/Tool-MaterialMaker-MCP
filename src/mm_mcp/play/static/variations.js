"use strict";

// A family keeps the exact inputs that produced it, independently of later edits.
window.WorkshopVariations = class WorkshopVariations {
  constructor(request, onUse, onPin, onError) {
    Object.assign(this, {request, onUse, onPin, onError});
    this.epoch = 0; this.candidates = []; this.context = null;
    this.ranges = new Map(); this.boundProject = null; this.submitting = false;
    this.ready = false; this.recipe = null; this.inspection = null;
    document.getElementById("family-cancel").onclick = () => this.cancel().catch(this.onError);
  }

  bind(project, recipe, locked, ready) {
    this.recipe = recipe; this.ready = ready; this.locked = locked;
    const specs = (project?.controls || []).filter(s => ["float", "int"].includes(s.kind));
    if (this.boundProject !== project?.project_id) {
      this.boundProject = project?.project_id;
      if (!this.keepRanges) this.ranges.clear();
      let enabled = [...this.ranges.values()].filter(value => value.enabled).length;
      for (const s of specs) {
        if (this.ranges.has(s.id)) continue;
        const spread = Math.max(Math.abs(s.value) * .25, s.kind === "int" ? 1 : .1);
        const lower = Number.isFinite(s.min) ? s.min : -Infinity, upper = Number.isFinite(s.max) ? s.max : Infinity;
        const center = Math.min(upper, Math.max(lower, s.value));
        let min = Math.max(lower, center - spread), max = Math.min(upper, center + spread);
        if (s.kind === "int") { min = Math.ceil(min); max = Math.floor(max); }
        else { min = Number(min.toPrecision(6)); max = Number(max.toPrecision(6)); }
        const vary = enabled < 2 && !/seed/i.test(s.label);
        if (vary) enabled++;
        this.ranges.set(s.id, {min, max, enabled: vary});
      }
    }
    this.keepRanges = false;
    const known = new Set(specs.map(s => s.id));
    for (const id of this.ranges.keys()) if (!known.has(id)) this.ranges.delete(id);
    const box = document.getElementById("range-controls"); box.replaceChildren();
    for (const s of specs) {
      const range = this.ranges.get(s.id);
      if (!range) continue;
      const fixed = locked.has(s.id), row = element("div", {className: "variation-range"}, box);
      row.dataset.controlId = s.id;
      const label = element("label", {textContent: humanize(s.label)}, row);
      const enabled = element("input", {type: "checkbox", checked: range.enabled && !fixed, disabled: fixed}, label);
      enabled.onchange = () => { range.enabled = enabled.checked; this.bind(project, recipe, locked, ready); };
      if (fixed) element("small", {textContent: "Locked in the editor"}, row);
      const bounds = element("div", {className: "range-bounds"}, row);
      for (const key of ["min", "max"]) {
        const field = element("input", {type: "number", value: range[key], step: s.kind === "int" ? "1" : "any", disabled: fixed || !range.enabled}, bounds);
        field.setAttribute("aria-label", humanize(s.label) + " " + (key === "min" ? "minimum" : "maximum"));
        if (Number.isFinite(s.min)) field.min = s.min;
        if (Number.isFinite(s.max)) field.max = s.max;
        field.oninput = () => { range[key] = field.valueAsNumber; };
        if (key === "min") element("span", {textContent: "to"}, bounds);
      }
    }
    document.getElementById("family-hint").textContent = !project ? "Choose a recipe to explore variations of its controls." :
      !recipe ? "This project has no library recipe. Save it as a personal recipe and open that recipe to vary it." :
      !ready ? "Connect the renderer in Setup & repair to preview variations." : !specs.length ?
      "This recipe has no numeric controls to vary. You can still edit its colors and save a personal recipe." :
      "Choose ranges below. Locked controls stay fixed; each variant keeps the settings you started with.";
    this.buttons();
  }

  buttons() {
    document.getElementById("family").disabled = !this.ready || !this.recipe || !this.ranges.size || this.submitting;
    document.getElementById("family-cancel").disabled = !this.submitting && !this.candidates.some(c => ["queued", "running"].includes(c.state));
    const complete = this.candidates.filter(c => c.state === "complete").length;
    document.getElementById("family-progress").textContent = this.submitting ? "Submitting…" :
      this.candidates.length ? `${complete} / ${this.candidates.length} ready` : "";
  }

  async clear(keepCompleted = false) {
    this.epoch++; this.submitting = false;
    this.keepRanges = keepCompleted;
    const old = this.candidates;
    this.candidates = keepCompleted ? old.filter(c => c.state === "complete") : [];
    if (!keepCompleted) this.context = null;
    this.inspection?.close();
    for (const c of old) if (!this.candidates.includes(c) && c.url) URL.revokeObjectURL(c.url);
    this.draw();
    await Promise.allSettled(old.filter(c => ["queued", "running"].includes(c.state) && c.job)
      .map(c => this.request(`/api/jobs/${c.job.job_id}/cancel`, {})));
  }

  async start(context) {
    const ranges = {};
    for (const [id, value] of this.ranges) if (value.enabled && !this.locked.has(id)) {
      if (!Number.isFinite(value.min) || !Number.isFinite(value.max) || value.min > value.max)
        throw new Error("Each variation needs a valid minimum and maximum.");
      ranges[id] = [value.min, value.max];
    }
    if (!Object.keys(ranges).length) throw new Error("Choose at least one unlocked control under ‘Choose what varies’.");
    const count = Number(document.getElementById("family-count").value), seed = Number(document.getElementById("family-seed").value);
    if (!Number.isInteger(count) || count < 2 || count > 12) throw new Error("Choose between 2 and 12 variants.");
    if (!Number.isInteger(seed) || seed < 0 || seed > 2147483647) throw new Error("Use a whole-number seed from 0 to 2147483647.");
    // Invalidate first, then keep every request and response attached to this epoch.
    const clearing = this.clear(); const epoch = this.epoch;
    this.context = copy(context); this.submitting = true; this.buttons();
    try {
      await clearing;
      if (epoch !== this.epoch) return;
      const result = await this.request("/api/family", {
        recipe_id: context.recipe_id, values: context.values, locked: context.locked,
        ranges, count, seed, build: true, ...context.settings
      });
      if (epoch !== this.epoch) {
        await Promise.allSettled(result.candidates.filter(c => c.job).map(c => this.request(`/api/jobs/${c.job.job_id}/cancel`, {})));
        return;
      }
      this.candidates = result.candidates.map(c => ({...c, state: "queued", result: null, error: null, url: null}));
      this.submitting = false; this.draw();
      await Promise.all(this.candidates.map(c => this.poll(c, epoch)));
    } catch (error) {
      if (epoch === this.epoch) throw error;
    } finally { if (epoch === this.epoch) { this.submitting = false; this.buttons(); } }
  }

  async poll(candidate, epoch) {
    try {
      for (;;) {
        const job = await this.request("/api/jobs/" + candidate.job.job_id);
        if (epoch !== this.epoch) return;
        const changed = candidate.state !== job.state;
        candidate.state = job.state;
        if (job.state === "complete") {
          candidate.result = job.result;
          try {
            const blob = await this.request(`/api/builds/${job.result.build_id}/thumbnail.png`, undefined, true);
            if (epoch !== this.epoch && !this.candidates.includes(candidate)) return;
            candidate.url = URL.createObjectURL(blob);
          } catch (_) { candidate.previewError = true; }
          if (epoch !== this.epoch && !this.candidates.includes(candidate)) return;
          this.draw(); return;
        }
        if (["failed", "cancelled"].includes(job.state)) {
          candidate.error = job.result?.error || (job.state === "cancelled" ? "Cancelled" : "Build failed");
          this.draw(); return;
        }
        if (changed) this.draw();
        await new Promise(resolve => setTimeout(resolve, 600));
        if (epoch !== this.epoch) return;
      }
    } catch (error) {
      await this.request(`/api/jobs/${candidate.job.job_id}/cancel`, {}).catch(() => {});
      if (epoch !== this.epoch) return;
      candidate.state = "failed"; candidate.error = error.message; this.draw();
    }
  }

  async cancel() {
    // Pending submission will cancel every returned job when its late reply arrives.
    if (this.submitting || this.candidates.some(c => c.submitting)) { await this.clear(true); return; }
    await Promise.all(this.candidates.filter(c => ["queued", "running"].includes(c.state))
      .map(c => this.request(`/api/jobs/${c.job.job_id}/cancel`, {})));
  }

  async retry(candidate) {
    const epoch = this.epoch, context = copy(this.context);
    candidate.state = "queued"; candidate.error = null; candidate.submitting = true; this.draw();
    try {
      const job = await this.request("/api/jobs", {recipe_id: context.recipe_id, values: candidate.values, ...context.settings, force: true});
      if (epoch !== this.epoch) { await this.request(`/api/jobs/${job.job_id}/cancel`, {}); return; }
      candidate.job = job; candidate.submitting = false; await this.poll(candidate, epoch);
    } catch (error) {
      if (epoch === this.epoch) { candidate.state = "failed"; candidate.error = error.message; this.draw(); }
    } finally {
      if (epoch === this.epoch) { candidate.submitting = false; this.buttons(); }
    }
  }

  draw() {
    const box = document.getElementById("family-cards"); box.replaceChildren();
    for (const candidate of this.candidates) {
      const card = element("article", {className: "variant-card"}, box);
      card.dataset.state = candidate.state;
      const preview = element("button", {className: "variant-image", disabled: candidate.state !== "complete"}, card);
      preview.setAttribute("aria-label", "Inspect variant " + (candidate.index + 1));
      if (candidate.url) element("img", {src: candidate.url, alt: `Variant ${candidate.index + 1} albedo`}, preview);
      else element("span", {textContent: candidate.previewError ? "Preview unavailable" : humanize(candidate.state)}, preview);
      preview.onclick = () => this.inspect(candidate);
      element("strong", {textContent: "Variant " + (candidate.index + 1)}, card);
      element("small", {className: "variant-status", textContent: candidate.state === "complete" ?
        (candidate.result.manifest.renderer_kind === "injected_test_double" ? "Test build · Albedo" : "Ready · Albedo") : humanize(candidate.state)}, card);
      if (candidate.error) element("p", {className: "hint error", textContent: candidate.error.slice(0, 160), title: candidate.error}, card);
      const actions = element("div", {className: "toolbar"}, card);
      if (candidate.state === "complete") {
        element("button", {className: "use-variant", textContent: "Use variant", onclick: () => this.onUse(candidate, copy(this.context)).catch(this.onError)}, actions);
        element("button", {className: "pin-variant", textContent: "Pin", onclick: () => this.onPin(candidate.result.build_id, this.context.title + " · variant " + (candidate.index + 1))}, actions);
      } else if (["failed", "cancelled"].includes(candidate.state)) {
        element("button", {textContent: "Retry", onclick: () => this.retry(candidate).catch(this.onError)}, actions);
      }
    }
    this.buttons();
  }

  inspect(candidate) {
    this.inspection?.close(); this.inspection?.remove();
    const dialog = element("dialog", {id: "variant-dialog", className: "inspection-dialog"}, document.body);
    this.inspection = dialog;
    dialog.setAttribute("aria-labelledby", "variant-title");
    const heading = element("div", {className: "section-heading"}, dialog);
    element("h2", {id: "variant-title", textContent: "Variant " + (candidate.index + 1)}, heading);
    element("button", {textContent: "Close", onclick: () => dialog.close()}, heading);
    if (candidate.url) element("img", {className: "inspection-image", src: candidate.url, alt: "Completed variant albedo"}, dialog);
    element("p", {className: "hint", textContent: "Albedo preview. Use this variant to inspect it in 3D and edit its controls."}, dialog);
    const list = element("dl", {className: "variant-values"}, dialog);
    const labels = new Map((this.context.controls || []).map(s => [s.id, s.label]));
    for (const [id, value] of Object.entries(candidate.values)) {
      element("dt", {textContent: humanize(labels.get(id) || id)}, list);
      element("dd", {textContent: typeof value === "number" ? String(Number(value.toFixed(5))) :
        typeof value === "boolean" ? (value ? "On" : "Off") : value?.type === "Color" ? colorHex(value) :
        value?.points ? `${value.points.length} color stops` : JSON.stringify(value)}, list);
    }
    const actions = element("div", {className: "toolbar"}, dialog);
    element("button", {className: "primary", textContent: "Use variant", onclick: () => {
      dialog.close(); this.onUse(candidate, copy(this.context)).catch(this.onError);
    }}, actions);
    element("button", {textContent: "Pin for comparison", onclick: () => this.onPin(candidate.result.build_id, this.context.title + " · variant " + (candidate.index + 1))}, actions);
    dialog.showModal();
  }
};
