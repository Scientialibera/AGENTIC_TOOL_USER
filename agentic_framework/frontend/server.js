// Lightweight Express server to host the built React app and provide a /login endpoint.
// Only the bcrypt hash of the password is stored in APP_PASSWORD_HASH (set as an App Setting in Azure).

const express = require('express');
const path = require('path');
const bcrypt = require('bcryptjs');
const helmet = require('helmet');
const cors = require('cors');

const app = express();
app.use(express.json());
app.use(helmet({
  contentSecurityPolicy: false, // Simplicity for demo; can be hardened later
}));

// Allow same-origin and basic CORS for local dev if needed
app.use(cors({
  origin: function (origin, cb) {
    // Allow requests with no origin (mobile apps, curl) or localhost during dev
    if (!origin || /localhost/.test(origin)) return cb(null, true);
    return cb(null, true); // Relaxed for demo; tighten for production
  },
  credentials: false
}));

const EXPECTED_USERNAME = process.env.APP_USERNAME || 'demo';
const PASSWORD_HASH = process.env.APP_PASSWORD_HASH || '';

if (!PASSWORD_HASH) {
  console.warn('[WARN] APP_PASSWORD_HASH not set. /login will always fail.');
}

app.get('/health', (_req, res) => {
  res.json({ status: 'ok' });
});

// POST /login { username, password }
app.post('/login', async (req, res) => {
  try {
    const { username, password } = req.body || {};
    if (!username || !password) {
      return res.status(400).json({ detail: 'username and password required' });
    }
    if (username !== EXPECTED_USERNAME) {
      return res.status(401).json({ detail: 'Invalid credentials' });
    }
    if (!PASSWORD_HASH) {
      return res.status(500).json({ detail: 'Password hash not configured' });
    }
    const match = await bcrypt.compare(password, PASSWORD_HASH);
    if (!match) {
      return res.status(401).json({ detail: 'Invalid credentials' });
    }
    // Issue a simple signed-in flag (could be a JWT in real scenario)
    res.json({ ok: true });
  } catch (err) {
    console.error('Login error', err);
    res.status(500).json({ detail: 'Internal error' });
  }
});

// Serve static files from React build
const buildPath = path.join(__dirname, 'build');
app.use(express.static(buildPath));

// SPA fallback
app.get('*', (req, res) => {
  res.sendFile(path.join(buildPath, 'index.html'));
});

const port = process.env.PORT || 8080;
app.listen(port, () => {
  console.log(`Frontend server listening on port ${port}`);
  console.log(`Expecting username: ${EXPECTED_USERNAME}`);
});
