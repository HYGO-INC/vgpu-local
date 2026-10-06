"""Container-only benchmark wrapper; inference stays in the upstream engine."""
import argparse
import json
import os
import subprocess
import threading
import time
from datetime import datetime, timezone
from importlib.metadata import version
from pathlib import Path

ROOT = Path('/data')
LOCK = json.loads(Path('/recipe/lock.json').read_text())
MODEL_FILES = ['model_index.json', 'scheduler/*', 'text_encoder/*', 'tokenizer/*', 'transformer/*', 'vae/*']


def write(path, data):
    temporary = path.with_suffix('.tmp')
    with temporary.open('w') as file:
        json.dump(data, file, indent=2)
        file.flush()
        os.fsync(file.fileno())
    temporary.replace(path)


def gpu_sample():
    fields = 'name,driver_version,memory.total,memory.used,utilization.gpu'
    line = subprocess.check_output(['nvidia-smi', f'--query-gpu={fields}', '--format=csv,noheader,nounits'], text=True, timeout=10)
    name, driver, total, used, utilization = [field.strip() for field in line.strip().split(',')]
    return dict(name=name, driver=driver, total_mib=int(total), used_mib=int(used), utilization_percent=int(utilization))


def preflight():
    import torch
    import fastvideo
    import fastvideo_kernel
    result = dict(image=LOCK['image'], image_source_revision=LOCK['image_source_revision'],
                  torch=torch.__version__, cuda=torch.version.cuda, fastvideo=version('fastvideo'),
                  kernel=version('fastvideo-kernel'), gpu=gpu_sample(),
                  capability=list(torch.cuda.get_device_capability(0)))
    assert torch.cuda.is_available()
    x = torch.arange(4096, device='cuda', dtype=torch.float32)
    assert x.sum().item() == 4095 * 4096 / 2
    torch.cuda.synchronize()
    result['cuda_reduction'] = 'passed'
    if LOCK['execution_backend'] == 'ray':
        import ray
        start_ray()
        try:
            def tensor():
                import torch
                return torch.arange(4096,device='cuda',dtype=torch.float32)
            received = ray.get(ray.remote(num_gpus=1)(tensor).remote(),timeout=90)
            assert received.sum().item() == 4095*4096/2
            result.update(ray=version('ray'),cuda_tensor_round_trip='passed')
        finally: ray.shutdown()
    write(ROOT / 'preflight.json', result)
    print(json.dumps(result), flush=True)


def start_ray():
    import ray
    ray.init(num_gpus=1,num_cpus=6,object_store_memory=256*1024*1024,include_dashboard=False,
             _node_ip_address='127.0.0.1',_temp_dir='/tmp/vgpu-ray')


def download():
    from huggingface_hub import snapshot_download
    start = time.perf_counter()
    path = snapshot_download(repo_id=LOCK['model'], revision=LOCK['model_revision'], token=False,
                             allow_patterns=MODEL_FILES,
                             max_workers=2)
    assert Path(path).name == LOCK['model_revision']
    result = dict(model=LOCK['model'], revision=LOCK['model_revision'], seconds=time.perf_counter()-start,
                  files=sorted(str(p.relative_to(path)) for p in Path(path).rglob('*') if p.is_file()))
    write(ROOT / 'download.json', result)
    print(json.dumps(result), flush=True)


