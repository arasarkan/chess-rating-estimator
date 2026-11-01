import fs from "node:fs";
import path from "node:path";
import type { GameState } from "./types.js";

/**
 * Oyun durumu deposu. Şimdilik bellek içi Map; aynı arayüzle Redis eklenebilir.
 */
export interface GameStore {
  get(gameId: string): GameState | undefined;
  save(state: GameState): void;
  all(): GameState[];
}

export class MemoryGameStore implements GameStore {
  protected map = new Map<string, GameState>();
  get(gameId: string) {
    return this.map.get(gameId);
  }
  save(state: GameState) {
    this.map.set(state.game_id, state);
  }
  all() {
    return [...this.map.values()];
  }
}

const SAFE_ID = /^[A-Za-z0-9_-]{1,128}$/;

/**
 * Bellek içi depo + her kayıtta `<dir>/<gid>.json` anlık görüntüsü.
 * Açılışta dizindeki tüm görüntüleri yükler (yeniden başlatmaya dayanıklılık).
 */
export class SnapshotGameStore extends MemoryGameStore {
  constructor(
    private dir: string,
    private log: (msg: string) => void = console.error,
  ) {
    super();
    fs.mkdirSync(dir, { recursive: true });
    for (const f of fs.readdirSync(dir)) {
      if (!f.endsWith(".json")) continue;
      try {
        const st = JSON.parse(fs.readFileSync(path.join(dir, f), "utf8")) as GameState;
        if (st && typeof st.game_id === "string" && Array.isArray(st.moves)) this.map.set(st.game_id, st);
      } catch (e) {
        this.log(`[store] anlık görüntü okunamadı: ${f}: ${String(e)}`);
      }
    }
  }

  override save(state: GameState) {
    super.save(state);
    if (!SAFE_ID.test(state.game_id)) {
      this.log(`[store] güvensiz game_id, diske yazılmadı: ${state.game_id}`);
      return;
    }
    const file = path.join(this.dir, `${state.game_id}.json`);
    const tmp = `${file}.tmp`;
    try {
      fs.writeFileSync(tmp, JSON.stringify(state));
      fs.renameSync(tmp, file);
    } catch (e) {
      this.log(`[store] anlık görüntü yazılamadı: ${state.game_id}: ${String(e)}`);
    }
  }
}
