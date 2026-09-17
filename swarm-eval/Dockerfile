# Sandbox image: Claude Code + the Android offensive toolchain, baked in (tickets 04, 07).
#
# Native-binary route: the standalone `claude` binary bundles its own runtime, so the base
# image needs nothing but curl + TLS certs to fetch it. No Node for CC itself.
#
# CC version is fixed by this image; pair it with `claude_code(version="sandbox")` in the
# solver so Inspect uses this binary and fails loud instead of downloading. No
# ANTHROPIC_API_KEY here — the bridge serves the model (keyless sandbox, S2).
#
# Ticket 04 added the dynamic reach (adb to the HOST emulator, frida client pinned to the
# provisioned server, objection). Ticket 07 makes that toolchain actually *usable* for offense:
# the frida-17 Java bridge (`frida-java-bridge` + `frida-compile`, since frida 17 dropped the
# built-in `Java` global), a non-interactive runner, and the STATIC tools folded in per CONTEXT
# (`dynamic = static + dynamic`): jadx, apktool, androguard, file/strings/unzip on a JRE. The
# build inherits ticket 02's gitignored corporate-CA caveat (it won't build in CI as-is).
FROM debian:bookworm-slim

# frida CLIENT version — MUST match the harness-provisioned frida-SERVER (CONTEXT.md: v17.17.0).
# A client/server mismatch is a classic silent failure, so the pin is explicit.
ARG FRIDA_VERSION=17.17.0
# Static-tool pins. Both are pure-Java (run on the JRE below), so they're arch-agnostic.
ARG JADX_VERSION=1.5.1
ARG APKTOOL_VERSION=2.10.0

