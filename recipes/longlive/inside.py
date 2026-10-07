"""Use the pinned upstream pipeline directly; record complete decoded outputs."""
import argparse
import gc
import importlib.metadata as metadata
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import threading
import time
from unittest.mock import patch


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('action',choices=['preflight','benchmark'])
    parser.add_argument('--latent-frames',type=int,default=21)
    parser.add_argument('--runs',type=int,default=1)
    args = parser.parse_args()
    lock = json.loads(Path('/recipe/lock.json').read_text())
    output = Path('/output')
    report = {'lock':lock,'action':args.action,'python':platform.python_version()}
    samples,stop = [],threading.Event()
    monitor_thread = None
    try:
        import torch
        import psutil
        from flash_attn import flash_attn_func
        from omegaconf import OmegaConf
        import peft
        import av
        report['versions'] = {name:metadata.version(name) for name in
            ['torch','torchvision','diffusers','transformers','flash_attn','peft','omegaconf','av','easydict','lmdb']}
        if torch.__version__ != '2.12.0+cu126' or not torch.cuda.is_available():
            raise RuntimeError('Pinned CUDA environment unavailable')
        report.update(gpu=torch.cuda.get_device_name(0),total_gpu_bytes=torch.cuda.get_device_properties(0).total_memory)
        torch.set_grad_enabled(False)
        q = torch.randn(1,64,4,64,device='cuda',dtype=torch.bfloat16)
        actual = flash_attn_func(q,q,q)
        expected = torch.nn.functional.scaled_dot_product_attention(q.transpose(1,2),q.transpose(1,2),q.transpose(1,2)).transpose(1,2)
        torch.testing.assert_close(actual,expected,atol=.05,rtol=.03)
        del q,actual,expected
        sys.path.insert(0,'/engine/'+lock['engine_directory'])
        from pipeline import CausalInferencePipeline
        from utils import wan_wrapper
        from utils.memory import DynamicSwapInstaller
        from utils.lora_utils import configure_lora_for_model
        if args.action == 'preflight':
            report.update(status='passed',flash_attention_checked=True,upstream_imports_checked=True)
            return
        Path('/work').mkdir(exist_ok=True)
        os.chdir('/work')
        for name in ['wan_models','longlive_models']:
            Path(name).symlink_to('/models/'+name,target_is_directory=True)
        process,started = psutil.Process(),time.perf_counter()
        def monitor():
            while not stop.is_set():
                sample = {'elapsed_seconds':time.perf_counter()-started,'process_rss_bytes':process.memory_info().rss}
                try:
                    text = subprocess.check_output(['nvidia-smi','--query-gpu=memory.used,utilization.gpu',
                                                    '--format=csv,noheader,nounits','--id=0'],text=True,timeout=5)
                    used,utilization = text.strip().split(',')
                    sample.update(board_memory_mib=int(used),gpu_utilization=int(utilization))
                except (OSError,ValueError,subprocess.SubprocessError): pass
                samples.append(sample)
                stop.wait(1)
        monitor_thread = threading.Thread(target=monitor,daemon=True)
        monitor_thread.start()
        config = OmegaConf.load('/engine/'+lock['engine_directory']+'/configs/longlive_inference.yaml')
        config.num_output_frames,config.seed = args.latent_frames,lock['seed']
        config.model_kwargs.use_infinite_attention = True
        report['config'] = OmegaConf.to_container(config,resolve=True)
        # The upstream constructor briefly creates a float32 T5 and moves it to
        # CUDA before its later BF16/offload setup. Load those same BF16 weights
        # directly on CPU, then inject the encoder through the public pipeline
        # constructor. This avoids that transient 22+ GiB GPU allocation.
        original_factory,original_load = wan_wrapper.umt5_xxl,torch.load
        def cpu_encoder(**kwargs):
            return original_factory(**{**kwargs,'dtype':torch.bfloat16,'device':torch.device('cpu')})
        def tensor_load(path,*positional,**kwargs):
            return original_load(path,*positional,**{**kwargs,'weights_only':True,'mmap':True})
        with patch.object(wan_wrapper,'umt5_xxl',cpu_encoder),patch.object(torch.cuda,'is_available',return_value=False),patch.object(torch,'load',tensor_load):
            text_encoder = wan_wrapper.WanTextEncoder()
        pipeline = CausalInferencePipeline(config,device=torch.device('cuda'),text_encoder=text_encoder)
        state = tensor_load(config.generator_ckpt,map_location='cpu')
        generator = state.get('generator',state.get('model'))
        if generator is None: raise RuntimeError('Unrecognized upstream generator checkpoint')
        pipeline.generator.load_state_dict(generator,strict=True)
        del generator,state
        pipeline.generator.model = configure_lora_for_model(pipeline.generator.model,'generator',config.adapter,is_main_process=False)
        state = tensor_load(config.lora_ckpt,map_location='cpu')
        result = peft.set_peft_model_state_dict(pipeline.generator.model,state.get('generator_lora',state))
        if result.unexpected_keys or any('lora_' in key for key in result.missing_keys):
            raise RuntimeError('LoRA checkpoint did not match the selected upstream model')
        del state
        pipeline.is_lora_enabled = True
        pipeline = pipeline.to(dtype=torch.bfloat16)
        DynamicSwapInstaller.install_model(pipeline.text_encoder,device=torch.device('cuda'))
        pipeline.generator.to(device='cuda')
        pipeline.vae.to(device='cuda')
        gc.collect()
        torch.cuda.synchronize()
        report.update(load_seconds=time.perf_counter()-started,latent_frames=args.latent_frames,runs=[])
        for number in range(1,args.runs+1):
            torch.manual_seed(lock['seed'])
            torch.cuda.reset_peak_memory_stats()
            beginning = time.perf_counter()
            noise = torch.randn([1,args.latent_frames,16,60,104],device='cuda',dtype=torch.bfloat16)
            video = pipeline.inference(noise=noise,text_prompts=[lock['prompt']],return_latents=False,low_memory=True,profile=False)
            torch.cuda.synchronize()
            generation = time.perf_counter()-beginning
            path = output/f'run-{number}.mp4'
            with av.open(str(path),'w') as destination:
                stream = destination.add_stream('libx264',rate=lock['fps'])
                stream.width,stream.height,stream.pix_fmt = lock['width'],lock['height'],'yuv420p'
                stream.options = {'crf':'18'}
                for frame in video[0]:
                    array = (frame.permute(1,2,0).clamp(0,1)*255).round().to(device='cpu',dtype=torch.uint8).numpy()
                    for packet in stream.encode(av.VideoFrame.from_ndarray(array,format='rgb24')): destination.mux(packet)
                for packet in stream.encode(): destination.mux(packet)
            del video,noise
            pipeline.vae.model.clear_cache()
            with av.open(str(path)) as decoded:
                stream = decoded.streams.video[0]
                dimensions = stream.width,stream.height
                fps = float(stream.average_rate)
                frames = sum(1 for _ in decoded.decode(video=0))
            row = {'generation_seconds':generation,'generation_and_save_seconds':time.perf_counter()-beginning,
                   'frames':frames,'width':dimensions[0],'height':dimensions[1],'fps':fps,'video_seconds':frames/fps,
                   'torch_peak_allocated_bytes':torch.cuda.max_memory_allocated(),'output':path.name}
            report['runs'].append(row)
            print(json.dumps(row),flush=True)
            if frames != args.latent_frames*4-3 or dimensions != (lock['width'],lock['height']) or fps != lock['fps']:
                raise RuntimeError('Decoded video differs from requested output')
        report['status'] = 'passed'
    except BaseException as error:
        report.update(status='failed',error_type=type(error).__name__,error=str(error))
        raise
    finally:
        stop.set()
        if monitor_thread: monitor_thread.join(timeout=10)
        if samples:
            (output/'samples.json').write_text(json.dumps(samples,indent=2))
            report['peak_process_rss_bytes'] = max(s['process_rss_bytes'] for s in samples)
            report['peak_board_memory_mib'] = max(s.get('board_memory_mib',0) for s in samples)
        root = Path('/sys/fs/cgroup')
        for name in ['memory.peak','memory.max','memory.events']:
            if (root/name).is_file(): report[name] = (root/name).read_text().strip()
        (output/'result.json').write_text(json.dumps(report,indent=2))


if __name__ == '__main__': main()
