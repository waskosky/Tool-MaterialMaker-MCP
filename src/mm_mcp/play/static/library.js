"use strict";

// Images come only from authenticated, completed build artifacts.
window.WorkshopLibrary = class WorkshopLibrary {
  constructor(request, onOpen, favorites, onError) {
    Object.assign(this, {request, onOpen, favorites, onError});
    this.models = []; this.requestEpoch = 0; this.drawEpoch = 0;
    this.urls = []; this.blobs = new Map(); this.observer = null;
  }

  async refresh() {
    const epoch = ++this.requestEpoch;
    const query = document.getElementById("search").value;
    let result;
    try { result = await this.request("/api/materials?q=" + encodeURIComponent(query)); }
    catch (error) {
      if (epoch !== this.requestEpoch || query !== document.getElementById("search").value) return;
      throw error;
    }
    if (epoch !== this.requestEpoch || query !== document.getElementById("search").value) return;
    this.models = result.materials;
    if (!query) {
      const select = document.getElementById("category"), selected = select.value;
      select.replaceChildren(new Option("All categories", ""));
      [...new Set(this.models.map(m => m.category))].sort().forEach(category =>
        select.add(new Option(category === "user" ? "Personal recipes" : humanize(category), category)));
      select.value = [...select.options].some(option => option.value === selected) ? selected : "";
    }
    this.draw();
  }

  draw() {
    const epoch = ++this.drawEpoch;
    this.observer?.disconnect(); this.urls.forEach(URL.revokeObjectURL); this.urls = [];
    const box = document.getElementById("gallery"), category = document.getElementById("category").value;
    const favoritesOnly = document.getElementById("favorites-only").checked;
    box.replaceChildren();
    const visible = this.models.filter(m => (!category || m.category === category) && (!favoritesOnly || this.favorites.has(m.id)));
    document.getElementById("recipe-count").textContent = visible.length;
    document.getElementById("gallery-empty").hidden = !!visible.length;
    this.observer = new IntersectionObserver(entries => {
      for (const entry of entries) if (entry.isIntersecting) {
        this.observer.unobserve(entry.target);
        this.thumbnail(entry.target, entry.target.preview, epoch);
      }
    }, {rootMargin: "100px"});
    for (const model of visible) {
      const title = model.display_name || humanize(model.name);
      const card = element("article", {className: "recipe-card"}, box);
      card.dataset.recipeId = model.id;
      const open = element("button", {className: "recipe-open", title: model.description || title}, card);
      open.setAttribute("aria-label", "Open " + title);
      open.onclick = () => this.onOpen(model.id, title).catch(this.onError);
      const preview = element("span", {className: "recipe-image"}, open);
      element("span", {className: "no-preview", textContent: "Preview after first build"}, preview);
      element("span", {className: "recipe-category", textContent: model.category === "user" ? "Personal" : humanize(model.category)}, open);
      element("strong", {textContent: title}, open);
      element("span", {className: "recipe-description", textContent: model.description || "An editable material recipe."}, open);
      const favorite = element("button", {className: "fav", textContent: this.favorites.has(model.id) ? "★" : "☆"}, card);
      favorite.setAttribute("aria-label", "Favorite " + title);
      favorite.setAttribute("aria-pressed", String(this.favorites.has(model.id)));
      favorite.onclick = () => {
        this.favorites.has(model.id) ? this.favorites.delete(model.id) : this.favorites.add(model.id);
        try { localStorage.setItem("mm.favorites", JSON.stringify([...this.favorites])); } catch (_) { /* The current tab still works with storage disabled. */ }
        this.draw();
      };
      if (model.thumbnail) {
        preview.preview = {...model.thumbnail, title};
        this.observer.observe(preview);
      }
    }
  }

  async thumbnail(host, preview, epoch) {
    try {
      let blob = this.blobs.get(preview.build_id);
      if (!blob) {
        blob = await this.request(preview.url, undefined, true);
        this.blobs.set(preview.build_id, blob);
        if (this.blobs.size > 64) this.blobs.delete(this.blobs.keys().next().value);
      }
      if (epoch !== this.drawEpoch) return;
      const url = URL.createObjectURL(blob); this.urls.push(url);
      host.replaceChildren();
      element("img", {src: url, alt: preview.title + ", last built albedo", loading: "lazy"}, host);
      element("span", {className: "preview-label", textContent: preview.renderer_kind === "injected_test_double" ? "Test build" : "Last build"}, host);
    } catch (_) {
      // Deleted/corrupt previews never prevent opening the editable recipe.
      if (epoch === this.drawEpoch) host.querySelector(".no-preview").textContent = "Preview unavailable";
    }
  }
};
