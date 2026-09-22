# Seed: demo-app-gif

Context-seed for a future grilling session. **Not a ticket yet.** Downstream: unblocks the
README's inline `<WIP>` demo-GIF placeholder.

## Goal

Build a **presentable Android app** and record a polished **GIF** for the GitHub README showing the
eval in action — an agent interacting with a **live emulator** (possibly multiple), with the
**message board updating live**. High-signal for the resume/showcase.

## Why

The README is quickstart-first; the showcase weight rides on visuals. A clean GIF of a real run is
the single most convincing artifact.

## Facts found (this session)

- There's already a self-contained toy target: `apks/rasp_dummy/rasp_dummy.apk`
  (`com.example.rasptarget`, flips a banner to `UNLOCKED` / reveals `FLAG{rasp-bypassed}`,
  success confirmable via logcat tag `RASPTARGET`). Good candidate for the on-screen app, though a
  more "presentable" purpose-built app may read better on camera.
- Live viewing hooks that a recording can use: per-worker console files (`tail -f`), the board dir
  under `swarm-eval/board/<swarm-id>/`, and `inspect view` (port 7575).

## Open questions (for the grill)

- Purpose-built presentable app vs dress up the RASP-dummy?
- Single emulator vs a multi-emulator + live-board split-screen composition?
- Recording tooling + where the GIF asset lands (`docs/assets/`).

## Downstream effect on docs

Once done, the README GIF `<WIP>` placeholder is replaced with the real asset.
