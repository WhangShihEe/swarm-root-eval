# Shared mission prompts

One eval flow, authored once, reused across many device specs. A prompt file here holds the
three app-agnostic mission slots — `objective`, `success_signal`, `details` — that would
otherwise be duplicated in every `devices/<app>.yaml`.

## How a spec uses one

In a device spec's `app:` block, name the prompt (its filename here, without `.yaml`):

```yaml
app:
  package: com.dbs.sg.dbsmbanking
  label: "DBS digibank"
  frida_mode: spawn
  prompt: get-running-disable-rasp
```

`swarm_eval/target.py::load_target` resolves it: when `app.prompt` is set, `objective`,
`success_signal`, and `details` are read from `devices/prompts/<name>.yaml`. **An inline
`app:` key still wins** — set `objective:` directly in a spec to override just that slot for one
app while inheriting the rest. A missing prompt file raises (a typo fails loudly).

Edit the flow for all specs in one place: change the prompt file, not the 10 specs.

## Prompts

- **`get-running-disable-rasp.yaml`** — the current probe flow. Phased: (1) get the app running
  at all, ruling out an environment/provisioning misconfig before blaming the app; (2) if the app
  deliberately blocks/exits/crashes, neutralize it to reach the real UI (no protection = fine,
  move on); (3) on the running app, find and PROVE a real flaw (broken authz / auth / server
  trust / injection / insecure storage) under stated rules of engagement — own issued accounts,
  PoC-not-payload, stop at proof. Deliberately **cold**: names no protection class, no expected
  checks, no method, and for phase 3 no endpoint or specific bug — discovering those is what the
  probe measures. Success is judged from evidence (running-app state, then a reproducible finding
  with raw request/response); "no flaw found, surface X covered" is an honest result. (The name
  is now a slight misnomer — the flow is more than RASP — but is kept so the 10 specs' `prompt:`
  need no churn.)

## Consumers

The 10 corpus specs — `devices/{cpf,dbs,healthhub,healthy365,mytransport,parking_sg,scamshield,
sgsecure,singpass,singtel}.yaml` — all reference `get-running-disable-rasp`.
(`devices/rasp_dummy.yaml` is the older toy target and still inlines its own prompt.)
