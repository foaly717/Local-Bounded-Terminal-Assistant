# Local Bounded Terminal Assistant

A small terminal client, local model launcher, and benchmark harness for running and evaluating local GGUF language models through `llama.cpp`.

The project is intentionally narrow: start a local model server in Docker, select a GGUF model, interact with it from the terminal, and evaluate model behavior against deterministic benchmark sets. The runtime interface is bounded rather than being a general-purpose agent or unrestricted shell executor.

This branch, `benchmark-development`, adds deterministic benchmarking and evidence-backed evaluation to the terminal assistant. The benchmark system is designed to remain model-agnostic and to keep benchmark definitions, evidence, model selection, and runtime management as separate concerns.

## Components

* `llm-start` — selects a `.gguf` model and starts the `llama.cpp` server in Docker.
* `llm-stop` — stops the running `llama.cpp` container.
* `llm-status` — reports the state and relevant runtime information for the local model server.
* `llm-ask6` — terminal wrapper for the Python client.
* `llm-client2.py` — Python client for the local OpenAI-compatible chat-completions endpoint.
* `llm-benchmark` — runs deterministic benchmark questions against the active local model and records evaluation, token, timing, and throughput results.

The Python client and benchmark harness use only the Python standard library.

## Requirements

* Linux
* Bash
* Python 3
* Docker Engine
* A compatible GGUF model
* The `ghcr.io/ggml-org/llama.cpp:server` container image

## Model setup

By default, `llm-start` looks for GGUF models in the repository-relative `models/` directory.

A different model directory can be selected with:

```bash
export LLM_MODELS_DIR="/path/to/models"
```

The launcher presents the available `.gguf` files and prompts for a model selection.

The model directory is mounted read-only into the container.

The launcher is separate from the benchmark harness. A benchmark does not select or load a model itself; it evaluates whichever compatible local model is running through the configured `llama.cpp` endpoint.

This makes the benchmark model-agnostic: the same benchmark definition can be run against different local GGUF models without changing the benchmark runner.

## Starting and managing the server

Run:

```bash
./llm-start
```

The launcher starts `llama.cpp` with:

* localhost binding on `127.0.0.1:8080`
* 20 GB container memory limit
* 8 CPU limit
* 6 llama.cpp threads
* 10240-token context
* 1536-token server generation limit
* prompt caching enabled
* flash attention enabled
* llama.cpp Web UI disabled

The container uses a read-only root filesystem, drops Linux capabilities, enables `no-new-privileges`, and limits temporary/shared-memory resources.

The server lifecycle is deliberately separated from the client and benchmark.

Check the current server state with:

```bash
./llm-status
```

Stop the running model server with:

```bash
./llm-stop
```

The same lifecycle tools are used whether the server is being used interactively through `llm-ask6` or as the model endpoint for `llm-benchmark`.

A typical workflow is:

```text
llm-start
    |
    v
llama.cpp local model server
    |
    +---- llm-ask6
    |
    +---- llm-benchmark
    |
    v
llm-status / llm-stop
```

The benchmark does not own the model lifecycle. Start, inspect, and stop the model explicitly through the launcher tools.

## Using the client

For a direct prompt:

```bash
./llm-ask6 "your prompt here"
```

For piped input:

```bash
some-command | ./llm-ask6 "analyze the supplied input"
```

For a file:

```bash
./llm-ask6 "summarize this file" /path/to/file
```

The client can combine a prompt, stdin, and a file. Individual input sources are bounded to 1 MiB by default.

## Client configuration

The following environment variables are supported:

* `LLM_API_KEY` — API key sent to the local `llama.cpp` server. Defaults to `local-only-key`.
* `LLM_MAX_TOKENS` — client-side generation limit. Defaults to `1024`.
* `LLM_TIMEOUT` — request timeout in seconds. Defaults to `300`.
* `LLM_MAX_INPUT_BYTES` — maximum size of each input source. Defaults to `1048576` bytes.
* `LLM_SYSTEM_PROMPT` — optional replacement for the built-in system prompt.

The client queries the server's `/props` endpoint to determine the configured context size and refuses requests whose estimated prompt size would exceed the available context after reserving the configured generation budget.

## Streaming behavior

Responses are streamed from `/v1/chat/completions`.

The client:

* processes server-sent event responses incrementally;
* writes model content as it arrives;
* sanitizes terminal control sequences and selected control/format characters;
* handles normal completion and length-limited generation;
* detects missing model content;
* handles common connection, timeout, interruption, and broken-pipe conditions.

The client does not independently verify factual claims made by the model.

## Benchmarking

