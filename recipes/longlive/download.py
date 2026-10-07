# /// script
# requires-python = ">=3.12,<3.13"
# dependencies = ["huggingface-hub==2.1.1"]
# ///
"""Download only the immutable upstream model snapshots selected by this recipe."""
import argparse
import json
from importlib.metadata import version
from pathlib import Path

from huggingface_hub import snapshot_download


parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--data-directory', type=Path, required=True)
parser.add_argument('--output-directory', type=Path, required=True)
args = parser.parse_args()
lock = json.loads(Path(__file__).with_name('lock.json').read_text())
result = {'lock':lock, 'download_client':version('huggingface-hub'), 'status':'running'}
try:
    for model in lock['models']:
        snapshot_download(model['id'], revision=model['revision'], local_dir=args.data_directory/'models'/model['directory'],
                          allow_patterns=model['allow_patterns'], token=False, max_workers=2)
    result['status'] = 'passed'
except BaseException as error:
    result.update(status='failed',error_type=type(error).__name__)
    raise
finally:
    (args.output_directory/'result.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
