import http from "node:http";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { WebSocketServer, WebSocket } from "ws";
import { ApiClient, type FetchLike } from "./api.js";
import { GameServer } from "./game.js";
import { SnapshotGameStore } from "./store.js";
import type { Conn } from "./types.js";

const PORT = Number(process.env.PORT ?? 8080);
const API_URL = process.env.API_URL ?? "http://localhost:8000";
const here = path.dirname(fileURLToPath(import.meta.url));
const DATA_DIR = process.env.GAME_DATA_DIR ?? path.resolve(here, "..", "data");

const log = (m: string) => console.log(`${new Date().toISOString()} ${m}`);

const store = new SnapshotGameStore(DATA_DIR, log);
const INTERNAL_TOKEN = process.env.CHESSDEX_INTERNAL_TOKEN || undefined;
const api = new ApiClient(API_URL, fetch as unknown as FetchLike, 10_000, INTERNAL_TOKEN);
if (!INTERNAL_TOKEN) log("[game] UYARI: CHESSDEX_INTERNAL_TOKEN yok; ölçüm servisi /games/* uçlarını korumasız çalıştırıyorsa üretim için uygun değil");
const games = new GameServer({ api, store, log });

const server = http.createServer((req, res) => {
  if (req.url === "/health") {
    res.writeHead(200, { "content-type": "application/json" });
    res.end(JSON.stringify({ ok: true }));
    return;
  }
  res.writeHead(404, { "content-type": "application/json" });
  res.end(JSON.stringify({ detail: "not found" }));
});

const wss = new WebSocketServer({ server, path: "/ws" });
const alive = new WeakMap<WebSocket, boolean>();

wss.on("connection", (ws) => {
  alive.set(ws, true);
  const conn: Conn = {
    send(msg) {
      if (ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify(msg));
    },
  };
  ws.on("pong", () => alive.set(ws, true));
  ws.on("message", (data) => {
    try {
      games.handleMessage(conn, data.toString());
    } catch (e) {
      log(`[ws] mesaj işlenemedi: ${String(e)}`);
    }
  });
  ws.on("close", () => games.handleClose(conn));
  ws.on("error", (e) => log(`[ws] hata: ${String(e)}`));
});

// Ölü bağlantıları yakala (kopma tespiti -> 60 sn terk sayacı).
const heartbeat = setInterval(() => {
  for (const ws of wss.clients) {
    if (alive.get(ws) === false) {
      ws.terminate();
      continue;
    }
    alive.set(ws, false);
    ws.ping();
  }
}, 15_000);

server.listen(PORT, () => log(`[game] ws://localhost:${PORT}/ws  (API_URL=${API_URL}, data=${DATA_DIR})`));

function shutdown() {
  clearInterval(heartbeat);
  games.shutdown();
  wss.close();
  server.close(() => process.exit(0));
  setTimeout(() => process.exit(0), 2_000).unref();
}
process.on("SIGINT", shutdown);
process.on("SIGTERM", shutdown);
