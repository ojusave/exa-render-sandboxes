<!-- Keep the project identity, supported clients, and useful navigation together. -->
<div align="center">

# Exa + Render Sandboxes

Compare AI code repairs with and without Exa search, then verify the results on Render.

<!-- Each badge links to the product, implementation, or real automated check it names. -->
<p>
  <a href="https://render.com/docs/sandboxes" target="_blank" rel="noopener noreferrer"><img src="https://img.shields.io/badge/Render-Sandboxes-6e40c9?logo=render&amp;logoColor=white" alt="Render Sandboxes" /></a>
  <a href="https://exa.ai/docs" target="_blank" rel="noopener noreferrer"><img src="https://img.shields.io/badge/Exa-Search-111111" alt="Exa Search" /></a>
  <a href="python/main.py" target="_blank" rel="noopener noreferrer"><img src="https://img.shields.io/badge/Python-Client-3776AB?logo=python&amp;logoColor=white" alt="Python client" /></a>
  <a href="typescript/main.ts" target="_blank" rel="noopener noreferrer"><img src="https://img.shields.io/badge/TypeScript-Client-3178C6?logo=typescript&amp;logoColor=white" alt="TypeScript client" /></a>
  <a href="https://github.com/ojusave/exa-render-sandboxes/actions/workflows/checks.yml" target="_blank" rel="noopener noreferrer"><img src="https://github.com/ojusave/exa-render-sandboxes/actions/workflows/checks.yml/badge.svg?branch=main" alt="Automated checks on main" /></a>
</p>

<p>
  <a href="#quickstart"><strong>Quickstart</strong></a>
  · <a href="guides/exa-sandboxes.md" target="_blank" rel="noopener noreferrer">Full guide</a>
  · <a href="#expected-result">Expected result</a>
  · <a href="VALIDATION.md" target="_blank" rel="noopener noreferrer">Test results</a>
</p>

</div>

A library upgrade breaks a Python reporting module. Exa finds the current documentation, Claude Haiku through OpenRouter proposes a fix, and Render Sandboxes runs the code on temporary Linux computers. Your local Python or TypeScript client coordinates the work and compares the output with fixed answers.

Both clients run the same experiment: give the model the broken code **with and without Exa's documentation**, allow up to two repair attempts, and check each final repair in a fresh sandbox. Each repair faces 15 tests, including 12 inputs the model did not see.

## Prerequisites

Git, a macOS/Linux terminal, and **Python 3.11+ or Node.js 22+**. You also need <a href="https://render.com/docs/sandboxes#1-confirm-access" target="_blank" rel="noopener noreferrer">Render Sandbox access</a>, an <a href="https://dashboard.exa.ai/api-keys" target="_blank" rel="noopener noreferrer">Exa key</a>, and <a href="https://openrouter.ai/settings/keys" target="_blank" rel="noopener noreferrer">OpenRouter credit</a>. Render Sandboxes is in early access.

A default run uses five paid temporary sandboxes, one Exa search, and at most four model requests. Keys stay in the local client. The client stops its sandboxes and deletes its prepared snapshot after the run.

## Quickstart

### 1. Download and configure

```sh
# Download the source and enter the project folder.
git clone https://github.com/ojusave/exa-render-sandboxes.git
cd exa-render-sandboxes
# Create a private settings file, excluded from Git.
cp .env.example .env
chmod 600 .env
```

Open `.env` and fill in `RENDER_API_KEY`, `RENDER_WORKSPACE_ID`, `EXA_API_KEY`, and `OPENROUTER_API_KEY`. The keys authorize requests to your accounts; the workspace ID selects where Render runs the code. <a href="guides/exa-sandboxes.md#prerequisites" target="_blank" rel="noopener noreferrer">Where to get each value.</a>

### 2. Load your settings

Run these commands in the same terminal, from the repository folder:

```sh
# Make the settings available to programs started from this terminal.
set -a
. ./.env
# Restore the usual behavior for settings defined later.
set +a
```

### 3. Choose one client

Both options run the complete comparison. Running both makes two sets of paid requests.

<!-- Each section contains installation and execution so readers can follow one language. -->
<details open>
<summary><strong>Python</strong></summary>

```sh
# Keep this client's libraries in a separate local environment.
python3 -m venv python/.venv
python/.venv/bin/python -m pip install -r python/requirements.txt
# Compare both modes and save the results under .runs/.
python/.venv/bin/python python/main.py compare
```

</details>

<details>
<summary><strong>TypeScript</strong></summary>

```sh
# Install the library versions recorded in the lockfile.
npm ci --prefix typescript
# Compare both modes and save the results under .runs/.
npm run compare --prefix typescript
```

</details>

The client prints the location of `run.json`, which records the results. Cloud setup can be quiet for several minutes. The <a href="guides/exa-sandboxes.md" target="_blank" rel="noopener noreferrer">full guide</a> explains each step and provides cleanup recovery commands.

## Expected result

Abbreviated output from the real TypeScript run; timings vary:

```text
baseline repetition 1: 15/15 checks, 20.2s
exa repetition 1: 15/15 checks, 22.1s
Cleanup verified: true
```

`baseline` is the mode without search. **Both modes passed all 15 tests in both languages.** This task demonstrates a working integration, but showed no repair-success improvement from Exa. See the <a href="VALIDATION.md" target="_blank" rel="noopener noreferrer">measured results and limits</a> before drawing broader conclusions.

Each run saves its repaired Python files and `run.json` in a new `.runs/` folder. The report includes test results, search sources, reported model/search costs, and cleanup status. The local files remain after remote cleanup.

## Explore the project

| Start here | What you will find |
| --- | --- |
| <a href="guides/exa-sandboxes.md" target="_blank" rel="noopener noreferrer">Full walkthrough</a> | Architecture, credentials, execution, cleanup and recovery |
| <a href="python/main.py" target="_blank" rel="noopener noreferrer">Python client</a> · <a href="typescript/main.ts" target="_blank" rel="noopener noreferrer">TypeScript client</a> | The two implementations of the same comparison |
| <a href="shared/starter.py" target="_blank" rel="noopener noreferrer">Broken module</a> · <a href="shared/cases.json" target="_blank" rel="noopener noreferrer">Test cases</a> | The reporting task and expected answers |
| <a href="VALIDATION.md" target="_blank" rel="noopener noreferrer">Validation</a> · <a href="examples/verified" target="_blank" rel="noopener noreferrer">Verified repairs</a> | Live evidence and the exact generated code that passed |

## Development

After installing the corresponding client libraries, these checks run locally without provider keys or cloud charges:

```sh
# Check Python behavior and the published evidence.
python/.venv/bin/python -m unittest discover -s tests -v
# Check TypeScript types and behavior.
npm run check --prefix typescript
npm run test --prefix typescript
```

<a href="LICENSE" target="_blank" rel="noopener noreferrer">MIT license</a> · <a href="https://github.com/ojusave/render-workflows-exa-langchain" target="_blank" rel="noopener noreferrer">Exa + Render Workflows</a> · <a href="https://github.com/ojusave/openrouter-sandboxes" target="_blank" rel="noopener noreferrer">OpenRouter + Render Sandboxes</a>
