"use strict";
// The local shared service owns graphs and builds; this client tracks selections.
const $ = id => document.getElementById(id);
const entryPath = location.pathname || "/", entrySearch = location.search || "";
const entryBase = entryPath.slice(0, entryPath.lastIndexOf("/") + 1);
const entryProject = new URLSearchParams(entrySearch).get("project");
const incoming = new URLSearchParams(location.hash.slice(1)).get("token");
if (incoming) { sessionStorage.setItem("mm.token", incoming); history.replaceState(null, "", entryPath + entrySearch); }
const token = sessionStorage.getItem("mm.token") || "";
let foundryPath = null;
let current = null, recipeId = null, initialValues = {}, locked = new Set();
let selectedBuild = null, activeJob = null, generation = 0, projectReadEpoch = 0, queue = Promise.resolve();
let searchTimer = null, previewTimer = null, comparisonURL = null, evidenceURLs = [], pinned = [], compareEpoch = 0;
const pinLabels = new Map();
let setupPanel = null, libraryPanel = null, familyPanel = null, setupKey = null;
let defaultPreviewSize = 256;
let catalogAvailable = false, pendingRecipe = null, snapshotReadEpoch = 0, projectListEpoch = 0;
function storedList(key) {
  try { const value = JSON.parse(localStorage.getItem(key) || "[]"); return Array.isArray(value) ? value.filter(v => typeof v === "string") : []; }
  catch (_) { return []; }
}
const favorites = new Set(storedList("mm.favorites"));
function element(tag, props = {}, parent) { const node = document.createElement(tag); Object.assign(node, props); if (parent) parent.appendChild(node); return node; }
function humanize(value) { const text = String(value || "").replace(/[_-]+/g, " "); return text.charAt(0).toUpperCase() + text.slice(1); }
function copy(value) { return JSON.parse(JSON.stringify(value)); }
function controlValues() { return Object.fromEntries((current?.controls || []).map(s => [s.id, copy(s.value)])); }
function freshKey() { return crypto.randomUUID ? crypto.randomUUID() : "request_" + Date.now() + "_" + Math.random().toString(16).slice(2); }
function colorHex(value) { return "#" + [value.r, value.g, value.b].map(n => Math.round(Math.max(0, Math.min(1, n)) * 255).toString(16).padStart(2, "0")).join(""); }
function readHex(text, a = 1) { return {type: "Color", r: parseInt(text.slice(1,3),16)/255, g: parseInt(text.slice(3,5),16)/255, b: parseInt(text.slice(5,7),16)/255, a}; }
function status(message, error = false) {
  const text = String(message); $("status").textContent = text.length > 300 ? text.slice(0, 300) + "…" : text;
  $("status").classList.toggle("error", error); $("status-details").hidden = text.length <= 300;
  $("status-detail-text").textContent = text; $("retry").hidden = true;
}
function apiURL(path) {
  if (!path.startsWith("/api/")) throw new Error("Workshop requests must use its local API.");
  return entryBase + path.slice(1);
}
async function request(path, body, raw = false) {
  const headers = {"X-MM-Token": token};
  if (body !== undefined) headers["Content-Type"] = "application/json";
  const response = await fetch(apiURL(path), {method: body === undefined ? "GET" : "POST", headers,
    body: body === undefined ? undefined : JSON.stringify(body), cache: "no-store"});
  if (!response.ok) {
    let failure; try { failure = await response.json(); } catch (_) { failure = {error: response.statusText}; }
    throw Object.assign(new Error(failure.error || "The local service could not complete this request."), failure);
  }
  const value = raw ? await response.blob() : await response.json();
  if (!raw && value.ok === false) throw Object.assign(new Error(value.error || "Operation failed"), value);
  return value;
}
function action(fn) { return () => Promise.resolve().then(fn).catch(error => status(error.message, true)); }
function foundryURL(build = null) {
  if (!foundryPath) return null;
  return foundryPath + (build ? "?workshop_build=" + encodeURIComponent(build.build_id) : "") + "#token=" + encodeURIComponent(token);
}
function updateCompanionNavigation() {
  $("foundry-link").hidden = !foundryPath;
  $("foundry-link").href = foundryURL() || "";
  $("send-foundry").hidden = !foundryPath || !selectedBuild;
}
function sendToFoundry() {
  if (selectedBuild && foundryPath) location.assign(foundryURL(selectedBuild));
}
function invalidate() {
  // Build-setting changes must not discard an accepted edit's graph refresh.
  generation++; snapshotReadEpoch++; selectedBuild = null; clearTimeout(previewTimer);
  updateCompanionNavigation();
  $("download").disabled = true; $("pin").disabled = true; $("retry").hidden = true;
  $("preview-note").textContent = "Preview needs rebuilding · Drag to orbit";
  $("viewport-shell").classList.toggle("stale", true);
}
async function stopBuild() {
  const job = activeJob; activeJob = null; $("cancel").disabled = true;
  if (job) await request("/api/jobs/" + job + "/cancel", {}).catch(() => {});
}
function clearPreview() {
  if (mesh) { mesh.visible = false; redraw(); }
  $("welcome").hidden = false;
  evidenceURLs.forEach(URL.revokeObjectURL); evidenceURLs = []; $("evidence").replaceChildren();
  $("preview-kind").hidden = true;
}
function schedulePreview() {
  clearTimeout(previewTimer);
  if (current && setupPanel?.ready()) previewTimer = setTimeout(() => build().catch(showBuildError), 350);
}
function showBuildError(error) {
  status(error.message, true); $("retry").hidden = !current;
  setupPanel?.load(false).catch(() => {});
}
async function refreshProject() {
  if (!current) return;
  const id = current.project_id, readEpoch = ++projectReadEpoch;
  let next;
  try { next = await request("/api/projects/" + id); }
  catch (error) { if (current?.project_id !== id || readEpoch !== projectReadEpoch) return; throw error; }
  if (current?.project_id !== id || readEpoch !== projectReadEpoch) return;
  current = next; recipeId = next.recipe_id ?? null; drawControls();
}
function mutateProject(path, fields, message) {
  if (!current) return;
  invalidate(); const pid = current.project_id, epoch = generation, body = copy(fields);
  queue = queue.then(async () => {
    if (current?.project_id !== pid) return;
    const result = await request(path, {...body, project_id: pid, expected_revision: current.revision});
    if (current?.project_id !== pid) return;
    // Reconcile the graph even if build settings changed while this edit ran.
    // Builds wait on this queue; presentation belongs only to its generation.
    current.revision = result.revision; await refreshProject();
    if (epoch !== generation) return;
    status(message); schedulePreview(); projects().catch(() => {});
  }).catch(async error => {
    if (current?.project_id !== pid) return;
    await refreshProject().catch(() => {});
    if (epoch !== generation) return;
    status(error.message + " Shared state has been reloaded; review it before trying again.", true);
  });
  return queue;
}
function setControls(values) {
  return mutateProject("/api/patch", {operations: [{op: "set_controls", values}], idempotency_key: freshKey()},
    "Changes saved. Updating the preview…");
}
function drawControls() {
  $("project-fields").disabled = !catalogAvailable; $("editor-hint").hidden = true;
  $("welcome").hidden = !!mesh?.visible;
  $("welcome").querySelector("h3").textContent = "Your material, ready to explore.";
  $("welcome").querySelector("p").textContent = setupPanel?.ready() ?
    "A preview appears when rendering finishes. Your graph stays editable as you explore." :
    catalogAvailable ? "Connect the renderer to see this material. You can edit and save its controls now." :
    "Connect the Material Maker source to load editable controls and prepare a preview.";
  $("material-name").textContent = current.title; $("preview-title").textContent = current.title;
  $("revision").textContent = `${current.project_id} · revision ${current.revision}`;
  const box = $("sliders"); box.replaceChildren(); let group = null;
  for (const spec of current.controls || []) {
    if (spec.group !== group) { element("h3", {textContent: humanize(spec.group)}, box); group = spec.group; }
    const row = element("div", {className: "control"}, box), title = element("div", {className: "control-title"}, row);
    element("label", {textContent: humanize(spec.label)}, title);
    const lockLabel = element("label", {className: "lock", textContent: "Lock "}, title);
    const lock = element("input", {type: "checkbox", checked: locked.has(spec.id)}, lockLabel);
    lock.setAttribute("aria-label", "Lock " + humanize(spec.label));
    lock.onchange = () => { lock.checked ? locked.add(spec.id) : locked.delete(spec.id); drawControls(); };
    const input = element("div", {className: "input-row"}, row);
    const add = (tag, props = {}, parent = input) => {
      const node = element(tag, {...props, disabled: locked.has(spec.id)}, parent);
      node.setAttribute("aria-label", props.title || humanize(spec.label)); return node;
    };
    let emitted = JSON.stringify(spec.value);
    const apply = value => {
      const next = JSON.stringify(value);
      if (!locked.has(spec.id) && next !== emitted) { emitted = next; setControls({[spec.id]: value}); }
    };
    if (spec.kind === "color") {
      const color = add("input", {type: "color", value: colorHex(spec.value)});
      const alpha = add("input", {type: "number", min: "0", max: "1", step: "0.01", value: spec.value.a, title: humanize(spec.label) + " opacity"});
      color.onchange = alpha.onchange = () => { if (alpha.reportValidity()) apply(readHex(color.value, alpha.valueAsNumber)); };
    } else if (spec.kind === "gradient") {
      input.className = "gradient"; const value = copy(spec.value);
      value.points.forEach((point, index) => {
        const stop = element("div", {className: "gradient-stop"}, input);
        const position = add("input", {type: "number", min: "0", max: "1", step: "0.01", value: point.pos, title: "Stop position"}, stop);
        const color = add("input", {type: "color", value: colorHex(point), title: "Stop color"}, stop);
        const alpha = add("input", {type: "number", min: "0", max: "1", step: "0.01", value: point.a, title: "Stop opacity"}, stop);
        const commit = () => {
          if (!position.reportValidity() || !alpha.reportValidity()) return;
          value.points[index] = {...point, ...readHex(color.value, alpha.valueAsNumber), pos: position.valueAsNumber};
          value.points.sort((a,b) => a.pos-b.pos); apply(value);
        };
        position.onchange = color.onchange = alpha.onchange = commit;
        const remove = add("button", {textContent: "−", title: "Remove stop"}, stop);
        remove.disabled ||= value.points.length <= 2;
        remove.onclick = () => { value.points.splice(index,1); apply(value); };
      });
      const addStop = add("button", {textContent: "Add stop"}); addStop.disabled ||= value.points.length >= 64;
      addStop.onclick = () => { value.points.push({...value.points[0], pos: .5}); value.points.sort((a,b) => a.pos-b.pos); apply(value); };
      const mode = add("select", {title: "Gradient interpolation"});
      // MMGradient.Interpolation in the pinned native source.
      ["Constant", "Linear", "Smoothstep", "Cubic"].forEach((name,i) => mode.add(new Option(name,String(i))));
      if ((value.interpolation ?? 1) > 3) mode.add(new Option("Legacy interpolation " + value.interpolation, String(value.interpolation)));
      mode.value = String(value.interpolation ?? 1); mode.onchange = () => { value.interpolation = Number(mode.value); apply(value); };
    } else if (spec.kind === "bool") {
      const node = add("input", {type: "checkbox", checked: !!spec.value}); node.onchange = () => apply(node.checked);
    } else if (spec.kind === "enum") {
      const node = add("select");
      (spec.options || []).forEach((value,i) => node.add(new Option(typeof value === "object" ? JSON.stringify(value) : String(value),String(i))));
      node.value = String(spec.value); node.onchange = () => apply(Number(node.value));
    } else if (["float", "int"].includes(spec.kind)) {
      const number = add("input", {type: "number", value: spec.value, step: spec.kind === "int" ? "1" : "any", required: true});
      number.onchange = () => { if (number.reportValidity() && Number.isFinite(number.valueAsNumber)) apply(number.valueAsNumber); };
      if (Number.isFinite(spec.min) && Number.isFinite(spec.max) && spec.max > spec.min) {
        const range = add("input", {type: "range", min: spec.min, max: spec.max, step: spec.step ?? (spec.kind === "int" ? 1 : (spec.max-spec.min)/200), value: spec.value});
        range.oninput = () => { number.value = range.value; }; range.onchange = () => apply(Number(range.value));
      }
    } else {
      element("pre", {textContent: JSON.stringify(spec.value,null,2)}, input);
      element("small", {textContent: "This value can be edited through the graph or assistant."}, row);
    }
    const details = element("details", {className: "control-details"}, row);
    element("summary", {textContent: "Control ID"}, details); element("code", {textContent: spec.id}, details);
  }
  $("render").disabled = !setupPanel?.ready();
  familyPanel?.bind(current, recipeId, locked, !!setupPanel?.ready());
}
async function gallery() { await libraryPanel.refresh(); }
async function projects() {
  const epoch = ++projectListEpoch;
  let result;
  try { result = await request("/api/projects"); }
  catch (error) { if (epoch !== projectListEpoch) return; throw error; }
  if (epoch !== projectListEpoch) return;
  const select = $("projects"); select.replaceChildren();
  select.add(new Option("Open a saved project…", ""));
  result.projects.forEach(project => select.add(new Option(project.title + " · r" + project.revision,project.id)));
  select.value = current?.project_id || "";
}
async function snapshots() {
  const id = current?.project_id; if (!id) return;
  const epoch = ++snapshotReadEpoch;
  let result;
  try { result = await request(`/api/projects/${id}/snapshots`); }
  catch (error) { if (current?.project_id !== id || epoch !== snapshotReadEpoch) return; throw error; }
  if (current?.project_id !== id || epoch !== snapshotReadEpoch) return;
  $("snapshot-count").textContent = result.snapshots.length; const list = $("snapshot-list"); list.replaceChildren();
  if (!result.snapshots.length) element("p", {className: "hint", textContent: "Save a named version before exploring a new direction."}, list);
  for (const snapshot of result.snapshots) {
    const row = element("div", {className: "snapshot-row"}, list);
    element("span", {textContent: snapshot.name}, row);
    const restore = element("button", {textContent: "Restore", title: "Restore " + snapshot.name}, row);
    restore.onclick = () => {
      if (current?.project_id !== id) return;
      return mutateProject("/api/restore", {name: snapshot.name}, "Saved version restored. Updating its preview…");
    };
  }
}
async function openRecipe(id, title) {
  projectReadEpoch++; invalidate(); const epoch = generation;
  await Promise.all([stopBuild(), familyPanel.clear()]);
  if (epoch !== generation) return;
  if (!catalogAvailable) {
    pendingRecipe = {id, title};
    status("Connect the Material Maker source in Setup & repair to open this recipe's editable controls.");
    setupPanel.show(); return;
  }
  pendingRecipe = null;
  clearPreview(); status("Opening editable recipe…");
  let next;
  try { next = await request("/api/projects", {recipe_id: id, ...(title ? {title} : {})}); }
  catch (error) { if (epoch !== generation) return; throw error; }
  if (epoch !== generation) return;
  current = next; recipeId = id; locked.clear(); $("size").value = String(defaultPreviewSize);
  await refreshProject(); if (epoch !== generation) return;
  initialValues = controlValues(); await Promise.all([projects(), snapshots()]);
  if (epoch !== generation) return;
  if (setupPanel.ready()) await build();
  else { status("Your editable project is ready. Connect the renderer in Setup & repair for a preview."); setupPanel.show(); }
}
async function openProject(id) {
  pendingRecipe = null; projectReadEpoch++; invalidate(); const epoch = generation;
  await Promise.all([stopBuild(), familyPanel.clear()]); if (epoch !== generation) return;
  clearPreview(); current = {project_id: id}; locked.clear(); await refreshProject();
  if (epoch !== generation) return;
  initialValues = controlValues(); await snapshots();
  if (epoch !== generation) return;
  $("projects").value = id;
  schedulePreview();
}
async function openLinkedProject(epoch) {
  // Setup/library reads can finish after the operator has already chosen a
  // material. The entry link owns only the initial, still-unselected generation.
  if (!entryProject || epoch !== generation || current || pendingRecipe) return;
  if (!/^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$/.test(entryProject) || entryProject.includes(".."))
    throw new Error("The Workshop project link is invalid.");
  await openProject(entryProject);
}
function buildSettings() {
  const settings = {size: Number($("size").value), target: $("target").value, physical_size_m: Number($("physical-size").value)};
  if (!Number.isFinite(settings.physical_size_m) || settings.physical_size_m <= 0 || settings.physical_size_m > 100000)
    throw new Error("Tile size must be greater than zero and no more than 100,000 meters.");
  return settings;
}
async function useVariant(candidate, context) {
  if (!candidate.result) return;
  projectReadEpoch++; invalidate(); const epoch = generation;
  await Promise.all([stopBuild(), familyPanel.clear(true)]); if (epoch !== generation) return;
  clearPreview(); status("Opening variant as an editable material…");
  let next;
  try { next = await request("/api/projects", {recipe_id: context.recipe_id, values: candidate.values, title: context.title + " · variant " + (candidate.index+1)}); }
  catch (error) { if (epoch !== generation) return; throw error; }
  if (epoch !== generation) return;
  current = next; recipeId = context.recipe_id; locked = new Set(context.locked);
  $("size").value = context.settings.size; $("target").value = context.settings.target; $("physical-size").value = context.settings.physical_size_m;
  await refreshProject(); if (epoch !== generation) return;
  initialValues = controlValues(); await Promise.all([projects(), snapshots()]); if (epoch !== generation) return;
  if (current.graph_hash === candidate.graph_hash) {
    await showBuild(candidate.result.manifest, epoch); if (epoch !== generation) return;
    $("welcome").hidden = true;
  }
  // Family jobs belong to a recipe, not this saved project. Keep their images
  // visible, but select only the normal project job's completed immutable build
  // so exports and Foundry carry this project's exact ID and source revision.
  await build();
}
function selectBuild(result) {
  $("welcome").hidden = true;
  selectedBuild = result; $("download").disabled = false; $("pin").disabled = false;
  updateCompanionNavigation();
  $("viewport-shell").classList.toggle("stale", false);
  $("preview-note").textContent = `${result.manifest.resolution}px · ${humanize(result.manifest.target)} · Drag to orbit`;
  $("preview-kind").textContent = result.manifest.renderer_kind === "injected_test_double" ? "Test renderer" : "Completed build";
  $("preview-kind").hidden = false; $("retry").hidden = true;
}
async function build(force = false) {
  const projectId = current?.project_id; await queue;
  if (!current) throw new Error("Choose a recipe or saved project first.");
  if (current.project_id !== projectId) return;
  if (setupPanel && !setupPanel.ready()) { setupPanel.show(); throw new Error("Connect the native renderer before building a preview."); }
  const settings = buildSettings(); invalidate(); const epoch = generation; let job = null;
  try {
    await stopBuild(); if (epoch !== generation) return;
    job = await request("/api/jobs", {project_id: projectId, revision: current.revision, ...settings, ...(force ? {force: true} : {})});
    if (epoch !== generation) { await request("/api/jobs/" + job.job_id + "/cancel", {}).catch(() => {}); return; }
    activeJob = job.job_id; $("cancel").disabled = false; status("Preview queued…");
    while (epoch === generation) {
      const state = await request("/api/jobs/" + job.job_id);
      if (epoch !== generation || activeJob !== job.job_id) return;
      if (state.state === "complete") {
        await showBuild(state.result.manifest, epoch);
        if (epoch !== generation || activeJob !== job.job_id) return;
        selectBuild(state.result); activeJob = null; $("cancel").disabled = true;
        status(state.result.cached ? "Preview ready. Reused your completed build." : "Preview ready. Adjust the controls, explore variations, or download your material.");
        gallery().catch(() => {}); projects().catch(() => {}); setupPanel?.load(false).catch(() => {}); return;
      }
      if (["failed", "cancelled"].includes(state.state)) throw new Error(state.result?.error || humanize(state.state));
      const elapsed = Number.isFinite(state.created) ? Math.max(0, Math.floor(Date.now()/1000-state.created)) + "s" : "";
      status((state.state === "queued" ? "Waiting for the renderer" : "Rendering your material") + (elapsed ? " · " + elapsed : ""));
      await new Promise(resolve => setTimeout(resolve,400));
    }
  } catch (error) {
    if (job) await request("/api/jobs/" + job.job_id + "/cancel", {}).catch(() => {});
    if (epoch !== generation) return;
    if (!job || activeJob === job.job_id) { activeJob = null; $("cancel").disabled = true; }
    throw error;
  }
}
function pinBuild(id, title = current?.title || "Material") {
  if (!pinned.includes(id)) pinned.push(id);
  pinLabels.set(id, title);
  pinned = pinned.slice(-16); compareEpoch++;
  for (const key of pinLabels.keys()) if (!pinned.includes(key)) pinLabels.delete(key);
  $("compare").disabled = !pinned.length; $("compare").textContent = `Compare pins (${pinned.length})`;
  $("comparison").hidden = true;
  status(`${pinned.length} material${pinned.length === 1 ? "" : "s"} pinned. Use Compare pins to see their albedo images together.`);
}
async function comparePins() {
  if (!pinned.length) return;
  const epoch = ++compareEpoch;
  const labels = pinned.map(id => pinLabels.get(id) || "Material");
  const result = await request("/api/compare", {build_ids: [...pinned]});
  const blob = await request("/api/comparisons/" + result.comparison_id + ".png", undefined, true);
  if (epoch !== compareEpoch) return;
  if (comparisonURL) URL.revokeObjectURL(comparisonURL);
  comparisonURL = URL.createObjectURL(blob); $("comparison").src = comparisonURL;
  $("comparison").hidden = false; $("comparison-panel").hidden = false;
  $("comparison-labels").replaceChildren();
  labels.forEach(label => element("li", {textContent: label}, $("comparison-labels")));
  status("Pinned albedo images are ready to compare below the variations.");
}
let renderer,scene,camera,mesh,env,theta=0.6,phi=1.2,distance=3.5,lastDrag=null;
const geometries={};let textures=[];
function redraw(){if(renderer)renderer.render(scene,camera);}
function positionCamera(){if(!camera)return;camera.position.set(distance*Math.sin(phi)*Math.sin(theta),distance*Math.cos(phi),distance*Math.sin(phi)*Math.cos(theta));camera.lookAt(0,0,0);redraw();}
function initViewer() {
  try {
    renderer=new THREE.WebGLRenderer({antialias:true});renderer.setPixelRatio(Math.min(devicePixelRatio,1.5));renderer.outputEncoding=THREE.sRGBEncoding;
    renderer.toneMapping=THREE.ACESFilmicToneMapping;scene=new THREE.Scene();scene.background=new THREE.Color(0x202731);
    camera=new THREE.PerspectiveCamera(42,1,0.05,100);
    geometries.sphere=new THREE.SphereGeometry(1,64,32);geometries.plane=new THREE.PlaneGeometry(2,2,32,32);geometries.cube=new THREE.BoxGeometry(1.5,1.5,1.5);
    Object.values(geometries).forEach(g=>g.setAttribute("uv2",g.attributes.uv.clone()));
    mesh=new THREE.Mesh(geometries.sphere,new THREE.MeshStandardMaterial({color:0xcccccc,roughness:0.7}));mesh.visible=false;scene.add(mesh);
    // Procedural studio environment supplies reflections; no network assets are loaded.
    const room=new THREE.Scene();room.background=new THREE.Color(0x777777);
    for(const [x,y,z,w,h] of [[0,3,0,4,2],[-3,1,0,2,4],[3,1,1,2,3],[0,1,-3,4,2]]) {
      const panel=new THREE.Mesh(new THREE.PlaneGeometry(w,h),new THREE.MeshBasicMaterial({color:0xffffff,side:THREE.DoubleSide}));
      panel.position.set(x,y,z);panel.lookAt(0,0,0);room.add(panel);
    }
    const pmrem=new THREE.PMREMGenerator(renderer);env=pmrem.fromScene(room,0.1);scene.environment=env.texture;pmrem.dispose();
    room.traverse(o=>{if(o.geometry)o.geometry.dispose();if(o.material)o.material.dispose();});
    const key=new THREE.DirectionalLight(0xffffff,2);key.name="key";scene.add(key);
    const fill=new THREE.HemisphereLight(0xddeeff,0x454545,0.5);fill.name="fill";scene.add(fill);
    const host=$("viewport");host.appendChild(renderer.domElement);
    new ResizeObserver(()=>{const w=host.clientWidth,h=host.clientHeight;renderer.setSize(w,h,false);camera.aspect=w/h;camera.updateProjectionMatrix();redraw();}).observe(host);
    host.onpointerdown=e=>{lastDrag=[e.clientX,e.clientY];host.setPointerCapture(e.pointerId);};
    host.onpointerup=()=>{lastDrag=null;};host.onpointercancel=()=>{lastDrag=null;};
    host.onpointermove=e=>{if(!lastDrag)return;theta-=(e.clientX-lastDrag[0])*0.01;phi=Math.max(0.1,Math.min(Math.PI-0.1,phi+(e.clientY-lastDrag[1])*0.01));lastDrag=[e.clientX,e.clientY];positionCamera();};
    host.addEventListener("wheel",e=>{e.preventDefault();distance=Math.max(1.6,Math.min(10,distance+e.deltaY*0.005));positionCamera();},{passive:false});
    lighting();positionCamera();
  } catch(e) {console.warn("Material preview unavailable:",e.message);$("viewport").textContent="3D preview unavailable: "+e.message+". Verified channel images remain available below.";renderer=null;}
}
function lighting() {if(!scene)return;const grazing=$("lighting").value==="grazing",soft=$("lighting").value==="soft";
  scene.getObjectByName("key").position.set(grazing?4:2,grazing?0.2:3,3);scene.getObjectByName("key").intensity=soft?0.7:2;
  scene.getObjectByName("fill").intensity=soft?1:0.35;if(mesh)mesh.material.envMapIntensity=soft?1:0.7;redraw();}
