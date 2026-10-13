# Exa + Render validation

Tested October 13, 2026. Both native clients completed a real comparison with `anthropic/claude-haiku-5.5` through OpenRouter, live Exa Search, and paid Render Sandboxes.

**Result:** all four generated repairs passed all 15 checks in fresh verification sandboxes. The no-search model also succeeded, so this pilot demonstrates integration correctness but provides no measured repair-success advantage for Exa on this task.

## Observed comparison

| Client | Mode | Checks passed | Model attempts | Time | Model cost | Exa cost |
| --- | --- | --- | --- | --- | --- | --- |
| Python | Without search | 15/15 | 1 | 20.3s | $0.0006488 | $0.000 |
| Python | With Exa | 15/15 | 1 | 21.9s | $0.0026187 | $0.007 |
| Typescript | Without search | 15/15 | 1 | 20.2s | $0.0006762 | $0.000 |
| Typescript | With Exa | 15/15 | 1 | 22.1s | $0.0022474 | $0.007 |

The four successful model requests cost $0.0061911 in reported model usage. Two comparison searches cost $0.014, for $0.0201911 combined. Two earlier diagnostic searches add $0.014. These figures exclude Render compute and snapshot charges, which this runner does not calculate. Two rejected model requests returned no usage amount; their cost is unknown rather than assumed zero.

Time covers initial public checks, optional search, model response, repair checks, fresh-machine verification and termination. Package setup, fixture calibration and initial repair-machine creation are excluded. One pair ran per client, without search first. This is too small and order-sensitive to draw general quality or latency conclusions. The fixture and query were selected by the maintainer, and both clients test the same task rather than independent problems.

Observed terminal output, abbreviated to result lines:

```text
Python:
baseline repetition 1: 15/15 checks, 20.3s
exa repetition 1: 15/15 checks, 21.9s
Cleanup verified: True

TypeScript:
baseline repetition 1: 15/15 checks, 20.2s
exa repetition 1: 15/15 checks, 22.1s
Cleanup verified: true
```

## What was independently checked

- Polars 2.0.0 was installed in Render, and all three original public cases failed as intended.
- The maintained reference solution passed all 15 cases before any model repair. It was not sent to the model.
- Each model-produced source file was saved and fingerprinted before held-out tests ran. The same bytes were uploaded into a separate verification sandbox.
- Fifteen checks covered unequal columns, empty columns, missing values, category ordering, empty categories, empty dates, leap dates, century boundaries and invalid dates.
- Each client's timeout probe was stopped, excessive output was capped, and application credentials were absent inside the execution environment.
- Both HTTPS probes to PyPI reached the eight-second execution deadline under an effective `deny-all` network policy. The matching local requests returned HTTP 200. This is a tested destination and observed timeout, not proof against every possible network bypass.
- Independent final API reads confirmed all **23** test-owned sandboxes terminated and all **7** snapshots absent. The count includes initial setup probes and diagnostic runs. No unknown creation outcomes remain.

The four final repairs are normal Polars operations, not fabricated test-output messages. The no-search model used an alternative label-mapping approach; the Exa-assisted repairs used the documented category conversion. The harness checks behavior, not whether a particular implementation was chosen. It is not a general defense against deliberately adversarial generated programs, and it does not measure runtime efficiency on large tables or malformed inputs beyond the declared cases.

## Local verification and versions

Publication checks add two evidence-integrity tests: **11 Python tests and 9 TypeScript tests pass**. The live execution files and saved repairs still match their recorded fingerprints. GitHub Actions runs these local checks on pushes and pull requests without provider keys or paid requests.

- 9 Python tests and 9 TypeScript tests passed. They cover candidate shape and byte limits, output judging, malformed results, held-out prompt exclusion, matched prompts, exhausted-credit preflight, incomplete command streams, output limits, lost deletion replies, snapshot pagination and unknown creation outcomes.
- TypeScript's type check passed.
- Clean installation from `python/requirements.txt` succeeded. The real Python comparison used the existing repository environment with Render 1.2.0 and HTTPX 0.28.1; the new isolated environment was also checked for imports and local tests.
- Python client runtime: 3.13.14. Node.js: 24.18.0. TypeScript: 6.0.3. TSX: 4.23.15. Both Render SDKs: 1.2.0. Executed library: Polars 2.0.0.
- Source fingerprints, the four generated repairs, per-case verification output and sanitized comparison summaries are in <a href="evidence.json" target="_blank" rel="noopener noreferrer">`evidence.json`</a>. Complete run journals and provider identifiers remain in the maintainer's ignored `.runs` folder. Public repair files are under `examples/verified/`.
- The local guide was rendered at 1120px and 390px widths. The diagram is readable, no page overflow was detected, all six language sections opened, and authored links use a new tab with safe link attributes. The diagram is included in `docs/flow.svg`.

## Failures found and retained

1. The first package-install probe hit Python's system-environment protection. Package installation now uses a separate virtual environment inside Render.
2. The first model request returned HTTP 404 because the selected model did not support the requested temperature setting. Both clients now omit that setting and check endpoint capabilities before creating machines.
3. The next request returned HTTP 402 because the original OpenRouter account had exhausted credit. Both clients now check account and key limits before allocation. A replacement key with available credit was used only in the client process.
4. The first network check assumed a connection exception. Render's deny-all environment instead left the request waiting until the process deadline. The final probes preserve the actual timeout and successful host-control response.
5. The first TypeScript integration check encountered certificate validation failure because the helper discarded this machine's certificate trust paths. The helper now preserves those paths without disabling certificate verification.
6. Review found that a repeated snapshot deletion could be falsely reported as failed after an earlier deletion succeeded. Both clients now resolve the outcome by independently checking the full snapshot listing; local tests cover a lost delete reply and later-page matches.

All failed run journals were retained. Each failed allocation path cleaned up its recorded resources, and the final independent check included them.

## Sources and interpretation

The fixture follows the <a href="https://docs.pola.rs/releases/upgrade/2/" target="_blank" rel="noopener noreferrer">Polars 2 migration guide</a>. The search request is fixed in <a href="shared/contract.json" target="_blank" rel="noopener noreferrer">the shared contract</a>, scoped to official Polars domains. Retrieved public URLs are included in the evidence; both clients used the same task, model settings and two-attempt limit.

Exa's <a href="https://exa.ai/blog/webcode" target="_blank" rel="noopener noreferrer">WebCode research</a> is a precedent for measuring search through executable coding tasks. Broader claims require additional independently chosen tasks. This first fixture shows equal pass rates with and without Exa.
