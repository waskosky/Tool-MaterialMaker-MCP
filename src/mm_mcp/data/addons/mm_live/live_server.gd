extends Node
## Authenticated, bounded native bridge. Full graph replacements are prepared
## off to the side and compared against the active revision immediately before
## publication. Recovery files are written before any native mutation.
## Experimental writes require MM_ENABLE_EXPERIMENTAL_LIVE_WRITES=1.

const LIVE_PORT := 8765
const PROTOCOL := "mm-live/2"
const MAX_BYTES := 8 * 1024 * 1024
const MAX_CONNECTIONS := 16
var _server := TCPServer.new()
var _connections: Array = []
var _token := ""
var _instance := ""
var _runtime := ""
var _output_root := ""
var _read_roots: Array = []
var _busy := false
var _writes := false
var _receipts: Dictionary = {}
var _undo: Array = []
var _redo: Array = []

func _ready() -> void:
	_token = OS.get_environment("MM_LIVE_TOKEN")
	if _token.length() < 32:
		_token = Crypto.new().generate_random_bytes(32).hex_encode()
	_instance = Crypto.new().generate_random_bytes(16).hex_encode()
	_runtime = OS.get_environment("MM_RUNTIME_DIR")
	if _runtime.is_empty():
		var home := OS.get_environment("USERPROFILE") if OS.get_name() == "Windows" else OS.get_environment("HOME")
		_runtime = home.path_join(".mm-mcp")
	DirAccess.make_dir_recursive_absolute(_runtime)
	if OS.get_name() != "Windows":
		FileAccess.set_unix_permissions(_runtime, 0x1c0)
	_output_root = OS.get_environment("MM_LIVE_OUTPUT_ROOT")
	if _output_root.is_empty():
		_output_root = _runtime.path_join("exports")
	_output_root = _output_root.simplify_path().replace("\\", "/")
	DirAccess.make_dir_recursive_absolute(_output_root)
	var roots = JSON.parse_string(OS.get_environment("MM_ALLOWED_ROOTS"))
	_read_roots = roots if roots is Array else [_output_root]
	_read_roots.append(ProjectSettings.globalize_path("res://").trim_suffix("/"))
	_writes = OS.get_environment("MM_ENABLE_EXPERIMENTAL_LIVE_WRITES") == "1"
	var error := _server.listen(LIVE_PORT, "127.0.0.1")
	if error != OK:
		push_error("mm_live cannot bind loopback port %d: %d" % [LIVE_PORT, error])
		return
	_write_json(_runtime.path_join("live.json"), {"protocol": PROTOCOL, "instance_id": _instance,
		"host": "127.0.0.1", "port": LIVE_PORT, "token": _token, "pid": OS.get_process_id()})

func _exit_tree() -> void:
	_server.stop()
	var path := _runtime.path_join("live.json")
	if FileAccess.file_exists(path):
		var record = JSON.parse_string(FileAccess.get_file_as_string(path))
		if record is Dictionary and record.get("instance_id") == _instance:
			DirAccess.remove_absolute(path)

func _write_json(path: String, value) -> bool:
	var temp := path + ".tmp"
	var file := FileAccess.open(temp, FileAccess.WRITE)
	if file == null:
		return false
	file.store_string(JSON.stringify(value))
	file.flush()
	file.close()
	if OS.get_name() != "Windows":
		FileAccess.set_unix_permissions(temp, 0x180)
	return DirAccess.rename_absolute(temp, path) == OK

func _process(_delta: float) -> void:
	while _server.is_connection_available():
		var peer := _server.take_connection()
		if _connections.size() >= MAX_CONNECTIONS:
			peer.disconnect_from_host()
		else:
			_connections.append({"peer": peer, "buf": PackedByteArray(), "started": Time.get_ticks_msec()})
	for i in range(_connections.size() - 1, -1, -1):
		var entry: Dictionary = _connections[i]
		var peer: StreamPeerTCP = entry.peer
		peer.poll()
		if peer.get_status() != StreamPeerTCP.STATUS_CONNECTED or Time.get_ticks_msec() - entry.started > 10000:
			peer.disconnect_from_host()
			_connections.remove_at(i)
			continue
		var available := peer.get_available_bytes()
		if available + entry.buf.size() > MAX_BYTES:
			peer.disconnect_from_host()
			_connections.remove_at(i)
			continue
		if available > 0:
			var chunk := peer.get_partial_data(available)
			if chunk[0] == OK:
				entry.buf.append_array(chunk[1])
		var newline: int = entry.buf.find(10)
		if newline >= 0:
			var line: String = entry.buf.slice(0, newline).get_string_from_utf8()
			_connections.remove_at(i)
			_dispatch(peer, line)

