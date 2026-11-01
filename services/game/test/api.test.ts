import { describe, expect, it } from "vitest";
import { ApiClient, type FetchLike } from "../src/api.js";

function recorder() {
  const calls: { url: string; headers: Record<string, string> }[] = [];
  const fetchFn: FetchLike = async (url, init) => {
    calls.push({ url, headers: init.headers });
    return { ok: true, status: 200, json: async () => ({ uci: "e2e4", think_ms: 1000 }) };
  };
  return { calls, fetchFn };
}

describe("ApiClient iç belirteç", () => {
  it("belirteç verilince her isteğe x-internal-token ekler", async () => {
    const { calls, fetchFn } = recorder();
    const api = new ApiClient("http://api/", fetchFn, 1000, "s3cret");
    await api.botMove("g1", "fen", 0);
    await api.userMove("g1", { ply: 0, fen_before: "f", uci: "e2e4", spent_ms: 1, clock_ms: 1 });
    expect(calls.map((c) => c.headers["x-internal-token"])).toEqual(["s3cret", "s3cret"]);
    expect(calls[0].url).toBe("http://api/games/g1/bot-move");
  });

  it("belirteç yoksa başlık eklemez", async () => {
    const { calls, fetchFn } = recorder();
    await new ApiClient("http://api", fetchFn).botMove("g1", "fen", 0);
    expect("x-internal-token" in calls[0].headers).toBe(false);
  });
});
