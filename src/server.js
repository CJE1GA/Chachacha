require('dotenv').config();

const crypto = require('node:crypto');
const path = require('node:path');
const express = require('express');
const helmet = require('helmet');
const axios = require('axios');
const { processIncoming, ROOT } = require('./chatbot');

const app = express();
app.disable('x-powered-by');
app.use(helmet({ crossOriginResourcePolicy: { policy: 'cross-origin' } }));
app.use(express.json({ limit: '1mb', verify: (req, _res, buffer) => { req.rawBody = buffer; } }));

const PORT = Number(process.env.PORT || 3000);
const VERIFY_TOKEN = process.env.VERIFY_TOKEN;
const ACCESS_TOKEN = process.env.META_ACCESS_TOKEN;
const PHONE_NUMBER_ID = process.env.META_PHONE_NUMBER_ID;
const APP_SECRET = process.env.WEBHOOK_APP_SECRET;

app.get('/health', (_req, res) => res.status(200).json({ status: 'ok' }));
app.get('/media/:file', (req, res) => {
  const allowed = new Set(['precios_guadalupe.png', 'precios_bosque_santa_anita.png']);
  if (!allowed.has(req.params.file)) return res.sendStatus(404);
  return res.sendFile(path.join(ROOT, 'Information', 'images', req.params.file));
});

app.get('/webhook', (req, res) => {
  const mode = req.query['hub.mode'];
  const token = req.query['hub.verify_token'];
  const challenge = req.query['hub.challenge'];
  if (mode === 'subscribe' && token && VERIFY_TOKEN && crypto.timingSafeEqual(Buffer.from(token), Buffer.from(VERIFY_TOKEN))) {
    return res.status(200).send(challenge);
  }
  return res.sendStatus(403);
});

function validSignature(req) {
  if (!APP_SECRET) return true;
  const signature = req.headers['x-hub-signature-256'];
  if (!signature) return false;
  const digest = `sha256=${crypto.createHmac('sha256', APP_SECRET).update(req.rawBody).digest('hex')}`;
  return crypto.timingSafeEqual(Buffer.from(digest), Buffer.from(signature));
}

async function sendMetaMessages(to, messages) {
  if (!ACCESS_TOKEN || !PHONE_NUMBER_ID) {
    console.warn('Meta credentials are not configured; outbound message skipped.');
    return;
  }
  for (const message of messages) {
    await axios.post(
      `https://graph.facebook.com/v23.0/${PHONE_NUMBER_ID}/messages`,
      { messaging_product: 'whatsapp', recipient_type: 'individual', to, ...message },
      { timeout: 10000, headers: { Authorization: `Bearer ${ACCESS_TOKEN}`, 'Content-Type': 'application/json' } }
    );
  }
}

app.post('/webhook', async (req, res) => {
  if (!validSignature(req)) return res.sendStatus(403);
  res.sendStatus(200);

  for (const entry of req.body.entry || []) {
    for (const change of entry.changes || []) {
      for (const event of change.value?.messages || []) {
        const from = event.from;
        let text = '';
        let selectedId = null;

        if (event.type === 'text') text = event.text?.body || '';
        if (event.type === 'interactive') {
          selectedId = event.interactive?.button_reply?.id || event.interactive?.list_reply?.id || null;
          text = event.interactive?.button_reply?.title || event.interactive?.list_reply?.title || '';
        }

        try {
          const replies = await processIncoming(text, selectedId, from);
          await sendMetaMessages(from, replies);
        } catch (error) {
          console.error('Webhook processing failed:', error);
          await sendMetaMessages(from, [{ type: 'text', text: { body: 'Tuvimos un pequeño tropiezo técnico. Intenta de nuevo o escríbenos por WhatsApp.' } }]);
        }
      }
    }
  }
});

app.listen(PORT, '0.0.0.0', () => {
  console.log(`Full Training chatbot listening on port ${PORT}`);
});
