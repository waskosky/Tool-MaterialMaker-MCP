"use strict";
// This adapter never evaluates graph code; all requests use the local shared service.
const $ = id => document.getElementById(id);
const incoming = new URLSearchParams(location.hash.slice(1)).get("token");
if (incoming) { sessionStorage.setItem("mm.token", incoming); history.replaceState(null, "", location.pathname); }
const token = sessionStorage.getItem("mm.token") || "";
let current = null, recipeId = null, initialValues = {}, locked = new Set();
let selectedBuild = null, activeJob = null, generation = 0, queue = Promise.resolve(), timer = null;
let comparisonURL = null, evidenceURLs = [], pinned = [], models = [];
const favorites = new Set(JSON.parse(localStorage.getItem("mm.favorites") || "[]"));
function status(text, error = false) { $("status").textContent = text; $("status").classList.toggle("error", error); }
async function request(path, body, raw = false) {
  const headers = {"X-MM-Token": token};
  if (body !== undefined) headers["Content-Type"] = "application/json";
  const response = await fetch(path, {method: body === undefined ? "GET" : "POST", headers,
    body: body === undefined ? undefined : JSON.stringify(body), cache: "no-store"});
  if (!response.ok) { const err = await response.json(); throw Object.assign(new Error(err.error || response.statusText), err); }
  const value = raw ? await response.blob() : await response.json();
  if (!raw && value.ok === false) throw Object.assign(new Error(value.error || "Operation failed"), value);
  return value;
}
function action(fn) { return () => Promise.resolve().then(fn).catch(e => status(e.message, true)); }
function invalidate() { generation++; selectedBuild = null; $("download").disabled = true; clearTimeout(timer); }
function copy(v) { return JSON.parse(JSON.stringify(v)); }
function controlValues() { return Object.fromEntries((current?.controls || []).map(s => [s.id, copy(s.value)])); }
function freshKey() { return crypto.randomUUID ? crypto.randomUUID() : "request_" + Date.now() + "_" + Math.random().toString(16).slice(2); }
function colorHex(v) { return "#" + [v.r,v.g,v.b].map(x => Math.round(Math.max(0,Math.min(1,x))*255).toString(16).padStart(2,"0")).join(""); }
function readHex(text, a = 1) { return {type:"Color",r:parseInt(text.slice(1,3),16)/255,g:parseInt(text.slice(3,5),16)/255,b:parseInt(text.slice(5,7),16)/255,a}; }
async function refreshProject() {
  if (!current) return;
  const id=current.project_id;
  const next=await request("/api/projects/"+id);
  if (current?.project_id===id) { current=next; drawControls(); }
}
function setControls(values) {
  if (!current) return;
  invalidate(); const pid=current.project_id;
  queue=queue.then(async () => {
    if (current?.project_id!==pid) return;
    const result=await request("/api/patch",{project_id:pid,expected_revision:current.revision,
      operations:[{op:"set_controls",values}],idempotency_key:freshKey()});
    if (current?.project_id!==pid) return;
    current.revision=result.revision;
    await refreshProject();
    timer=setTimeout(() => build().catch(e=>status(e.message,true)),350);
  }).catch(async e => { status(e.message+" Reload shared state before retrying.",true); await refreshProject().catch(()=>{}); });
}
function element(tag, props = {}, parent) { const e=document.createElement(tag);Object.assign(e,props);if(parent)parent.appendChild(e);return e; }
function drawControls() {
  $("material-name").textContent=current.title; $("revision").textContent=`${current.project_id} · revision ${current.revision}`;
  const box=$("sliders");box.replaceChildren();let group=null;
  for (const s of current.controls || []) {
    if (s.group!==group) { element("h2",{textContent:s.group},box);group=s.group; }
    const row=element("div",{className:"control"},box), title=element("div",{className:"control-title"},row);
    element("label",{textContent:s.label},title);
    const lock=element("label",{className:"lock",textContent:" Lock "},title);
    const check=element("input",{type:"checkbox",checked:locked.has(s.id)},lock);
    check.onchange=()=>check.checked?locked.add(s.id):locked.delete(s.id);
    element("code",{textContent:s.id},row);
    const input=element("div",{className:"input-row"},row);
    const apply=v=>{if(!locked.has(s.id))setControls({[s.id]:v});};
    if (s.kind==="color") {
      const c=element("input",{type:"color",value:colorHex(s.value)},input);
      const a=element("input",{type:"number",min:"0",max:"1",step:"0.01",value:s.value.a},input);
      c.onchange=a.onchange=()=>apply(readHex(c.value,Number(a.value)));
    } else if(s.kind==="gradient") {
      input.className="gradient";
      const value=copy(s.value);
      value.points.forEach((point,index)=>{
        const stop=element("div",{className:"gradient-stop"},input);
        const position=element("input",{type:"number",min:"0",max:"1",step:"0.01",value:point.pos,title:"Stop position"},stop);
        const c=element("input",{type:"color",value:colorHex(point)},stop);
        const a=element("input",{type:"number",min:"0",max:"1",step:"0.01",value:point.a,title:"Opacity"},stop);
        const commit=()=>{value.points[index]={...point,...readHex(c.value,Number(a.value)),pos:Number(position.value)};value.points.sort((x,y)=>x.pos-y.pos);apply(value);};
        position.onchange=c.onchange=a.onchange=commit;
        const remove=element("button",{textContent:"−",disabled:value.points.length<=2,title:"Remove stop"},stop);
        remove.onclick=()=>{value.points.splice(index,1);apply(value);};
      });
      element("button",{textContent:"Add stop",onclick:()=>{if(value.points.length<64){value.points.push({...value.points[0],pos:0.5});value.points.sort((a,b)=>a.pos-b.pos);apply(value);}}},input);
      const mode=element("input",{type:"number",min:"0",max:"4",step:"1",value:value.interpolation??1,title:"Native interpolation index"},input);
      mode.onchange=()=>{value.interpolation=Number(mode.value);apply(value);};
    } else if(s.kind==="bool") {
      const e=element("input",{type:"checkbox",checked:!!s.value},input);e.onchange=()=>apply(e.checked);
    } else if(s.kind==="enum") {
      const e=element("select",{},input);
      (s.options||[]).forEach((v,i)=>element("option",{value:String(i),textContent:typeof v==="object"?JSON.stringify(v):String(v)},e));
      e.value=String(s.value);e.onchange=()=>apply(Number(e.value));
    } else if(s.kind==="float"||s.kind==="int") {
      const number=element("input",{type:"number",value:s.value,step:s.step??(s.kind==="int"?1:"any")},input);
      number.onchange=()=>apply(Number(number.value));
      if(Number.isFinite(s.min)&&Number.isFinite(s.max)&&s.max>s.min) {
        const range=element("input",{type:"range",min:s.min,max:s.max,step:s.step??(s.kind==="int"?1:(s.max-s.min)/200),value:s.value},input);
        range.oninput=()=>{number.value=range.value;}; range.onchange=()=>apply(Number(range.value));
      }
    } else {
      element("pre",{textContent:JSON.stringify(s.value,null,2)},input);
      element("small",{textContent:"This control has no supported editor; it remains unchanged."},row);
    }
  }
}
async function gallery() {
  const result=await request("/api/materials?q="+encodeURIComponent($("search").value));models=result.materials;
  const box=$("gallery");box.replaceChildren();
  for(const m of models) {
    const name=m.name||m.recipe_id;if($("favorites-only").checked&&!favorites.has(name))continue;
    const row=element("div",{className:"recipe-row"},box);
    element("button",{textContent:name,title:m.category||"",onclick:action(()=>openRecipe(name))},row);
    element("button",{textContent:favorites.has(name)?"★":"☆",className:"fav",title:"Toggle favorite",onclick:()=>{
      favorites.has(name)?favorites.delete(name):favorites.add(name);localStorage.setItem("mm.favorites",JSON.stringify([...favorites]));gallery().catch(e=>status(e.message,true));}},row);
  }
}
async function openRecipe(name) {
  invalidate();const epoch=generation;
  if(activeJob)await request("/api/jobs/"+activeJob+"/cancel",{}).catch(()=>{});
  if(epoch!==generation)return;
  status("Opening editable recipe…");
  const next=await request("/api/projects",{recipe_id:name});
  if(epoch!==generation)return;
  current=next;recipeId=name;locked.clear();await refreshProject();initialValues=controlValues();
  status("Editable project ready. Build a preview or adjust its controls.");await projects();
}
async function projects() {
  const result=await request("/api/projects");const select=$("projects");select.replaceChildren();
  element("option",{value:"",textContent:"Select a shared project"},select);
  result.projects.forEach(p=>element("option",{value:p.id,textContent:p.title+" · r"+p.revision},select));
  select.value=current?.project_id||"";
}
async function build() {
  const projectId=current?.project_id;
  await queue;if(!current)throw new Error("Open a recipe or shared project first.");
  if(current.project_id!==projectId)return;
  invalidate();const epoch=generation;
  const body={project_id:projectId,revision:current.revision,size:Number($("size").value),
    target:$("target").value,physical_size_m:Number($("physical-size").value)};
  let job=null;
  try {
    if(activeJob)await request("/api/jobs/"+activeJob+"/cancel",{}).catch(()=>{});
    if(epoch!==generation)return;
    job=await request("/api/jobs",body);
    if(epoch!==generation) {
      await request("/api/jobs/"+job.job_id+"/cancel",{}).catch(()=>{});return;
    }
    activeJob=job.job_id;$("cancel").disabled=false;status("Build queued…");
    while(epoch===generation) {
      const state=await request("/api/jobs/"+job.job_id);
      if(epoch!==generation||activeJob!==job.job_id)return;
      if(state.state==="complete") {
        await showBuild(state.result.manifest,epoch);
        if(epoch!==generation||activeJob!==job.job_id)return;
        selectedBuild=state.result;
        $("download").disabled=false;$("cancel").disabled=true;activeJob=null;
        status(selectedBuild.cached?"Preview ready. Reused the saved build.":"Preview ready. Review the material or download its files.");return;
      }
      if(state.state==="failed"||state.state==="cancelled")throw new Error(state.result?.error||state.state);
      status(state.state+" · "+job.job_id);await new Promise(r=>setTimeout(r,400));
    }
  } catch(e) {
    if(epoch!==generation)return;
    if(!job||activeJob===job.job_id){activeJob=null;$("cancel").disabled=true;}
    throw e;
  }
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
    mesh=new THREE.Mesh(geometries.sphere,new THREE.MeshStandardMaterial({color:0xcccccc,roughness:0.7}));scene.add(mesh);
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
function repeatMaps(){for(const t of textures)t.repeat.set(Number($("repeat").value),Number($("repeat").value));redraw();}
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
  repeatMaps();lighting();m.needsUpdate=true;redraw();
}
$("search").oninput=()=>{clearTimeout(timer);timer=setTimeout(action(gallery),200);};
$("favorites-only").onchange=action(gallery);$("refresh-projects").onclick=action(projects);
$("projects").onchange=action(async()=>{if(!$("projects").value)return;invalidate();current={project_id:$("projects").value};recipeId=null;locked.clear();await refreshProject();initialValues=controlValues();});
$("render").onclick=action(build);$("refresh").onclick=action(async()=>{invalidate();await refreshProject();status("Shared project state reloaded.");});
$("cancel").onclick=action(async()=>{invalidate();const epoch=generation,job=activeJob;if(job)await request("/api/jobs/"+job+"/cancel",{});if(epoch!==generation||activeJob!==job)return;activeJob=null;$("cancel").disabled=true;status("Cancellation requested.");});
for(const direction of ["undo","redo"])$(direction).onclick=action(async()=>{await queue;if(!current)return;invalidate();current=await request("/api/history",{project_id:current.project_id,expected_revision:current.revision,direction});drawControls();});
$("reset").onclick=()=>setControls(Object.fromEntries(Object.entries(initialValues).filter(([k])=>!locked.has(k))));
for(const id of ["size","target","physical-size"])$(id).onchange=()=>{invalidate();status("Build settings changed. Build again before downloading.");};
$("download").onclick=action(async()=>{if(!selectedBuild)throw new Error("Build the current state first.");const id=selectedBuild.build_id;
  const blob=await request("/api/export?build_id="+id,undefined,true);const url=URL.createObjectURL(blob);const a=element("a",{href:url,download:id+".zip"},document.body);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),1000);});
