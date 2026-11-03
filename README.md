# Donatello

Donatello is a local-first Python coding assistant. It processes each coding
request in two phases: a project manager turns the request into ordered JSON
tasks, then a coding agent implements each task in a selected repository and
runs supported tests. Before it changes anything, it shows you what it wants to
do and waits for your approval (see [Approval](#approval)).

## Requirements

- Python 3.10 or later
- [Ollama](https://ollama.com/) running locally, with a model pulled:

  ```sh
  ollama pull qwen2.5-coder:7b
  ```

Donatello uses only the Python standard library at runtime.

## Install and use

From this directory, install the command:

```sh
python -m pip install -e .
```

`--repo` is optional. By default Donatello works on the git repository
containing the current directory (or the current directory itself if it is not
in a git repository). Pass `--repo` to work on a different project. Only `run`
modifies it (`benchmark` accepts `--repo` but does not use the repository).

To call `donatello` from any directory, link the installed command onto your
`PATH`, e.g. `ln -s /path/to/Donatello/.venv/bin/donatello ~/.local/bin/donatello`.
Keep the editable install (`pip install -e .`) in place: configs and the log
file are located relative to this source folder.

Create a plan without modifying the repository (run from inside the project):

```sh
donatello plan "Add input validation to the user registration endpoint"
```

Run the plan against the project, or against another one with `--repo`:

```sh
donatello run "Add input validation to registration"
donatello run --repo /path/to/project "Add input validation to registration"
```

Use another local model or a different Ollama server:

```sh
donatello run --model qwen3:8b \
  --ollama-url http://localhost:11434 "Improve error handling"
```

## Approval

`run` asks for approval before acting. It first shows the proposed plan, then,
for each task, the full path of every file it wants to create or overwrite, why,
the complete code it will write, and the test commands it will run. Prompts go
to stderr; nothing is written or run until you approve.

At each prompt:

- `y` / `yes` approves.
- Any other text is treated as suggested changes; Donatello asks the model to
  revise the plan or task accordingly and shows the new proposal.
- `n` / `no` asks what should change; a blank answer cancels the run.
- `--auto` approves and skips all further approval prompts.

Pass `--auto` on the command line (`donatello run --auto "..."`) to skip
approval entirely. `plan` never asks, since it changes nothing. If input ends
(for example when piped) while a prompt is waiting, the run is cancelled; use
`--auto` for unattended runs.

The coding model is asked to give a `reason` for each file; if it omits one,
the task summary or description is shown instead. Approval is per task, not
per file.

## Configs

Models and system prompts live in JSON files in [configs/](configs). Without
`--config`, `configs/default.json` is used. Copy it to make your own and select
it by file name (the `.json` extension is optional):

```sh
donatello plan --config fast "Add input validation"
donatello run --config fast "Add input validation"
```

Each config defines `planner_model`, `coder_model`, `planner_system_prompt` and
`coder_system_prompt`. `--model` overrides both models.

Generated file paths are restricted to the selected repository. The coding
agent can run Python `unittest` or `pytest` commands returned by the model;
other test commands are rejected.

## Logs

`plan` and `run` append entries to `donatello.log` in the Donatello source
folder (override with the `DONATELLO_LOG_FILE` environment variable). Each entry
is indented, multi-line JSON tagged with a request ID:

- `plan` entries record the original `request`, all command-line `arguments`
  (including the repository actually used), the `plan` (or an `error`) and the
  duration.
- `task` entries record the task, duration, `files_written` as absolute paths,
  and any `error`.

Your home directory is written as `~` in the log. Log write failures are
ignored so they never interrupt a run. `benchmark` does not log.

## External-agent fallback

The local Ollama model remains the primary provider. To configure an
OpenAI-compatible external agent as a fallback for provider failures or
invalid JSON responses, set:

```sh
export DONATELLO_EXTERNAL_BASE_URL=https://your-provider.example/v1
export DONATELLO_EXTERNAL_MODEL=your-model
export DONATELLO_EXTERNAL_API_KEY=your-api-key
```

`DONATELLO_EXTERNAL_API_KEY` is optional for services that do not require
authentication. The equivalent `--external-base-url` and `--external-model`
options are available for `plan` and `run`. If either endpoint or model is
missing, Donatello uses Ollama only.

## Compare models

Benchmark identical prompts on multiple models and review latency, token
counts, whether the response contains valid JSON, and the response itself:

```sh
donatello benchmark --models qwen2.5-coder:7b qwen3:8b \
  --prompt "Return a JSON object with an answer explaining Python decorators."
```

The benchmark does not claim to grade code correctness; its output gives
consistent timing and response-format data to help compare models.

## Development

Run the test suite with:

```sh
python -m unittest discover -s tests -v
```
