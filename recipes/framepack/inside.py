"""Headless harness: the pinned upstream worker runs without a public Gradio server."""
import argparse
import hashlib
import inspect
import json
import os
import platform
import runpy
import subprocess
import sys
import threading
import time
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=['preflight', 'benchmark'])
    parser.add_argument('--data-directory', type=Path, required=True)
    parser.add_argument('--output-directory', type=Path, required=True)
    parser.add_argument('--input-image', type=Path)
    parser.add_argument('--seconds', type=float, default=5)
    parser.add_argument('--runs', type=int, default=1)
    args = parser.parse_args()
    recipe = Path(__file__).resolve().parent
    lock = json.loads((recipe/'lock.json').read_text())
    output = args.output_directory
    report = {'lock': lock, 'action': args.action, 'python': platform.python_version(), 'platform': platform.platform()}
    try:
        import torch
        import psutil
        if not torch.cuda.is_available():
            raise RuntimeError('CUDA unavailable in isolated environment')
        if torch.__version__ != '2.6.0+cu126':
            raise RuntimeError('Unexpected Torch version')
        report.update(torch=torch.__version__, cuda=torch.version.cuda, gpu=torch.cuda.get_device_name(0),
                      total_gpu_bytes=torch.cuda.get_device_properties(0).total_memory,
                      system_memory_bytes=psutil.virtual_memory().total)
        value = torch.ones((256, 256), device='cuda').sum().item()
        if value != 65536:
            raise RuntimeError('CUDA reduction failed')
        if args.action == 'preflight':
            report.update(status='passed')
            return
        # The qualification run approached host exhaustion while offloading.
        # Do not repeat that on a busy workstation by default. This admission
        # check is headroom, not a hard native-process memory limit.
        available = psutil.virtual_memory().available
        report['available_ram_before_models_bytes'] = available
        if available < 48 * 1024**3:
            raise RuntimeError('FramePack benchmark requires 48 GiB available host RAM; the measured 64 GiB host was under memory pressure')
        if args.input_image is None:
            raise RuntimeError('Input image required')
        source = args.data_directory/'engine'
        sys.path.insert(0, str(source))
        from PIL import Image
        import numpy as np
        import gradio as gr
        from diffusers import AutoencoderKLHunyuanVideo
        from transformers import LlamaModel, CLIPTextModel, LlamaTokenizerFast, CLIPTokenizer, SiglipImageProcessor, SiglipVisionModel
        from diffusers_helper.models.hunyuan_video_packed import HunyuanVideoTransformer3DModelPacked
        local_models = {m['id']: args.data_directory/'models'/m['directory'] for m in lock['models']}
        # Redirect only model location, preserving all upstream loading options.
        # Unknown model IDs fail; offline mode forbids fallback downloads.
        def pinned_loader(original):
            def load(cls, identifier, *positional, **kwargs):
                if identifier not in local_models:
                    raise RuntimeError('Unexpected upstream model identifier')
                kwargs['local_files_only'] = True
                return original(str(local_models[identifier]), *positional, **kwargs)
            return classmethod(load)
        samples = []
        done = threading.Event()
        process = psutil.Process()
        def monitor():
            while not done.is_set():
                sample = {'elapsed_seconds':time.perf_counter()-started, 'process_rss_bytes':process.memory_info().rss,
                          'system_available_bytes':psutil.virtual_memory().available}
                try:
                    text = subprocess.check_output(['nvidia-smi', '--query-gpu=memory.used,utilization.gpu',
                                                    '--format=csv,noheader,nounits', '--id=0'], text=True, timeout=5)
                    used, utilization = text.strip().split(',')
                    sample.update(board_memory_mib=int(used), gpu_utilization=int(utilization))
                except (OSError, ValueError, subprocess.SubprocessError):
                    pass
                samples.append(sample)
                done.wait(1)
        started = time.perf_counter()
        monitor_thread = threading.Thread(target=monitor, daemon=True)
        monitor_thread.start()
        try:
            classes = [LlamaModel, CLIPTextModel, LlamaTokenizerFast, CLIPTokenizer, AutoencoderKLHunyuanVideo,
                       SiglipImageProcessor, SiglipVisionModel, HunyuanVideoTransformer3DModelPacked]
            with ExitStack() as stack:
                for cls in classes:
                    stack.enter_context(patch.object(cls, 'from_pretrained', pinned_loader(cls.from_pretrained)))
                stack.enter_context(patch.object(gr.Blocks, 'launch', lambda *a, **kw: None))
                stack.enter_context(patch.object(sys, 'argv', [str(source/'demo_gradio.py'), '--server', '127.0.0.1']))
                namespace = runpy.run_path(str(source/'demo_gradio.py'))
            report['load_seconds'] = time.perf_counter()-started
            worker = namespace['worker']
            globals_ = inspect.unwrap(worker).__globals__
            image = np.array(Image.open(args.input_image).convert('RGB'))
            report['input_sha256'] = hashlib.sha256(args.input_image.read_bytes()).hexdigest()
            report['requested_seconds'] = args.seconds
            report['runs'] = []
            sections = int(max(round(args.seconds*30/(lock['latent_window_size']*4)),1))
            expected_frames = sections*lock['latent_window_size']*4+1
            for number in range(1,args.runs+1):
                folder = output/f'run-{number}'
                folder.mkdir()
                files = []
                class Input:
                    def top(self): return None
                class Output:
                    def push(self, item):
                        kind, value = item
                        if kind == 'file':
                            files.append(Path(value))
                            print('Section saved: '+str(value), flush=True)
                        # Drop GUI previews immediately instead of retaining every array.
                class Stream:
                    input_queue = Input()
                    output_queue = Output()
                globals_.update(outputs_folder=str(folder), stream=Stream())
                torch.cuda.reset_peak_memory_stats()
                beginning = time.perf_counter()
                worker(image, lock['prompt'], '', lock['seed'], args.seconds, lock['latent_window_size'],
                       lock['steps'], lock['cfg'], lock['distilled_guidance'], lock['guidance_rescale'],
                       lock['gpu_memory_preservation_gb'], lock['teacache'], lock['mp4_crf'])
                torch.cuda.synchronize()
                elapsed = time.perf_counter()-beginning
                if not files:
                    raise RuntimeError('Upstream worker returned without any video')
                import av
                with av.open(str(files[-1])) as video:
                    stream = video.streams.video[0]
                    fps = float(stream.average_rate)
                    width, height = stream.width, stream.height
                    frames = sum(1 for _ in video.decode(video=0))
                if frames != expected_frames or fps != 30:
                    raise RuntimeError(f'Incomplete upstream output: {frames} frames, expected {expected_frames}, FPS {fps}')
                report['runs'].append({'generation_seconds':elapsed, 'frames':frames, 'fps':fps, 'width':width,
                                       'height':height, 'video_seconds':frames/fps,
                                       'torch_peak_allocated_bytes':torch.cuda.max_memory_allocated(),
                                       'output':str(files[-1].relative_to(output))})
                print(json.dumps(report['runs'][-1]), flush=True)
        finally:
            done.set()
            monitor_thread.join(timeout=10)
            (output/'samples.json').write_text(json.dumps(samples,indent=2),encoding='utf-8')
            report['peak_process_rss_bytes'] = max((s['process_rss_bytes'] for s in samples),default=0)
            report['peak_board_memory_mib'] = max((s.get('board_memory_mib',0) for s in samples),default=0)
            report['minimum_system_available_bytes'] = min((s['system_available_bytes'] for s in samples),default=0)
        report['status'] = 'passed'
    except BaseException as error:
        report.update(status='failed',error_type=type(error).__name__,error=str(error))
        raise
    finally:
        (output/'result.json').write_text(json.dumps(report,indent=2),encoding='utf-8')


if __name__ == '__main__':
    main()
