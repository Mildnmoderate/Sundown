# Sundown demo guide

## One-command prep (do this at 3:45)

```bash
./run.sh      # terminal 1: server + UI + worker  -> http://localhost:8001
./test.sh     # terminal 2: health check + full test suite (all PASS)
./demo.sh     # terminal 2: clean slate, chaos ON, worker running
```

- [ ] Header pill says **agent: running**
- [ ] Atlas open on `events` and `tasks` in a second tab
- [ ] Repo is **public**, `.env` not committed, all teammates added on the submission page
- [ ] Screen recording ready, notifications off
- Between rehearsal runs: `./demo.sh` (do not click Reset mid-run)

## 1-minute submission video

| Time | Show | Say |
|---|---|---|
| 0:00 | UI, all rows grey | "Sundown offboards an employee across five systems and only says done when it can prove access is gone." |
| 0:08 | Click **Start offboarding** (Priya) | "A 200 OK is just a claim. Watch the ground-truth column." |
| 0:15 | GitHub yellow, ground truth still red | "GitHub returned 200 but her token still works. Sundown marks it sent, not verified, and retries." |
| 0:25 | Okta row shows adapted | "Okta changed its API mid-run. Vector Search finds a similar past fix, Groq double-checks it, and Sundown re-verifies." |
| 0:35 | **Kill agent**, then **Restart agent** | "We killed the worker. It resumes and skips what's already verified." |
| 0:45 | All green, open a proof drawer | "Every step has evidence stored in Atlas. Access is dead on all five systems." |
| 0:55 | Title card | "Sundown. Finish the Job." |

## 3-minute live script

1. **0:00** Pitch: "Agents report success when an API says 200. Ours reports success when the token stops working."
2. **0:20** Click **Start offboarding**. Point at the ground-truth column.
3. **0:50** GitHub: yellow, token alive. Open the proof drawer, press **Probe now** (token works). The retry goes green.
4. **1:20** Okta drift: show the 400, then the Vector Search hit (experience ID + score) and Groq's one-line check, then green.
5. **1:55** Google delay: stays yellow while probing, no resend. Use the wait to **Kill agent**, then **Restart agent**. Point out the skipped steps.
6. **2:25** Atlas tab: `events`, a step with its evidence, and the Groq `summary` on the task.
7. **2:50** Close: "Access is dead everywhere, with evidence. Sundown never trusts a 200."

## If something breaks

- **Chaos stuck:** click **All off**, then `./demo.sh`.
- **Agent stopped:** click **Restart agent**, or `./demo.sh`.
- **"systems API unreachable":** `./run.sh` is not running.
- **No Groq lines:** fine. Groq is optional and the run still completes.
- **Backup:** keep the recorded video open in a tab.

## Likely judge questions

- **Isn't this just a workflow?** A deterministic state machine owns verification, because a model must never decide whether access is dead. Vector Search picks the fix, Groq explains it and writes the audit summary, and the probe is always the final judge.
- **Why not trust a 200?** That is the demo: a 200 is a claim, a probe is evidence.
- **Why Vector Search?** Past fixes are free text keyed by error shape, so we retrieve by similarity, not exact match.
- **Do idempotency keys stop double-sends?** The real protection is write-ahead state plus probing before any resend. The key is sent for systems that support it.
- **Are the systems real?** They are simulators so failures can be triggered on demand. The agent logic is the product.
- **What was built today?** The agent, systems, UI and tests. Setup boilerplate was prepared before kickoff. Show the commit history.