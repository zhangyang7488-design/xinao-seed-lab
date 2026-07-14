FROM python:3.12-slim

WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
COPY scripts/replay/canonical_golden.py ./scripts/replay/canonical_golden.py
COPY tests/fixtures/canonical/golden_vectors.json ./tests/fixtures/canonical/golden_vectors.json
RUN python -m pip install --no-cache-dir .

ENTRYPOINT ["python", "scripts/replay/canonical_golden.py", "--verify"]
