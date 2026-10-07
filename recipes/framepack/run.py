"""Run a pinned upstream FramePack benchmark in its own Python environment."""
import argparse
import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['setup', 'download', 'preflight', 'benchmark'])
    parser.add_argument('--data-directory', required=True, type=Path)
    parser.add_argument('--input-image', type=Path)
    parser.add_argument('--seconds', type=float, default=5)
    parser.add_argument('--runs', type=int, default=1)
    parser.add_argument('--timeout-seconds', type=int, default=3600)
    args = parser.parse_args()
    if not 1 <= args.seconds <= 60 or not 1 <= args.runs <= 3 or not 30 <= args.timeout_seconds <= 14400:
        parser.error('Require seconds 1..60, runs 1..3 and timeout 30..14400')
    if args.action == 'benchmark' and (not args.input_image or not args.input_image.is_file()):
        parser.error('Benchmark requires --input-image')
    recipe = Path(__file__).resolve().parent
    lock = json.loads((recipe / 'lock.json').read_text())
    data = args.data_directory.resolve()
    data.mkdir(parents=True, exist_ok=True)
    engine = data / 'engine'
    environment = data / 'environment'
    env = dict(os.environ, UV_PROJECT_ENVIRONMENT=str(environment), HF_HOME=str(data/'huggingface'),
               HF_HUB_DISABLE_IMPLICIT_TOKEN='1', HF_HUB_DISABLE_TELEMETRY='1', GRADIO_ANALYTICS_ENABLED='False',
               HF_XET_CHUNK_CACHE_SIZE_BYTES='0', HF_XET_RECONSTRUCT_WRITE_SEQUENTIALLY='1',
               TOKENIZERS_PARALLELISM='false', PYTHONUNBUFFERED='1')
    # No inherited model-service or model-hub credentials belong in this recipe.
    for key in ['HF_TOKEN', 'HUGGING_FACE_HUB_TOKEN', 'HUGGINGFACEHUB_API_TOKEN']:
        env.pop(key, None)
    if args.action == 'setup':
        subprocess.run(['uv', 'sync', '--locked', '--project', str(recipe)], env=env, check=True, timeout=args.timeout_seconds)
        if not engine.exists():
            subprocess.run(['git', 'init', str(engine)], check=True, timeout=30)
            subprocess.run(['git', '-C', str(engine), 'remote', 'add', 'origin', lock['source']], check=True, timeout=30)
        origin = subprocess.check_output(['git', '-C', str(engine), 'remote', 'get-url', 'origin'], text=True).strip()
        if origin != lock['source']:
            raise RuntimeError('Unexpected engine origin; refusing to update it')
        dirty = subprocess.check_output(['git', '-C', str(engine), 'status', '--porcelain'], text=True).strip()
        if dirty:
            raise RuntimeError('Engine checkout has local changes; refusing to replace it')
        subprocess.run(['git', '-C', str(engine), 'fetch', '--depth', '1', 'origin', lock['source_revision']], check=True, timeout=120)
        subprocess.run(['git', '-C', str(engine), 'checkout', '--detach', lock['source_revision']], check=True, timeout=30)
        return
    python = environment / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
    if not python.is_file():
        raise RuntimeError('Run setup first')
    sha = subprocess.check_output(['git', '-C', str(engine), 'rev-parse', 'HEAD'], text=True).strip()
    dirty = subprocess.check_output(['git', '-C', str(engine), 'status', '--porcelain', '--untracked-files=no'], text=True).strip()
    if sha != lock['source_revision'] or dirty:
        raise RuntimeError('Engine does not match the unmodified pinned source')
    if args.action != 'download':
        env.update(HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1')
    else:
        env.pop('HF_HUB_OFFLINE', None)
        env.pop('TRANSFORMERS_OFFLINE', None)
        env['HF_HUB_DISABLE_XET'] = '1'
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')
    output = data / (stamp+'-'+args.action)
    output.mkdir()
    command = [str(python), str(recipe/'inside.py'), args.action, '--data-directory', str(data),
               '--output-directory', str(output), '--seconds', str(args.seconds), '--runs', str(args.runs)]
    if args.input_image:
        command += ['--input-image', str(args.input_image.resolve())]
    if args.action == 'download':
        command = ['uv', 'run', '--script', '--locked', str(recipe/'download.py'),
                   '--data-directory', str(data), '--output-directory', str(output)]
    record = dict(action=args.action, started_at=datetime.now(timezone.utc).isoformat(), lock=lock, status='running')
    print('Artifacts: '+str(output), flush=True)
    path = output/'invocation.json'
    path.write_text(json.dumps(record, indent=2), encoding='utf-8')
    child = None
    try:
        with (output/'engine.log').open('w', encoding='utf-8') as log:
            child = subprocess.Popen(command, env=env, cwd=output, stdout=log, stderr=subprocess.STDOUT,
                                     start_new_session=os.name != 'nt')
            code = child.wait(timeout=args.timeout_seconds)
        record.update(status='passed' if code == 0 else 'failed', exit_code=code)
        if code:
            raise RuntimeError('Engine failed; see '+str(output/'engine.log'))
        print((output/'result.json').read_text(), flush=True)
    except (subprocess.TimeoutExpired, KeyboardInterrupt) as error:
        record.update(status='aborted', reason=type(error).__name__)
        if child and child.poll() is None:
            if os.name == 'nt':
                subprocess.run(['taskkill', '/PID', str(child.pid), '/T', '/F'], timeout=30, check=False)
            else:
                import signal
                os.killpg(child.pid, signal.SIGKILL)
            child.wait(timeout=30)
        raise
    finally:
        record['finished_at'] = datetime.now(timezone.utc).isoformat()
        path.write_text(json.dumps(record, indent=2), encoding='utf-8')


if __name__ == '__main__':
    main()
