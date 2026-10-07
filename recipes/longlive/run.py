"""Pinned LongLive 1.3B recipe with isolated, bounded Docker inference."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=['setup','download','preflight','benchmark'])
    parser.add_argument('--data-directory',type=Path,required=True)
    parser.add_argument('--latent-frames',type=int,default=21)
    parser.add_argument('--runs',type=int,default=1)
    parser.add_argument('--timeout-seconds',type=int,default=3600)
    args = parser.parse_args()
    if args.latent_frames not in range(3,244,3) or not 1 <= args.runs <= 3 or not 30 <= args.timeout_seconds <= 14400:
        parser.error('Require latent frames 3..243 in blocks of 3, runs 1..3 and timeout 30..14400')
    recipe = Path(__file__).resolve().parent
    lock = json.loads((recipe/'lock.json').read_text())
    build_hash = hashlib.sha256((recipe/'Dockerfile').read_bytes()+(recipe/'requirements.txt').read_bytes()).hexdigest()
    data = args.data_directory.resolve()
    data.mkdir(parents=True,exist_ok=True)
    engine = data/'engine'
    image_file = data/'image-id.txt'
    if args.action == 'setup':
        if not engine.exists():
            subprocess.run(['git','init',str(engine)],check=True,timeout=30)
            subprocess.run(['git','-C',str(engine),'remote','add','origin',lock['source']],check=True,timeout=30)
        origin = subprocess.check_output(['git','-C',str(engine),'remote','get-url','origin'],text=True).strip()
        dirty = subprocess.check_output(['git','-C',str(engine),'status','--porcelain'],text=True).strip()
        if origin != lock['source'] or dirty: raise RuntimeError('Unexpected or modified engine checkout')
        subprocess.run(['git','-C',str(engine),'fetch','--depth','1','origin',lock['source_revision']],check=True,timeout=180)
        subprocess.run(['git','-C',str(engine),'checkout','--detach',lock['source_revision']],check=True,timeout=30)
        subprocess.run(['docker','build','--label','vgpu.recipe.sha256='+build_hash,'--iidfile',str(image_file),str(recipe)],
                       check=True,timeout=args.timeout_seconds)
        return
    sha = subprocess.check_output(['git','-C',str(engine),'rev-parse','HEAD'],text=True).strip()
    dirty = subprocess.check_output(['git','-C',str(engine),'status','--porcelain','--untracked-files=no'],text=True).strip()
    if sha != lock['source_revision'] or dirty: raise RuntimeError('Engine differs from pinned unmodified source')
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')
    output = data/(stamp+'-'+args.action)
    output.mkdir()
    environment = dict(os.environ,HF_HUB_DISABLE_IMPLICIT_TOKEN='1',HF_HUB_DISABLE_TELEMETRY='1',HF_HUB_DISABLE_XET='1')
    for key in ['HF_TOKEN','HUGGING_FACE_HUB_TOKEN','HUGGINGFACEHUB_API_TOKEN']:
        environment.pop(key,None)
    container = 'vgpu-longlive-'+stamp.lower().replace('.','-')
    image = None
    if args.action == 'download':
        environment.pop('HF_HUB_OFFLINE',None)
        environment.pop('TRANSFORMERS_OFFLINE',None)
        command = ['uv','run','--script','--locked',str(recipe/'download.py'),
                   '--data-directory',str(data),'--output-directory',str(output)]
    else:
        image = image_file.read_text().strip()
        if len(image) != 71 or not image.startswith('sha256:'):
            raise RuntimeError('Run setup to build the pinned environment')
        details = json.loads(subprocess.check_output(['docker','image','inspect',image],text=True,timeout=30))[0]
        if details['Config']['Labels'].get('vgpu.recipe.sha256') != build_hash:
            raise RuntimeError('Environment build does not match recipe')
        (data/'models').mkdir(exist_ok=True)
        memory = str(lock['cpu_memory_gib'])+'g'
        command = ['docker','run','--rm','--name',container,'--gpus','device=0','--network','none',
            '--memory',memory,'--memory-swap',memory,'--cpus','6','--shm-size','1g',
            '--mount',f'type=bind,source={recipe},target=/recipe,readonly',
            '--mount',f'type=bind,source={engine},target=/engine,readonly',
            '--mount',f'type=bind,source={data/"models"},target=/models,readonly',
            '--mount',f'type=bind,source={output},target=/output',
            '--env','HF_HUB_OFFLINE=1','--env','TRANSFORMERS_OFFLINE=1','--env','PYTHONUNBUFFERED=1',
            image,'/recipe/inside.py',args.action,'--latent-frames',str(args.latent_frames),'--runs',str(args.runs)]
    invocation = {'action':args.action,'lock':lock,'image_id':image,'status':'running',
                  'started_at':datetime.now(timezone.utc).isoformat()}
    print(output,flush=True)
    (output/'invocation.json').write_text(json.dumps(invocation,indent=2),encoding='utf-8')
    child = None
    try:
        with (output/'engine.log').open('w',encoding='utf-8') as log:
            child = subprocess.Popen(command,stdout=log,stderr=subprocess.STDOUT,env=environment,
                                     start_new_session=os.name != 'nt')
            code = child.wait(timeout=args.timeout_seconds)
            if code:
                raise subprocess.CalledProcessError(code,command)
        invocation['status'] = 'passed'
    except BaseException as error:
        invocation.update(status='failed',error_type=type(error).__name__)
        if args.action != 'download':
            subprocess.run(['docker','stop','--time','10',container],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=30)
        if child and child.poll() is None:
            if os.name == 'nt':
                subprocess.run(['taskkill','/PID',str(child.pid),'/T','/F'],check=False,timeout=30)
            else:
                import signal
                os.killpg(child.pid,signal.SIGKILL)
            child.wait(timeout=30)
        raise
    finally:
        invocation['finished_at'] = datetime.now(timezone.utc).isoformat()
        (output/'invocation.json').write_text(json.dumps(invocation,indent=2),encoding='utf-8')
        print(output,flush=True)


if __name__ == '__main__': main()