function repeatMaps(){const value=Number($("repeat").value);const repeat=Number.isFinite(value)?Math.max(1,Math.min(32,Math.round(value))):1;$("repeat").value=repeat;for(const t of textures)t.repeat.set(repeat,repeat);redraw();}
async function showBuild(manifest,epoch) {
  const mapNames=manifest.maps.filter(n=>/^material_(albedo|normal|orm|height|heightmap|emission)\.png$/.test(n));
  const entries=await Promise.all(mapNames.map(async name=>({name,blob:await request(`/api/builds/${manifest.build_id}/files/${name}`,undefined,true)})));
  if(epoch!==generation)return;
  evidenceURLs.forEach(URL.revokeObjectURL);evidenceURLs=[];$("evidence").replaceChildren();
  for(const e of entries){const url=URL.createObjectURL(e.blob);e.url=url;evidenceURLs.push(url);
    const f=element("figure",{},$("evidence"));element("img",{src:url,alt:e.name},f);element("figcaption",{textContent:e.name.replace("material_","")},f);}
  if(!mesh||!renderer)return;
  const loaded=await Promise.all(entries.map(e=>new Promise((resolve,reject)=>new THREE.TextureLoader().load(e.url,t=>resolve({...e,texture:t}),undefined,reject))));
  if(epoch!==generation){loaded.forEach(e=>e.texture.dispose());return;}
  textures.forEach(t=>t.dispose());textures=loaded.map(e=>e.texture);mesh.material.dispose();
  const m=new THREE.MeshStandardMaterial({color:0xffffff,metalness:1,roughness:1,side:THREE.DoubleSide});mesh.material=m;
  for(const e of loaded){const t=e.texture;t.wrapS=t.wrapT=THREE.RepeatWrapping;
    t.encoding=/(albedo|emission)\.png$/.test(e.name)?THREE.sRGBEncoding:THREE.LinearEncoding;
    if(e.name==="material_albedo.png")m.map=t;
    if(e.name==="material_normal.png")m.normalMap=t;
    if(e.name==="material_orm.png"){m.aoMap=t;m.roughnessMap=t;m.metalnessMap=t;}
    if(e.name==="material_emission.png"){m.emissiveMap=t;m.emissive.setRGB(1,1,1);}
    if(/material_height(map)?\.png$/.test(e.name)&&$("height-toggle").checked){m.bumpMap=t;m.bumpScale=0.05;m.normalMap=null;}
  }
  if(m.bumpMap)m.normalMap=null; // A normal map otherwise overrides height preview.
  mesh.visible=true;repeatMaps();lighting();m.needsUpdate=true;redraw();
}
$("search").oninput = () => { clearTimeout(searchTimer); searchTimer = setTimeout(action(gallery), 200); };
$("category").onchange = $("favorites-only").onchange = () => libraryPanel.draw();
$("refresh-projects").onclick = action(projects);
$("projects").onchange = action(async () => { if ($("projects").value) await openProject($("projects").value); });
$("render").onclick = () => build().catch(showBuildError);
$("retry").onclick = () => build(true).catch(showBuildError);
$("refresh").onclick = action(async () => {
  const pid = current?.project_id; await queue; if (!pid || current?.project_id !== pid) return;
  invalidate(); const epoch = generation;
  await refreshProject(); if (epoch !== generation) return;
  await snapshots(); if (epoch !== generation) return;
  status("Shared state reloaded."); schedulePreview();
});
$("cancel").onclick = action(async () => { invalidate(); await stopBuild(); status("Preview cancelled. Your edits are saved."); $("retry").hidden = false; });
for (const direction of ["undo", "redo"]) $(direction).onclick = () => mutateProject("/api/history", {direction},
  direction === "undo" ? "Change undone." : "Change restored.");
