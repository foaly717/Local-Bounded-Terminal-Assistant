#!/usr/bin/env python3

import json
import os
import re
import sys
import urllib.request
import urllib.error
import tempfile
from datetime import datetime, timedelta, timezone

# Explicit Vulkan topology endpoint
LLM_BASE_URL = "http://172.20.0.100:8080"

ENDPOINT = f"{LLM_BASE_URL}/v1/chat/completions"
PROPS_ENDPOINT = f"{LLM_BASE_URL}/props"

API_KEY = os.environ.get("LLM_API_KEY", "local-only-key")
MAX_TOKENS = int(os.environ.get("LLM_MAX_TOKENS", "1536"))
TIMEOUT_SECONDS = int(os.environ.get("LLM_TIMEOUT", "300"))
MAX_INPUT_BYTES = int(os.environ.get("LLM_MAX_INPUT_BYTES", "1048576"))
SESSION_FILE = os.environ.get(
    "LLM_SESSION_FILE",
    os.path.join(tempfile.gettempdir(), "gpu-ask-vulkan-session.json"),
)
VERBOSE_MODE = False
LOG_DIRECTORY = "/home/lincolnbrennan/agent-workspace/llm-proving-ground/gpu_chat_logs"
LOG_MAX_AGE_DAYS = 180
LOG_STATE_FILE = os.path.join(
    tempfile.gettempdir(),
    "gpu-ask-vulkan-log-session.json",
)

