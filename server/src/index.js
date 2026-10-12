/* Air Cricket rooms.
   One Durable Object per room code keeps who is in the room and how each of them is getting on, and passes
   updates between them over WebSockets. The game itself runs on each phone: everyone in a match gets the
   same chase code, so the same balls come down for all of them, and only scores travel.

     GET /                -> "ok"
     GET /room/<CODE>     -> WebSocket into that room

   Client -> room                                     Room -> clients
     hello { pid, name, mode: 'create' | 'join' }       roster { code, host, round, match, players: [...] }
     start { level }            (host only)             start  { code, level, round }
     ball  { round, runs, wkts, balls, mark }           ball   { pid, round, runs, wkts, balls, mark }
     done  { round, runs, wkts, balls, res }            done   { pid, round, runs, wkts, balls, res }
     leave {}                                           error  { why: 'no-room' | 'taken' | 'full' | ... }
*/

const CODE = /^[A-HJ-NP-Z2-9]{4}$/;          // no I, O, 0 or 1, so codes read clearly over the phone
const PID = /^[a-z0-9]{8,24}$/;
const MAX_PLAYERS = 4;
const LEVELS = ['club', 'pro', 'intl'];
const IDLE_MS = 60 * 60 * 1000;              // an empty room is forgotten after an hour

export default {
  async fetch(req, env) {
    const url = new URL(req.url);
    if (url.pathname === '/') return new Response('ok', { headers: { 'content-type': 'text/plain' } });
    const m = url.pathname.match(/^\/room\/([A-Za-z0-9]+)$/);
    if (!m || !CODE.test(m[1].toUpperCase())) return new Response('not found', { status: 404 });
    if (req.headers.get('Upgrade') !== 'websocket') return new Response('expected a WebSocket', { status: 426 });
    const code = m[1].toUpperCase();
    return env.ROOMS.get(env.ROOMS.idFromName(code)).fetch(new Request(`https://room/${code}`, req));
  },
};

const int = (v, lo, hi) => Number.isInteger(v) && v >= lo && v <= hi;
const cleanName = s => String(s || '').replace(/[\u0000-\u001f\u007f<>]/g, '').trim().slice(0, 16) || 'Player';

export class Room {
  constructor(ctx) {
    this.ctx = ctx;
    this.room = null;
    // phones send "ping" every 25 s to keep mobile networks from dropping the connection; answer without waking the room
    ctx.setWebSocketAutoResponse(new WebSocketRequestResponsePair('ping', 'pong'));
  }

  async load(code) {
    if (!this.room) this.room = (await this.ctx.storage.get('room')) || { code, host: null, round: 0, match: null, players: {} };
    return this.room;
  }
  save() { return this.ctx.storage.put('room', this.room); }

  async fetch(req) {
    const code = new URL(req.url).pathname.slice(1);
    await this.load(code);
    const [client, server] = Object.values(new WebSocketPair());
    this.ctx.acceptWebSocket(server);
    server.serializeAttachment({ code, pid: null });
    await this.ctx.storage.deleteAlarm();
    return new Response(null, { status: 101, webSocket: client });
  }

  sockets(except) { return this.ctx.getWebSockets().filter(ws => ws !== except); }
  online(except) { return new Set(this.sockets(except).map(ws => (ws.deserializeAttachment() || {}).pid).filter(Boolean)); }
  send(ws, msg) { try { ws.send(JSON.stringify(msg)); } catch (_) { /* gone */ } }
  broadcast(msg, except) { const s = JSON.stringify(msg); for (const ws of this.sockets(except)) { try { ws.send(s); } catch (_) {} } }
  roster(except) {
    const r = this.room, on = this.online(except);
    return {
      t: 'roster', code: r.code, host: r.host, round: r.round, match: r.match,
      players: Object.entries(r.players).map(([pid, p]) => ({ pid, name: p.name, online: on.has(pid), runs: p.runs, wkts: p.wkts, balls: p.balls, done: p.done, res: p.res })),
    };
  }
  fail(ws, why) { this.send(ws, { t: 'error', why }); try { ws.close(4000, why); } catch (_) {} }