$("reset").onclick = () => setControls(Object.fromEntries(Object.entries(initialValues).filter(([id]) => !locked.has(id))));
for (const id of ["size", "target", "physical-size"]) $(id).onchange = () => { invalidate(); status("Build settings saved for the next preview."); schedulePreview(); };
$("download").onclick = action(async () => {
  if (!selectedBuild) throw new Error("Build the current state first.");
  const id = selectedBuild.build_id, blob = await request("/api/export?build_id=" + id, undefined, true);
  const url = URL.createObjectURL(blob), anchor = element("a", {href: url, download: id + ".zip"}, document.body);
  anchor.click(); anchor.remove(); setTimeout(() => URL.revokeObjectURL(url), 1000);
});
$("send-foundry").onclick = sendToFoundry;
$("shape").onchange = () => { if (mesh) { mesh.geometry = geometries[$("shape").value]; redraw(); } };
$("lighting").onchange = lighting; $("repeat").onchange = repeatMaps;
$("height-toggle").onchange = action(async () => { if (selectedBuild) await showBuild(selectedBuild.manifest, generation); });
$("pin").onclick = () => { if (selectedBuild) pinBuild(selectedBuild.build_id); };
$("compare").onclick = action(comparePins);
$("clear-pins").onclick = () => {
  pinned = []; pinLabels.clear(); compareEpoch++; $("compare").disabled = true; $("compare").textContent = "Compare pins (0)"; $("comparison-panel").hidden = true;
  if (comparisonURL) { URL.revokeObjectURL(comparisonURL); comparisonURL = null; }
};
$("family").onclick = action(async () => {
  const pid = current?.project_id; await queue;
  if (!pid || current?.project_id !== pid || !recipeId) return;
  await familyPanel.start({project_id: pid, recipe_id: recipeId, title: current.title, controls: current.controls,
    values: controlValues(), locked: [...locked], settings: buildSettings()});
});
$("snapshot").onclick = action(async () => {
  const pid = current?.project_id, name = $("snapshot-name").value.trim(); await queue;
  if (!pid || current?.project_id !== pid) return;
  if (!name) throw new Error("Give this saved version a name.");
  await request("/api/snapshot", {project_id: pid, name});
  if (current?.project_id !== pid) return;
  $("snapshot-name").value = ""; await snapshots(); status("Saved version: " + name);
});
$("save-recipe").onclick = action(async () => {
  const pid = current?.project_id, title = $("recipe-name").value.trim(); await queue;
  if (!pid || current?.project_id !== pid) return;
  if (!title) throw new Error("Give your personal recipe a name.");
  const slug = title.normalize("NFKD").toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_+|_+$/g, "").slice(0, 80) || "material";
  const name = slug + "_" + freshKey().replace(/[^a-z0-9]/gi, "").slice(-8);
  await request("/api/recipes/save", {project_id: pid, name, metadata: {display_name: title, description: "Your saved material, ready to edit again."}});
  await gallery(); status("Personal recipe saved: " + title); $("recipe-name").value = "";
});
(async () => {
  const entryEpoch = generation;
  initViewer();
  try {
    const [capabilities, companion] = await Promise.all([request("/api/capabilities"), request("/api/companion")]);
    foundryPath = companion.foundry_path;
    updateCompanionNavigation();
    catalogAvailable = capabilities.catalog_available;
    const maximum = capabilities.limits.max_resolution;
    defaultPreviewSize = Math.min(256, maximum);
    $("size").replaceChildren();
    [32,64,128,256,512,1024,2048,4096].filter(size => size <= maximum)
      .forEach(size => $("size").add(new Option(String(size), String(size))));
    $("size").value = String(defaultPreviewSize);
    libraryPanel = new window.WorkshopLibrary(request, async (id, title) => {
      try { await openRecipe(id, title); } catch (error) { showBuildError(error); }
    }, favorites, error => status(error.message, true));
    familyPanel = new window.WorkshopVariations(request, useVariant, pinBuild, error => status(error.message, true));
    setupPanel = new window.WorkshopSetup(request, async model => {
      catalogAvailable = !!model.catalog_available;
      $("capabilities").textContent = "Local workspace · " + setupPanel.label();
      $("welcome-setup").hidden = setupPanel.ready();
      $("render").disabled = !setupPanel.ready(); familyPanel.ready = setupPanel.ready(); familyPanel.buttons();
      const key = JSON.stringify([model.settings, catalogAvailable]), changed = setupKey !== null && setupKey !== key;
      const first = setupKey === null; setupKey = key;
      if (first || changed) await gallery();
      if (changed && current) {
        invalidate(); await familyPanel.clear(); familyPanel.boundProject = null;
        await refreshProject();
      }
      if (pendingRecipe && catalogAvailable) {
        const selected = pendingRecipe; pendingRecipe = null; setupPanel.dialog.close();
        openRecipe(selected.id, selected.title).catch(showBuildError);
      }
    });
    $("setup-open").onclick = $("welcome-setup").onclick = () => setupPanel.show();
    $("setup-open").disabled = false;
    await setupPanel.load(); await projects(); await openLinkedProject(entryEpoch);
  } catch (error) { status(error.message, true); }
})();
