# Donatello

Donatello is a local-first Python coding assistant. It processes each coding
request in two phases: a project manager turns the request into ordered JSON
tasks, then a coding agent implements each task in a selected repository and
runs supported tests.

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

Create a plan without modifying a repository:

```sh
donatello plan "Add input validation to the user registration endpoint"
```

Run the plan against another project:

```sh
donatello run --repo /path/to/project "Add input validation to registration"
```

Use another local model or a different Ollama server:

```sh
donatello run --repo /path/to/project --model qwen3:8b \
  --ollama-url http://localhost:11434 "Improve error handling"
```

Generated file paths are restricted to the selected repository. The coding
agent can run Python `unittest` or `pytest` commands returned by the model;
other test commands are rejected.

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
