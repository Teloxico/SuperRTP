# AGENTS.md

# SuperRTP Agent Operating Contract

Read this before working in this repository.

SuperRTP is a standalone clean-room compatibility and open-resource project for legacy RPG engines. Correctness, provenance, compatibility, and observed runtime behavior matter more than producing large amounts of code.

The objective is a **verified working result**.

> **Writing code is not progress by itself. Do not compensate for uncertainty by generating more code. Reduce uncertainty first.**

## 1. Priorities

When rules conflict, use this order:

1. Protect clean-room and licensing integrity.
2. Preserve user work and existing correct behavior.
3. Establish facts before acting on uncertain assumptions.
4. Produce the smallest complete solution to the actual requirement.
5. Verify the real result with the strongest practical evidence.
6. Keep the implementation maintainable, searchable, and understandable.
7. Optimize speed, token use, and convenience only after the above.

Do not optimize for appearing productive.

## 2. Project Boundary and Host Safety

SuperRTP is independent of Nebula and other launchers. Do not introduce dependencies on Nebula architecture, APIs, file layout, or assumptions. Other applications may consume SuperRTP later through stable interfaces.

Treat this repository as the writable project boundary unless the user explicitly grants another location.

Normal autonomous work includes repository edits, builds, tests, validators, converters, runtimes, project-local dependency installation, generated artifacts, and ordinary Git operations.

Do not autonomously:

- modify unrelated repositories or user files;
- remove system packages;
- alter host security settings;
- use `sudo` merely to make development tooling work;
- weaken browser, OS, container, or filesystem security to bypass tooling problems;
- destroy or overwrite pre-existing user work.

If tooling fails because of permissions or security policy, diagnose the root cause and prefer a scoped project-level solution.

## 3. Clean-Room Invariant

SuperRTP MUST contain zero proprietary RTP creative content.

Never copy, trace, redraw, recolor, remix, extract, AI-transform, or otherwise derive redistributable creative assets from proprietary RPG Maker or WOLF RTP material. Do not use proprietary RTP creative assets as image/audio generation references.

Functional interoperability facts may be documented where legally permitted, including filenames, paths, file formats, dimensions, frame geometry, animation layouts, lookup behavior, semantic roles, and compatibility behavior.

Every external creative asset entering SuperRTP must have documented provenance and redistribution-compatible licensing.

If provenance or redistribution rights are uncertain, do not import the asset.

Do not interpret phrases such as "free", "free to use", "free for games", or "non-commercial use allowed" as permission to redistribute raw assets.

Legal uncertainty is a blocker, not an implementation detail.

## 4. Work Loop

For non-trivial work, follow this loop:

1. Inspect `git status` and preserve existing user changes.
2. Inspect the relevant repository structure and current implementation.
3. Read affected callers/consumers and relevant tests, fixtures, schemas, validators, and docs.
4. Separate known facts, inferences, and unknowns.
5. Research external facts when required by Section 5.
6. Decide the smallest complete approach and how it will be verified.
7. Implement one coherent increment.
8. Run mechanical checks.
9. Exercise the real runtime/user flow where applicable.
10. Inspect generated artifacts and screenshots where applicable.
11. Fix failures and repeat verification.
12. Inspect the final diff against the requested outcomes before claiming completion.

For multi-part work, maintain a finite checklist tied to the user's requested outcomes. Do not silently drop secondary requirements because context became large.

Before substantial edits, be able to answer concisely:

- What problem is actually being solved?
- What mechanism will be used?
- Why this mechanism rather than realistic alternatives?
- What assumptions does it depend on?
- What evidence will prove completion?

Do not turn routine implementation into a long planning essay. Do not ask the user to decide routine implementation choices that can be resolved from evidence.

## 5. Research Gate

Internet research is REQUIRED when implementation depends on external facts that may be current, undocumented locally, legally significant, version-sensitive, security-sensitive, or easy to misremember.

Typical triggers include engine behavior/file formats, EasyRPG, mkxp-z, WOLF RPG Editor, licensing, current third-party APIs, library/platform compatibility, upstream bugs/releases, and current tooling/configuration syntax.

Prefer sources in this order:

1. official specifications/documentation;
2. current upstream source code;
3. official issue trackers/release notes;
4. maintainer statements;
5. high-quality technical references;
6. community reports only where primary sources do not cover the behavior.

Community reports are evidence of experience, not proof of general behavior.

Do not implement from model memory when current documentation or source code can answer the question.

For ordinary factual research, prefer structured/textual retrieval such as official docs, source repositories, `gh`, `curl`, search tools, package metadata, release notes, and issue trackers. Use an interactive browser only when live page state, authentication state, visual behavior, or UI interaction is genuinely required.

When research materially determines architecture, compatibility, or licensing, preserve the decision-relevant references in the appropriate project document, provenance record, or implementation note.

Stop researching when additional searching is unlikely to change the implementation decision.

## 6. Implementation Discipline

### No code avalanche

Do not generate large implementations before understanding the integration point, constraints, and failure modes.

Prefer vertical slices that prove something meaningful in the real system.

Example:

    one clean asset
      -> provenance validation
      -> compatibility mapping
      -> deterministic conversion/build
      -> target runtime
      -> inspected result

Large systems should grow from verified slices. Do not build infrastructure merely because a future system might need it.

### No hidden placeholders

Never hide unfinished work behind TODO/FIXME implementations, empty/no-op functions where behavior is expected, `pass`/`NotImplemented` production paths, stub handlers, hard-coded success values, fake data presented as real output, mock production paths, disabled validation, swallowed exceptions, catch-all fallbacks, silently skipped requirements, or disconnected UI that only looks functional.

Placeholders are allowed only when explicitly requested or an unavoidable external blocker prevents completion. If one is unavoidable, make it visible, state exactly what is missing, and do not report the feature complete.

Before reporting substantial work complete, inspect changed files for accidental placeholders and concealed fallback/no-op paths.

A superficially working result is worse than an explicitly incomplete result.

### Code quality

Prefer the simplest mechanism that completely satisfies the requirement.

Follow existing project patterns unless evidence shows they are unsuitable.

Avoid speculative abstraction, premature generalization, unrelated refactoring, excessive indirection, enormous god files, dozens of microscopic files, duplicate sources of truth, and clever code that is difficult to search.

Modules should represent meaningful responsibilities, not arbitrary line-count targets.

Comments should explain non-obvious reasons, constraints, compatibility behavior, or provenance requirements. Do not narrate obvious code.

Prefer deterministic programs over model judgment whenever correctness can be expressed mechanically.

## 7. Dependencies and Environment

Before adding a dependency, confirm the existing stack does not already solve the problem, verify maintenance and license status, check platform compatibility, and understand why the dependency is preferable to a small local implementation.

Project-local development dependencies may be installed autonomously.

Prefer project-local tooling over global installation where practical.

Do not use `sudo` for npm/pnpm/pip merely to bypass an install-scope permissions error.

Do not remove or replace existing dependencies merely to satisfy preference. Do not perform unrelated system-wide package changes.

## 8. Verification Standard

A task is not complete because code exists, compiles, or passes unit tests.

Verification must exercise the behavior the user actually cares about.

Where correctness can be checked mechanically, prefer deterministic checks such as schemas, dimensions/frame counts, hashes, provenance completeness, license metadata, generated paths, parsers, reproducible builds, tests, and static analysis.

Do not ask an LLM to judge something a deterministic program can verify.

When behavior depends on a real runtime, exercise the real runtime. For compatibility work, prefer an actual minimal fixture running through the target runtime over assumptions based only on file layout.

Examples include EasyRPG Player for RM2000/RM2003, mkxp-z for XP/VX/VX Ace, and appropriate WOLF execution/conversion tooling where applicable.

Inspect logs, runtime output, generated files, and observable behavior. If a generated artifact is the deliverable, inspect the artifact itself rather than inferring correctness from the generator's exit code.

## 9. Antigravity 2.0, Browser, and Visual Verification

This project is intended to work under Antigravity 2.0.

Use project skills when they match the task instead of re-inventing their instructions.

For browser-visible or interactive web work, use both workspace skills:

- `browser-verification`
- `playwright-cli`

Use the project-local CLI:

    npx --no-install playwright-cli

`.playwright/cli.config.json` is the source of truth for browser configuration. Do not override it casually.