$("shape").onchange=()=>{if(mesh){mesh.geometry=geometries[$("shape").value];redraw();}};$("lighting").onchange=lighting;$("repeat").onchange=repeatMaps;
$("height-toggle").onchange=action(async()=>{if(selectedBuild)await showBuild(selectedBuild.manifest,generation);});
$("pin").onclick=()=>{if(selectedBuild&&!pinned.includes(selectedBuild.build_id)){pinned.push(selectedBuild.build_id);pinned=pinned.slice(-16);status(`${pinned.length} builds pinned for channel comparison.`);}};
$("compare").onclick=action(async()=>{if(!pinned.length)throw new Error("Pin a completed build first.");const c=await request("/api/compare",{build_ids:pinned});const blob=await request("/api/comparisons/"+c.comparison_id+".png",undefined,true);
  if(comparisonURL)URL.revokeObjectURL(comparisonURL);comparisonURL=URL.createObjectURL(blob);$("comparison").src=comparisonURL;$("comparison").hidden=false;status(c.warning);});
$("family").onclick=action(async()=>{await queue;if(!recipeId)throw new Error("Open a library recipe to generate a family.");
  const result=await request("/api/family",{recipe_id:recipeId,count:6,seed:Number($("family-seed").value),ranges:JSON.parse($("ranges").value),locked:[...locked],values:controlValues(),build:true,size:Number($("size").value),target:$("target").value});
  $("family-result").textContent=JSON.stringify(result.candidates,null,2);status("Variant jobs submitted. Job IDs and exact parameter values are shown below.");});
$("snapshot").onclick=action(async()=>{await queue;if(!current)return;await request("/api/snapshot",{project_id:current.project_id,name:$("snapshot-name").value});status("Named snapshot saved.");});
$("restore").onclick=action(async()=>{await queue;if(!current)return;invalidate();await request("/api/restore",{project_id:current.project_id,name:$("snapshot-name").value,expected_revision:current.revision});await refreshProject();status("Snapshot restored as a new revision.");});
$("save-recipe").onclick=action(async()=>{await queue;if(!current)return;const result=await request("/api/recipes/save",{project_id:current.project_id,name:$("recipe-name").value});await gallery();status("Personal recipe saved: "+JSON.stringify(result));});
(async()=>{initViewer();try{const caps=await request("/api/capabilities");$("capabilities").textContent=caps.native_render_configured?"Local workspace · native render configured, not yet verified":"Local workspace · "+(caps.render_configuration_error||"Native render not configured");await gallery();await projects();}catch(e){status(e.message,true);}})();
