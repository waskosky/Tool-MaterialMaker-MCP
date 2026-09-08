"""Run real batch-render acceptance in a fresh workspace, never an artist tab.

This is opt-in. Native engine/editor import and artistic quality need additional
checks from docs/upgrade/TESTING.md. No mock fallback exists in this script.
"""
import argparse
from dataclasses import replace
import json
from pathlib import Path
import sys
import tempfile

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from mm_mcp.config import load_config,require_valid
from mm_mcp.core import ServiceError,atomic_json
from mm_mcp.service import MaterialService

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--recipe',default='t01_sand_dunes')
    parser.add_argument('--size',type=int,default=256)
    args=parser.parse_args()
    cfg=load_config();require_valid(cfg)
    output=Path(cfg.output_dir);output.mkdir(parents=True,exist_ok=True)
    workspace=Path(tempfile.mkdtemp(prefix='native-acceptance-',dir=output))
    cfg=replace(cfg,workspace_dir=str(workspace),allowed_roots=list(set(cfg.allowed_roots+[str(output)])))
    service=MaterialService(cfg);report={'native':True,'workspace':str(workspace),'passed':False,'steps':[]}
    try:
        project=service.instantiate(args.recipe)
        base={'project_id':project['project_id'],'revision':project['revision'],'size':args.size}
        first=service.build(base);assert first['manifest']['renderer_kind']=='native_material_maker'
        second=service.build(base);assert second['cached'] and first['build_id']==second['build_id']
        data=service.builds.export(first['build_id'])
        (workspace/'verified-build.zip').write_bytes(data)
        seeded=service.build({**base,'seed':73021})
        assert seeded['build_id']!=first['build_id']
        graph=json.loads(service.builds.artifact(seeded['build_id'],'material.ptex').read_text())
        assert graph['seed_int']==73021
        report.update(passed=True,steps=['Native PNG decode and complete expected-channel verification','Source-bound cache hit','Verified export archive','Distinct explicit-seed build'],
                      build_ids=[first['build_id'],seeded['build_id']],
                      not_tested=['Native editor writes/global undo','Visual quality or change caused by seed','Three-dimensional browser preview','Engine imports'])
    except Exception as exc:
        report['error']=str(exc)
        if isinstance(exc,ServiceError):report['error_details']=exc.result()
    finally:
        service.close();atomic_json(workspace/'acceptance.json',report)
    print(json.dumps(report,indent=2));return 0 if report['passed'] else 1
if __name__=='__main__':raise SystemExit(main())
