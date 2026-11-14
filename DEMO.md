# Sundown demo guide

## Pre-flight (do this at 3:45, record at 4:00)

- [ ] `python -m scripts.check_all` prints ALL GOOD
- [ ] Mock systems running: `python -m uvicorn systems.main:app --port 8001`, UI open at http://localhost:8001
- [ ] Agent worker running, header pill says **agent: running**
- [ ] Click **Reset demo** (clears events and tasks, restores all tokens)
- [ ] Past adaptations seeded in `experiences` so Vector Search has something to retrieve
- [ ] Atlas UI open on the `events` collection in a second tab
- [ ] Repo is **public**, `.env` is not committed, all teammates added on the submission page
- [ ] Screen recording tool ready, notifications off

## Chaos setup before every run

Turn on all three toggles (or click **All on**): GitHub lies, Google delays 20s, Okta API v2 drift.

## 1-minute submission video (record at 4:00)

| Time | Show | Say |
|---|---|---|
| 0:00 | UI, all rows grey | "Sundown offboards an employee across five systems, and only says done when it can prove access is gone." |
| 0:08 | Click **Start offboarding** (Priya) | "A 200 OK is just a claim. Watch the ground-truth column." |
| 0:15 | GitHub row yellow, ground truth still red | "GitHub returned 200 but her token still works. Sundown marks it sent, not verified, and retries." |
| 0:25 | Okta flips to v2, row adapts | "Okta changed its API mid-run. Sundown finds a similar past fix with Vector Search, adapts and re-verifies." |
| 0:35 | Click **Kill agent**, then **Restart agent** | "We just killed the worker. It restarts and resumes only the unverified steps." |
| 0:45 | All rows green, ground truth green, open a proof drawer | "Every step has stored evidence in Atlas. Access is dead on all five systems." |
| 0:55 | Title card | "Sundown. Finish the Job." |

## 3-minute live script (judging)

1. **0:00** Pitch in two sentences (problem plus "we prove it").
2. **0:20** Toggles on, click **Start offboarding**. Point at the ground-truth column.
3. **0:50** GitHub: yellow, token still alive. Open the proof drawer and press **Probe now**: token works. The agent retries with the second call and it goes green.
4. **1:20** Okta drift: show the 400, then the Vector Search hit and the adapted call in the drawer, then green. Show the new experience in Atlas.
5. **1:55** Google delay: row stays yellow until the probe passes (about 20s). Use this wait to **Kill agent**, then **Restart agent**. Point out it skips verified steps.
6. **2:25** Atlas tab: show `events` and a step doc with its evidence. If the scope-gate demo is built, start a run for Marcus's account against Priya's ticket and show it blocked.
7. **2:50** Close: "Access is dead everywhere, with evidence. Sundown never trusts a 200."

## If something breaks

- **Chaos stuck:** click **All off**, then **Reset demo**.
- **Agent won't restart:** check `AGENT_CMD` was set before starting uvicorn, or start the worker by hand in its terminal.
- **UI shows "systems API unreachable":** uvicorn isn't running on port 8001.
- **No live events:** the change stream needs Atlas (not a local Mongo); check `[stream]` lines in the uvicorn log.
- **Backup:** keep the recorded video open in a tab.

## Likely judge questions

- **Isn't this just a workflow?** Planning and adaptation are model-driven; the state machine is what makes them safe.
- **Why not trust a 200?** That is the demo: a 200 is a claim, a probe is evidence.
- **Why Vector Search?** Past fixes are free text keyed by error shape, so we retrieve by similarity, not exact match.
- **What was built today?** All of it. Show the commit history.
