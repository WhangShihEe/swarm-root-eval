# 03: Host-side device lease (`agent_runner`) + `single_agent.py` + conductor/swarm migration

**What to build:** move device acquire/release out of the Inspect task and into the launchers,
behind one shared per-run primitive; add the single-agent entrypoint; and migrate the conductor
+ `swarm.py` onto that same primitive and the yaml-only entrypoint. After this there are two clean
entrypoints — `single_agent.py` (one agent) and `swarm.py` (N agents + board) — over ONE agent
unit (`dynamic_agent`) that only ever consumes an injected device contract.

**Blocked by:** 02.

**Status:** ready-for-agent

- [ ] `swarm_eval/agent_runner.py` holds the shared host-side machinery both launchers use: acquire/release a broker device, write the contract to a host file, build the `inspect eval dynamic_agent.py -T spec=… --model … --time-limit … [--message-limit …]` argv, build the run env (`DEVICE_CONTRACT` + `INSPECT_LOG_DIR`, plus the board env when a swarm), and launch the subprocess.
- [ ] `dynamic_agent`'s setup solver now consumes an **injected** `DEVICE_CONTRACT` (reads + parses the host file, writes the contract + connect helper into the sandbox) and **fails fast with a clear message if none is present** ("run via single_agent.py or swarm.py"). The in-task broker `acquire` and `release_device` teardown are removed — a contract is always injected, and the launcher owns the lease.
- [ ] The swarm signal (board-tools + `swarm_prompt` collaboration wrapper) is the presence of the board env (`SWARM_ID`), not `DEVICE_CONTRACT`. A single run (contract, no board env) gets neither; a conductor worker (contract + board env) gets both.
- [ ] `single_agent.py` is entrypoint 1: `python single_agent.py devices/<name>.yaml [--model --time-limit --message-limit --log-dir]` leases one device, launches one `dynamic_agent` run with the budget/time-limit, and releases the device in a `finally` (guaranteed even on failure). The scored self-report lives in the inspect log.
- [ ] `conductor.py` uses `agent_runner`'s shared primitives instead of its own duplicated argv/env/acquire/release; it keeps only the swarm layer (messageboard, agent ids, arbiter, collation) and still releases every device it leased.
- [ ] `swarm.py` takes the yaml as the **required positional** (`python swarm.py devices/<name>.yaml`); `--spec` is dropped; `--workers`/`--model`/`--cap`/`--time-limit`/etc. stay optional. `python swarm.py devices/x.yaml` with `-n 1` is the single-in-swarm case on the same per-run path.
- [ ] Guaranteed release holds for both launchers: a failed/timed-out run still frees its scarce broker slot.
- [ ] Verifiable without a live emulator: `single_agent.py` and `swarm.py` arg-parsing; a faked-broker/faked-subprocess dry-run showing acquire → `-T spec=` + `DEVICE_CONTRACT` set → release; `inspect eval dynamic_agent.py` with no launcher errors clearly (fail-fast). Both `devices/rasp_dummy.yaml` and `devices/healthhub.yaml` exercise the same path, differing only by their yaml.
- [ ] Tests updated/added and green: `test_single_agent.py` (CLI + lease/finally), `test_agent_runner.py` (argv/env builders), the `dynamic_agent`/`swarm_worker` tests for the injected-contract + board-env signal, and `test_conductor.py` + `test_swarm_cli.py` for the migration and the positional yaml.

## Notes

- Replacing the self-report scorer with a device-verifying oracle is a separate known-needed
  feature (inspect-swarm ticket 06), not part of this ticket.
