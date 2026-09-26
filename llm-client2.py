#!/usr/bin/env python3

import json
import os
import re
import sys
import urllib.request
import urllib.error


ENDPOINT = "http://127.0.0.1:8080/v1/chat/completions"
PROPS_ENDPOINT = "http://127.0.0.1:8080/props"

API_KEY = os.environ.get("LLM_API_KEY", "local-only-key")
MAX_TOKENS = int(os.environ.get("LLM_MAX_TOKENS", "1024"))
TIMEOUT_SECONDS = int(os.environ.get("LLM_TIMEOUT", "300"))
MAX_INPUT_BYTES = int(os.environ.get("LLM_MAX_INPUT_BYTES", "1048576"))

SYSTEM_PROMPT = os.environ.get(
    "LLM_SYSTEM_PROMPT",
    """Ubuntu/Linux terminal and coding assistant. Focus on Python, Bash, SQL, data engineering, and analysis.

Be concise and factual. Answer the user's question directly. Do not add unrelated advice, warnings, examples, or explanations unless useful.

Never invent facts, commands, paths, variables, file contents, or execution results. Never claim a command was executed unless its output is provided.

For terminal commands:
- Never emit emoji, Unicode block/box-drawing characters, terminal control sequences, or decorative symbols.
- Mark potentially destructive commands with WARNING.
- Prefer commands that validate their own result.

For provided files or piped command output:
- Use the provided content as evidence.
- Distinguish commands for searching from verified search results.
- Claim a match or file content only when supported by the provided content.
- If requested information is absent, say "not found in provided input".
- When asked how to search, provide the command and example usage; do not imply it was executed.
- If the provided input is insufficient, say what is missing instead of guessing."""
)

CONTROL_SEQUENCE_REGEX = re.compile(
    r"""
    (?:
        \x1B
        \[[0-?]*[ -/]*[@-~]
    )
    |
    [\x00-\x08\x0B\x0C\x0E-\x1F\x7F]
    |
    [\x80-\x9F]
    |
    [\x0D]
    |
    [\u202A-\u202E\u2066-\u2069\u200E\u200F\u061C]
    """,
    re.VERBOSE,
)


def die(message):
    print(f"ERROR: {message}", file=sys.stderr)
    raise SystemExit(2)


def sanitize_output(text):
    return CONTROL_SEQUENCE_REGEX.sub("", text)


def read_checked(data, label):
    if len(data) > MAX_INPUT_BYTES:
        die(f"{label} exceeds {MAX_INPUT_BYTES} byte limit")

    if b"\x00" in data:
        die(f"{label} contains NUL bytes")

    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        die(f"{label} is not valid UTF-8")


def read_inputs(prompt, file_path):
    parts = [prompt]

    if not sys.stdin.isatty():
        stdin_text = read_checked(
            sys.stdin.buffer.read(MAX_INPUT_BYTES + 1),
            "stdin",
        )

        if stdin_text:
            parts.append(
                "STDIN INPUT:\n" + stdin_text
            )

    if file_path:
        with open(file_path, "rb") as f:
            file_text = read_checked(
                f.read(MAX_INPUT_BYTES + 1),
                "file",
            )

        parts.append(
            "FILE: "
            + os.path.basename(file_path)
            + "\nFILE CONTENT:\n"
            + file_text
        )

    return "\n\n".join(parts)


def get_context():
    request = urllib.request.Request(
        PROPS_ENDPOINT,
        headers={
            "Authorization": f"Bearer {API_KEY}",
        },
    )

    try:
        with urllib.request.urlopen(
            request,
            timeout=TIMEOUT_SECONDS,
        ) as response:
            data = json.load(response)

    except urllib.error.HTTPError as exc:
        die(
            f"/props HTTP error {exc.code}: "
            f"{exc.read().decode(errors='replace')}"
        )

    except urllib.error.URLError as exc:
        die(f"/props connection error: {exc.reason}")

    except TimeoutError:
        die("/props request timed out")

    except json.JSONDecodeError:
        die("/props returned invalid JSON")

    if "n_ctx" in data:
        return int(data["n_ctx"])

    settings = data.get(
        "default_generation_settings",
        {},
    )

    if "n_ctx" in settings:
        return int(settings["n_ctx"])

    die("/props response missing n_ctx")