func _error(code: String, message: String) -> Dictionary:
	return {"ok": false, "code": code, "error": message}

func _graph_edit():
	if mm_globals.main_window == null:
		return null
	return mm_globals.main_window.get_current_graph_edit()

func _snapshot() -> Dictionary:
	var edit = _graph_edit()
	if edit == null or edit.top_generator == null:
		return _error("NO_GRAPH", "No active material graph.")
	var graph: Dictionary = edit.top_generator.serialize()
	var project := str(edit.get_instance_id())
	var revision := _instance + ":" + project + ":" + JSON.stringify(graph).sha256_text()
	return {"ok": true, "graph": graph, "project_id": project, "revision": revision, "instance_id": _instance}

func _dispatch(peer: StreamPeerTCP, line: String) -> void:
	var request = JSON.parse_string(line)
	var result: Dictionary
	if not request is Dictionary or typeof(request.get("cmd")) != TYPE_STRING:
		result = _error("BAD_REQUEST", "Expected a command object.")
	elif request.get("token", "") != _token or request.get("protocol", "") != PROTOCOL:
		result = _error("AUTH_REQUIRED", "Authenticated mm-live/2 client required.")
	elif _busy and request.cmd != "ping":
		result = _error("BUSY", "A native transaction or export is active.")
	else:
		match request.cmd:
			"ping":
				var snap := _snapshot()
				result = {"ok": true, "ready": mm_globals.main_window != null, "has_graph": snap.ok,
					"protocol": PROTOCOL, "instance_id": _instance, "busy": _busy,
					"features": {"read": true, "replace_transaction": _writes, "bridge_undo": _writes,
						"native_global_undo": false, "render": true, "arbitrary_legacy_writes": false},
					"godot_version": Engine.get_version_info().string, "max_resolution": 2048}
			"get_graph":
				result = _snapshot()
			"replace_graph":
				_busy = true
				result = await _replace(request)
				_busy = false
			"undo", "redo":
				_busy = true
				result = await _history(request)
				_busy = false
			"transaction_status":
				var key := str(request.get("idempotency_key", ""))
				result = _receipts.get(key, _error("RECEIPT_NOT_FOUND", "No completed receipt in this native session."))
				if result.get("ok", false) and result.get("client_request_hash", "") != request.get("client_request_hash", ""):
					result = _error("IDEMPOTENCY_CONFLICT", "Key reused with different client intent.")
			"render":
				_busy = true
				result = await _render(request)
				_busy = false
			_:
				result = _error("UNSUPPORTED_COMMAND", "Use validated replace_graph transactions; legacy unguarded writes are disabled.")
	peer.put_data((JSON.stringify(result) + "\n").to_utf8_buffer())

func _structural_check(graph: Dictionary, depth: int = 0, budget: Array = [0]) -> bool:
	if depth > 24 or not graph.get("nodes", []) is Array or not graph.get("connections", []) is Array:
		return false
	if graph.get("connections", []).size() > 65536:
		return false
	var names: Dictionary = {}
	for node in graph.get("nodes", []):
		budget[0] += 1
		if budget[0] > 4096 or not node is Dictionary:
			return false
		var name = node.get("name")
		if not name is String or name.is_empty() or "/" in name or "\\" in name or names.has(name):
			return false
		names[name] = true
		if node.get("type") == "graph" and not _structural_check(node, depth + 1, budget):
			return false
	for edge in graph.get("connections", []):
		if not edge is Dictionary or not names.has(edge.get("from")) or not names.has(edge.get("to")):
			return false
		for port in [edge.get("from_port", 0), edge.get("to_port", 0)]:
			if typeof(port) not in [TYPE_INT, TYPE_FLOAT] or port < 0 or port != floor(port):
				return false
	return true

func _shader_hashes(value, hashes: Dictionary) -> void:
	if value is Dictionary:
		if value.has("shader_model"):
			hashes[JSON.stringify(value.shader_model).sha256_text()] = true
		for child in value.values():
			_shader_hashes(child, hashes)
	elif value is Array:
		for child in value:
			_shader_hashes(child, hashes)

