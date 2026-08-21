#!/usr/bin/env node
'use strict';
// enc.js - encoding-safe-edit implementation (Node; fallback runtime)
// Contract parity with enc.py (Python is the baseline).
// R8: GBK/GB18030 codec data is bundled in enc.gbkdata.js (generated from Python codec facts).
const fs = require('fs');
const path = require('path');
const cp = require('child_process');
const data = require('./enc.gbkdata.js');

const EXIT_OK = 0, EXIT_ERROR = 1, EXIT_UNMATCHED = 2;
const HINT_DUAL = 'valid in both utf-8 and gbk; follow project policy';
const HINT_NUL = 'contains many NUL bytes; maybe BOM-less UTF-16/UTF-32';
const HINT_BOM_CORRUPT = '带 BOM 但正文无法严格解码，可能已损坏';
const HINT_UTF32 = 'UTF-32 BOM detected but unsupported; convert with an external tool';
const HINT_CODECS = ['big5', 'shift_jis', 'euc_jp', 'euc_kr', 'cp1252'];
const MOJIBAKE_PATTERNS = ['锟斤拷', '锘', '鈥', 'Ã©', 'Ã¤'];
const DEFAULT_Q_RATIO = 0.05;

// ---------------- codec primitives (verified against Python) ----------------
function slotOf(lead, trail) { return (lead - 0x81) * 190 + (trail < 0x80 ? trail - 0x40 : trail - 0x80 + 63); }
const GBK = new Uint16Array(data.GBK_HEX.length / 4);
for (let i = 0; i < GBK.length; i++) GBK[i] = parseInt(data.GBK_HEX.substr(i * 4, 4), 16);
const FILL = new Map(data.GB18030_FILL);
function gb18030_2byte_cp(lead, trail) {
  const s = slotOf(lead, trail);
  const v = GBK[s];
  if (v) return v;
  return FILL.get(s) || 0;
}
const RANGES = data.GB18030_RANGES;
function gb18030_4byte_cp(b1, b2, b3, b4) {
  const idx = ((b1 - 0x81) * 10 + (b2 - 0x30)) * 1260 + (b3 - 0x81) * 10 + (b4 - 0x30);
  if (idx >= data.ASTRAL_START && idx <= data.ASTRAL_END) return idx + data.ASTRAL_DELTA;
  if (idx > data.ASTRAL_END) return -1;
  let lo = 0, hi = RANGES.length - 1;
  while (lo <= hi) {
    const mid = (lo + hi) >> 1;
    const st = RANGES[mid][0];
    if (idx < st) { hi = mid - 1; continue; }
    const nextSt = mid + 1 < RANGES.length ? RANGES[mid + 1][0] : 39420;
    if (idx >= nextSt) { lo = mid + 1; continue; }
    return idx + RANGES[mid][1];
  }
  return -1;
}
function gb18030_4byte_bytes(cp) {
  let idx;
  if (cp >= 0x10000) {
    idx = cp - data.ASTRAL_DELTA;
  } else {
    let lo = 0, hi = RANGES.length - 1, found = -1;
    while (lo <= hi) {
      const mid = (lo + hi) >> 1;
      const seg = RANGES[mid];
      const segStartCp = seg[0] + seg[1];
      const segEndCp = (mid + 1 < RANGES.length ? RANGES[mid + 1][0] : 39420) + seg[1] - 1;
      if (cp < segStartCp) hi = mid - 1;
      else if (cp > segEndCp) lo = mid + 1;
      else { found = mid; break; }
    }
    if (found < 0) return null;
    idx = cp - RANGES[found][1];
  }
  const x = idx;
  return Buffer.from([0x81 + Math.floor(x / 12600), 0x30 + (Math.floor(x / 1260) % 10), 0x81 + (Math.floor(x / 10) % 126), 0x30 + (x % 10)]);
}
function decodeGBK(buf) {
  const out = [];
  let i = 0;
  while (i < buf.length) {
    const c = buf[i];
    if (c < 0x80) { out.push(String.fromCharCode(c)); i++; continue; }
    if (c >= 0x81 && c <= 0xFE && i + 1 < buf.length) {
      const t = buf[i + 1];
      if ((t >= 0x40 && t <= 0x7E) || (t >= 0x80 && t <= 0xFE)) {
        const cpv = GBK[slotOf(c, t)];
        if (cpv) { out.push(String.fromCharCode(cpv)); i += 2; continue; }
      }
    }
    return null;
  }
  return out.join('');
}
function decodeGB18030(buf) {
  const out = [];
  let i = 0;
  while (i < buf.length) {
    const c = buf[i];
    if (c < 0x80) { out.push(String.fromCharCode(c)); i++; continue; }
    if (c >= 0x81 && c <= 0xFE && i + 1 < buf.length) {
      const t = buf[i + 1];
      if ((t >= 0x40 && t <= 0x7E) || (t >= 0x80 && t <= 0xFE)) {
        const cpv = gb18030_2byte_cp(c, t);
        if (cpv) { out.push(String.fromCharCode(cpv)); i += 2; continue; }
      }
      if (t >= 0x30 && t <= 0x39 && i + 3 < buf.length) {
        const b3 = buf[i + 2], b4 = buf[i + 3];
        if (b3 >= 0x81 && b3 <= 0xFE && b4 >= 0x30 && b4 <= 0x39) {
          const cpv = gb18030_4byte_cp(c, t, b3, b4);
          if (cpv > 0) { out.push(String.fromCodePoint(cpv)); i += 4; continue; }
        }
      }
    }
    return null;
  }
  return out.join('');
}
function decodeUTF8(buf) {
  // strict: re-encode must equal original (catches invalid sequences Node maps
  // to U+FFFD); legitimate U+FFFD (EF BF BD) round-trips, matching Python strict.
  const s = buf.toString('utf8');
  const re = Buffer.from(s, 'utf8');
  return re.equals(buf) ? s : null;
}
// Python utf-16-le/be strict decode validates surrogate well-formedness:
// high surrogate must be followed by low; lone low surrogate fails.
function decodeUTF16LE(buf, stripBom) {
  let start = 0;
  if (stripBom && buf.length >= 2 && buf[0] === 0xFF && buf[1] === 0xFE) start = 2;
  if ((buf.length - start) % 2 !== 0) return null;
  let s = '';
  let i = start;
  while (i < buf.length) {
    const u = buf[i] | (buf[i + 1] << 8);
    if (u >= 0xD800 && u <= 0xDBFF) {
      if (i + 3 >= buf.length) return null;
      const u2 = buf[i + 2] | (buf[i + 3] << 8);
      if (u2 < 0xDC00 || u2 > 0xDFFF) return null;
      s += String.fromCharCode(u, u2); i += 4;
    } else if (u >= 0xDC00 && u <= 0xDFFF) {
      return null;
    } else {
      s += String.fromCharCode(u); i += 2;
    }
  }
  return s;
}
function decodeUTF16BE(buf, stripBom) {
  let start = 0;
  if (stripBom && buf.length >= 2 && buf[0] === 0xFE && buf[1] === 0xFF) start = 2;
  if ((buf.length - start) % 2 !== 0) return null;
  let s = '';
  let i = start;
  while (i < buf.length) {
    const u = (buf[i] << 8) | buf[i + 1];
    if (u >= 0xD800 && u <= 0xDBFF) {
      if (i + 3 >= buf.length) return null;
      const u2 = (buf[i + 2] << 8) | buf[i + 3];
      if (u2 < 0xDC00 || u2 > 0xDFFF) return null;
      s += String.fromCharCode(u, u2); i += 4;
    } else if (u >= 0xDC00 && u <= 0xDFFF) {
      return null;
    } else {
      s += String.fromCharCode(u); i += 2;
    }
  }
  return s;
}
function hasLoneSurrogate(s) {
  for (let i = 0; i < s.length; i++) {
    const c = s.charCodeAt(i);
    if (c >= 0xD800 && c <= 0xDBFF) {
      if (i + 1 >= s.length) return true;
      const n = s.charCodeAt(i + 1);
      if (n < 0xDC00 || n > 0xDFFF) return true;
      i++;
    } else if (c >= 0xDC00 && c <= 0xDFFF) {
      return true;
    }
  }
  return false;
}
function encodeUTF8(s) { return hasLoneSurrogate(s) ? null : Buffer.from(s, 'utf8'); }
function encodeUTF16LE(s) {
  if (hasLoneSurrogate(s)) return null;
  const out = [];
  for (let i = 0; i < s.length; i++) {
    const c = s.charCodeAt(i);
    out.push(c & 0xFF, (c >> 8) & 0xFF);
  }
  return Buffer.from(out);
}
function encodeUTF16BE(s) {
  if (hasLoneSurrogate(s)) return null;
  const out = [];
  for (let i = 0; i < s.length; i++) {
    const c = s.charCodeAt(i);
    out.push((c >> 8) & 0xFF, c & 0xFF);
  }
  return Buffer.from(out);
}
const gbkInv = new Map();
for (let i = 0; i < GBK.length; i++) if (GBK[i] && !gbkInv.has(GBK[i])) gbkInv.set(GBK[i], i);
function encodeGBK(s) {
  const out = [];
  for (const ch of s) {
    const c = ch.codePointAt(0);
    if (c < 0x80) { out.push(c); continue; }
    const slot = gbkInv.get(c);
    if (slot === undefined) return null;
    const lead = 0x81 + Math.floor(slot / 190);
    const ti = slot % 190;
    out.push(lead, ti < 63 ? ti + 0x40 : ti - 63 + 0x80);
  }
  return Buffer.from(out);
}
const gb18030Inv = new Map();
for (let i = 0; i < GBK.length; i++) if (GBK[i] && !gb18030Inv.has(GBK[i])) gb18030Inv.set(GBK[i], i);
for (const [slot, cpv] of data.GB18030_FILL) if (!gb18030Inv.has(cpv)) gb18030Inv.set(cpv, slot);
function encodeGB18030(s) {
  const out = [];
  for (const ch of s) {
    const c = ch.codePointAt(0);
    if (c < 0x80) { out.push(c); continue; }
    if (c > 0x10FFFF || (c >= 0xD800 && c <= 0xDFFF)) return null;
    const slot = gb18030Inv.get(c);
    if (slot !== undefined) {
      const lead = 0x81 + Math.floor(slot / 190);
      const ti = slot % 190;
      out.push(lead, ti < 63 ? ti + 0x40 : ti - 63 + 0x80);
      continue;
    }
    const b4 = gb18030_4byte_bytes(c);
    if (!b4) return null;
    out.push(b4[0], b4[1], b4[2], b4[3]);
  }
  return Buffer.from(out);
}
function bitGet(b64, idx) {
  const buf = Buffer.from(b64, 'base64');
  return (buf[idx >> 3] >> (idx & 7)) & 1;
}
function decodeBig5(buf) {
  let i = 0;
  while (i < buf.length) {
    const c = buf[i];
    if (c < 0x80) { i++; continue; }
    if (c >= 0x81 && c <= 0xFE && i + 1 < buf.length) {
      const t = buf[i + 1];
      if ((t >= 0x40 && t <= 0x7E) || (t >= 0xA1 && t <= 0xFE)) {
        if (bitGet(data.HINTS.big5, (c - 0x81) * 157 + (t < 0x80 ? t - 0x40 : t - 0xA1 + 63))) { i += 2; continue; }
      }
    }
    return false;
  }
  return true;
}
function decodeShiftJIS(buf) {
  let i = 0;
  while (i < buf.length) {
    const c = buf[i];
    if (c < 0x80 || (c >= 0xA1 && c <= 0xDF)) { i++; continue; }
    if ((c >= 0x81 && c <= 0x9F) || (c >= 0xE0 && c <= 0xEF)) {
      if (i + 1 < buf.length) {
        const t = buf[i + 1];
        if ((t >= 0x40 && t <= 0x7E) || (t >= 0x80 && t <= 0xFC)) {
          const leadIdx = c <= 0x9F ? c - 0x81 : c - 0xE0 + 31;
          const trailIdx = t < 0x80 ? t - 0x40 : t - 0x80 + 63;
          if (bitGet(data.HINTS.shift_jis, leadIdx * 188 + trailIdx)) { i += 2; continue; }
        }
      }
    }
    return false;
  }
  return true;
}
function decodeEUCJP(buf) {
  let i = 0;
  while (i < buf.length) {
    const c = buf[i];
    if (c < 0x80) { i++; continue; }
    if (c === 0x8E && i + 1 < buf.length) { const n = buf[i + 1]; if (n >= 0xA1 && n <= 0xDF) { i += 2; continue; } return false; }
    if (c === 0x8F && i + 2 < buf.length) {
      const n1 = buf[i + 1], n2 = buf[i + 2];
      if (n1 >= 0xA1 && n1 <= 0xFE && n2 >= 0xA1 && n2 <= 0xFE) { i += 3; continue; }
      return false;
    }
    if (c >= 0xA1 && c <= 0xFE && i + 1 < buf.length) {
      const t = buf[i + 1];
      if (t >= 0xA1 && t <= 0xFE && bitGet(data.HINTS.euc_jp, (c - 0xA1) * 94 + (t - 0xA1))) { i += 2; continue; }
    }
    return false;
  }
  return true;
}
function decodeEUCKR(buf) {
  let i = 0;
  while (i < buf.length) {
    const c = buf[i];
    if (c < 0x80) { i++; continue; }
    if (c >= 0xA1 && c <= 0xFE && i + 1 < buf.length) {
      const t = buf[i + 1];
      if (t >= 0xA1 && t <= 0xFE && bitGet(data.HINTS.euc_kr, (c - 0xA1) * 94 + (t - 0xA1))) { i += 2; continue; }
    }
    return false;
  }
  return true;
}
function decodeCP1252(buf) {
  const undef = new Set(data.CP1252_UNDEFINED);
  for (const b of buf) if (b >= 0x80 && undef.has(b)) return false;
  return true;
}
// ---------------- legacy codec decode/encode (from data.LEGACY) ----------------
function legacyDecodeTable(codec) {
  const L = data.LEGACY[codec];
  const hex = L.decode || L.decode2;
  const arr = new Uint16Array(hex.length / 4);
  for (let i = 0; i < arr.length; i++) arr[i] = parseInt(hex.substr(i * 4, 4), 16);
  return { arr: arr, trails: L.trails, overrides: L.overrides || {}, special: L.special || {}, compose: L.compose || '', decode3: L.decode3 };
}
function decodeLegacy(buf, codec) {
  const T = legacyDecodeTable(codec);
  const arr = T.arr;
  const trails = T.trails;
  const out = [];
  let i = 0;
  while (i < buf.length) {
    const c = buf[i];
    if (c < 0x80) { out.push(String.fromCharCode(c)); i++; continue; }
    if (codec === 'cp1252') {
      const v = arr[c - 0x80];
      if (v) { out.push(String.fromCharCode(v)); i++; continue; }
      return null;
    }
    if (codec === 'shift_jis' && c >= 0xA1 && c <= 0xDF) { out.push(String.fromCharCode(0xFF61 + (c - 0xA1))); i++; continue; }
    if (codec === 'euc_jp' && c === 0x8E && i + 1 < buf.length) {
      const n = buf[i + 1];
      if (n >= 0xA1 && n <= 0xDF) { out.push(String.fromCharCode(0xFF61 + (n - 0xA1))); i += 2; continue; }
      return null;
    }
    if (codec === 'euc_jp' && c === 0x8F && i + 2 < buf.length) {
      const n1 = buf[i + 1], n2 = buf[i + 2];
      if (n1 >= 0xA1 && n1 <= 0xFE && n2 >= 0xA1 && n2 <= 0xFE) {
        const v = T.decode3 ? parseInt(T.decode3.substr(((n1 - 0xA1) * 94 + (n2 - 0xA1)) * 4, 4), 16) : 0;
        if (v) { out.push(String.fromCharCode(v)); i += 3; continue; }
      }
      return null;
    }
    if (codec === 'euc_jp' || codec === 'euc_kr') {
      if (c >= 0xA1 && c <= 0xFE && i + 1 < buf.length) {
        const t = buf[i + 1];
        if (t >= 0xA1 && t <= 0xFE) {
          const v = arr[(c - 0xA1) * 94 + (t - 0xA1)];
          if (v) { out.push(String.fromCharCode(v)); i += 2; continue; }
        }
      }
      return null;
    }
    if (codec === 'shift_jis') {
      if ((c >= 0x81 && c <= 0x9F) || (c >= 0xE0 && c <= 0xEF)) {
        if (i + 1 < buf.length) {
          const t = buf[i + 1];
          if ((t >= 0x40 && t <= 0x7E) || (t >= 0x80 && t <= 0xFC)) {
            const li = c <= 0x9F ? c - 0x81 : c - 0xE0 + 31;
            const ti = t < 0x80 ? t - 0x40 : t - 0x80 + 63;
            const v = arr[li * 188 + ti];
            if (v) { out.push(String.fromCharCode(v)); i += 2; continue; }
          }
        }
      }
      return null;
    }
    // big5: lead 0x81-0xFE, trail 0x40-0x7E / 0xA1-0xFE
    if (c >= 0x81 && c <= 0xFE && i + 1 < buf.length) {
      const t = buf[i + 1];
      if ((t >= 0x40 && t <= 0x7E) || (t >= 0xA1 && t <= 0xFE)) {
        const v = arr[(c - 0x81) * trails + (t < 0x80 ? t - 0x40 : t - 0xA1 + 63)];
        if (v) { out.push(String.fromCharCode(v)); i += 2; continue; }
      }
    }
    return null;
  }
  return out.join('');
}
function encodeLegacy(text, codec) {
  const T = legacyDecodeTable(codec);
  const arr = T.arr;
  const trails = T.trails;
  const inv = new Map();
  for (let i = 0; i < arr.length; i++) if (arr[i] && !inv.has(arr[i])) inv.set(arr[i], i);
  let compose = null;
  if (T.compose) {
    compose = new Map();
    for (const part of T.compose.split(';')) {
      if (!part) continue;
      const m = part.match(/^([0-9A-F]+):([0-9A-F]+)$/);
      if (m) compose.set(parseInt(m[1], 16), Buffer.from(m[2], 'hex'));
    }
  }
  const special = new Map();
  for (const k of Object.keys(T.special)) special.set(parseInt(k, 16), Buffer.from(T.special[k], 'hex'));
  const out = [];
  for (const ch of text) {
    const c = ch.codePointAt(0);
    if (c < 0x80) { out.push(c); continue; }
    if (special.has(c)) { for (const b of special.get(c)) out.push(b); continue; }
    if (codec === 'cp1252') {
      // invert single-byte
      let found = null;
      for (let i = 0; i < arr.length; i++) if (arr[i] === c) { found = i + 0x80; break; }
      if (found === null) return null;
      out.push(found);
      continue;
    }
    if (codec === 'shift_jis' && c >= 0xFF61 && c <= 0xFF9F) { out.push(0xA1 + (c - 0xFF61)); continue; }
    if (codec === 'euc_jp' && c >= 0xFF61 && c <= 0xFF9F) { out.push(0x8E, 0xA1 + (c - 0xFF61)); continue; }
    if (compose && compose.has(c)) { for (const b of compose.get(c)) out.push(b); continue; }
    const ov = T.overrides[c];
    const slot = ov !== undefined ? ov : inv.get(c);
    if (slot !== undefined) {
      if (codec === 'big5') {
        out.push(0x81 + Math.floor(slot / trails), (slot % trails) < 63 ? (slot % trails) + 0x40 : (slot % trails) - 63 + 0xA1);
      } else if (codec === 'shift_jis') {
        const n = 47;
        const li = Math.floor(slot / trails);
        const ti = slot % trails;
        out.push(li < 31 ? 0x81 + li : 0xE0 + (li - 31), ti < 63 ? ti + 0x40 : ti - 63 + 0x80);
      } else {
        out.push(0xA1 + Math.floor(slot / 94), 0xA1 + (slot % 94));
      }
      continue;
    }
    if (codec === 'euc_jp' && T.decode3) {
      // 3-byte (JIS X 0212)
      let found = -1;
      for (let i = 0; i < 94 * 94; i++) {
        if (parseInt(T.decode3.substr(i * 4, 4), 16) === c) { found = i; break; }
      }
      if (found >= 0) { out.push(0x8F, 0xA1 + Math.floor(found / 94), 0xA1 + (found % 94)); continue; }
    }
    return null;
  }
  return Buffer.from(out);
}
function normalizeEncoding(enc) {
  const e = String(enc).toLowerCase();
  const map = {
    'utf8': 'utf-8', 'utf_8': 'utf-8', 'u8': 'utf-8', 'utf': 'utf-8', 'cp65001': 'utf-8',
    'utf-16le': 'utf-16-le', 'utf16le': 'utf-16-le', 'utf_16_le': 'utf-16-le',
    'utf-16be': 'utf-16-be', 'utf16be': 'utf-16-be', 'utf_16_be': 'utf-16-be',
    'cp936': 'gbk', 'ms936': 'gbk', '936': 'gbk', 'gb2312': 'gbk', 'gb18030-2000': 'gb18030',
    'shift-jis': 'shift_jis', 'euc-jp': 'euc_jp', 'euc-kr': 'euc_kr',
  };
  return map[e] || e;
}
function decodeByEncoding(buf, enc) {
  enc = normalizeEncoding(enc);
  switch (enc) {
    case 'utf-8': return decodeUTF8(buf);
    case 'utf-16-le': return decodeUTF16LE(buf, false);
    case 'utf-16-be': return decodeUTF16BE(buf, false);
    case 'gbk': return decodeGBK(buf);
    case 'gb18030': return decodeGB18030(buf);
    case 'ascii': {
      for (const b of buf) if (b >= 0x80) return null;
      return buf.toString('latin1');
    }
    case 'big5': case 'shift_jis': case 'euc_jp': case 'euc_kr': case 'cp1252':
      return decodeLegacy(buf, enc);
    default: return null;
  }
}
function encodeByEncoding(text, enc) {
  enc = normalizeEncoding(enc);
  switch (enc) {
    case 'utf-8': return encodeUTF8(text);
    case 'utf-16-le': return encodeUTF16LE(text);
    case 'utf-16-be': return encodeUTF16BE(text);
    case 'gbk': return encodeGBK(text);
    case 'gb18030': return encodeGB18030(text);
    case 'ascii': {
      for (const ch of text) if (ch.codePointAt(0) > 0x7F) return null;
      return Buffer.from(text, 'latin1');
    }
    case 'big5': case 'shift_jis': case 'euc_jp': case 'euc_kr': case 'cp1252':
      return encodeLegacy(text, enc);
    default: return null;
  }
}
function decodeHintOk(buf, enc) {
  switch (enc) {
    case 'big5': return decodeBig5(buf);
    case 'shift_jis': return decodeShiftJIS(buf);
    case 'euc_jp': return decodeEUCJP(buf);
    case 'euc_kr': return decodeEUCKR(buf);
    case 'cp1252': return decodeCP1252(buf);
    default: return false;
  }
}
// ---------------- helpers ----------------
function emit(obj, exitCode) {
  process.stdout.write(JSON.stringify(obj) + '\n');
  process.exitCode = exitCode;
  return exitCode;
}
function errJson(error, exitCode, hint) {
  return { ok: false, error: error, exitCode: exitCode, hint: hint || null };
}
function log(msg) { process.stderr.write(msg + '\n'); }
function readBytes(p) { return fs.readFileSync(p); }
function isRegularFile(p) { try { return fs.statSync(p).isFile(); } catch (e) { return false; } }
function bomOf(buf) {
  if (buf.length >= 3 && buf[0] === 0xEF && buf[1] === 0xBB && buf[2] === 0xBF) return ['utf-8', buf.slice(3)];
  if (buf.length >= 4 && buf[0] === 0xFF && buf[1] === 0xFE && buf[2] === 0x00 && buf[3] === 0x00) return ['utf-32le', buf.slice(4)];
  if (buf.length >= 4 && buf[0] === 0x00 && buf[1] === 0x00 && buf[2] === 0xFE && buf[3] === 0xFF) return ['utf-32be', buf.slice(4)];
  if (buf.length >= 2 && buf[0] === 0xFF && buf[1] === 0xFE) return ['utf-16le', buf.slice(2)];
  if (buf.length >= 2 && buf[0] === 0xFE && buf[1] === 0xFF) return ['utf-16be', buf.slice(2)];
  return ['none', buf];
}
function bomBytes(kind) {
  if (kind === 'utf-8') return Buffer.from([0xEF, 0xBB, 0xBF]);
  if (kind === 'utf-16le') return Buffer.from([0xFF, 0xFE]);
  if (kind === 'utf-16be') return Buffer.from([0xFE, 0xFF]);
  return Buffer.alloc(0);
}
function detectLineEnding(t) {
  if (t.indexOf('\r\n') >= 0) {
    const rest = t.replace(/\r\n/g, '');
    if (rest.indexOf('\n') >= 0 || rest.indexOf('\r') >= 0) return 'mixed';
    return 'crlf';
  }
  if (t.indexOf('\r') >= 0) return t.indexOf('\n') >= 0 ? 'mixed' : 'cr';
  if (t.indexOf('\n') >= 0) return 'lf';
  return 'unknown';
}
function normalizeLf(t) { return t.replace(/\r\n/g, '\n').replace(/\r/g, '\n'); }
function splitKeepends(text) {
  const lines = text.match(/[^\r\n]*(?:\r\n|\r|\n|$)/g) || [];
  const out = [];
  for (const ln of lines) {
    if (ln === '') continue;
    const m = ln.match(/^(.*?)(\r\n|\r|\n|)$/);
    out.push([m[1], m[2]]);
  }
  return out;
}
function atomicWrite(p, buf) {
  const dir = path.dirname(path.resolve(p));
  const tmp = path.join(dir, '.enc-' + Date.now() + '-' + Math.random().toString(36).slice(2) + '.tmp');
  fs.writeFileSync(tmp, buf);
  let mode = null;
  try { mode = fs.statSync(p).mode; } catch (e) {}
  // POSIX：保留原文件权限位；Windows 不做（无意义且会干扰只读清理）
  if (mode !== null && process.platform !== 'win32') {
    try { fs.chmodSync(tmp, mode & 0o7777); } catch (e) {}
  }
  try { fs.renameSync(tmp, p); } catch (e) {
    try { if (process.platform === 'win32') { fs.chmodSync(tmp, 0o600); } } catch (e2) {}
    try { fs.unlinkSync(tmp); } catch (e2) {}
    throw e;
  }
}
function writeWithBackup(p, buf, backup) {
  if (backup) fs.copyFileSync(p, p + '.orig');
  atomicWrite(p, buf);
}
const CRED_RE = /((?:password|passwd|pwd|secret|token|api[_-]?key|authorization|credential)\s*[:=]\s*)[^\s,;"']+/gi;
function redact(text, limit) {
  const lim = limit || 60;
  const t = String(text).replace(CRED_RE, '$1***');
  return t.length <= lim ? t : t.slice(0, lim) + '...';
}
function verboseHex(buf, label) {
  // 先对文本样本脱敏再 hex（避免 hex 可逆泄露文件头明文，如 password=...）
  const sample = redact(buf.slice(0, 64).toString('latin1'));
  log('[verbose] ' + label + ' bytes=' + buf.length + ' first64=' + Buffer.from(sample, 'latin1').toString('hex').replace(/(..)/g, '$1 ').trim());
}

// ---------------- detect ----------------
function detectFile(p) {
  const data = readBytes(p);
  const [bomKind, body] = bomOf(data);
  const d = {
    file: path.resolve(p), encoding: 'unknown', confidence: 'low', bom: 'none',
    lineEnding: 'unknown', fffdCount: 0, asciiOnly: true, decodeHints: [],
    safeToEditDirectly: false, suggestedAction: 'unknown: ask'
  };
  const nulHeavy = data.length > 0 && (countNul(data) / data.length) > 0.01;
  if (bomKind === 'utf-32le' || bomKind === 'utf-32be') {
    d.decodeHints = [HINT_UTF32];
    return d;
  }
  if (bomKind === 'utf-8' || bomKind === 'utf-16le' || bomKind === 'utf-16be') {
    const enc = { 'utf-8': 'utf-8', 'utf-16le': 'utf-16-le', 'utf-16be': 'utf-16-be' }[bomKind];
    d.bom = bomKind;
    d.asciiOnly = allAscii(body);
    const t = decodeByEncoding(body, enc);
    if (t !== null) {
      d.encoding = bomKind;
      d.confidence = 'high';
      d.lineEnding = detectLineEnding(t);
      d.fffdCount = countFffd(t);
      d.safeToEditDirectly = false;
      d.suggestedAction = bomKind === 'utf-8' ? 'use replace tool' : 'use replace/convert tool';
    } else {
      d.encoding = bomKind;
      d.confidence = 'medium';
      d.decodeHints = [HINT_BOM_CORRUPT];
      d.safeToEditDirectly = false;
      d.suggestedAction = 'use replace tool / follow project policy';
    }
    return d;
  }
  if (allAscii(data)) {
    d.encoding = 'ascii';
    d.confidence = nulHeavy ? 'medium' : 'low';
    d.asciiOnly = true;
    if (nulHeavy) {
      d.decodeHints = [HINT_NUL];
      d.safeToEditDirectly = false;
      d.suggestedAction = 'use replace/convert tool with explicit --encoding';
    } else {
      d.safeToEditDirectly = true;
      d.suggestedAction = 'native edit allowed if project permits';
    }
    if (data.length > 0) d.lineEnding = detectLineEnding(data.toString('latin1'));
    return d;
  }
  d.asciiOnly = false;
  const utf8ok = decodeUTF8(data) !== null;
  const gbkok = decodeGBK(data) !== null;
  if (utf8ok) {
    d.encoding = 'utf-8';
    const t = decodeUTF8(data);
    d.lineEnding = detectLineEnding(t);
    d.fffdCount = countFffd(t);
    if (gbkok) {
      d.confidence = 'medium';
      d.decodeHints = [HINT_DUAL];
      d.safeToEditDirectly = false;
      d.suggestedAction = 'use replace tool / follow project policy';
    } else {
      d.confidence = 'high';
      d.safeToEditDirectly = true;
      d.suggestedAction = 'native edit allowed if project permits';
    }
    if (nulHeavy) {
      d.confidence = 'medium';
      d.decodeHints = [HINT_NUL];
      d.safeToEditDirectly = false;
      d.suggestedAction = 'use replace/convert tool with explicit --encoding';
    }
    return d;
  }
  if (gbkok) {
    d.encoding = 'gbk';
    const t = decodeGBK(data);
    d.lineEnding = detectLineEnding(t);
    d.fffdCount = countFffd(t);
    d.confidence = nulHeavy ? 'medium' : 'high';
    if (nulHeavy) {
      d.decodeHints = [HINT_NUL];
      d.safeToEditDirectly = false;
      d.suggestedAction = 'use replace/convert tool with explicit --encoding';
    } else {
      d.safeToEditDirectly = false;
      d.suggestedAction = 'use replace tool';
    }
    return d;
  }
  if (decodeGB18030(data) !== null) {
    d.encoding = 'gb18030';
    const t = decodeGB18030(data);
    d.lineEnding = detectLineEnding(t);
    d.fffdCount = countFffd(t);
    d.confidence = nulHeavy ? 'medium' : 'high';
    if (nulHeavy) {
      d.decodeHints = [HINT_NUL];
      d.safeToEditDirectly = false;
      d.suggestedAction = 'use replace/convert tool with explicit --encoding';
    } else {
      d.safeToEditDirectly = false;
      d.suggestedAction = 'use replace tool';
    }
    return d;
  }
  const hints = [];
  for (const c of HINT_CODECS) if (decodeHintOk(data, c)) hints.push('could be ' + c);
  if (nulHeavy) hints.push(HINT_NUL);
  d.decodeHints = hints;
  return d;
}
function countNul(buf) { let n = 0; for (const b of buf) if (b === 0) n++; return n; }
function allAscii(buf) { for (const b of buf) if (b >= 0x80) return false; return true; }
function countFffd(t) { let n = 0; for (const ch of t) if (ch === '\uFFFD') n++; return n; }

// ---------------- source encoding resolution (write-path fail-closed) ----------------
function resolveSourceEncoding(p, data, explicit) {
  if (explicit) {
    const ne = normalizeEncoding(explicit);
    if (ne === 'utf-16' || ne === 'utf16' || ne === 'utf_16') {
      return { err: "encoding '" + explicit + "' is ambiguous; use utf-16-le or utf-16-be" };
    }
    if (ne.indexOf('utf-32') === 0 || ne.indexOf('utf_32') === 0 || ne.indexOf('utf32') === 0) {
      return { err: "encoding '" + explicit + "' is not supported (UTF-32); convert with an external tool" };
    }
    const [bk] = bomOf(data);
    return { enc: ne, bom: bk };
  }
  const det = detectFile(p);
  if (det.encoding === 'unknown') return { err: 'unknown encoding; specify --encoding explicitly' };
  if (det.confidence === 'medium' && det.decodeHints.indexOf(HINT_NUL) >= 0) {
    return { err: 'NUL-heavy file (possible BOM-less UTF-16/UTF-32); specify --encoding utf-16-le/be explicitly' };
  }
  const [bomKind] = bomOf(data);
  return { enc: det.encoding, bom: bomKind };
}
function decodeWithBom(data, enc) {
  enc = normalizeEncoding(enc);
  if (enc === 'utf-8') {
    const [k, body] = bomOf(data);
    if (k !== 'none' && k !== 'utf-8') return null;
    return decodeUTF8(body);
  }
  if (enc === 'utf-16-le' || enc === 'utf-16le') {
    const [k, body] = bomOf(data);
    if (k !== 'none' && k !== 'utf-16le') return null;
    return decodeUTF16LE(body, false);
  }
  if (enc === 'utf-16-be' || enc === 'utf-16be') {
    const [k, body] = bomOf(data);
    if (k !== 'none' && k !== 'utf-16be') return null;
    return decodeUTF16BE(body, false);
  }
  return decodeByEncoding(data, enc);
}
function encodeWithBom(text, enc, bom) {
  enc = normalizeEncoding(enc);
  let out;
  if (enc === 'utf-8') out = encodeUTF8(text);
  else if (enc === 'utf-16-le' || enc === 'utf-16le') out = encodeUTF16LE(text);
  else if (enc === 'utf-16-be' || enc === 'utf-16be') out = encodeUTF16BE(text);
  else out = encodeByEncoding(text, enc);
  if (out === null) return null;
  return Buffer.concat([bomBytes(bom), out]);
}
function loadOps(opsArg, fromFile) {
  let raw;
  if (fromFile) {
    if (!fs.existsSync(fromFile)) return { err: 'ops file not found: ' + fromFile };
    try { raw = fs.readFileSync(fromFile, 'utf8'); } catch (e) { return { err: 'cannot read ops file: ' + e.message }; }
  } else raw = opsArg;
  let ops;
  try { ops = JSON.parse(raw); } catch (e) { return { err: 'ops JSON parse error: ' + e.message }; }
  if (!Array.isArray(ops)) return { err: 'ops must be a JSON array' };
  const cleaned = [];
  for (let i = 0; i < ops.length; i++) {
    const op = ops[i];
    if (!op || typeof op !== 'object' || typeof op.search !== 'string' || op.search === '') {
      return { err: 'ops[' + i + '] must be an object with non-empty string search' };
    }
    if (op.replace !== undefined && typeof op.replace !== 'string') {
      return { err: 'ops[' + i + '].replace must be a string' };
    }
    if (op.label !== undefined && typeof op.label !== 'string') {
      return { err: 'ops[' + i + '].label must be a string' };
    }
    cleaned.push({ search: op.search, replace: op.replace === undefined ? '' : op.replace, label: op.label === undefined ? 'op' + (i + 1) : op.label });
  }
  return { ops: cleaned };
}
function applyOps(text, ops) {
  const counts = ops.map(() => 0);
  const whole = ops.some(o => normalizeLf(o.search).indexOf('\n') >= 0 || normalizeLf(o.replace).indexOf('\n') >= 0);
  if (whole) {
    if (detectLineEnding(text) === 'mixed') {
      return { err: 'cannot apply multi-line op to a mixed-line-ending file (fail-closed); normalize line endings first' };
    }
    let cur = normalizeLf(text);
    for (let i = 0; i < ops.length; i++) {
      const s = normalizeLf(ops[i].search);
      const r = normalizeLf(ops[i].replace);
      let c = 0;
      let idx = cur.indexOf(s);
      while (idx >= 0) { c++; cur = cur.slice(0, idx) + r + cur.slice(idx + s.length); idx = cur.indexOf(s, idx + r.length); }
      counts[i] = c;
    }
    let end = '\n';
    if (text.indexOf('\r\n') >= 0) end = '\r\n';
    else if (text.indexOf('\r') >= 0) end = '\r';
    return { text: cur.replace(/\n/g, end), counts, whole: true };
  }
  const lines = splitKeepends(text);
  const newLines = [];
  for (const [content, term] of lines) {
    let c2 = content;
    for (let i = 0; i < ops.length; i++) {
      const s = ops[i].search;
      const r = ops[i].replace;
      let c = 0;
      let idx = c2.indexOf(s);
      while (idx >= 0) { c++; c2 = c2.slice(0, idx) + r + c2.slice(idx + s.length); idx = c2.indexOf(s, idx + r.length); }
      counts[i] += c;
    }
    newLines.push(c2 + term);
  }
  return { text: newLines.join(''), counts, whole: false };
}

// ---------------- commands ----------------
function cmdDetect(p) {
  if (!isRegularFile(p)) return emit(errJson('not a regular file: ' + p, EXIT_ERROR), EXIT_ERROR);
  try { return emit(detectFile(p), EXIT_OK); } catch (e) { return emit(errJson('IO error: ' + e.message, EXIT_ERROR), EXIT_ERROR); }
}
function cmdRead(p, out, explicit) {
  if (!isRegularFile(p)) return emit(errJson('not a regular file: ' + p, EXIT_ERROR), EXIT_ERROR);
  let data;
  try { data = readBytes(p); } catch (e) { return emit(errJson('IO error: ' + e.message, EXIT_ERROR), EXIT_ERROR); }
  const r = resolveSourceEncoding(p, data, explicit);
  if (r.err) return emit(errJson(r.err, EXIT_ERROR, 'use --encoding to specify the file encoding'), EXIT_ERROR);
  const text = decodeWithBom(data, r.enc);
  if (text === null) return emit(errJson('strict decode failed as ' + r.enc, EXIT_ERROR), EXIT_ERROR);
  if (out) {
    try { fs.writeFileSync(out, text, { encoding: 'utf8' }); } catch (e) { return emit(errJson('cannot write out file: ' + e.message, EXIT_ERROR), EXIT_ERROR); }
    return emit({ ok: true, out: path.resolve(out), encoding: r.enc, bom: r.bom, bytesWritten: Buffer.byteLength(text, 'utf8') }, EXIT_OK);
  }
  process.stdout.write(text);
  const det = explicit ? null : detectFile(p);
  if (det) log('detect: encoding=' + det.encoding + ' confidence=' + det.confidence + ' bom=' + det.bom + ' lineEnding=' + det.lineEnding);
  return EXIT_OK;
}
function cmdReplace(p, opsArg, fromFile, explicit, dryRun, noBackup, verbose, force) {
  if (!isRegularFile(p)) return emit(errJson('not a regular file: ' + p, EXIT_ERROR), EXIT_ERROR);
  const lo = loadOps(opsArg, fromFile);
  if (lo.err) return emit(errJson(lo.err, EXIT_ERROR), EXIT_ERROR);
  const ops = lo.ops;
  let data;
  try { data = readBytes(p); } catch (e) { return emit(errJson('IO error: ' + e.message, EXIT_ERROR), EXIT_ERROR); }
  const r = resolveSourceEncoding(p, data, explicit);
  if (r.err) return emit(errJson(r.err, EXIT_ERROR, 'use --encoding to specify the file encoding'), EXIT_ERROR);
  const text = decodeWithBom(data, r.enc);
  if (text === null) return emit(errJson('strict decode failed as ' + r.enc + ' (fail-closed; nothing written)', EXIT_ERROR), EXIT_ERROR);
  const applied = applyOps(text, ops);
  if (applied.err) return emit(errJson(applied.err, EXIT_ERROR), EXIT_ERROR);
  const unmatched = [];
  for (let i = 0; i < ops.length; i++) if (applied.counts[i] === 0) unmatched.push(ops[i].label);
  if (unmatched.length && !force) {
    return emit(errJson(unmatched.length + ' op(s) unmatched; nothing written (fail-closed)', EXIT_UNMATCHED, 'use --force to apply matched ops anyway'), EXIT_UNMATCHED);
  }
  if (dryRun) {
    const preview = ops.map((o, i) => ({ label: o.label, count: applied.counts[i] }));
    return emit({ ok: true, dryRun: true, applied: applied.counts.filter(c => c > 0).length, matches: preview, unmatched: unmatched, warnings: [] },
      unmatched.length ? EXIT_UNMATCHED : EXIT_OK);
  }
  const outBom = r.bom !== 'none' ? r.bom : 'none';
  const payload = encodeWithBom(applied.text, r.enc, outBom);
  if (payload === null) return emit(errJson('strict encode failed as ' + r.enc + ' (fail-closed; nothing written)', EXIT_ERROR), EXIT_ERROR);
  if (verbose) {
    verboseHex(data, 'original');
    verboseHex(payload, 'result');
    ops.forEach((o, i) => log('[verbose] op' + (i + 1) + ' ' + JSON.stringify(redact(o.search)) + ' -> ' + JSON.stringify(redact(o.replace)) + ' count=' + applied.counts[i]));
  }
  if (ops.length === 0) return emit({ ok: true, applied: 0, matches: [], backup: null, dryRun: false, warnings: [] }, EXIT_OK);
  try { writeWithBackup(p, payload, !noBackup); } catch (e) { return emit(errJson('write failed: ' + e.message, EXIT_ERROR), EXIT_ERROR); }
  if (verbose) log('[verbose] wrote ' + payload.length + ' bytes; backup=' + (noBackup ? null : p + '.orig'));
  const warnings = unmatched.map(l => ({ label: l }));
  return emit({ ok: true, applied: applied.counts.filter(c => c > 0).length,
    matches: ops.map((o, i) => ({ label: o.label, count: applied.counts[i] })),
    backup: noBackup ? null : p + '.orig', dryRun: false, warnings: warnings },
    unmatched.length ? EXIT_UNMATCHED : EXIT_OK);
}
function cmdConvert(p, to, fromEnc, bomPolicy, lineEnding, dryRun, noBackup) {
  if (!isRegularFile(p)) return emit(errJson('not a regular file: ' + p, EXIT_ERROR), EXIT_ERROR);
  if (!to) return emit(errJson('--to <encoding> is required', EXIT_ERROR), EXIT_ERROR);
  to = normalizeEncoding(to);
  if (to === 'utf-16' || to === 'utf16' || to === 'utf_16') {
    return emit(errJson('--to ' + to + ' is ambiguous; use utf-16-le or utf-16-be', EXIT_ERROR), EXIT_ERROR);
  }
  if (to.indexOf('utf-32') === 0 || to.indexOf('utf_32') === 0 || to.indexOf('utf32') === 0) {
    return emit(errJson('--to ' + to + ' is not supported (UTF-32); convert with an external tool', EXIT_ERROR), EXIT_ERROR);
  }
  let data;
  try { data = readBytes(p); } catch (e) { return emit(errJson('IO error: ' + e.message, EXIT_ERROR), EXIT_ERROR); }
  const r = resolveSourceEncoding(p, data, fromEnc);
  if (r.err) return emit(errJson(r.err, EXIT_ERROR, 'use --from to specify the source encoding'), EXIT_ERROR);
  const text0 = decodeWithBom(data, r.enc);
  if (text0 === null) return emit(errJson('strict decode failed as ' + r.enc + ' (fail-closed; nothing written)', EXIT_ERROR), EXIT_ERROR);
  let text = text0;
  if (lineEnding === 'crlf') text = normalizeLf(text).replace(/\n/g, '\r\n');
  else if (lineEnding === 'lf') text = normalizeLf(text);
  const [bomKind] = bomOf(data);
  let targetBom = 'none';
  if (to === 'utf-8') {
    if (bomPolicy === 'add' || (bomPolicy === 'keep' && bomKind !== 'none')) targetBom = 'utf-8';
  } else if (to === 'utf-16-le') {
    if (bomPolicy === 'add' || (bomPolicy === 'keep' && bomKind !== 'none')) targetBom = 'utf-16le';
  } else if (to === 'utf-16-be') {
    if (bomPolicy === 'add' || (bomPolicy === 'keep' && bomKind !== 'none')) targetBom = 'utf-16be';
  }
  const payload = encodeWithBom(text, to, targetBom);
  if (payload === null) return emit(errJson('strict encode failed as ' + to + ' (fail-closed; nothing written)', EXIT_ERROR), EXIT_ERROR);
  if (dryRun) return emit({ ok: true, dryRun: true, from: r.enc, to: to, bom: targetBom, lineEnding: lineEnding, backup: null }, EXIT_OK);
  try { writeWithBackup(p, payload, !noBackup); } catch (e) { return emit(errJson('write failed: ' + e.message, EXIT_ERROR), EXIT_ERROR); }
  return emit({ ok: true, from: r.enc, to: to, bom: targetBom, lineEnding: lineEnding, dryRun: false, backup: noBackup ? null : p + '.orig' }, EXIT_OK);
}
function cmdVerify(p, explicit) {
  if (!isRegularFile(p)) return emit(errJson('not a regular file: ' + p, EXIT_ERROR), EXIT_ERROR);
  let data;
  try { data = readBytes(p); } catch (e) { return emit(errJson('IO error: ' + e.message, EXIT_ERROR), EXIT_ERROR); }
  const det = detectFile(p);
  const enc = explicit || det.encoding;
  if (enc === 'unknown') return emit(errJson('unknown encoding; cannot verify', EXIT_ERROR, 'use --encoding'), EXIT_ERROR);
  const text = decodeWithBom(data, enc);
  if (text === null) return emit(errJson('strict decode failed as ' + enc + '; cannot verify', EXIT_ERROR), EXIT_ERROR);
  const fffdSamples = [];
  let fffdCount = 0;
  for (let i = 0; i < text.length; i++) {
    if (text[i] === '\uFFFD') {
      fffdCount++;
      if (fffdSamples.length < 5) {
        const pos = i;
        fffdSamples.push({ charOffset: pos, snippet: redact(text.slice(Math.max(0, pos - 10), pos + 11), 40) });
      }
    }
  }
  let qCount = 0;
  for (const ch of text) if (ch === '?') qCount++;
  const total = text.length;
  const qRatio = qCount / Math.max(1, total);
  const threshold = parseFloat(process.env.ENC_VERIFY_Q_RATIO || String(DEFAULT_Q_RATIO));
  let nonAscii = false;
  for (const ch of text) if (ch.charCodeAt(0) > 0x7F) { nonAscii = true; break; }
  const suspiciousQ = qRatio > threshold && nonAscii;
  const mojibake = {};
  for (const pat of MOJIBAKE_PATTERNS) {
    let c = 0, idx = text.indexOf(pat);
    while (idx >= 0) { c++; idx = text.indexOf(pat, idx + pat.length); }
    if (c) mojibake[pat] = c;
  }
  const damaged = fffdCount > 0 || Object.keys(mojibake).length > 0 || suspiciousQ;
  const action = damaged
    ? 'file appears damaged; restore from backup (e.g. <file>.orig) if available and re-edit via enc replace'
    : 'no damage detected; safe to proceed (run `enc cleanup <file>` to remove the backup snapshot)';
  return emit({ ok: true, file: path.resolve(p), encoding: enc, confidence: det.confidence,
    fffdCount: fffdCount, fffdSamples: fffdSamples, qCount: qCount, qRatio: Math.round(qRatio * 1e6) / 1e6,
    mojibakePatterns: mojibake, damaged: damaged, suggestedAction: action }, EXIT_OK);
}
function cmdCleanup(p) {
  if (!isRegularFile(p)) return emit(errJson('not a regular file: ' + p, EXIT_ERROR), EXIT_ERROR);
  const backup = p + '.orig';
  if (!fs.existsSync(backup)) {
    return emit({ ok: true, file: path.resolve(p), removed: null }, EXIT_OK);
  }
  let st;
  try { st = fs.statSync(backup); } catch (e) { return emit(errJson('cleanup failed: ' + e.message, EXIT_ERROR), EXIT_ERROR); }
  if (!st.isFile()) return emit(errJson('backup path is not a regular file: ' + backup, EXIT_ERROR), EXIT_ERROR);
  try { fs.unlinkSync(backup); } catch (e) { return emit(errJson('cleanup failed: ' + e.message, EXIT_ERROR), EXIT_ERROR); }
  return emit({ ok: true, file: path.resolve(p), removed: path.resolve(backup) }, EXIT_OK);
}
function existsOnPath(name) {
  const isWin = process.platform === 'win32';
  const exts = isWin ? ['', '.exe', '.cmd', '.bat'] : [''];
  const dirs = (process.env.PATH || '').split(path.delimiter).filter(Boolean);
  for (const d of dirs) {
    for (const ex of exts) {
      try { fs.accessSync(path.join(d, name) + ex, fs.constants.X_OK); return true; } catch (e) {}
    }
  }
  return false;
}
function probeRuntime(cmdArr) {
  const found = existsOnPath(cmdArr[0]);
  try {
    const out = cp.execFileSync(cmdArr[0], cmdArr.slice(1).concat(['--version']), { encoding: 'utf8', timeout: 15000 });
    const ok = out.trim().length > 0;
    return { found: found, usable: ok, version: ok ? out.trim().split(/\r?\n/)[0] : null };
  } catch (e) {
    return { found: found, usable: false, version: null };
  }
}
function cmdSelfcheck() {
  const runtimes = {};
  runtimes['python3'] = probeRuntime(['python3']);
  runtimes['python'] = probeRuntime(['python']);
  runtimes['py -3'] = probeRuntime(['py', '-3']);
  runtimes['uv'] = probeRuntime(['uv', 'run', '--no-project', 'python']);
  runtimes['node'] = probeRuntime(['node']);
  let selected = null;
  for (const name of ['python3', 'python', 'py -3', 'uv', 'node']) if (runtimes[name].usable) { selected = name; break; }
  return emit({ ok: selected !== null, runtimes: runtimes, selectedRuntime: selected,
    message: selected === null ? 'no usable runtime; install Python or Node, or use --runtime to force' : null }, EXIT_OK);
}

// ---------------- CLI ----------------
function takeOption(args, flag, needValue) {
  const rest = [];
  let value = null, found = false;
  for (let i = 0; i < args.length; i++) {
    const a = args[i];
    if (a.startsWith(flag + '=')) { found = true; value = a.slice(flag.length + 1); continue; }
    if (a === flag) {
      found = true;
      if (needValue) { if (i + 1 < args.length) { value = args[i + 1]; i++; } else value = null; }
      continue;
    }
    rest.push(a);
  }
  return { rest: rest, value: found ? value : undefined };
}
const USAGE = 'usage: enc <subcommand> [options]\n' +
  '  detect <file>\n' +
  '  read <file> [--out <utf8-path>] [--encoding <enc>]\n' +
  '  replace <file> <ops-json> | --from-file <ops-file> [--encoding <enc>] [--dry-run] [--no-backup] [--verbose] [--force]\n' +
  '  convert <file> --to <enc> [--from <enc>] [--bom add|remove|keep] [--line-ending keep|crlf|lf] [--dry-run] [--no-backup]\n' +
  '  verify <file> [--encoding <enc>]\n' +
  '  cleanup <file>\n' +
  '  selfcheck\n';
function main(argv) {
  if (!argv.length) { process.stderr.write(USAGE); return EXIT_ERROR; }
  const sub = argv[0];
  let args = argv.slice(1);
  if (sub === 'detect') {
    if (args.length !== 1) return emit(errJson('detect requires exactly one <file>', EXIT_ERROR), EXIT_ERROR);
    return cmdDetect(args[0]);
  }
  if (sub === 'read') {
    let o = takeOption(args, '--out', true); args = o.rest; const out = o.value;
    o = takeOption(args, '--encoding', true); args = o.rest; const enc = o.value;
    if (args.length !== 1) return emit(errJson('read requires exactly one <file>', EXIT_ERROR), EXIT_ERROR);
    return cmdRead(args[0], out, enc);
  }
  if (sub === 'replace') {
    let o = takeOption(args, '--from-file', true); args = o.rest; const ff = o.value;
    o = takeOption(args, '--encoding', true); args = o.rest; const enc = o.value;
    o = takeOption(args, '--dry-run'); args = o.rest; const dry = o.value !== undefined;
    o = takeOption(args, '--no-backup'); args = o.rest; const nb = o.value !== undefined;
    o = takeOption(args, '--verbose'); args = o.rest; const verb = o.value !== undefined;
    o = takeOption(args, '--force'); args = o.rest; const force = o.value !== undefined;
    if (ff !== undefined) {
      if (args.length !== 1) return emit(errJson('replace --from-file requires exactly one <file>', EXIT_ERROR), EXIT_ERROR);
      return cmdReplace(args[0], null, ff, enc, dry, nb, verb, force);
    }
    if (args.length !== 2) return emit(errJson('replace requires <file> <ops-json> or --from-file <ops-file>', EXIT_ERROR), EXIT_ERROR);
    return cmdReplace(args[0], args[1], null, enc, dry, nb, verb, force);
  }
  if (sub === 'convert') {
    let o = takeOption(args, '--to', true); args = o.rest; const to = o.value;
    o = takeOption(args, '--from', true); args = o.rest; const frm = o.value;
    o = takeOption(args, '--bom', true); args = o.rest; const bom = o.value;
    o = takeOption(args, '--line-ending', true); args = o.rest; const le = o.value;
    o = takeOption(args, '--dry-run'); args = o.rest; const dry = o.value !== undefined;
    o = takeOption(args, '--no-backup'); args = o.rest; const nb = o.value !== undefined;
    if (args.length !== 1) return emit(errJson('convert requires exactly one <file>', EXIT_ERROR), EXIT_ERROR);
    if (bom !== undefined && ['add', 'remove', 'keep'].indexOf(bom) < 0) return emit(errJson('--bom must be add|remove|keep', EXIT_ERROR), EXIT_ERROR);
    if (le !== undefined && ['keep', 'crlf', 'lf'].indexOf(le) < 0) return emit(errJson('--line-ending must be keep|crlf|lf', EXIT_ERROR), EXIT_ERROR);
    return cmdConvert(args[0], to, frm, bom || 'keep', le || 'keep', dry, nb);
  }
  if (sub === 'verify') {
    const o = takeOption(args, '--encoding', true); args = o.rest; const enc = o.value;
    if (args.length !== 1) return emit(errJson('verify requires exactly one <file>', EXIT_ERROR), EXIT_ERROR);
    return cmdVerify(args[0], enc);
  }
  if (sub === 'cleanup') {
    if (args.length !== 1) return emit(errJson('cleanup requires exactly one <file>', EXIT_ERROR), EXIT_ERROR);
    return cmdCleanup(args[0]);
  }
  if (sub === 'selfcheck') return cmdSelfcheck();
  return emit(errJson('unknown subcommand: ' + sub, EXIT_ERROR), EXIT_ERROR);
}
if (require.main === module) {
  process.exit(main(process.argv.slice(2)));
}
// exported for external test harnesses
module.exports = {
  decodeByEncoding, encodeByEncoding, decodeUTF8, decodeGBK, decodeGB18030,
  decodeUTF16LE, decodeUTF16BE, encodeUTF8, encodeUTF16LE, encodeUTF16BE,
  encodeGBK, encodeGB18030, decodeHintOk, detectFile,
};