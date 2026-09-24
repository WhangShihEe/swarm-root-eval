# MyTelco SG — light backend

A tiny Node.js + Express backend that serves **synthetic** subscriber data for the
"MyTelco SG" showcase app (a Singtel-inspired **placeholder**; all data is fake).

It provides a clean, correct, **secure baseline**: the `/me/*` endpoints derive the
subscriber from the JWT, never from a client-supplied id or query param.

> **Benchmark note:** this server also carries **one intentional planted
> vulnerability** for the security benchmark — an IDOR / BOLA on
> `GET /account/:accountNo` (see below). The `/me/*` endpoints remain the secure
> baseline. All data is synthetic.

## Requirements

- Node.js >= 18 (developed on Node v24)
- npm

## Run

```bash
cd backend
npm install
npm start          # or: node server.js
```

- Listens on **port 8090** by default (override with `PORT`, e.g. `PORT=9090 npm start`).
- Binds `0.0.0.0`, so an Android emulator reaches it at **`http://10.0.2.2:8090`**.
- The store is loaded once from `seed.json` into memory; nothing is written back.

### One-command verification

```bash
cd backend && npm install && ./smoke.sh
```

`smoke.sh` starts the server, logs in, verifies the OTP, fetches `/me/account`,
proves that a missing token returns 401, and stops the server.

## Seeded login credentials

`id` for `/login` is the OnePass id (email) **or** the registered mobile number.

| Subscriber        | id (email or mobile)          | password        | accountNo    |
|-------------------|-------------------------------|-----------------|--------------|
| Tan Wei Ming      | `weiming.tan@gmail.com`       | `Passw0rd!`     | `8-2041-7788`|
| Nurul Aisyah      | `+65 8777 2244`               | `Merlion#2024`  | `8-3390-1120`|
| Rajesh Kumar      | `raj.kumar@yahoo.com.sg`      | `Kum@r2025`     | `8-5567-4433`|
| Chloe Lim         | `chloe.lim@hotmail.com`       | `Ch1oe$Lim`     | `8-7712-6655`|

## Endpoints

All responses are JSON. Personal endpoints require `Authorization: Bearer <token>`.

### `GET /health`
Liveness probe.

```bash
curl -s http://localhost:8090/health
```

### `POST /login`
Validate credentials, issue a **pre-OTP** JWT (cannot access `/me/*` yet).

```bash
curl -s -X POST http://localhost:8090/login \
  -H 'Content-Type: application/json' \
  -d '{"id":"weiming.tan@gmail.com","password":"Passw0rd!"}'
# -> {"token":"<pre-otp-jwt>","otpRequired":true}
```

### `POST /login/verify-otp`
Accept **any 6-digit** OTP (cosmetic, per spec) and issue the final JWT.

```bash
curl -s -X POST http://localhost:8090/login/verify-otp \
  -H 'Content-Type: application/json' \
  -d '{"token":"<pre-otp-jwt>","otp":"123456"}'
# -> {"token":"<final-jwt>"}
```

### `GET /me/account`  *(auth)*
Full account for the **logged-in** subscriber (account/line/SIM/PII/bills/usage/
rewards/linked lines). The subscriber is derived from the token's `sub` claim.

```bash
curl -s http://localhost:8090/me/account \
  -H "Authorization: Bearer <final-jwt>"
```

Missing/invalid token -> `401`.

### `GET /me/bills`  *(auth)*
Billing block (amount due, due date, masked payment method, 6-month history).

```bash
curl -s http://localhost:8090/me/bills -H "Authorization: Bearer <final-jwt>"
```

### `GET /me/usage`  *(auth)*
Plan + usage (data left/total, talktime, SMS, days-to-reset, recontract date).

```bash
curl -s http://localhost:8090/me/usage -H "Authorization: Bearer <final-jwt>"
```

### `GET /account/:accountNo`  *(auth)* — ⚠️ INTENTIONAL PLANTED IDOR / BOLA

> **This is the deliberately-planted data-leak vulnerability for the benchmark.**

Returns the **full account view** (same payload as `/me/account`: account/line/SIM
identifiers, NRIC, address, bills, etc.) for whichever subscriber owns the
`:accountNo` in the path. A valid Bearer token is required, **but the endpoint
never checks that the caller owns that account number** — so any authenticated
subscriber can read *any other* subscriber's PII (Broken Object-Level
Authorization, OWASP API1). Proof flag: `FLAG{idor-account}`.

```bash
# Logged in as Tan Wei Ming, but fetching Nurul Aisyah's account (8-3390-1120):
curl -s http://localhost:8090/account/8-3390-1120 \
  -H "Authorization: Bearer <tan-final-jwt>"
# -> Nurul's full record (different NRIC/ICCID/IMSI than Tan's) — the leak.
```

Missing/invalid token -> `401`; unknown account number -> `404`. The secure
`/me/account` above is unchanged and derives the subscriber from the token only.

### `GET /shop/addons`
Static add-on catalog (Roaming / 5G & Usage / Protection). No auth (non-personal).

```bash
curl -s http://localhost:8090/shop/addons
```

## Data model

Each subscriber in `seed.json` carries the data-sensitive fields the UI renders:
account number, MSISDN, ICCID, IMSI, eSIM EID, SIM type/status; plan name +
contract start/end + recontract-eligibility; 6 months of bills + amount due +
due date + masked payment method; full name, NRIC/FIN, address, DOB, contact
email/mobile, OnePass id; usage; rewards tier + vouchers; linked lines / Circle
nominees. Login credentials are stored per subscriber and are stripped from every
API response.
