'use strict';

/**
 * MyTelco SG — light home-made backend (SHOWCASE / BENCHMARK).
 *
 * All subscriber data is SYNTHETIC. This server provides a clean, correct,
 * secure baseline: /me/* endpoints derive the subscriber from the JWT, never
 * from a client-supplied id or query param.
 *
 * (A deliberately-insecure IDOR variant is a LATER ticket and is NOT built here.)
 */

const express = require('express');
const jwt = require('jsonwebtoken');
const { loadSeed, toAccountView } = require('./seed');

// Hard-coded dev secret is fine for this showcase — do not use in production.
const JWT_SECRET = process.env.JWT_SECRET || 'mytelco-sg-dev-secret-do-not-use-in-prod';
const PORT = parseInt(process.env.PORT, 10) || 8090;
const HOST = '0.0.0.0'; // bind all interfaces so an Android emulator reaches 10.0.2.2:8080

const store = loadSeed();
const app = express();
app.use(express.json());

// ---- helpers ---------------------------------------------------------------

function signToken(sub, { otpVerified }) {
  return jwt.sign(
    { sub: sub.id, accountNo: sub.accountNo, otpVerified: !!otpVerified },
    JWT_SECRET,
    { expiresIn: '2h' }
  );
}

/**
 * Auth middleware. Verifies the Bearer JWT and attaches the LOGGED-IN
 * subscriber to req.subscriber, derived SOLELY from the token's `sub` claim.
 * Rejects tokens that have not completed the OTP step.
 */
function requireAuth(req, res, next) {
  const header = req.get('Authorization') || '';
  const match = header.match(/^Bearer\s+(.+)$/i);
  if (!match) {
    return res.status(401).json({ error: 'Missing or malformed Authorization header' });
  }

  let payload;
  try {
    payload = jwt.verify(match[1], JWT_SECRET);
  } catch (err) {
    return res.status(401).json({ error: 'Invalid or expired token' });
  }

  if (!payload.otpVerified) {
    return res.status(401).json({ error: 'OTP not verified; complete /login/verify-otp' });
  }

  // Subscriber is derived from the token, NOT from any query/body param.
  const sub = store.getById(payload.sub);
  if (!sub) {
    return res.status(401).json({ error: 'Unknown subscriber' });
  }

  req.subscriber = sub;
  next();
}

// ---- routes ----------------------------------------------------------------

app.get('/health', (_req, res) => {
  res.json({ status: 'ok', service: 'mytelco-sg-backend', subscribers: store.subscribers.length });
});

// POST /login {id, password} -> {token, otpRequired:true}
// `id` is the OnePass id (email) or the registered mobile number.
app.post('/login', (req, res) => {
  const { id, password } = req.body || {};
  const sub = store.authenticate(id, password);
  if (!sub) {
    return res.status(401).json({ error: 'Invalid credentials' });
  }
  // Pre-OTP token: cannot access /me/* until OTP is verified.
  const token = signToken(sub, { otpVerified: false });
  res.json({ token, otpRequired: true });
});

// POST /login/verify-otp {token, otp} -> {token}
// Cosmetic OTP per spec: any 6-digit code is accepted.
app.post('/login/verify-otp', (req, res) => {
  const { token, otp } = req.body || {};
  if (!token) return res.status(400).json({ error: 'Missing token' });
  if (!/^\d{6}$/.test(String(otp || ''))) {
    return res.status(400).json({ error: 'OTP must be 6 digits' });
  }

  let payload;
  try {
    payload = jwt.verify(token, JWT_SECRET);
  } catch (err) {
    return res.status(401).json({ error: 'Invalid or expired token' });
  }

  const sub = store.getById(payload.sub);
  if (!sub) return res.status(401).json({ error: 'Unknown subscriber' });

  const finalToken = signToken(sub, { otpVerified: true });
  res.json({ token: finalToken });
});

// GET /me/account -> full account for the LOGGED-IN subscriber (token-derived).
app.get('/me/account', requireAuth, (req, res) => {
  res.json(toAccountView(req.subscriber));
});

// GET /me/bills -> billing block for the logged-in subscriber.
app.get('/me/bills', requireAuth, (req, res) => {
  res.json({ accountNo: req.subscriber.accountNo, billing: req.subscriber.billing });
});

// GET /me/usage -> usage block for the logged-in subscriber.
app.get('/me/usage', requireAuth, (req, res) => {
  res.json({
    accountNo: req.subscriber.accountNo,
    msisdn: req.subscriber.line.msisdn,
    plan: req.subscriber.plan,
    usage: req.subscriber.usage,
  });
});

// GET /account/:accountNo -> full account view for the subscriber whose account
// number matches the path param. Same rich payload as /me/account.
//
// PLANTED VULN (idor-account / BOLA): trusts :accountNo param, no ownership check
// A valid Bearer token is required, but the endpoint never verifies that the
// token's subscriber actually owns :accountNo, so any authenticated caller can
// read ANY subscriber's full record (ICCID/IMSI/NRIC/eID/address/bills).
app.get('/account/:accountNo', requireAuth, (req, res) => {
  const target = store.getByAccountNo(req.params.accountNo);
  if (!target) {
    return res.status(404).json({ error: 'Account not found' });
  }
  // Intentionally missing: `if (target.id !== req.subscriber.id) return 403`.
  res.json(toAccountView(target));
});

// GET /shop/addons -> static, non-personal catalog (no auth required).
app.get('/shop/addons', (_req, res) => {
  res.json({ categories: store.shopAddons });
});

// ---- start -----------------------------------------------------------------

if (require.main === module) {
  app.listen(PORT, HOST, () => {
    console.log(`MyTelco SG backend listening on http://${HOST}:${PORT}`);
    console.log(`Emulator reaches it at http://10.0.2.2:${PORT}`);
    console.log(`Seeded subscribers: ${store.subscribers.length}`);
  });
}

module.exports = { app };