Do not use the browser subagent for ordinary factual research when docs, source, search, `gh`, `curl`, or another structured source can answer the question more directly.

Use Antigravity's native browser mainly for exploratory investigation, hard-to-reproduce authenticated state, or live visual debugging where Playwright is unsuitable. For repeatable verification, prefer Playwright.

### Browser hard rules

- Start from a known state and define the expected observable result.
- Prefer semantic locators/roles/labels over coordinate clicking.
- Perform one meaningful interaction at a time and inspect the resulting state.
- Never assume a click/navigation succeeded merely because the command returned successfully.
- If the same intended interaction fails twice, STOP. Inspect page state, URL, console, requests, logs, DOM, and the original assumption before trying a different mechanism.
- Do not fix browser flakiness by blindly adding sleeps or repeatedly changing selectors.

### Screenshot hard rule

For visually meaningful states:

1. reach the state through the real user flow;
2. capture a screenshot under `artifacts/browser/`;
3. **open/view the screenshot with an image-capable tool**;
4. inspect it visually;
5. fix visible defects;
6. repeat the flow and inspect the corrected result.

**Creating a screenshot without opening and inspecting it does not count as visual verification.**

Do not claim visual verification from DOM structure, source/CSS inspection, compilation, a Playwright snapshot alone, screenshot creation alone, or an automated assertion that an element exists.

If screenshot inspection is unavailable, report the result as **VISUALLY UNVERIFIED**.

When browser behavior is suspicious, inspect console and requests. Do not hide runtime/console failures merely because the page appears acceptable.

Do not run Playwright with `sudo`. Do not disable Chromium sandboxing, weaken AppArmor, or change host security settings merely to make browser automation work.

For non-browser/native visual work, where tools permit: launch the real application/runtime, interact with the actual UI using keyboard/mouse/cursor actions, capture decision-relevant screenshots, open and inspect them, inspect runtime logs, fix defects, and repeat the flow.

## 10. Tests and Debugging

Tests support the result. Tests are not the result.

Write tests when they protect meaningful behavior, compatibility contracts, transformations, regressions, or difficult edge cases.

Prefer a small number of high-value tests over hundreds of shallow assertions. Do not manufacture huge test suites to create the appearance of rigor or overfit tests to implementation details.

For important user-facing or compatibility behavior, combine tests with actual runtime evidence. A passing test does not override contradictory real-world behavior.

When something fails:

1. read the complete error/output;
2. reproduce the failure;
3. identify the failing layer;
4. compare against a working/reference case when available;
5. form one specific hypothesis;
6. make the smallest change that tests it;
7. verify before making another change.

If two materially similar fix attempts fail, stop iterating blindly and reassess the assumption or architecture.

Fix root causes rather than masking symptoms. Do not convert warnings/errors into ignored output merely to obtain a green command.

## 11. Git and Autonomy

Git is part of normal autonomous work.

Before editing, inspect `git status` and preserve pre-existing user changes. During substantial work, use coherent commits for coherent completed units, inspect the diff before committing, and avoid unrelated formatting churn.

Allowed without routine approval when appropriate to the task: status, diff, add, commit, branch/switch, safe stash, merge/rebase when clearly required, and ordinary remote fetch/pull/push when the repository is configured for it and the task expects it.

Never force-push protected/main branches, destroy unrelated user work, silently discard existing modifications, rewrite unrelated history, or use destructive cleanup merely to obtain a clean working tree.

A clean Git status is not evidence that the feature works.

Proceed autonomously through ordinary research, implementation, project-local dependency installation, debugging, testing, verification, and Git operations.

Escalate only when:

- two materially different interpretations remain after investigation;
- an architectural choice has significant irreversible consequences;
- legal/licensing evidence remains genuinely ambiguous;
- required credentials or permissions are unavailable;
- an action would affect data/systems outside the granted project scope;
- a destructive action could discard user work;
- the user's explicit decision is genuinely required.

Investigate before escalating. Do not turn ordinary uncertainty into repeated permission requests.

## 12. SuperRTP Architecture and AI Assets

SuperRTP should ultimately maintain one canonical source of compatibility and asset metadata rather than six independently maintained RTP packs.

Prefer the conceptual flow:

    canonical source
      -> provenance
      -> semantic identity
      -> compatibility mapping
      -> deterministic transformation
      -> target-specific output
      -> runtime verification