func _replace(request: Dictionary, record_history: bool = true) -> Dictionary:
	if not _writes:
		return _error("WRITES_DISABLED", "Operator must enable MM_ENABLE_EXPERIMENTAL_LIVE_WRITES after native acceptance testing.")
	var key := str(request.get("idempotency_key", ""))
	if key.length() < 8 or key.length() > 128:
		return _error("KEY_REQUIRED", "An 8–128 character idempotency key is required.")
	var request_hash := JSON.stringify({"data": request.get("data"), "revision": request.get("expected_revision"), "dry_run": request.get("dry_run", false)}).sha256_text()
	if _receipts.has(key):
		var prior: Dictionary = _receipts[key]
		return prior if prior.get("request_hash") == request_hash else _error("IDEMPOTENCY_CONFLICT", "Key reused with different arguments.")
	var before := _snapshot()
	if not before.ok:
		return before
	if request.get("expected_revision", "") != before.revision:
		return _error("REVISION_CONFLICT", "Active graph or tab changed; inspect before editing.")
	var text = request.get("data")
	if not text is String or text.length() > MAX_BYTES:
		return _error("GRAPH_LIMIT", "A bounded serialized graph is required.")
	var decoded = JSON.parse_string(text)
	if not decoded is Dictionary or not _structural_check(decoded, 0, [0]):
		return _error("INVALID_GRAPH", "Graph structure is invalid or exceeds limits.")
	if not _references_allowed(decoded):
		return _error("ASSET_PATH_DENIED", "Explicit asset references must stay within approved native roots.")
	var old_shaders: Dictionary = {}
	var new_shaders: Dictionary = {}
	_shader_hashes(before.graph, old_shaders)
	_shader_hashes(decoded, new_shaders)
	if OS.get_environment("MM_ALLOW_CUSTOM_SHADERS") != "1":
		for hash_value in new_shaders:
			if not old_shaders.has(hash_value):
				return _error("CUSTOM_SHADER_DISABLED", "New inline shader definitions require operator permission.")
	var recovery := _runtime.path_join("recovery_" + _instance + "_" + key.sha256_text() + ".json")
	if not _write_json(recovery, before):
		return _error("RECOVERY_WRITE_FAILED", "Cannot persist recovery snapshot; graph was not changed.")
	var edit = _graph_edit()
	var data: Dictionary = mm_loader.string_to_dict_tree(text)
	var candidate = await mm_loader.create_gen(data)
	if candidate == null:
		return _error("NATIVE_BUILD_FAILED", "Material Maker rejected the candidate; original graph retained.")
	var current := _snapshot()
	if not current.ok or current.revision != before.revision or _graph_edit() != edit:
		candidate.free()
		return _error("REVISION_CONFLICT", "A person changed the graph while the candidate was prepared.")
	if request.get("dry_run", false):
		candidate.free()
		return {"ok": true, "status": "planned", "revision": before.revision, "recovery": recovery}
	# set_new_generator is the same native installation path used by Material Maker
	# loading. The old graph remains authoritative until candidate creation completes.
	edit.set_new_generator(candidate)
	var after := _snapshot()
	if not after.ok:
		var restored = await mm_loader.create_gen(mm_loader.string_to_dict_tree(JSON.stringify(before.graph)))
		if restored != null:
			edit.set_new_generator(restored)
			return _error("COMMIT_FAILED", "Candidate installation failed; original graph restored from snapshot.")
		return _error("ROLLBACK_FAILED", "Cannot restore natively; use the persisted recovery JSON before further edits.")
	edit.set_need_save(true)
	if record_history:
		_undo.append({"project_id": before.project_id, "before": before.graph, "after": after.graph})
		if _undo.size() > 64:
			_undo.pop_front()
		_redo.clear()
	var result := {"ok": true, "status": "committed", "revision": after.revision,
		"project_id": after.project_id, "recovery": recovery, "request_hash": request_hash,
		"native_global_undo": false, "bridge_undo": true, "client_request_hash": request.get("client_request_hash", "")}
	_receipts[key] = result
	if _receipts.size() > 1024:
		_receipts.erase(_receipts.keys()[0])
	_write_json(_runtime.path_join("receipt_" + _instance + "_" + key.sha256_text() + ".json"), result)
	return result