# Base OS packages, one layer:
#  - curl/ca-certificates: fetch CC + the static tools at build time.
#  - adb from Debian (native-arch: the emulator target is arm64-v8a and this image is arm64 on
#    an Apple-Silicon host — Google's platform-tools-latest-linux.zip is x86_64-only and dies
#    under Rosetta). adb's wire protocol is backward-compatible, so its client version isn't the
#    pinned-critical one — frida is (below).
#  - python3/venv: frida-tools, objection, androguard, and the frida-run runner.
#  - default-jre-headless: runs jadx + apktool (both pure-Java).
#  - file/binutils(strings)/unzip: static triage.
#  - nodejs/npm: the frida-compile agent toolchain (the frida-17 Java bridge is an npm module).
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        curl ca-certificates \
        adb python3 python3-venv \
        default-jre-headless file binutils unzip \
        nodejs npm \
    && rm -rf /var/lib/apt/lists/*

# This network does TLS interception; the container must trust the same corporate
# CA bundle the host uses, or curl can't verify claude.ai at build time. The
# bundle is gitignored (certs/) — a corporate cert, never committed. Runtime CC
# talks to the keyless bridge over plain localhost, so this CA is build-only.
COPY certs/ca-bundle-cf.pem /usr/local/share/ca-certificates/corp-ca-bundle.crt
RUN update-ca-certificates
ENV CURL_CA_BUNDLE=/usr/local/share/ca-certificates/corp-ca-bundle.crt
# pip/python don't read the system CA store (they use certifi), so point them at the corp
# bundle too or every https install fails behind the intercepting proxy.
ENV PIP_CERT=/usr/local/share/ca-certificates/corp-ca-bundle.crt
ENV SSL_CERT_FILE=/usr/local/share/ca-certificates/corp-ca-bundle.crt
# node/npm ignore the system CA store as well (they have their own), so the frida-compile
# npm install fails behind the proxy without this.
ENV NODE_EXTRA_CA_CERTS=/usr/local/share/ca-certificates/corp-ca-bundle.crt

# --- Dynamic reach: frida client + objection + androguard (ticket 04, extended) -------------
# frida (client pinned to the provisioned server), frida-tools, objection, androguard — in a
# dedicated venv on PATH (Debian bookworm is PEP-668 externally-managed). frida==${FRIDA_VERSION}
# is listed first so the resolver honors the pin. androguard is the arm64-safe manifest reader
# (pure Python) standing in for aapt/aapt2, whose only Google binaries are x86_64 (see below).
RUN python3 -m venv /opt/frida \
    && /opt/frida/bin/pip install --no-cache-dir --upgrade pip \
    && /opt/frida/bin/pip install --no-cache-dir \
        "frida==${FRIDA_VERSION}" frida-tools objection androguard
ENV PATH="/opt/frida/bin:${PATH}"
# Symlink the CLIs onto the default PATH (/usr/local/bin) so they resolve even under a login
# shell, which resets PATH and would otherwise drop /opt/frida/bin (bites the agent's Bash tool).
RUN ln -sf /opt/frida/bin/frida* /usr/local/bin/ \
    && ln -sf /opt/frida/bin/objection /usr/local/bin/ \
    && ln -sf /opt/frida/bin/androguard /usr/local/bin/

# --- Static analysis: jadx (Java decompile) + apktool (smali/resources/manifest) ------------
# Both are pure-Java (the JRE above), so they're arch-agnostic — unlike aapt/aapt2, whose only
# Google-shipped binaries are x86_64 and die under Rosetta here (the same reason adb comes from
# apt, not platform-tools). androguard (pip, above) covers arm64 manifest reads.
RUN curl -fsSL "https://github.com/skylot/jadx/releases/download/v${JADX_VERSION}/jadx-${JADX_VERSION}.zip" -o /tmp/jadx.zip \
    && unzip -q /tmp/jadx.zip -d /opt/jadx \
    && rm /tmp/jadx.zip \
    && ln -sf /opt/jadx/bin/jadx /usr/local/bin/jadx \
    && ln -sf /opt/jadx/bin/jadx-gui /usr/local/bin/jadx-gui
# apktool = wrapper script + jar, both in /usr/local/bin (the upstream-documented layout: the
# wrapper resolves apktool.jar next to itself).
RUN curl -fsSL "https://github.com/iBotPeaches/Apktool/releases/download/v${APKTOOL_VERSION}/apktool_${APKTOOL_VERSION}.jar" -o /usr/local/bin/apktool.jar \
    && curl -fsSL "https://raw.githubusercontent.com/iBotPeaches/Apktool/master/scripts/linux/apktool" -o /usr/local/bin/apktool \
    && chmod +x /usr/local/bin/apktool

# --- Dynamic offense: frida-17 Java bridge + compiler (ticket 07) ---------------------------
# frida 17 removed the built-in `Java` global, so a custom `Java.perform(...)` agent must
# `require('frida-java-bridge')` and be bundled with frida-compile. Bake both into a scaffold
# project; author custom agents inside this dir so the compiler's module resolver finds the
# bridge on its node_modules walk-up. NODE_PATH also points here for agents compiled elsewhere.
ENV FRIDA_AGENT_DIR=/opt/frida-agent
RUN mkdir -p "$FRIDA_AGENT_DIR" \
    && cd "$FRIDA_AGENT_DIR" \
    && npm init -y >/dev/null \
    && npm install --no-audit --no-fund frida-compile frida-java-bridge \
    && ln -sf "$FRIDA_AGENT_DIR/node_modules/.bin/frida-compile" /usr/local/bin/frida-compile
ENV NODE_PATH=/opt/frida-agent/node_modules

# Non-interactive runner (frida-run) + a Java-bridge smoke/template agent. frida-run's shebang
# is the venv python so `import frida` resolves.
COPY sandbox/frida-run /usr/local/bin/frida-run
COPY sandbox/examples/ /opt/frida-agent/examples/
RUN chmod +x /usr/local/bin/frida-run

# --- Build-time smokes ----------------------------------------------------------------------
# adb launches and the frida client is EXACTLY the pinned version (hard fail on mismatch —
# that's the whole point of the pin).
RUN adb --version \
    && got="$(frida --version)" \
    && { [ "$got" = "${FRIDA_VERSION}" ] || { echo "frida $got != pinned ${FRIDA_VERSION}" >&2; exit 1; }; }

# Static tools launch, and the arm64 manifest reader imports.
RUN jadx --version \
    && apktool --version \
    && file --version >/dev/null \
    && strings --version >/dev/null \
    && unzip -v >/dev/null \
    && /opt/frida/bin/python -c "import androguard; print('androguard', androguard.__version__)"

# The runner imports frida and parses args; objection's CLI answers (its compiled agent ships
# the bridge, so it works on frida 17 — the actual bypass is proven live, not at build time).
RUN /opt/frida/bin/python -c "import frida; print('frida-py', frida.__version__)" \
    && frida-run --help >/dev/null \
    && objection version

# The frida-17 Java bridge actually bundles: compile a `require('frida-java-bridge')` agent from
# inside the scaffold dir (the documented pattern) and assert the output is large — a bare agent
# is a few hundred bytes; with the bridge bundled it is hundreds of KB. Also probe whether
# NODE_PATH lets an agent compiled from an arbitrary cwd resolve the bridge (informational).
RUN set -eux; \
    printf "const Java = require('frida-java-bridge');\nJava.perform(() => { send({ type: 'done', ok: true }); });\n" > "$FRIDA_AGENT_DIR/_bridge_smoke.js"; \
    ( cd "$FRIDA_AGENT_DIR" && frida-compile _bridge_smoke.js -o /tmp/_bridge_smoke.compiled.js ); \
    bytes="$(wc -c < /tmp/_bridge_smoke.compiled.js)"; \
    echo "bridge-bundled agent = ${bytes} bytes"; \
    [ "$bytes" -gt 50000 ] || { echo "frida-java-bridge did not bundle (only ${bytes} bytes)" >&2; exit 1; }; \
    if ( cd /tmp && frida-compile "$FRIDA_AGENT_DIR/_bridge_smoke.js" -o /tmp/_bridge_np.js ) 2>/dev/null && [ "$(wc -c < /tmp/_bridge_np.js)" -gt 50000 ]; then \
      echo "NODE_PATH-resolved bridge from arbitrary cwd: YES"; \
    else \
      echo "NODE_PATH-resolved bridge from arbitrary cwd: NO (author agents inside $FRIDA_AGENT_DIR)"; \
    fi; \
    rm -f "$FRIDA_AGENT_DIR/_bridge_smoke.js"

RUN curl -fsSL https://claude.ai/install.sh | bash

# The installer drops the binary in ~/.local/bin.
ENV PATH="/root/.local/bin:${PATH}"

# Set the endpoint for inspect Claude Code
ENV ANTHROPIC_BASE_URL="http://localhost:13131"

# Build-time smoke: fail the build if the binary can't launch.
RUN claude --version

CMD ["claude"]
