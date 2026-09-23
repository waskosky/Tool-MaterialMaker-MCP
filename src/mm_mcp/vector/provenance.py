"""Verify the fixed compiler projection before importing its implementation."""
from pathlib import Path
import hashlib
import json
import re
from importlib.metadata import PackageNotFoundError, version
from mm_mcp.core import ServiceError

ROOT = Path(__file__).parent
PROFILE = 'workshop-vector-authoring-v1'


def verify(root=ROOT):
    root = Path(root)
    producer = root / 'producer'
    lock = json.loads((root / 'source-lock.json').read_bytes())
    raw = (producer / 'manifest.json').read_bytes()
    manifest = json.loads(raw)
    if (lock.get('schema') != 'workshop.vector-compiler-lock/v1'
            or lock.get('manifest_sha256') != hashlib.sha256(raw).hexdigest()
            or not re.fullmatch(r'[a-f0-9]{40}', str(lock.get('source_revision', '')))
            or lock.get('source_revision') != manifest.get('source_revision')
            or manifest.get('source_repository') != 'waskosky/rai'
            or manifest.get('source_clean') is not True
            or manifest.get('profile') != PROFILE
            or manifest.get('schema') != 'rai.vector-compiler-export/v1'):
        raise ServiceError('VECTOR_COMPILER_PIN', 'The plant compiler differs from its reviewed source pin.')
    records = manifest.get('files')
    if not isinstance(records, list) or not 1 <= len(records) <= 20:
        raise ServiceError('VECTOR_COMPILER_PIN', 'Invalid compiler inventory.')
    if manifest.get('host_dependencies') != {'pyclipper': '1.4.0'}:
        raise ServiceError('VECTOR_COMPILER_PIN', 'Compiler host dependencies differ from the reviewed contract.')
    try:
        if version('pyclipper') != '1.4.0':
            raise PackageNotFoundError('pyclipper==1.4.0')
    except PackageNotFoundError as exc:
        raise ServiceError('VECTOR_COMPILER_PIN', 'Install the pinned pyclipper==1.4.0 host dependency.') from exc
    actual = set()
    if producer.is_symlink():
        raise ServiceError('VECTOR_COMPILER_PIN', 'Compiler cannot be a symlink.')
    for path in producer.rglob('*'):
        if path.is_symlink():
            raise ServiceError('VECTOR_COMPILER_PIN', 'Compiler cannot contain symlinks.')
        if path.is_file():
            relative = path.relative_to(producer)
            if '__pycache__' in relative.parts and path.suffix == '.pyc':
                continue
            actual.add(relative.as_posix())
    expected = {r['path'] for r in records}
    if len(expected) != len(records) or actual != expected | {'manifest.json'}:
        raise ServiceError('VECTOR_COMPILER_PIN', 'Compiler inventory differs from the reviewed projection.')
    total = 0
    for record in records:
        path = producer / record['path']
        if not path.resolve().is_relative_to(producer.resolve()):
            raise ServiceError('VECTOR_COMPILER_PIN', 'Invalid compiler inventory path.')
        data = path.read_bytes()
        total += len(data)
        if len(data) != record['size'] or hashlib.sha256(data).hexdigest() != record['sha256']:
            raise ServiceError('VECTOR_COMPILER_PIN', 'Compiler bytes differ from the reviewed projection.')
    if hashlib.sha256((producer / 'data/catalog.json').read_bytes()).hexdigest() != lock.get('recipe_catalog_sha256'):
        raise ServiceError('VECTOR_COMPILER_PIN', 'Recipe catalog differs from its independent pin.')
    if total > 512 * 1024:
        raise ServiceError('VECTOR_COMPILER_PIN', 'Compiler exceeds its bound.')
    return lock