func _history(request: Dictionary) -> Dictionary:
	var key := str(request.get("idempotency_key", ""))
	if _receipts.has(key):
		var receipt: Dictionary = _receipts[key]
		return receipt if receipt.get("client_request_hash", "") == request.get("client_request_hash", "") else _error("IDEMPOTENCY_CONFLICT", "Key reused with different history intent.")
	var is_undo: bool = request.cmd == "undo"
	var stack: Array = _undo if is_undo else _redo
	if stack.is_empty():
		return _error("HISTORY_EMPTY", "No bridge history for this operation.")
	var entry: Dictionary = stack.back()
	var current := _snapshot()
	if not current.ok or current.project_id != entry.project_id:
		return _error("PROJECT_CONFLICT", "History belongs to another native tab.")
	var expected_graph: Dictionary = entry.after if is_undo else entry.before
	if JSON.stringify(current.graph) != JSON.stringify(expected_graph):
		return _error("HISTORY_DIVERGED", "Manual edits diverged from bridge history. Save them or restore a named snapshot explicitly.")
	var command := request.duplicate(true)
	command.data = JSON.stringify(entry.before if is_undo else entry.after)
	var result := await _replace(command, false)
	if result.ok:
		stack.pop_back()
		if is_undo:
			_redo.append(entry)
		else:
			_undo.append(entry)
	return result

func _render(request: Dictionary) -> Dictionary:
	var before := _snapshot()
	if not before.ok:
		return before
	if request.get("expected_revision", "") != before.revision:
		return _error("REVISION_CONFLICT", "Render requires the current native revision.")
	var prefix := str(request.get("prefix", "")).simplify_path().replace("\\", "/")
	if not prefix.begins_with(_output_root + "/") or not prefix.get_file().is_valid_filename() or not _no_link_parents(prefix):
		return _error("PATH_DENIED", "Live exports must stay inside MM_LIVE_OUTPUT_ROOT.")
	var raw_size = request.get("size", 512)
	if typeof(raw_size) not in [TYPE_INT, TYPE_FLOAT] or raw_size != floor(raw_size):
		return _error("RESOLUTION", "Pixel size must be an integer.")
	var size := int(raw_size)
	if size < 32 or size > 2048 or (size & (size - 1)) != 0:
		return _error("RESOLUTION", "Use a power-of-two size between 32 and 2048.")
	if request.get("profile", "Godot/Godot 4 Standard") != "Godot/Godot 4 Standard":
		return _error("PROFILE", "Only the canonical Godot profile is allowed on this bridge.")
	var edit = _graph_edit()
	var material_node = edit.get_material_node()
	if material_node == null:
		return _error("NO_MATERIAL", "No material output in the active graph.")
	await material_node.export_material(prefix, "Godot/Godot 4 Standard", size, true)
	var after := _snapshot()
	if not after.ok or after.revision != before.revision:
		return _error("REVISION_CONFLICT", "Graph changed during rendering; outputs must not be published.")
	return {"ok": true, "revision": before.revision, "size": size, "verification": "client_must_decode_outputs"}

func _no_link_parents(path: String) -> bool:
	var cursor := path
	while cursor != cursor.get_base_dir() and not cursor.is_empty():
		var directory := DirAccess.open(cursor.get_base_dir())
		if directory != null and directory.is_link(cursor.get_file()):
			return false
		cursor = cursor.get_base_dir()
	return true

func _allowed_asset(path: String) -> bool:
	var absolute := ProjectSettings.globalize_path(path) if path.begins_with("res://") else path
	absolute = absolute.simplify_path().replace("\\", "/")
	if not absolute.is_absolute_path():
		return false
	for root in _read_roots:
		var base := str(root).simplify_path().replace("\\", "/").trim_suffix("/")
		if absolute.begins_with(base + "/"):
			# res:// dependencies belong to the trusted application checkout. Explicit
			# external assets do not follow symlinks into otherwise unapproved roots.
			return path.begins_with("res://") or _no_link_parents(absolute)
	return false

func _references_allowed(value, depth: int = 0) -> bool:
	if depth > 96:
		return false
	if value is Dictionary:
		for key in value:
			if key == "shader_model":
				continue # Whole definitions are checked by _shader_hashes before execution.
			var child = value[key]
			if key in ["image", "image_path", "file_name", "filename", "file_path", "path", "texture_path", "model_path"] and child is String and not child.is_empty():
				if "/" in child or "\\" in child or child.get_extension().to_lower() in ["png", "jpg", "jpeg", "exr", "hdr", "tga", "svg", "webp", "obj", "glb", "gltf"]:
					if not _allowed_asset(child):
						return false
			if not _references_allowed(child, depth + 1):
				return false
	elif value is Array:
		for child in value:
			if not _references_allowed(child, depth + 1):
				return false
	return true
