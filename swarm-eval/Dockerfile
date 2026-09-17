# Sandbox image: Claude Code + the Android offensive toolchain, baked in (ticket 04).
#
# Native-binary route: the standalone `claude` binary bundles its own runtime, so the base
# image needs nothing but curl + TLS certs to fetch it. No Node.
#
# CC version is fixed by this image; pair it with `claude_code(version="sandbox")` in the
# solver so Inspect uses this binary and fails loud instead of downloading. No
# ANTHROPIC_API_KEY here — the bridge serves the model (keyless sandbox, S2).
#
# Ticket 04 adds the dynamic-agent toolchain: adb (platform-tools) to reach the HOST emulator
# over the compose host-loopback, plus frida/frida-tools (client pinned to the provisioned
# frida-server) and objection for the RootBeer bypass. The image build inherits ticket 02's
# gitignored corporate-CA caveat (it won't build in CI as-is).
FROM debian:bookworm-slim

# frida CLIENT version — MUST match the harness-provisioned frida-SERVER (CONTEXT.md: v17.17.0).
# A client/server mismatch is a classic silent failure, so the pin is explicit.
ARG FRIDA_VERSION=17.17.0

# adb from Debian (native-arch: the emulator target is arm64-v8a and this image is arm64 on
# an Apple-Silicon host — Google's platform-tools-latest-linux.zip is x86_64-only and dies
# under Rosetta). adb's wire protocol is backward-compatible, so the client version isn't the
# pinned-critical one — frida is (below).
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        curl ca-certificates adb python3 python3-venv \
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

# --- Android offensive toolchain (ticket 04) ------------------------------------------------
# adb is installed above (apt, native arch); it reaches the host emulator via
# `adb connect host.docker.internal:<adb_port>`.
#
# frida (client pinned to the provisioned server), frida-tools, objection — in a dedicated
# venv on PATH (Debian bookworm is PEP-668 externally-managed). frida==${FRIDA_VERSION} is
# listed first so the resolver honors the pin.
RUN python3 -m venv /opt/frida \
    && /opt/frida/bin/pip install --no-cache-dir --upgrade pip \
    && /opt/frida/bin/pip install --no-cache-dir \
        "frida==${FRIDA_VERSION}" frida-tools objection
ENV PATH="/opt/frida/bin:${PATH}"
# Symlink the CLIs onto the default PATH (/usr/local/bin) so they resolve even under a login
# shell, which resets PATH and would otherwise drop /opt/frida/bin (bites the agent's Bash tool).
RUN ln -sf /opt/frida/bin/frida* /usr/local/bin/ \
    && ln -sf /opt/frida/bin/objection /usr/local/bin/

# Build-time smoke: adb launches and the frida client is EXACTLY the pinned version (hard
# fail on a mismatch — that's the whole point of the pin). objection is imported at runtime.
RUN adb --version \
    && got="$(frida --version)" \
    && { [ "$got" = "${FRIDA_VERSION}" ] || { echo "frida $got != pinned ${FRIDA_VERSION}" >&2; exit 1; }; }

RUN curl -fsSL https://claude.ai/install.sh | bash

# The installer drops the binary in ~/.local/bin.
ENV PATH="/root/.local/bin:${PATH}"

# Set the endpoint for inspect Claude Code
ENV ANTHROPIC_BASE_URL="http://localhost:13131"

# Build-time smoke: fail the build if the binary can't launch.
RUN claude --version

CMD ["claude"]