def benchmark(profile, runs):
    from huggingface_hub import snapshot_download
    # Resolve the pinned snapshot without a network. Loading must never fetch a
    # mutable branch or silently switch models when a required file is absent.
    model_path = snapshot_download(repo_id=LOCK['model'], revision=LOCK['model_revision'], token=False,
                                   local_files_only=True, allow_patterns=MODEL_FILES)
    os.environ['FASTVIDEO_ATTENTION_BACKEND'] = LOCK['attention_backend']
    from fastvideo import VideoGenerator
    from fastvideo.api.sampling_param import SamplingParam
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')
    output = ROOT / f'{stamp}-{profile}'
    output.mkdir()
    report = dict(schema_version=1, status='running', started_at=stamp, lock=LOCK, profile=profile,
                  baseline_gpu=gpu_sample(), measurements=[], memory_measurement='whole GPU board; includes other host processes')
    done = threading.Event()
    peak = report['baseline_gpu']['used_mib']
    def sample():
        nonlocal peak
        while not done.wait(0.25):
            try: peak = max(peak, gpu_sample()['used_mib'])
            except Exception: pass
    observer = threading.Thread(target=sample, daemon=True)
    observer.start()
    write(output / 'result.json', report)
    generator = None
    try:
        start = time.perf_counter()
        if LOCK['execution_backend'] == 'ray': start_ray()
        generator = VideoGenerator.from_pretrained(model_path,
            num_gpus=1, use_fsdp_inference=False, text_encoder_cpu_offload=LOCK['text_encoder_cpu_offload'],
            text_encoder_precisions=(LOCK['text_encoder_precision'],),
            distributed_executor_backend=LOCK['execution_backend'],
            pin_cpu_memory=False, dit_cpu_offload=False, vae_cpu_offload=False, VSA_sparsity=LOCK['sparsity'])
        report['load_seconds'] = time.perf_counter()-start
        sampling = SamplingParam.from_pretrained(LOCK['model'])
        for key, value in LOCK['profiles'][profile].items(): setattr(sampling, key, value)
        sampling.seed = LOCK['seed']
        report['sampling'] = {key:getattr(sampling,key) for key in ('height','width','num_frames','fps','num_inference_steps','guidance_scale','seed')}
        for run in range(runs):
            start = time.perf_counter()
            generator.generate_video(LOCK['prompt'], output_path=str(output / f'run-{run+1}'), save_video=True, sampling_param=sampling)
            report['measurements'].append(dict(run=run+1, seconds=time.perf_counter()-start,
                                              includes_first_use_costs=run == 0))
            write(output / 'result.json', report)
        videos = sorted(output.rglob('*.mp4'))
        if len(videos) != runs: raise RuntimeError('Expected one video artifact per run')
        import av
        report['videos'] = []
        for video in videos:
            with av.open(str(video)) as container:
                stream = container.streams.video[0]
                frames = sum(1 for _ in container.decode(stream))
                report['videos'].append(dict(file=str(video.relative_to(output)), frames=frames,
                                              width=stream.width, height=stream.height, fps=float(stream.average_rate)))
                if frames != sampling.num_frames: raise RuntimeError('Decoded frame count mismatch')
                if (stream.width, stream.height) != (sampling.width, sampling.height):
                    raise RuntimeError('Decoded dimensions mismatch')
        report['status'] = 'passed'
    except BaseException as error:
        report['status'] = 'failed'
        report['error_type'] = type(error).__name__
        report['error'] = str(error)[:2000]
        raise
    finally:
        done.set(); observer.join(timeout=12)
        report['gpu_board_peak_mib'] = peak
        cgroup = Path('/sys/fs/cgroup/memory.peak')
        if cgroup.exists(): report['container_memory_peak_bytes_including_cache'] = int(cgroup.read_text())
        limit = Path('/sys/fs/cgroup/memory.max')
        if limit.exists(): report['container_memory_limit_bytes'] = int(limit.read_text())
        events = Path('/sys/fs/cgroup/memory.events')
        if events.exists(): report['container_memory_events'] = dict(line.split() for line in events.read_text().splitlines())
        write(output / 'result.json', report)
        print(f'Benchmark report: {output}/result.json', flush=True)
        # Kill engine actors while their Ray cluster still exists. Otherwise the
        # executor destructor's ray.kill can auto-start a second local cluster.
        try:
            if generator is not None: generator.shutdown()
        finally:
            if LOCK['execution_backend'] == 'ray':
                import ray
                ray.shutdown()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=['preflight','download','benchmark'])
    parser.add_argument('--profile', choices=['smoke','480p'], default='smoke')
    parser.add_argument('--runs', type=int, default=2)
    args = parser.parse_args()
    if args.action == 'preflight': preflight()
    elif args.action == 'download': download()
    else: benchmark(args.profile,args.runs)