Engine-specific outputs are generated artifacts, not independent sources of truth.

Compatibility slots and creative assets are distinct concepts. A filename expected by an engine describes a compatibility requirement; it does not make an independently created asset semantically identical to the proprietary asset that historically occupied that slot.

Keep faithful compatibility behavior and generic fallback behavior distinguishable.

Do not freeze speculative architecture prematurely. Validate architecture through small working vertical slices.

AI may be used to create original assets. Do not provide proprietary RTP creative assets as generation references.

Prefer neutral functional specifications, original project-owned references, geometric templates, masks, palettes, and independently licensed source material where the license permits the intended use.

Retain useful generation provenance such as model/provider, model version when known, prompt/specification, generation date, and relevant seed/settings when available.

For animated sprites, tiles, and other structured assets, visual plausibility is not sufficient. Validate structural properties deterministically.

## 13. Completion and Evidence

Use completion words precisely:

- **Implemented**: the implementation exists.
- **Tested**: the stated tests were actually executed.
- **Verified**: the relevant real behavior/artifact was actually examined.
- **Visually verified**: the relevant screenshot/UI state was actually opened and inspected.
- **Working**: the observed end-to-end behavior succeeded.
- **Complete**: the requested scope is implemented with no known hidden placeholders or unreported blockers.

If a check was not run, say **NOT RUN**.

If behavior was not observed, say **UNVERIFIED**.

If visual state was not inspected, say **VISUALLY UNVERIFIED**.

Before reporting substantial work complete, perform one focused adversarial review:

- Did I implement every requested outcome?
- Did I silently drop a secondary requirement?
- Did I introduce a placeholder or concealed fallback?
- Did I rely on an unverified external assumption?
- Did I change unrelated behavior?
- Did I verify the real integration point/runtime?
- Did I inspect generated artifacts?
- Did I exercise a meaningful failure path where appropriate?
- For visual work, did I actually interact with and inspect the real UI/screenshots?
- Is there evidence for every major completion claim?

Do not turn self-review into endless re-analysis. One focused adversarial pass is enough unless it reveals a real problem.

After substantial implementation, report concisely:

- what changed;
- why the chosen mechanism was used;
- what research materially informed it;
- what real commands/checks were run;
- what runtime/user flow was exercised;
- which screenshots/artifacts were opened and inspected;
- what remains uncertain, unverified, or blocked.

Evidence is more valuable than confident prose.

## 14. Gemini 3.8 Flash Discipline

Gemini 3.8 Flash is fast enough that premature implementation can look productive. Do not let speed replace evidence.

When operating as Gemini 3.8 Flash:

- convert multi-part requests into a finite outcome checklist before implementation;
- inspect integration points before coding;
- research current external facts rather than inventing them;
- never invent APIs, filenames, formats, licenses, or behavior;
- do not add unsolicited features merely because they seem useful;
- do not expand task scope while implementing;
- prefer several verified increments over one enormous generated patch;
- inspect the final diff against every requested outcome;
- use Playwright for repeatable browser verification instead of long exploratory click loops;
- use actual screenshot inspection before claiming visual success;
- stop research/exposition once enough evidence exists;
- stop and reassess after two failed attempts at the same interaction or diagnosis;
- if genuinely stuck on architecture/reasoning and Antigravity offers a stronger review/boost path, use it instead of continuing a low-confidence loop.

Speed is useful only when the result remains grounded.

## 15. Communication and Durable Knowledge

Keep progress communication short and factual.

Do not narrate obvious tool calls, dump large code into chat when files can be edited directly, or produce long speculative essays while implementation is waiting.

When reasoning is uncertain, use tools and evidence rather than filling the response with caveats. When enough evidence exists, make the decision and continue. Stop exploring when further exploration is unlikely to change the action.

Do not turn `AGENTS.md` into a project diary.

Only add rules here when they are broadly applicable, non-obvious, stable, repeatedly useful, and expensive for an agent to rediscover.

Put detailed engine specifications, legal analyses, architectural decisions, source-specific notes, and long research results in their appropriate project documentation.

If removing an instruction would not plausibly cause a future agent to make a meaningful mistake, it probably does not belong in `AGENTS.md`.
