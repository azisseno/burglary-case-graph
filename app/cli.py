import json
import subprocess
from pathlib import Path


class CliError(RuntimeError):
    pass


runner = subprocess.run

STDERR_TAIL_CHARS = 800


def build_command(schema, model, allowed_tools, mcp_config, max_turns, builtin_tools=""):
    command = [
        "claude", "-p",
        "--model", model,
        "--output-format", "json",
        "--no-session-persistence",
        "--tools", builtin_tools,
    ]
    if allowed_tools:
        command.append(f"--allowedTools={','.join(allowed_tools)}")
    if schema is not None:
        command += ["--json-schema", json.dumps(schema)]
    if mcp_config is not None:
        command += ["--mcp-config", str(mcp_config), "--strict-mcp-config"]
    if max_turns is not None:
        command += ["--max-turns", str(max_turns)]
    return command


def parse_envelope(stdout):
    try:
        envelope = json.loads(stdout)
    except json.JSONDecodeError as error:
        raise CliError(f"claude printed invalid JSON: {error}; head: {stdout[:200]}") from error
    if not isinstance(envelope, dict):
        raise CliError("claude envelope is not an object")
    if envelope.get("is_error"):
        raise CliError(f"claude reported an error: {str(envelope.get('result'))[:STDERR_TAIL_CHARS]}")
    return envelope


def parse_result(envelope, schema):
    result = envelope.get("result")
    if schema is None:
        return result
    if isinstance(envelope.get("structured_output"), (dict, list)):
        return envelope["structured_output"]
    if isinstance(result, (dict, list)):
        return result
    try:
        return json.loads(result)
    except (TypeError, json.JSONDecodeError) as error:
        raise CliError(f"result is not valid JSON: {error}; head: {str(result)[:200]}") from error


def write_run_log(run_dir, step, entry):
    folder = Path(run_dir)
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{step}.json").write_text(json.dumps(entry, indent=2, default=str))


def scratch_folder(run_dir):
    folder = Path(run_dir) / "scratch"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def run_claude(prompt, schema=None, model="sonnet", cwd=None, allowed_tools=(), builtin_tools="",
               mcp_config=None, max_turns=None, timeout=240, run_dir=None, step=None):
    command = build_command(schema, model, allowed_tools, mcp_config, max_turns, builtin_tools)
    if cwd is None and run_dir is not None:
        cwd = scratch_folder(run_dir)
    entry = {"prompt": prompt, "command": command, "returncode": None, "stdout": None,
             "stderr_tail": None, "result": None, "error": None}
    try:
        try:
            completed = runner(command, cwd=str(cwd) if cwd else None, capture_output=True,
                               text=True, timeout=timeout, input=prompt)
        except subprocess.TimeoutExpired as error:
            raise CliError(f"claude timed out after {timeout}s") from error
        except OSError as error:
            raise CliError(f"claude could not start: {error}") from error
        entry.update(returncode=completed.returncode, stdout=completed.stdout,
                     stderr_tail=(completed.stderr or "")[-STDERR_TAIL_CHARS:])
        if completed.returncode != 0:
            raise CliError(f"claude exited {completed.returncode}: {entry['stderr_tail']}")
        envelope = parse_envelope(completed.stdout)
        parsed = parse_result(envelope, schema)
        entry.update(stdout=None, result=parsed,
                     envelope={key: value for key, value in envelope.items() if key != "result"})
        return parsed
    except CliError as error:
        entry["error"] = str(error)
        raise
    finally:
        if run_dir is not None:
            write_run_log(run_dir, step or "step", entry)