def build_payload(prompt, file_path):
    context = get_context()

    if context <= MAX_TOKENS:
        die(
            f"Context window {context} <= output tokens {MAX_TOKENS}"
        )

    full_prompt = read_inputs(prompt, file_path)

    estimate = (len(full_prompt) + 3) // 4

    print(
        f"Input chars: {len(full_prompt)}",
        file=sys.stderr,
    )

    print(
        f"Estimated tokens: {estimate}",
        file=sys.stderr,
    )

    if estimate > context - MAX_TOKENS:
        die(
            f"Input requires approximately {estimate} tokens "
            f"but only {context - MAX_TOKENS} available"
        )

    return {
        "messages": [
            {
                "role": "system",
                "content": SYSTEM_PROMPT,
            },
            {
                "role": "user",
                "content": full_prompt,
            },
        ],
        "temperature": 0.1,
        "max_tokens": MAX_TOKENS,
        "stream": True,
    }


def stream_request(payload):
    request = urllib.request.Request(
        ENDPOINT,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {API_KEY}",
        },
    )

    received_done = False
    finish_reason = None
    usage = None
    content_received = False
    server_error = False

    try:
        with urllib.request.urlopen(
            request,
            timeout=TIMEOUT_SECONDS,
        ) as response:

            for raw in response:
                try:
                    line = raw.decode("utf-8").strip()
                except UnicodeDecodeError:
                    die("model response contained invalid UTF-8")

                if not line:
                    continue

                if line == "data: [DONE]":
                    received_done = True
                    continue

                if not line.startswith("data: "):
                    continue

                try:
                    chunk = json.loads(line[6:])
                except json.JSONDecodeError:
                    die("invalid JSON in model stream")

                if "error" in chunk:
                    print(
                        f"server error: {chunk['error']}",
                        file=sys.stderr,
                    )
                    server_error = True
                    continue

                choices = chunk.get("choices", [])

                if choices:
                    choice = choices[0]

                    delta = choice.get(
                        "delta",
                        {},
                    )

                    content = delta.get(
                        "content",
                        "",
                    )

                    if content:
                        try:
                            clean_content = sanitize_output(content)
                            if clean_content:
                                content_received = True
                                sys.stdout.write(clean_content)
                                sys.stdout.flush()
                        except BrokenPipeError:
                            devnull = os.open(os.devnull, os.O_WRONLY)
                            os.dup2(devnull, sys.stdout.fileno())
                            os.close(devnull)
                            raise SystemExit(0)

                    if choice.get("finish_reason"):
                        finish_reason = choice["finish_reason"]

                if chunk.get("usage"):
                    usage = chunk["usage"]

    except urllib.error.HTTPError as exc:
        die(
            f"HTTP error {exc.code}: "
            f"{exc.read().decode(errors='replace')}"
        )

    except urllib.error.URLError as exc:
        die(f"connection error: {exc.reason}")

    except (
        ConnectionResetError,
        ConnectionAbortedError,
        BrokenPipeError,
        EOFError,
        OSError,
    ) as exc:
        die(f"stream connection failed: {exc}")

    except TimeoutError:
        die("request timed out")

    except KeyboardInterrupt:
        die("interrupted")

    try:
        print()
    except BrokenPipeError:
        devnull = os.open(os.devnull, os.O_WRONLY)
        os.dup2(devnull, sys.stdout.fileno())
        os.close(devnull)
        raise SystemExit(0)

    if server_error:
        print(
            "[error: server returned an error]",
            file=sys.stderr,
        )
        raise SystemExit(1)

    if not received_done:
        print(
            "[incomplete stream: missing DONE marker]",
            file=sys.stderr,
        )
        raise SystemExit(1)

    if not content_received:
        print(
            "[error: model returned no content]",
            file=sys.stderr,
        )
        raise SystemExit(1)

    if finish_reason == "length":
        print(
            "[stopped: finish_reason=length]",
            file=sys.stderr,
        )

    elif finish_reason:
        print(
            f"[completed: finish_reason={finish_reason}]",
            file=sys.stderr,
        )

    else:
        print(
            "[completed: finish_reason=unknown]",
            file=sys.stderr,
        )

    if usage:
        print(
            f"[tokens: prompt={usage.get('prompt_tokens')} "
            f"completion={usage.get('completion_tokens')} "
            f"total={usage.get('total_tokens')}]",
            file=sys.stderr,
        )


def main():
    if len(sys.argv) < 2 or len(sys.argv) > 3:
        print(
            "Usage: llm-client2.py \"prompt\" [file]",
            file=sys.stderr,
        )
        raise SystemExit(2)

    prompt = sys.argv[1]
    file_path = sys.argv[2] if len(sys.argv) == 3 else None

    if file_path and not os.path.isfile(file_path):
        die(f"File does not exist or is not regular: {file_path}")

    payload = build_payload(
        prompt,
        file_path,
    )

    stream_request(payload)


if __name__ == "__main__":
    main()