  async webSocketMessage(ws, raw) {
    if (raw === 'ping') return this.send(ws, 'pong');
    if (typeof raw !== 'string' || raw.length > 2048) return this.fail(ws, 'bad-message');
    let msg; try { msg = JSON.parse(raw); } catch (_) { return this.fail(ws, 'bad-message'); }
    const att = ws.deserializeAttachment() || {};
    const r = await this.load(att.code);

    if (msg.t === 'hello') {
      if (!PID.test(msg.pid || '')) return this.fail(ws, 'bad-hello');
      const known = !!r.players[msg.pid], count = Object.keys(r.players).length;
      if (!known && msg.mode === 'join' && count === 0) return this.fail(ws, 'no-room');
      if (!known && msg.mode === 'create' && count > 0) return this.fail(ws, 'taken');
      if (!known && count >= MAX_PLAYERS) return this.fail(ws, 'full');
      for (const other of this.sockets(ws))              // a reconnect replaces the old connection
        if ((other.deserializeAttachment() || {}).pid === msg.pid) { try { other.close(4001, 'replaced'); } catch (_) {} }
      ws.serializeAttachment({ code: att.code, pid: msg.pid });
      const p = r.players[msg.pid] || (r.players[msg.pid] = { runs: 0, wkts: 0, balls: 0, done: false, res: null, round: 0 });
      p.name = cleanName(msg.name);
      if (!r.host || !r.players[r.host]) r.host = msg.pid;
      await this.save();
      this.broadcast(this.roster());
      if (r.match) this.send(ws, { t: 'start', ...r.match, round: r.round });   // a late joiner gets the match in progress
      return;
    }

    const pid = att.pid, me = pid && r.players[pid];
    if (!me) return this.fail(ws, 'say-hello');

    if (msg.t === 'start') {
      if (pid !== r.host && this.online().has(r.host)) return this.send(ws, { t: 'error', why: 'not-host' });
      r.host = pid;                                      // the host has gone away: whoever starts takes over
      if (Object.keys(r.players).length < 2) return this.send(ws, { t: 'error', why: 'alone' });
      r.round++;
      r.match = { code: 1000 + Math.floor(Math.random() * 899000), level: LEVELS.includes(msg.level) ? msg.level : 'pro' };
      for (const p of Object.values(r.players)) Object.assign(p, { runs: 0, wkts: 0, balls: 0, done: false, res: null, round: r.round });
      await this.save();
      this.broadcast({ t: 'start', ...r.match, round: r.round });
      return;
    }

    if (msg.t === 'ball' || msg.t === 'done') {
      if (msg.round !== r.round || !int(msg.runs, 0, 999) || !int(msg.wkts, 0, 10) || !int(msg.balls, 0, 600)) return;
      Object.assign(me, { runs: msg.runs, wkts: msg.wkts, balls: msg.balls, round: r.round });
      const out = { t: msg.t, pid, round: r.round, runs: msg.runs, wkts: msg.wkts, balls: msg.balls };
      if (msg.t === 'ball') out.mark = String(msg.mark == null ? '' : msg.mark).slice(0, 4);
      else { me.done = true; me.res = out.res = ['won', 'lost', 'tie'].includes(msg.res) ? msg.res : 'lost'; }
      await this.save();
      this.broadcast(out);
      return;
    }

    if (msg.t === 'leave') {
      delete r.players[pid];
      if (r.host === pid) r.host = Object.keys(r.players)[0] || null;
      ws.serializeAttachment({ code: att.code, pid: null });
      try { ws.close(1000, 'left'); } catch (_) {}
      if (!r.host) { this.room = null; await this.ctx.storage.deleteAll(); return; }
      await this.save();
      this.broadcast(this.roster(ws), ws);
    }
  }

  async webSocketClose(ws) { await this.gone(ws); }
  async webSocketError(ws) { await this.gone(ws); }
  async gone(ws) {
    const att = ws.deserializeAttachment() || {};
    if (!att.code) return;
    await this.load(att.code);
    if (this.sockets(ws).length === 0) { await this.ctx.storage.setAlarm(Date.now() + IDLE_MS); return; }
    this.broadcast(this.roster(ws), ws);                  // the others see this player as away
  }

  async alarm() {
    if (this.ctx.getWebSockets().length === 0) { this.room = null; await this.ctx.storage.deleteAll(); }
  }
}
