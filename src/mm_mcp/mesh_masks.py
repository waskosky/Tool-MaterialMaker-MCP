"""Bounded CPU baking of triangle-OBJ coverage, height and upward-facing masks.

This is an explicit, small mesh-context backend: no ambient occlusion, curvature,
physics, topology repair, polygon triangulation, or automatic UV unwrapping.
OBJ faces must already be triangles and have a unique zero-to-one UV layout.
"""
from __future__ import annotations
import math
from pathlib import Path
import shutil
import tempfile
import os
from PIL import Image
from mm_mcp.core import ServiceError, atomic_json, digest, file_digest, file_lock, finite, resolution, identifier, parse_json
from mm_mcp.paths import ensure_within_roots,PathNotAllowed


def _index(text, size):
    index=int(text)
    if index==0:raise ValueError('OBJ indices start at one, not zero.')
    result=index-1 if index>0 else size+index
    if not 0<=result<size:raise ValueError('OBJ index is outside the defined array.')
    return result


def parse_obj(text: str):
    vertices=[];uvs=[];triangles=[]
    if len(text.encode())>16*1024*1024:raise ServiceError('MESH_LIMIT','OBJ input exceeds 16 MiB.')
    for line_no,line in enumerate(text.splitlines(),1):
        if len(line)>8192:raise ServiceError('MESH_LIMIT','OBJ line exceeds the parser limit.')
        parts=line.partition('#')[0].split()
        if not parts:continue
        try:
            if parts[0]=='v':
                if len(parts)!=4:raise ValueError('Use three Cartesian vertex coordinates; extended vertex formats are not supported.')
                point=tuple(float(v) for v in parts[1:4])
                if not all(finite(v) and abs(v)<=1e8 for v in point):raise ValueError('Invalid vertex coordinate.')
                vertices.append(point)
            elif parts[0]=='vt':
                if len(parts) not in (3,4):raise ValueError('Texture coordinates require u and v.')
                uv=tuple(float(v) for v in parts[1:3])
                if not all(finite(v) and 0<=v<=1 for v in uv):raise ValueError('Use an unwrapped zero-to-one UV layout.')
                uvs.append(uv)
            elif parts[0]=='f':
                if len(parts)!=4:raise ValueError('Triangulate faces before baking.')
                face=[]
                for token in parts[1:]:
                    fields=token.split('/')
                    if len(fields)<2 or not fields[1]:raise ValueError('Every face corner requires a texture-coordinate index.')
                    face.append((_index(fields[0],len(vertices)),_index(fields[1],len(uvs))))
                triangles.append(face)
            # vn/group/material statements do not trigger filesystem access.
            if max(len(vertices),len(uvs),len(triangles))>100000:
                raise ValueError('Mesh array limit exceeded.')
        except (ValueError,IndexError) as exc:
            raise ServiceError('OBJ_FORMAT',f'OBJ line {line_no}: {exc}') from exc
    if not vertices or not triangles:raise ServiceError('OBJ_EMPTY','The OBJ contains no usable triangles.')
    return vertices,uvs,triangles


def bake_arrays(vertices,uvs,triangles,size=256,up_axis='y',max_raster_work=8_000_000):
    resolution(size,512)
    if up_axis not in ('x','y','z'):raise ServiceError('UP_AXIS','Choose x, y or z explicitly.')
    axis='xyz'.index(up_axis);low=min(v[axis] for v in vertices);high=max(v[axis] for v in vertices)
    height=bytearray(size*size);upward=bytearray(size*size);coverage=bytearray(size*size)
    overlaps=0;degenerate=0;work=0
    for face in triangles:
        xyz=[vertices[a] for a,_ in face];uv=[(uvs[b][0]*size,(1-uvs[b][1])*size) for _,b in face]
        (ax,ay),(bx,by),(cx,cy)=uv
        denominator=(by-cy)*(ax-cx)+(cx-bx)*(ay-cy)
        e1=[xyz[1][i]-xyz[0][i] for i in range(3)];e2=[xyz[2][i]-xyz[0][i] for i in range(3)]
        normal=[e1[1]*e2[2]-e1[2]*e2[1],e1[2]*e2[0]-e1[0]*e2[2],e1[0]*e2[1]-e1[1]*e2[0]]
        length=math.sqrt(sum(n*n for n in normal))
        if abs(denominator)<1e-12 or length<1e-12:degenerate+=1;continue
        facing=round(255*max(0,normal[axis]/length))
        x0=max(0,math.floor(min(v[0] for v in uv)));x1=min(size,math.ceil(max(v[0] for v in uv)))
        y0=max(0,math.floor(min(v[1] for v in uv)));y1=min(size,math.ceil(max(v[1] for v in uv)))
        work+=(x1-x0)*(y1-y0)
        if work>max_raster_work:raise ServiceError('RASTER_BUDGET','Mesh exceeds the CPU raster budget; reduce resolution or simplify the mesh.')
        for y in range(y0,y1):
            for x in range(x0,x1):
                px,py=x+.5,y+.5
                w0=((by-cy)*(px-cx)+(cx-bx)*(py-cy))/denominator
                w1=((cy-ay)*(px-cx)+(ax-cx)*(py-cy))/denominator
                w2=1-w0-w1
                if min(w0,w1,w2)<-1e-9:continue
                index=y*size+x
                if coverage[index]:
                    # A shared triangle edge is benign. True overlapping interiors
                    # are refused so no last-triangle-wins ambiguity enters a mask.
                    if min(w0,w1,w2)>1e-8:overlaps+=1
                    continue
                h=sum(w*v[axis] for w,v in zip((w0,w1,w2),xyz))
                height[index]=min(255,max(0,round(255*(h-low)/(high-low)))) if high>low else 0
                upward[index]=facing;coverage[index]=255
    if overlaps:raise ServiceError('UV_OVERLAP','UV triangle interiors overlap; provide a unique layout.',overlap_samples=overlaps)
    if not any(coverage):raise ServiceError('NO_COVERAGE','No triangles cover pixel centers at the requested resolution.')
    return {'coverage':coverage,'height':height,'upward':upward}, {'degenerate_triangles':degenerate,'raster_work':work,'height_bounds':[low,high],
        'coverage_fraction':sum(v!=0 for v in coverage)/(size*size)}


