"""A bounded index of real completed builds and small verified albedo previews.

This cache never invokes a renderer. Recipe versions come from build provenance,
so a changed cookbook entry cannot inherit an old version's apparent appearance.
"""
from collections import OrderedDict
from contextlib import contextmanager
import io
import itertools
import os
from pathlib import Path
import sqlite3
import threading

from PIL import Image

from mm_mcp.core import ServiceError, digest, identifier, parse_json


class ThumbnailStore:
    DISCOVERY_LIMIT = 256
    CACHE_LIMIT = 128

    def __init__(self, root, builds, project_origin):
        self.path = Path(root) / 'previews.sqlite3'
        self.builds = builds
        self.project_origin = project_origin
        self._lock = threading.RLock()
        self._cache = OrderedDict()
        self._discovered = False
        self._schema_ready = False

    @contextmanager
    def _db(self):
        db = sqlite3.connect(self.path, timeout=5)
        db.row_factory = sqlite3.Row
        try:
            if not self._schema_ready:
                # An unavailable optional index must not prevent service startup.
                with db:
                    db.execute('''CREATE TABLE IF NOT EXISTS previews(
                        build_id TEXT, recipe_id TEXT, recipe_version TEXT, project_id TEXT,
                        graph_hash TEXT, created REAL, renderer_kind TEXT,
                        PRIMARY KEY(build_id, recipe_id, recipe_version))''')
                    db.execute('CREATE INDEX IF NOT EXISTS recipe_previews ON previews(recipe_id,recipe_version,created DESC)')
                    db.execute('CREATE INDEX IF NOT EXISTS project_previews ON previews(project_id,graph_hash,created DESC)')
                    db.execute('CREATE INDEX IF NOT EXISTS recipe_graph_previews ON previews(recipe_id,recipe_version,graph_hash,created DESC)')
                self._schema_ready = True
            with db:
                yield db
        finally:
            db.close()

    def _signature(self, build_id, manifest):
        directory = self.builds.directory(build_id)
        paths = [directory, directory / 'manifest.json']
        paths.extend(directory / entry['name'] for entry in manifest['files'])
        return tuple((stat.st_mode, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns)
                     for stat in (path.lstat() for path in paths))

    def _verified(self, build_id):
        """Reuse verification only while every inventoried artifact is unchanged."""
        cached = self._cache.get(build_id)
        if cached and self._signature(build_id, cached['manifest']) == cached['signature']:
            self._cache.move_to_end(build_id)
            return cached
        manifest = self.builds.get(build_id)
        cached = {'manifest': manifest, 'signature': self._signature(build_id, manifest)}
        self._cache[build_id] = cached
        self._cache.move_to_end(build_id)
        while len(self._cache) > self.CACHE_LIMIT:
            self._cache.popitem(last=False)
        return cached

    def record(self, build_id, *, recipe=None):
        """Index a verified build; recipe is used only to reuse a saved graph."""
        with self._lock:
            manifest = self._verified(build_id)['manifest']
            request = parse_json((self.builds.directory(build_id) / 'request.json').read_bytes())
            origin = request.get('provenance', {})
            project_id = origin.get('project_id')
            if project_id and not origin.get('recipe_id'):
                # Older project builds recorded only project ID and revision.
                origin = {**self.project_origin(project_id), **origin}
            recipe_id = recipe['id'] if recipe else origin.get('recipe_id')
            version = recipe['recipe_version'] if recipe else origin.get('recipe_version')
            if not recipe_id or not version:
                return
            identifier(recipe_id, 'recipe ID')
            with self._db() as db:
                db.execute('INSERT OR IGNORE INTO previews VALUES(?,?,?,?,?,?,?)', (
                    build_id, recipe_id, version, project_id, digest(request['graph']),
                    manifest['created_unix'], manifest.get('renderer_kind', 'unknown'),
                ))

    def discover(self):
        """One bounded compatibility pass per service, never a scan per search."""
        with self._lock:
            if self._discovered:
                return
            self._discovered = True
            with os.scandir(self.builds.root) as entries:
                candidates = [entry.name for entry in itertools.islice(entries, self.DISCOVERY_LIMIT)
                              if entry.name.startswith('b_') and entry.is_dir(follow_symlinks=False)]
            if not candidates:
                return
            with self._db() as db:
                slots = ','.join('?' for _ in candidates)
                known = {row[0] for row in db.execute(
                    f'SELECT DISTINCT build_id FROM previews WHERE build_id IN ({slots})', candidates)}
            for build_id in candidates:
                if build_id in known:
                    continue
                try:
                    self.record(build_id)
                except (ServiceError, OSError, ValueError, KeyError, TypeError):
                    # Interrupted, missing and corrupt historical builds are not previews.
                    continue

    def image(self, build_id):
        identifier(build_id, 'build ID')
        try:
            with self._lock:
                cached = self._verified(build_id)
                if 'png' not in cached:
                    entry = next((item for item in cached['manifest']['files']
                                  if item.get('channel') == 'albedo'), None)
                    if entry is None:
                        raise ServiceError('CHANNEL_MISSING', 'Build has no albedo image.')
                    path = self.builds.directory(build_id) / entry['name']
                    with Image.open(path) as source:
                        if source.format != 'PNG' or source.width * source.height > 4096 * 4096:
                            raise ServiceError('INVALID_IMAGE', 'Invalid albedo preview.')
                        source.load()
                        preview = source.convert('RGBA' if 'A' in source.getbands() else 'RGB')
                        preview = preview.resize((128, 128), Image.Resampling.LANCZOS)
                    output = io.BytesIO()
                    preview.save(output, format='PNG')
                    cached['png'] = output.getvalue()
                return cached['png']
        except (ServiceError, OSError, ValueError, KeyError, TypeError, Image.DecompressionBombError) as exc:
            raise ServiceError('THUMBNAIL_NOT_FOUND', 'No verified albedo preview is available for this build.') from exc

    def for_recipe(self, recipe_id, version):
        self.discover()
        with self._db() as db:
            rows = db.execute('''SELECT build_id,renderer_kind FROM previews
                WHERE recipe_id=? AND recipe_version=? ORDER BY created DESC,build_id DESC LIMIT 8''',
                (recipe_id, version)).fetchall()
        for row in rows:
            try:
                self.image(row['build_id'])
            except ServiceError:
                continue
            return {'build_id': row['build_id'], 'url': f"/api/builds/{row['build_id']}/thumbnail.png",
                    'renderer_kind': row['renderer_kind']}
        return None

    def reuse_project(self, project_id, graph_hash, recipe):
        self.discover()
        origin = self.project_origin(project_id)
        with self._db() as db:
            rows = db.execute('''SELECT DISTINCT build_id,created FROM previews
                WHERE project_id=? AND graph_hash=? ORDER BY created DESC,build_id DESC LIMIT 8''',
                (project_id, graph_hash)).fetchall()
            # Selecting a family candidate creates a new project without another
            # bake. Reuse its exact graph only within the originating recipe version.
            if origin.get('recipe_id') and origin.get('recipe_version'):
                rows += db.execute('''SELECT build_id,created FROM previews
                    WHERE recipe_id=? AND recipe_version=? AND graph_hash=?
                    ORDER BY created DESC,build_id DESC LIMIT 8''',
                    (origin['recipe_id'], origin['recipe_version'], graph_hash)).fetchall()
        for row in rows:
            try:
                self.image(row['build_id'])
                self.record(row['build_id'], recipe=recipe)
                return
            except ServiceError:
                continue
