/**
 * Procedural sound design — Web Audio API only, no shipped audio files.
 *
 * The sim doesn't need recorded audio: a single AudioContext with a few
 * synth voices gives a "rotor whirr that pitches with thrust" + intercept
 * klaxon + telemetry beeps + UI clicks at zero asset cost.
 *
 * Browsers won't let us start audio without a user gesture, so the
 * manager lazily initialises the AudioContext on the first call after a
 * click / keypress.  Safari additionally needs `resume()` on the first
 * user-driven event, which we handle via `ensureUnlocked()`.
 *
 * All sounds respect a master mute flag stored in the same module
 * (driven by the store toggle).
 */

let _ctx: AudioContext | null = null;
let _master: GainNode | null = null;
let _muted = false;

// Persistent rotor voice — one filtered noise source we can pitch on demand.
let _rotorNoise: AudioBufferSourceNode | null = null;
let _rotorFilter: BiquadFilterNode | null = null;
let _rotorGain: GainNode | null = null;

function getCtx(): AudioContext | null {
  if (typeof window === "undefined") return null;
  if (_ctx) return _ctx;
  const Cls = (window.AudioContext ||
    (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext);
  if (!Cls) return null;
  _ctx = new Cls();
  _master = _ctx.createGain();
  _master.gain.value = _muted ? 0 : 0.55;
  _master.connect(_ctx.destination);
  return _ctx;
}

function ensureUnlocked(ctx: AudioContext) {
  if (ctx.state === "suspended") {
    void ctx.resume();
  }
}

// --------------------------------------------------------------------- //
// Public mute control                                                   //
// --------------------------------------------------------------------- //

export function setMuted(muted: boolean) {
  _muted = muted;
  if (_master) _master.gain.value = muted ? 0 : 0.55;
}

export function isMuted() {
  return _muted;
}

// --------------------------------------------------------------------- //
// White-noise buffer (built once)                                       //
// --------------------------------------------------------------------- //

function makeNoiseBuffer(ctx: AudioContext, durationS = 2): AudioBuffer {
  const length = Math.floor(ctx.sampleRate * durationS);
  const buf = ctx.createBuffer(1, length, ctx.sampleRate);
  const data = buf.getChannelData(0);
  for (let i = 0; i < length; i++) data[i] = Math.random() * 2 - 1;
  return buf;
}

// --------------------------------------------------------------------- //
// ROTOR WHIRR                                                           //
// --------------------------------------------------------------------- //

export function startRotor() {
  const ctx = getCtx();
  if (!ctx || !_master) return;
  ensureUnlocked(ctx);
  if (_rotorNoise) return; // already running

  const buf = makeNoiseBuffer(ctx, 2);
  const src = ctx.createBufferSource();
  src.buffer = buf; src.loop = true;

  const filter = ctx.createBiquadFilter();
  filter.type = "bandpass";
  filter.frequency.value = 220;
  filter.Q.value = 1.4;

  const gain = ctx.createGain();
  gain.gain.value = 0.0;

  src.connect(filter).connect(gain).connect(_master);
  src.start();

  _rotorNoise = src;
  _rotorFilter = filter;
  _rotorGain = gain;
}

export function stopRotor() {
  if (_rotorNoise) {
    try { _rotorNoise.stop(); } catch {}
    _rotorNoise.disconnect();
    _rotorNoise = null;
  }
  if (_rotorFilter) { _rotorFilter.disconnect(); _rotorFilter = null; }
  if (_rotorGain)   { _rotorGain.disconnect();   _rotorGain = null; }
}

/**
 * Update the rotor whirr's pitch + level based on a thrust percentage
 * (0..1).  Smoothed to avoid clicks.  Call every frame from the scene.
 */
export function setRotorThrottle(throttle01: number) {
  if (!_rotorFilter || !_rotorGain || !_ctx) return;
  const t = Math.max(0, Math.min(1, throttle01));
  const target = 180 + t * 480;          // 180–660 Hz centre-frequency sweep
  const gain = 0.05 + t * 0.18;          // 5–23% mix
  const now = _ctx.currentTime;
  _rotorFilter.frequency.linearRampToValueAtTime(target, now + 0.08);
  _rotorGain.gain.linearRampToValueAtTime(gain,  now + 0.12);
}

// --------------------------------------------------------------------- //
// One-shot voices                                                       //
// --------------------------------------------------------------------- //

function envelope(g: GainNode, attack = 0.005, decay = 0.18, peak = 0.4) {
  if (!_ctx) return;
  const now = _ctx.currentTime;
  g.gain.cancelScheduledValues(now);
  g.gain.setValueAtTime(0, now);
  g.gain.linearRampToValueAtTime(peak, now + attack);
  g.gain.exponentialRampToValueAtTime(0.0001, now + attack + decay);
}

export function playClick() {
  const ctx = getCtx();
  if (!ctx || !_master) return;
  ensureUnlocked(ctx);
  const osc = ctx.createOscillator();
  osc.type = "triangle";
  osc.frequency.value = 1450;
  const g = ctx.createGain();
  osc.connect(g).connect(_master);
  envelope(g, 0.002, 0.06, 0.18);
  osc.start();
  osc.stop(ctx.currentTime + 0.08);
}

export function playBeep(freq = 880) {
  const ctx = getCtx();
  if (!ctx || !_master) return;
  ensureUnlocked(ctx);
  const osc = ctx.createOscillator();
  osc.type = "sine";
  osc.frequency.value = freq;
  const g = ctx.createGain();
  osc.connect(g).connect(_master);
  envelope(g, 0.005, 0.18, 0.32);
  osc.start();
  osc.stop(ctx.currentTime + 0.22);
}

export function playWaypointCapture() {
  // Two-tone "ding" — quick perfect-fifth interval.
  playBeep(880);
  setTimeout(() => playBeep(1320), 90);
}

export function playKlaxon() {
  const ctx = getCtx();
  if (!ctx || !_master) return;
  ensureUnlocked(ctx);
  // Two descending sawtooth pulses
  for (let i = 0; i < 2; i++) {
    const osc = ctx.createOscillator();
    osc.type = "sawtooth";
    const g = ctx.createGain();
    osc.connect(g).connect(_master);
    const startT = ctx.currentTime + i * 0.35;
    osc.frequency.setValueAtTime(740, startT);
    osc.frequency.exponentialRampToValueAtTime(380, startT + 0.28);
    g.gain.setValueAtTime(0.0001, startT);
    g.gain.linearRampToValueAtTime(0.5, startT + 0.02);
    g.gain.exponentialRampToValueAtTime(0.0001, startT + 0.32);
    osc.start(startT);
    osc.stop(startT + 0.35);
  }
}

export function playWhoosh() {
  const ctx = getCtx();
  if (!ctx || !_master) return;
  ensureUnlocked(ctx);
  const buf = makeNoiseBuffer(ctx, 0.4);
  const src = ctx.createBufferSource();
  src.buffer = buf;
  const filter = ctx.createBiquadFilter();
  filter.type = "lowpass";
  const now = ctx.currentTime;
  filter.frequency.setValueAtTime(2400, now);
  filter.frequency.exponentialRampToValueAtTime(380, now + 0.35);
  const g = ctx.createGain();
  g.gain.setValueAtTime(0.0001, now);
  g.gain.linearRampToValueAtTime(0.22, now + 0.04);
  g.gain.exponentialRampToValueAtTime(0.0001, now + 0.36);
  src.connect(filter).connect(g).connect(_master);
  src.start();
  src.stop(now + 0.4);
}