def bake_mesh_masks(obj_path: str, cfg, *, size=256,up_axis='y'):
    try:path=Path(ensure_within_roots(obj_path,cfg.allowed_roots))
    except PathNotAllowed as exc:raise ServiceError('ASSET_PATH_DENIED',str(exc)) from exc
    if path.suffix.lower()!='.obj' or not path.is_file():raise ServiceError('OBJ_REQUIRED','Supply an approved triangle OBJ file.')
    if path.stat().st_size>16*1024*1024:raise ServiceError('MESH_LIMIT','OBJ input exceeds 16 MiB.')
    resolution(size,min(512,getattr(cfg,'max_resolution',2048)))
    raw=path.read_bytes()
    try:
        text=raw.decode('utf-8')
    except UnicodeError as exc:
        raise ServiceError('OBJ_ENCODING','OBJ must be UTF-8 text.') from exc
    import hashlib
    inputs={'schema_version':1,'backend':'obj-masks-v1','source':str(path),'source_sha256':hashlib.sha256(raw).hexdigest(),'size':size,'up_axis':up_axis}
    key='m_'+digest(inputs);root=Path(cfg.workspace_dir or Path(cfg.output_dir)/'workspace')/'mesh_masks';root.mkdir(parents=True,exist_ok=True)
    target=root/key
    with file_lock(root/'.masks.lock'):
        if target.exists():
            import json
            if target.is_symlink():
                raise ServiceError('ARTIFACT_SYMLINK','Mask cache directory must not be a symlink.')
            result=parse_json((target/'manifest.json').read_bytes())
            if result.get('mask_id') != key or result.get('inputs') != inputs:
                raise ServiceError('ARTIFACT_CORRUPT','Cached mask identity changed.')
            for f in result['files']:
                artifact=target/identifier(f['name'],'mask filename')
                if artifact.is_symlink() or file_digest(artifact)!=f['sha256']:raise ServiceError('ARTIFACT_CORRUPT','A cached mesh mask changed.')
            return {**result,'cached':True}
        arrays,metrics=bake_arrays(*parse_obj(text),size=size,up_axis=up_axis)
        stage=Path(tempfile.mkdtemp(prefix='.mesh-',dir=root))
        try:
            files=[]
            for channel,data in arrays.items():
                image=stage/f'mask_{channel}.png';Image.frombytes('L',(size,size),bytes(data)).save(image)
                files.append({'name':image.name,'sha256':file_digest(image),'path':str(target/image.name),'channel':channel})
            result={'ok':True,'mask_id':key,'inputs':inputs,'metrics':metrics,'files':files,
                    'color_space':'linear','image_origin':'top-left; OBJ v is flipped during rasterization',
                    'geometry_space':'OBJ coordinates; no world transform applied','height_units':'normalized from source coordinate bounds',
                    'limitations':['No occlusion or curvature is inferred.','Upward facing uses triangle winding, not smoothed normals.','No padding/dilation; use coverage to mask empty texels.','UV overlap is rejected; triangulation and UV unwrapping are prerequisites.']}
            atomic_json(stage/'manifest.json',result)
            if file_digest(path)!=inputs['source_sha256']:raise ServiceError('DEPENDENCY_CHANGED','Mesh changed during baking.')
            os.replace(stage,target);return {**result,'cached':False}
        finally:
            if stage.exists():shutil.rmtree(stage,ignore_errors=True)
