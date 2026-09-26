# Local Bounded Terminal Assistant

A small terminal client and launcher for running a local GGUF language model through `llama.cpp`.

The project is intentionally narrow: start a local model server in Docker, select a GGUF model, and interact with it from the terminal. The client supports direct prompts, piped stdin, and file input while enforcing bounded input and generation limits.

## Components

* `llm-start` — selects a `.gguf` model and starts the `llama.cpp` server in Docker.
* `llm-stop` — stops the running `llama.cpp` container.
* `llm-ask6` — terminal wrapper for the Python client.
* `llm-client2.py` — Python client for the local OpenAI-compatible chat-completions endpoint.

The Python client uses only the Python standard library.

## Requirements

* Linux
* Bash
* Python 3
* Docker Engine
* A compatible GGUF model
* The `ghcr.io/ggml-org/llama.cpp:server` container image

See COMPATIBILITY.md for OS/ platform-specific setup and limitations.

## Model setup

By default, `llm-start` looks for GGUF models in the repository-relative `models/` directory.

A different model directory can be selected with:

```bash
export LLM_MODELS_DIR="/path/to/models"
```

The launcher presents the available `.gguf` files and prompts for a model selection.

The model directory is mounted read-only into the container.

## Starting the server

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

* `LLM_API_KEY` — API key sent to the local llama.cpp server. Defaults to `local-only-key`.
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

## Scope

This is a local terminal interface around a `llama.cpp` server, not a general-purpose agent framework or sandbox. Docker resource and filesystem restrictions are applied by the launcher, while input-size, context, streaming, and terminal-output handling are implemented by the client.

No model files are included in the repository.

## Repository layout

```text
.
├── llm-ask6
├── llm-client2.py
├── llm-start
├── llm-stop
└── .gitignore
```

