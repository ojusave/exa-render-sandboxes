<!-- Keep the project identity, supported clients, and useful navigation together. -->
<div align="center">

# Exa + Render Sandboxes

Repair Python code with Exa, Claude, and Render Sandboxes.

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

The sample Python report uses Polars, a library for working with tables, but breaks on version 2.0. This example asks Claude Haiku to fix it. Exa finds the current docs, and Render Sandboxes runs the proposed code to check whether it works.

You can run the example from Python or TypeScript. That program runs on your computer, calls Claude through OpenRouter, and sends the generated Python code to a temporary Linux environment on Render.

It also tries the same repair without Exa, so you can compare the two. Each version gets up to two attempts, then a fresh sandbox tests the final code. There are 15 test cases, including 12 that Claude doesn't see while working on the fix.

## Prerequisites

You'll need Git and **Python 3.11+ or Node.js 22+**, with a terminal on macOS or Linux. You'll also need <a href="https://render.com/docs/sandboxes#1-confirm-access" target="_blank" rel="noopener noreferrer">Render Sandbox access</a>, an <a href="https://dashboard.exa.ai/api-keys" target="_blank" rel="noopener noreferrer">Exa key</a>, and <a href="https://openrouter.ai/settings/keys" target="_blank" rel="noopener noreferrer">OpenRouter credit</a>. Render Sandboxes is in early access.

The default comparison uses five paid sandboxes, one Exa search, and up to four model requests. Your keys aren't passed to the sandboxes. When the run finishes, the program stops the sandboxes and deletes the saved setup it used to create them.

## Quickstart

### 1. Get the code

```sh
# Download the source and enter the project folder.
git clone https://github.com/ojusave/exa-render-sandboxes.git
cd exa-render-sandboxes
# Create a private settings file, excluded from Git.
cp .env.example .env
chmod 600 .env
```

Open `.env` and fill in `RENDER_API_KEY`, `RENDER_WORKSPACE_ID`, `EXA_API_KEY`, and `OPENROUTER_API_KEY`. The keys let the program use your accounts. The workspace ID tells Render where to create the sandboxes. <a href="guides/exa-sandboxes.md#prerequisites" target="_blank" rel="noopener noreferrer">Where to get each value.</a>

### 2. Load your settings

Run these commands in the same terminal, from the repository folder:

```sh
# Make the settings available to programs started from this terminal.
set -a
. ./.env
# Restore the usual behavior for settings defined later.
set +a
```

### 3. Run the comparison

Choose Python or TypeScript below. Either one runs the full comparison; running both means paying for two runs.

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

Setup can take several minutes without printing anything. When the run finishes, you'll see where it saved `run.json`, the results file. If the run stops before cleanup finishes, follow the <a href="guides/exa-sandboxes.md" target="_blank" rel="noopener noreferrer">full guide</a> to stop any remaining sandboxes.

## Expected result

Here's the end of a completed TypeScript run. The times will vary from run to run:

```text
baseline repetition 1: 15/15 checks, 20.2s
exa repetition 1: 15/15 checks, 22.1s
Cleanup verified: true
```

`baseline` means Claude worked without Exa. We tested both programs, and all four repairs passed all 15 checks. Claude fixed this particular task with or without the docs, so these results don't show that Exa improved the repair. The <a href="VALIDATION.md" target="_blank" rel="noopener noreferrer">test results</a> include all four runs and their limits.

Each run gets its own folder under `.runs/`, with the repaired Python files and a `run.json` report. The report lists the tests, sources Exa found, reported model and search costs, and whether cleanup finished. These files stay on your computer after the sandboxes are gone.

## Explore the project

| File | What it covers |
| --- | --- |
| <a href="guides/exa-sandboxes.md" target="_blank" rel="noopener noreferrer">Full walkthrough</a> | How the pieces fit together, setup, and what to do if a run fails |
| <a href="python/main.py" target="_blank" rel="noopener noreferrer">Python client</a> · <a href="typescript/main.ts" target="_blank" rel="noopener noreferrer">TypeScript client</a> | Start here to change how the comparison runs |
| <a href="shared/starter.py" target="_blank" rel="noopener noreferrer">Broken module</a> · <a href="shared/cases.json" target="_blank" rel="noopener noreferrer">Test cases</a> | The reporting task and expected answers |
| <a href="VALIDATION.md" target="_blank" rel="noopener noreferrer">Validation</a> · <a href="examples/verified" target="_blank" rel="noopener noreferrer">Verified repairs</a> | What happened in the test runs, plus the fixes Claude wrote |

## Development

After installing the libraries for the language you're using, run its checks below. They run on your computer and don't need keys or create cloud charges.

```sh
# Check Python behavior and the published evidence.
python/.venv/bin/python -m unittest discover -s tests -v
# Check TypeScript types and behavior.
npm run check --prefix typescript
npm run test --prefix typescript
```

<a href="LICENSE" target="_blank" rel="noopener noreferrer">MIT license</a> · <a href="https://github.com/ojusave/render-workflows-exa-langchain" target="_blank" rel="noopener noreferrer">Exa + Render Workflows</a> · <a href="https://github.com/ojusave/openrouter-sandboxes" target="_blank" rel="noopener noreferrer">OpenRouter + Render Sandboxes</a>
