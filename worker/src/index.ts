// MCP по Streamable HTTP без SDK: сервер без состояния, каждый POST /mcp —
// одно JSON-RPC-сообщение, ответ — обычный JSON без SSE. Этого хватает
// клиентам для initialize → tools/list → tools/call.
//
// Доступ закрыт токеном: открытый адрес воркера был бы прокси к сайту,
// который просит не обходить себя автоматически.

import { InvalidInput, ParseError, parsePlayerSearch, type SearchResult } from "./parse";

interface Env {
  AUTH_TOKEN?: string;
}

const BASE_URL = "https://r.ttw.ru";
const USER_AGENT = "ttw-mcp/0.1 (+https://github.com/lappi/ttw-mcp)";
const TIMEOUT_MS = 30_000;
const SERVER_INFO = { name: "ttw", version: "0.0.1-worker" };
const PROTOCOLS = ["2025-11-25", "2025-06-18", "2025-03-26", "2024-11-05"];

const SEARCH_PLAYERS = {
  name: "search_players",
  description:
    "Ищет игроков r.ttw.ru по фамилии или части имени. Сайт возвращает максимум 500 строк " +
    "без пагинации; при достижении потолка truncated = true и запрос надо сузить. limit " +
    "укорачивает только players, total_found — сколько строк нашлось на самом деле.",
  inputSchema: {
    type: "object",
    properties: {
      name: { type: "string", description: "фамилия или часть имени" },
      limit: { type: "integer", minimum: 1, default: 25 },
    },
    required: ["name"],
  },
};

class UpstreamError extends Error {}

type Json = Record<string, unknown>;

function rpc(id: unknown, body: Json, headers: HeadersInit = {}): Response {
  return Response.json({ jsonrpc: "2.0", id, ...body }, { headers });
}

async function searchPlayers(args: Json): Promise<{ result: SearchResult; upstreamMs: number }> {
  const name = typeof args.name === "string" ? args.name.trim() : "";
  if (!name) throw new InvalidInput("name не может быть пустым");
  const limit = args.limit === undefined ? 25 : Number(args.limit);

  const url = `${BASE_URL}/players/?player-name=${encodeURIComponent(name)}`;
  // Часы воркера стоят, пока идёт вычисление, и сдвигаются только на
  // вводе-выводе. Эта разница — ожидание сайта, а не CPU; CPU смотреть
  // в Workers Logs.
  const started = Date.now();
  const response = await fetch(url, {
    headers: { "User-Agent": USER_AGENT },
    signal: AbortSignal.timeout(TIMEOUT_MS),
  });
  const upstreamMs = Date.now() - started;
  if (!response.ok) throw new UpstreamError(`${url}: HTTP ${response.status}`);
  const result = await parsePlayerSearch(response, limit);
  console.log(JSON.stringify({ tool: "search_players", upstream_ms: upstreamMs, found: result.total_found }));
  return { result, upstreamMs };
}

async function handle(message: Json): Promise<Response> {
  const { id, method } = message;
  const params = (message.params ?? {}) as Json;

  if (id === undefined) return new Response(null, { status: 202 }); // уведомление

  switch (method) {
    case "initialize": {
      const asked = String(params.protocolVersion ?? "");
      return rpc(id, {
        result: {
          protocolVersion: PROTOCOLS.includes(asked) ? asked : PROTOCOLS[1],
          capabilities: { tools: {} },
          serverInfo: SERVER_INFO,
        },
      });
    }
    case "ping":
      return rpc(id, { result: {} });
    case "tools/list":
      return rpc(id, { result: { tools: [SEARCH_PLAYERS] } });
    case "tools/call": {
      if (params.name !== SEARCH_PLAYERS.name) {
        return rpc(id, { error: { code: -32602, message: `неизвестный инструмент ${String(params.name)}` } });
      }
      try {
        const { result, upstreamMs } = await searchPlayers((params.arguments ?? {}) as Json);
        return rpc(
          id,
          { result: { content: [{ type: "text", text: JSON.stringify(result) }], structuredContent: result } },
          { "Server-Timing": `upstream;dur=${upstreamMs}` },
        );
      } catch (err) {
        // Ошибки инструмента уходят в result с isError, чтобы модель их видела.
        const kind = err instanceof InvalidInput ? "InvalidInput" : err instanceof ParseError ? "ParseError" : "UpstreamError";
        const text = `${kind}: ${err instanceof Error ? err.message : String(err)}`;
        return rpc(id, { result: { content: [{ type: "text", text }], isError: true } });
      }
    }
    default:
      return rpc(id, { error: { code: -32601, message: `метод не поддерживается: ${String(method)}` } });
  }
}

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    const { pathname } = new URL(request.url);
    if (pathname !== "/mcp") return new Response("not found", { status: 404 });

    if (!env.AUTH_TOKEN) return new Response("AUTH_TOKEN не задан", { status: 500 });
    if (request.headers.get("Authorization") !== `Bearer ${env.AUTH_TOKEN}`) {
      return new Response("unauthorized", { status: 401, headers: { "WWW-Authenticate": "Bearer" } });
    }
    // Потока уведомлений от сервера нет, GET и DELETE сессии не нужны.
    if (request.method !== "POST") return new Response(null, { status: 405, headers: { Allow: "POST" } });

    let message: unknown;
    try {
      message = await request.json();
    } catch {
      return rpc(null, { error: { code: -32700, message: "некорректный JSON" } });
    }
    if (typeof message !== "object" || message === null || Array.isArray(message)) {
      return rpc(null, { error: { code: -32600, message: "ожидалось одно JSON-RPC-сообщение" } });
    }
    return handle(message as Json);
  },
};