`llm-benchmark` provides a deterministic evaluation layer on top of the local model interface.

The benchmark harness sends defined questions to the active model, evaluates the resulting responses against the benchmark's expected behavior, and records the results as JSON.

The benchmark separates four concerns:

```text
Benchmark definition
        |
        +---- evidence
        |
        v
   llm-benchmark
        |
        v
OpenAI-compatible endpoint
        |
        v
  Active GGUF model
```

Benchmark definitions and evidence are stored independently from the model being evaluated. This allows the same benchmark to be used across different models while keeping the evaluation conditions consistent.

### Swappable evidence

Benchmark evidence is stored under:

```text
Benchmark Results/benchmarks/evidence/
```

The evidence files provide the source material used by benchmark definitions. They are inputs to the benchmark rather than properties of the model.

Evidence can therefore be exchanged or expanded independently of the model and benchmark runner. This supports evaluation against different command documentation or other evidence-backed task sets without embedding those sources directly into the model-specific runtime.

The benchmark is intended to evaluate observable model behavior against known expectations rather than assume that a particular model was trained for a particular benchmark.

### Model-agnostic evaluation

`llm-benchmark` communicates with the same OpenAI-compatible `/v1/chat/completions` interface used by the terminal client. It does not depend on a model-specific API or invocation mechanism.

The model is selected separately through `llm-start`. The benchmark records the model information associated with each run so results can be compared across different local GGUF models.

The same benchmark can therefore be run against different:

* GGUF models;
* model revisions;
* quantizations;
* local runtime configurations.

The benchmark runner itself does not need to change when the model changes.

### Running a benchmark

Start the desired model:

```bash
./llm-start
```

Inspect the running server:

```bash
./llm-status
```

Run the benchmark against the active endpoint:

```bash
./llm-benchmark
```

When finished:

```bash
./llm-stop
```

The benchmark does not automatically start or stop the model. This keeps model lifecycle management separate from evaluation and makes the runtime configuration explicit.

## Benchmark results

Benchmark definitions are stored under:

```text
Benchmark Results/benchmarks/
```

Benchmark results are written under:

```text
Benchmark Results/results/
```

A result document records the benchmark definition, execution configuration, individual question results, and aggregate measurements.

The result document begins with a compact `summary` object so the primary outcome can be understood without reading the complete per-question results.

The summary includes:

* `correct` — number of questions evaluated as correct.
* `questions` — number of questions in the run.
* `prompt_tokens` — total prompt tokens reported across the questions.
* `completion_tokens` — total generated completion tokens.
* `total_tokens` — total prompt and completion tokens.
* `benchmark_elapsed_seconds` — elapsed benchmark time measured from benchmark start through completion of the benchmark run.

For example:

```json
"summary": {
  "correct": 7,
  "questions": 10,
  "prompt_tokens": 1234,
  "completion_tokens": 5678,
  "total_tokens": 6912,
  "benchmark_elapsed_seconds": 42.37
}
```

The detailed result retains per-question timing and token measurements as well as aggregate throughput information. This provides a compact human-readable summary while preserving the underlying measurements for later analysis.

`benchmark_elapsed_seconds` is an end-to-end benchmark timing metric. It is not intended to represent `llama.cpp`'s internal pure-generation time.

## Benchmark evidence and results

The benchmark branch currently contains a terminal benchmark definition and its associated command-help evidence:

```text
Benchmark Results/
├── benchmarks/
│   ├── evidence/
│   │   ├── curl-help.txt
│   │   ├── ffmpeg-help.txt
│   │   ├── find-help.txt
│   │   ├── git-help.txt
│   │   ├── grep-help.txt
│   │   ├── sed-help.txt
│   │   └── tar-help.txt
│   └── terminal-v1.json
└── results/
```

Individual result files in `Benchmark Results/results/` are generated from benchmark runs and identify the benchmark run, model, and system-prompt configuration in their filenames.

## Scope

This is a local terminal interface and bounded benchmark harness around a `llama.cpp` server, not a general-purpose agent framework or unrestricted shell environment.

Docker resource and filesystem restrictions are applied by the launcher, while input-size, context, streaming, and terminal-output handling are implemented by the client.

Benchmarking adds deterministic evaluation and result recording but does not turn the project into an autonomous agent or unrestricted execution system.

No model files are included in the repository.

## Repository layout

```text
.
├── Benchmark Results/
│   ├── benchmarks/
│   │   ├── evidence/
│   │   └── terminal-v1.json
│   └── results/
├── llm-ask6
├── llm-benchmark
├── llm-client2.py
├── llm-start
├── llm-status
├── llm-stop
└── README.md
```