SYSTEM_PROMPT = os.environ.get(
    "LLM_SYSTEM_PROMPT",
    """You are an expert terminal/coding assistant in a Linux system. Use Simplified Technical English wherever possible. Never output Unicode block characters, box-drawing characters, emoji, terminal control sequences, or decorative symbols in terminal commands. Be concise and clear. Only explain your output when asked. Flag any potentially destructive commands you suggest using the plain text word WARNING. Default to code that self-tests.
When suggesting commands against provided files:
- distinguish between how to search a file and actual search results
- never claim a pattern, match, or file content exists unless it was verified from the provided input
When answering from piped input or provided files:
- Prefer facts directly present in the input.
- If the piped input or provided file does not contain the requested information, say FIRST "information not found in provided input" before defaulting to background knowledge.
- Do not invent environment variables, file locations, web UI paths, or commands."""
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


def load_history():
    try:
        with open(SESSION_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return []

    if not isinstance(data, list):
        return []

    return [
        {"role": message["role"], "content": message["content"]}
        for message in data
        if (
            isinstance(message, dict)
            and message.get("role") in {"user", "assistant"}
            and isinstance(message.get("content"), str)
        )
    ]


def save_history(history):
    directory = os.path.dirname(SESSION_FILE) or "."
    os.makedirs(directory, exist_ok=True)

    fd, temporary = tempfile.mkstemp(
        prefix=".gpu-ask-vulkan-",
        suffix=".json",
        dir=directory,
        text=True,
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(history, f, ensure_ascii=False, indent=2)
            f.write("\n")
        os.replace(temporary, SESSION_FILE)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass



def log_path_is_expired(path):
    try:
        modified = datetime.fromtimestamp(
            os.path.getmtime(path),
            timezone.utc,
        )
    except OSError:
        return True

    cutoff = datetime.now(timezone.utc) - timedelta(days=LOG_MAX_AGE_DAYS)
    return modified < cutoff


def load_log_state():
    try:
        with open(LOG_STATE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return None

    path = data.get("path") if isinstance(data, dict) else None

    if not isinstance(path, str):
        return None

    if not os.path.isfile(path):
        return None

    return path


def save_log_state(path):
    temporary = f"{LOG_STATE_FILE}.tmp"

    try:
        with open(temporary, "w", encoding="utf-8") as f:
            json.dump({"path": path}, f)
            f.write("\n")

        os.replace(temporary, LOG_STATE_FILE)

    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def clear_log_state():
    try:
        os.unlink(LOG_STATE_FILE)
    except FileNotFoundError:
        pass


def create_log_path():
    os.makedirs(LOG_DIRECTORY, exist_ok=True)

    timestamp = datetime.now().astimezone().strftime(
        "%Y-%m-%d_%H-%M-%S"
    )

    path = os.path.join(
        LOG_DIRECTORY,
        f"gpu-chat-{timestamp}.json",
    )

    suffix = 1

    while os.path.exists(path):
        path = os.path.join(
            LOG_DIRECTORY,
            f"gpu-chat-{timestamp}-{suffix}.json",
        )
        suffix += 1

    return path


def save_transcript(history, log_path):
    os.makedirs(LOG_DIRECTORY, exist_ok=True)

    existing = None

    try:
        with open(log_path, "r", encoding="utf-8") as f:
            existing = json.load(f)
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        pass

    created_at = (
        existing.get("created_at")
        if isinstance(existing, dict)
        else None
    )

    if not isinstance(created_at, str):
        created_at = datetime.now(timezone.utc).isoformat()

    transcript = {
        "created_at": created_at,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "messages": history,
    }

    fd, temporary = tempfile.mkstemp(
        prefix=".gpu-chat-",
        suffix=".json",
        dir=LOG_DIRECTORY,
        text=True,
    )

    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(
                transcript,
                f,
                ensure_ascii=False,
                indent=2,
            )
            f.write("\n")

        os.replace(temporary, log_path)

    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def update_transcript(history, enable_logging, new_session):
    if new_session:
        clear_log_state()

    log_path = load_log_state()

    if enable_logging:
        if log_path is None or log_path_is_expired(log_path):
            log_path = create_log_path()
            save_log_state(log_path)

    if log_path:
        save_transcript(history, log_path)

        if VERBOSE_MODE:
            print(
                f"[log] transcript={log_path}",
                file=sys.stderr,
            )


def trim_history(history, context):
    available = context - MAX_TOKENS
    if available <= 0:
        die(f"Context window {context} <= output tokens {MAX_TOKENS}")

    turns = []
    current = []

    for message in history:
        current.append(message)
        if message["role"] == "assistant":
            turns.append(current)
            current = []

    if current:
        turns.append(current)

    retained = []
    used_chars = len(SYSTEM_PROMPT)

    for turn in reversed(turns):
        turn_chars = sum(len(message["content"]) for message in turn)
        projected_tokens = (used_chars + turn_chars + 3) // 4
        if projected_tokens > available:
            break
        retained[0:0] = turn
        used_chars += turn_chars

    if VERBOSE_MODE and len(retained) < len(history):
        print(
            f"[session] trimmed {len(history) - len(retained)} old message(s)",
            file=sys.stderr,
        )

    return retained


def build_payload(prompt, file_path):
    context = get_context()

    if context <= MAX_TOKENS:
        die(
            f"Context window {context} <= output tokens {MAX_TOKENS}"
        )

    full_prompt = read_inputs(prompt, file_path)
    history = load_history()
    history.append(
        {
            "role": "user",
            "content": full_prompt,
        }
    )

    retained = trim_history(history, context)
    messages = [
        {
            "role": "system",
            "content": SYSTEM_PROMPT,
        },
        *retained,
    ]

    estimate = (sum(len(message["content"]) for message in messages) + 3) // 4

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
        "messages": messages,
        "temperature": 0.1,
        "max_tokens": MAX_TOKENS,
        "stream": True,
        "chat_template_kwargs": {
            "enable_thinking": False,
        },
    }, history


def save_assistant_response(history, response):
    history.append(
        {
            "role": "assistant",
            "content": response,
        }
    )
    save_history(history)

def stream_request(payload, verbose=False):
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
    response_content = []

    if verbose:
        print(
            f"[verbose] endpoint={ENDPOINT}",
            file=sys.stderr,
        )
        print(
            f"[verbose] max_tokens={payload.get('max_tokens')}",
            file=sys.stderr,
        )
        print(
            f"[verbose] stream={payload.get('stream')}",
            file=sys.stderr,
        )

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

                if verbose:
                    print(
                        f"[verbose] SSE: {json.dumps(chunk, ensure_ascii=False)}",
                        file=sys.stderr,
                    )

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

                    reasoning_content = delta.get(
                        "reasoning_content",
                        "",
                    )

                    if reasoning_content and verbose:
                        print(
                            f"[reasoning] {reasoning_content}",
                            file=sys.stderr,
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
                                response_content.append(clean_content)
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

    return "".join(response_content)


def main():
    args = sys.argv[1:]
    global VERBOSE_MODE
    verbose = False
    log = False

    while args and args[0].startswith("--"):
        if args[0] == "--verbose":
            verbose = True
        elif args[0] == "--log":
            log = True
        else:
            print(
                f"ERROR: unknown option: {args[0]}",
                file=sys.stderr,
            )
            raise SystemExit(2)

        args = args[1:]

    VERBOSE_MODE = verbose

    if len(args) < 1 or len(args) > 2:
        print(
            'Usage: llm-client-vulkan.py [--verbose] [--log] "prompt" [file]',
            file=sys.stderr,
        )
        raise SystemExit(2)

    prompt = args[0]
    file_path = args[1] if len(args) == 2 else None

    if file_path and not os.path.isfile(file_path):
        die(f"File does not exist or is not regular: {file_path}")

    new_session = not os.path.exists(SESSION_FILE)

    payload, history = build_payload(
        prompt,
        file_path,
    )

    response = stream_request(
        payload,
        verbose=verbose,
    )

    if response:
        save_assistant_response(history, response)
        update_transcript(
            history,
            log,
            new_session,
        )


if __name__ == "__main__":
    main()
