"""Image verification and immutable artifact inventories."""
import io
from pathlib import Path
import zipfile
from PIL import Image, ImageChops, ImageStat, UnidentifiedImageError
from mm_mcp.core import ServiceError, file_digest, identifier, parse_json

CHANNELS = ('albedo','normal','orm','roughness','metallic','ao','height','emission')
ALIASES = {'heightmap':'height', 'depth':'height', 'rough':'roughness', 'metal':'metallic'}

def channel_name(path):
    stem=Path(path).stem.lower()
    for name in sorted((*CHANNELS,*ALIASES), key=len, reverse=True):
        if stem.endswith('_'+name):
            return ALIASES.get(name,name)
    return None

def verify_images(paths, size=None, required=(), root=None):
    entries=[]; seen=set()
    for path in paths:
        p=Path(path)
        if p.is_symlink():
            raise ServiceError('ARTIFACT_SYMLINK','Artifacts must be regular files, not symlinks.')
        if root is not None and not p.resolve().is_relative_to(Path(root).resolve()):
            raise ServiceError('ARTIFACT_ESCAPE','Renderer returned a file outside the private build directory.')
        if not p.is_file() or p.stat().st_size > 128 * 1024 * 1024:
            raise ServiceError('ARTIFACT_SIZE','Missing or oversized image artifact.')
        try:
            with Image.open(p) as im:
                if im.format != 'PNG':
                    raise ServiceError('IMAGE_FORMAT','Only PNG is certified on the canonical build path.')
                if im.width*im.height > 4096*4096:
                    raise ServiceError('IMAGE_LIMIT','Image exceeds verification pixel budget.')
                if size is not None and im.size != (size,size):
                    raise ServiceError('IMAGE_DIMENSIONS',f'Expected {size}×{size}; got {im.width}×{im.height}.')
                im.verify()
            with Image.open(p) as im:
                im.load(); dims=list(im.size); mode=im.mode
        except (OSError, ValueError, Image.DecompressionBombError) as exc:
            if isinstance(exc, ServiceError):
                raise
            raise ServiceError('INVALID_IMAGE',f'Image cannot be decoded: {p.name}') from exc
        channel=channel_name(p)
        if channel and channel in seen:
            raise ServiceError('DUPLICATE_CHANNEL',f'Multiple outputs for {channel}.')
        if channel:
            seen.add(channel)
        entries.append({'name':p.name,'sha256':file_digest(p),'bytes':p.stat().st_size,
                        'dimensions':dims,'mode':mode,'channel':channel,
                        'color_space':'srgb' if channel in ('albedo','emission') else 'linear'})
    missing=set(required)-seen
    if missing:
        raise ServiceError('MISSING_CHANNELS','Render is incomplete.',missing=sorted(missing))
    if not entries:
        raise ServiceError('NO_IMAGES','No verified images were produced.')
    return entries

def image_metrics(path):
    """Descriptive measurements, not an aesthetic score or unconditional gate."""
    with Image.open(path) as source:
        im=source.convert('RGB'); im.thumbnail((512,512))
    stat=ImageStat.Stat(im)
    w,h=im.size
    horizontal=ImageStat.Stat(ImageChops.difference(im.crop((0,0,1,h)),im.crop((w-1,0,w,h)))).mean
    vertical=ImageStat.Stat(ImageChops.difference(im.crop((0,0,w,1)),im.crop((0,h-1,w,h)))).mean
    return {'mean_rgb':[round(v/255,6) for v in stat.mean],
            'stddev_rgb':[round(v/255,6) for v in stat.stddev],
            'edge_difference':{'horizontal':sum(horizontal)/(3*255),'vertical':sum(vertical)/(3*255)},
            'notes':'Edge differences are screening signals. Flat maps and nonzero edge differences may be intentional.'}

def contact_sheet(paths, dest, labels=None, thumb=192):
    if not 1 <= len(paths) <= 32:
        raise ServiceError('SHEET_LIMIT','A contact sheet accepts 1–32 verified images.')
    from PIL import ImageDraw
    columns=min(4,len(paths)); rows=(len(paths)+columns-1)//columns
    sheet=Image.new('RGB',(columns*thumb,rows*(thumb+28)),(28,30,34)); draw=ImageDraw.Draw(sheet)
    for i,path in enumerate(paths):
        with Image.open(path) as src:
            im=src.convert('RGB'); im.thumbnail((thumb,thumb))
        x=(i%columns)*thumb; y=(i//columns)*(thumb+28)
        sheet.paste(im,(x,y)); draw.text((x+4,y+thumb+5),(labels[i] if labels else Path(path).stem)[:30],fill='white')
    sheet.save(dest)
    return str(dest)

def verify_manifest(directory):
    directory=Path(directory)
    if directory.is_symlink():
        raise ServiceError('ARTIFACT_SYMLINK','Build directory must not be a symlink.')
    manifest_path=directory/'manifest.json'
    if manifest_path.is_symlink():
        raise ServiceError('ARTIFACT_SYMLINK','Manifest must not be a symlink.')
    manifest=parse_json(manifest_path.read_bytes())
    if not isinstance(manifest,dict) or manifest.get('status') != 'complete':
        raise ServiceError('BUILD_INCOMPLETE','Build is not complete.')
    if manifest.get('build_id') != directory.name or manifest.get('schema_version') != 1:
        raise ServiceError('ARTIFACT_CORRUPT','Manifest identity or schema does not match the build.')
    files=manifest.get('files')
    if not isinstance(files,list) or not 1 <= len(files) <= 128:
        raise ServiceError('ARTIFACT_CORRUPT','Invalid artifact inventory.')
    seen=set()
    for item in files:
        if not isinstance(item,dict):
            raise ServiceError('ARTIFACT_CORRUPT','Artifact entry must be an object.')
        name=identifier(item.get('name'),'artifact filename'); p=directory/name
        if name in seen or name=='manifest.json':
            raise ServiceError('ARTIFACT_CORRUPT','Duplicate or reserved inventory filename.')
        seen.add(name)
        if p.is_symlink() or not p.is_file() or p.stat().st_size != item.get('bytes') or file_digest(p)!=item.get('sha256'):
            raise ServiceError('ARTIFACT_CORRUPT',f'Artifact verification failed: {name}')
    if not {'material.ptex','request.json','target.json','quality.json'} <= seen:
        raise ServiceError('ARTIFACT_CORRUPT','Build is missing its required source or contracts.')
    return manifest

def zip_build(directory):
    directory=Path(directory); manifest=verify_manifest(directory)
    buf=io.BytesIO()
    with zipfile.ZipFile(buf,'w',zipfile.ZIP_DEFLATED) as z:
        for name in sorted([f['name'] for f in manifest['files']]+['manifest.json']):
            # Fixed timestamps make the archive deterministic for a completed build.
            info=zipfile.ZipInfo(name, date_time=(2020,1,1,0,0,0)); info.compress_type=zipfile.ZIP_DEFLATED
            info.external_attr=0o644 << 16
            z.writestr(info,(directory/name).read_bytes())
    return buf.getvalue()
