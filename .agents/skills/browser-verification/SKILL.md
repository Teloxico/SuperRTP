---
name: browser-verification
description: Use for rigorous browser and visual verification after any web-visible, interactive, rendered, or browser-dependent change. Uses Playwright CLI and requires actual runtime evidence, screenshots, and inspection before claiming success.
---

# Browser Verification

Use the official `playwright-cli` skill for browser mechanics.

In this repository invoke the CLI as:

    npx --no-install playwright-cli

Do not use browser automation for ordinary factual research when source code,
documentation, APIs, curl, gh, or textual retrieval can answer the question.

## Core rule

A successful command is not proof of a successful user experience.

Never claim browser or visual verification from:
- source inspection;
- compilation;
- unit tests alone;
- DOM existence alone;
- a successful click command;
- an uninspected screenshot.

## Workflow

Before interaction:

1. State exactly what behavior is being verified.
2. Determine the expected observable result.
3. Start the real application.
4. Confirm the correct URL and state.
5. Use a clean session unless persisted state is part of the test.

Interaction loop:

1. Inspect current page state.
2. Identify the intended target from evidence.
3. Perform one meaningful action.
4. Inspect resulting state.
5. Continue only if the expected transition occurred.

Prefer semantic locators and element references over coordinate clicking.

## Two-strike rule

If the same intended interaction fails twice, STOP.

Do not repeatedly:
- click;
- change selectors randomly;
- add arbitrary sleeps;
- retry the same hypothesis.

Instead inspect:
- current page state;
- URL;
- console;
- requests;
- application logs;
- DOM state;
- the original assumption.

Then change the diagnosis or mechanism.

## Visual verification

For visually meaningful work, perform a final headed pass when practical.

For each important state:

1. reach it through the real user flow;
2. capture a screenshot;
3. inspect the screenshot visually;
4. look for clipping, overlap, missing content, broken alignment,
   unexpected loading states, unreadable text, and rendering failures;
5. fix defects;
6. repeat the same flow;
7. capture and inspect the corrected result.

Taking a screenshot without inspecting it does not count.

## Console and network

When behavior is suspicious, inspect:

    npx --no-install playwright-cli console
    npx --no-install playwright-cli requests

Do not ignore console/runtime failures because the page appears visually correct.

## Evidence

Store important screenshots under:

    artifacts/browser/

Use meaningful names.

Before reporting completion:

1. run the actual user flow;
2. inspect resulting state;
3. inspect screenshots;
4. check console/network failures where relevant;
5. reconcile evidence against every requested requirement.

If something was not exercised, report it as UNVERIFIED.

## Efficiency

Use targeted snapshots and semantic references.

Do not dump huge page states into context unnecessarily.

Stop investigating once enough evidence exists to establish the result.
