const fs = require('node:fs');
const path = require('node:path');

const ROOT = path.resolve(__dirname, '..');
const readText = (name) => fs.readFileSync(path.join(ROOT, 'Information', 'messages', name), 'utf8').trim();

const WELCOME = readText('mensaje_bienvenida.txt');
const GUADALUPE = readText('Horario_Guadalupe.txt');
const SANTA_ANITA = readText('Horario_bosque_Santa_Anita.txt');
const HYROX = readText('Hyrox.txt');

function readLinks() {
  const text = readText('Links.txt');
  const urls = {};
  for (const [, label, url] of text.matchAll(/(Guadalupe|Santa Anita|Wellness):\s*"([^"]+)"/gi)) {
    urls[label.toLowerCase().replace(/\s+/g, ' ')] = url;
  }
  return urls;
}

const LINKS = readLinks();
const sessions = new Map();

function normalize(value = '') {
  return value.normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase().replace(/[^a-z0-9]+/g, ' ').trim();
}

function distance(a, b) {
  const matrix = Array.from({ length: b.length + 1 }, (_, i) => [i]);
  for (let j = 0; j <= a.length; j++) matrix[0][j] = j;
  for (let i = 1; i <= b.length; i++) {
    for (let j = 1; j <= a.length; j++) {
      matrix[i][j] = b[i - 1] === a[j - 1]
        ? matrix[i - 1][j - 1]
        : Math.min(matrix[i - 1][j - 1], matrix[i][j - 1], matrix[i - 1][j]) + 1;
    }
  }
  return matrix[b.length][a.length];
}

function matchOption(text) {
  const input = normalize(text);
  const options = {
    guadalupe: ['guadalupe', 'guad', 'guadalup', 'gpe'],
    santa_anita: ['bosque santa anita', 'santa anita', 'santa', 'bosque', 'bosques'],
    wellness: ['wellness', 'bienestar', 'spa'],
    hyrox: ['hyrox', 'crossfit', 'competencia', 'reto']
  };
  for (const [option, aliases] of Object.entries(options)) {
    if (aliases.some((alias) => input.includes(alias) || (alias.length >= 5 && distance(input, alias) <= 2))) return option;
  }
  return null;
}

function optionsMenu() {
  return {
    type: 'interactive',
    interactive:
    {
      type: 'list',
      body: { text: 'Elige la opción que deseas conocer:' },
      action: {
        button: 'Ver opciones',
        sections: [{
          title: 'Full Training',
          rows: [
            { id: 'guadalupe', title: 'Guadalupe' },
            { id: 'santa_anita', title: 'Bosque Santa Anita' },
            { id: 'wellness', title: 'Wellness' },
            { id: 'hyrox', title: 'Hyrox' }
          ]
        }]
      }
    }
  };
}

function branchMenu() {
  return {
    type: 'interactive',
    interactive: {
      type: 'button',
      body: { text: 'HYROX está listo para ti. ¿En qué sucursal te gustaría entrenar?' },
      action: { buttons: [
        { type: 'reply', reply: { id: 'guadalupe', title: 'Guadalupe' } },
        { type: 'reply', reply: { id: 'santa_anita', title: 'Santa Anita' } }
      ] }
    }
  };
}

