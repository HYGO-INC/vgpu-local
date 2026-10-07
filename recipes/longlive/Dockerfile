FROM ghcr.io/hao-ai-lab/fastvideo/fastvideo-dev@sha256:b30fbb7013f965b52cbacc3a2316a4d8503d5fad3522bc5396ac627d1eea80b3
COPY requirements.txt /tmp/longlive-requirements.txt
RUN /opt/venv/bin/python -m pip install --disable-pip-version-check --no-deps --require-hashes -r /tmp/longlive-requirements.txt
ENTRYPOINT ["/opt/venv/bin/python"]
