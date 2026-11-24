const test = require('node:test');
const assert = require('node:assert/strict');
const { processIncoming, getSession } = require('../src/chatbot');

test('greets and offers four options', async () => {
  const phone = 'test-welcome';
  const messages = await processIncoming('', null, phone);
  assert.equal(messages.length, 2);
  assert.equal(messages[1].interactive.action.sections[0].rows.length, 4);
});

test('Guadalupe enters registration and validates name', async () => {
  const phone = 'test-guadalupe';
  await processIncoming('Guadalupe', null, phone);
  const invalid = await processIncoming('Ana', null, phone);
  assert.match(invalid[0].text.body, /nombre completo/i);
  const valid = await processIncoming('Ana López', null, phone);
  assert.match(valid[0].text.body, /teléfono/i);
});

test('Hyrox asks for a branch', async () => {
  const phone = 'test-hyrox';
  await processIncoming('Inicio', null, phone);
  const messages = await processIncoming('Hyrox', null, phone);
  assert.equal(messages.length, 2);
  assert.equal(messages[1].interactive.type, 'button');
});

test('unknown option is reprompted', async () => {
  const phone = 'test-unknown';
  await processIncoming('Inicio', null, phone);
  const messages = await processIncoming('volando por marte', null, phone);
  assert.match(messages[0].text.body, /elige/i);
  assert.equal(getSession(phone).phase, 'welcome');
});