function isValidName(value) {
  const words = value.trim().split(/\s+/);
  return words.length >= 2 && /^[\p{L}\s.'’-]{3,100}$/u.test(value.trim());
}

function isValidPhone(value) {
  const digits = value.replace(/\D/g, '');
  return digits.length >= 8 && digits.length <= 15;
}

function isValidEmail(value) {
  return /^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/i.test(value.trim());
}

function isValidBirthYear(value) {
  const year = Number(value.trim());
  const current = new Date().getFullYear();
  return Number.isInteger(year) && year >= current - 100 && year <= current - 14;
}

function linkFor(option) {
  if (option === 'guadalupe') return LINKS.guadalupe;
  if (option === 'santa_anita') return LINKS['santa anita'];
  if (option === 'wellness') return LINKS.wellness;
  return LINKS.guadalupe;
}

function optionLabel(option) {
  return { guadalupe: 'Guadalupe', santa_anita: 'Bosque Santa Anita', wellness: 'Wellness', hyrox: 'Hyrox' }[option] || option;
}

function getSession(phone) {
  if (!sessions.has(phone)) sessions.set(phone, { phase: 'welcome', option: null, registration: {}, hasGreeted: false });
  return sessions.get(phone);
}

function resetSession(phone) {
  sessions.set(phone, { phase: 'welcome', option: null, registration: {}, hasGreeted: false });
}

async function appendRegistration(registration, option) {
  const url = process.env.GOOGLE_SHEET_WEBHOOK_URL;
  if (!url) return { skipped: true };
  const axios = require('axios');
  const now = new Date();
  const payload = {
    name: registration.name,
    phone: registration.phone,
    email: registration.email,
    birthYear: registration.birthYear,
    year: now.getFullYear(),
    month: now.getMonth() + 1,
    day: now.getDate(),
    option: optionLabel(option)
  };
  await axios.post(url, payload, { timeout: 10000, headers: { 'Content-Type': 'application/json' } });
  return payload;
}

async function processIncoming(text, selectedId, from) {
  const session = getSession(from);
  const input = (text || '').trim();
  const optionFromSelection = selectedId && matchOption(selectedId);

  if (/^(reiniciar|reset|inicio|menu|menú)$/i.test(input) || selectedId === 'menu') {
    resetSession(from);
    const resetSessionNow = getSession(from);
    resetSessionNow.hasGreeted = true;
    return [
      { type: 'text', text: { body: WELCOME } },
      optionsMenu()
    ];
  }

  if (session.phase === 'welcome') {
    if (!session.hasGreeted) {
      session.hasGreeted = true;
      const initialOption = optionFromSelection || matchOption(input);
      if (!initialOption) {
        return [
          { type: 'text', text: { body: WELCOME } },
          optionsMenu()
        ];
      }
      session.option = initialOption;
      return await enterOption(session, from);
    }

    const option = optionFromSelection || matchOption(input);
    if (!option) {
      return [{ type: 'text', text: { body: 'Para darte la mejor ruta, elige una de las cuatro opciones — ¡prometo no perseguirte por las demás! 😄' } }, optionsMenu()];
    }
    session.option = option;
    return await enterOption(session, from);
  }

  if (session.phase === 'hyrox_branch') {
    const branch = optionFromSelection || (matchOption(input) === 'guadalupe' ? 'guadalupe' : matchOption(input) === 'santa_anita' ? 'santa_anita' : null);
    if (!branch) return [{ type: 'text', text: { body: 'Elige una sucursal para que te muestre horarios y precios.' } }, branchMenu()];
    session.option = branch;
    session.phase = 'register_name';
    return await enterOption(session, from);
  }

  if (session.phase.startsWith('register_')) {
    return await collectRegistration(session, input, from);
  }

  if (session.phase === 'complete') {
    const link = linkFor(session.option);
    return [{ type: 'text', text: { body: `Ya quedó tu registro en modo “lista para entrenar” 😄 Para confirmar disponibilidad, precios o resolver cualquier duda, escríbinos por WhatsApp:\n${link}` } }];
  }

  return [{ type: 'text', text: { body: 'No tengo esa respuesta registrada, pero sí tengo el camino directo a nuestro equipo. Escríbenos por WhatsApp:' } }, { type: 'text', text: { body: linkFor(session.option) } }];
}

async function enterOption(session, from) {
  const baseUrl = (process.env.PUBLIC_BASE_URL || '').replace(/\/$/, '');
  if (session.option === 'guadalupe') {
    session.phase = 'register_name';
    const messages = [{ type: 'text', text: { body: GUADALUPE } }];
    if (baseUrl) messages.push({ type: 'image', image: { link: `${baseUrl}/media/precios_guadalupe.png`, caption: 'Precios de Guadalupe' } });
    messages.push({ type: 'text', text: { body: '¡Gran elección! Primero hagamos tu registro rápido. ¿Cuál es tu nombre completo?' } });
    return messages;
  }
  if (session.option === 'santa_anita') {
    session.phase = 'register_name';
    const messages = [{ type: 'text', text: { body: SANTA_ANITA } }];
    if (baseUrl) messages.push({ type: 'image', image: { link: `${baseUrl}/media/precios_bosque_santa_anita.png`, caption: 'Precios de Bosque Santa Anita' } });
    messages.push({ type: 'text', text: { body: '¡Excelente! Vamos con tu registro. ¿Cuál es tu nombre completo?' } });
    return messages;
  }
  if (session.option === 'wellness') {
    session.phase = 'register_name';
    const messages = [{ type: 'text', text: { body: 'Nuestro espacio Wellness de Full solo está disponible en la sucursal Guadalupe. ¡Es momento de darle balance a tanta fuerza! 🧘💪' } }];
    if (baseUrl) messages.push({ type: 'image', image: { link: `${baseUrl}/media/precios_guadalupe.png`, caption: 'Precios de Guadalupe' } });
    messages.push({ type: 'text', text: { body: 'Para registrarte en Wellness y comenzar tu plan, dime tu nombre completo.' } });
    return messages;
  }
  if (session.option === 'hyrox') {
    session.phase = 'hyrox_branch';
    return [{ type: 'text', text: { body: HYROX } }, branchMenu()];
  }
  return [];
}

async function collectRegistration(session, input, from) {
  if (session.phase === 'register_name') {
    if (!isValidName(input)) return [{ type: 'text', text: { body: 'Necesito tu nombre completo (nombre y apellido). Ejemplo: Ana López.' } }];
    session.registration.name = input;
    session.phase = 'register_phone';
    return [{ type: 'text', text: { body: '¿Cuál es tu número de teléfono? Puedes escribirlo con lada.' } }];
  }
  if (session.phase === 'register_phone') {
    if (!isValidPhone(input)) return [{ type: 'text', text: { body: 'Ese teléfono no parece válido. Escríbelo con entre 8 y 15 dígitos.' } }];
    session.registration.phone = input;
    session.phase = 'register_email';
    return [{ type: 'text', text: { body: 'Ahora necesito tu correo electrónico.' } }];
  }
  if (session.phase === 'register_email') {
    if (!isValidEmail(input)) return [{ type: 'text', text: { body: 'Revisa el correo, por favor. Debe tener este formato: nombre@dominio.com' } }];
    session.registration.email = input.trim().toLowerCase();
    session.phase = 'register_birthYear';
    return [{ type: 'text', text: { body: '¿Cuál es tu año de nacimiento? Escríbelo con 4 dígitos, por ejemplo: 1995.' } }];
  }
  if (session.phase === 'register_birthYear') {
    if (!isValidBirthYear(input)) return [{ type: 'text', text: { body: 'Escribe un año de nacimiento válido con 4 dígitos.' } }];
    session.registration.birthYear = input.trim();
    session.phase = 'complete';

    let sheetError = null;
    try {
      await appendRegistration(session.registration, session.option);
    } catch (error) {
      sheetError = error.message;
      console.error('Google Sheets append failed:', error.message);
    }

    const link = linkFor(session.option);
    const sheetWarning = sheetError ? '\n\nNota técnica: hubo un problema temporal al guardar el registro.' : '';
    return [{ type: 'text', text: { body: `¡Registro completado, ${session.registration.name}! 🔥 Ya estás un paso más cerca de tu mejor versión.${sheetWarning}\n\nPara confirmar tu clase o atención personalizada, escríbenos por WhatsApp:\n${link}` } }];
  }
  return [{ type: 'text', text: { body: 'No entendí tu respuesta. Podemos empezar de nuevo con “Inicio”.' } }];
}

module.exports = { processIncoming, getSession, sessions, ROOT };
