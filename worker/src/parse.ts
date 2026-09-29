// Разбор страницы поиска игроков потоком через HTMLRewriter.
// Порт ttw_mcp/parsers/search.py и нужных хелперов из parsers/common.py.
//
// HTMLRewriter не строит дерево: обработчики срабатывают по селекторам по
// мере прихода байтов, текст приходит кусками. Поэтому каждая строка таблицы
// копит сырой текст ячеек, а превращение в числа идёт после конца потока.
// Там же проверяется якорь: не встретился div.player-list — значит вёрстка
// изменилась, и это ошибка, а не пустая выдача.

export const PLAYER_SEARCH_CAP = 500;
const PARSER = "parse_player_search";

export class ParseError extends Error {
  constructor(parser: string, selector: string, detail = "") {
    super(`${parser}: не найден ${selector}${detail ? ` — ${detail}` : ""}`);
  }
}

export class InvalidInput extends Error {}

// Python-овский \b понимает кириллицу, а JavaScript-овский — нет, даже с
// флагом u: для него «левая» не слово, и \b рядом с ней не срабатывает.
// Граница слова собрана вручную на тех же классах, что у Python \w.
const W = String.raw`[\p{L}\p{M}\p{N}_]`;
const B = String.raw`(?:(?<=${W})(?!${W})|(?<!${W})(?=${W}))`;
const HAND = new RegExp(
  String.raw`${B}(левая|правая|левой|правой)${B}(?:\s*/\s*|\s+)?(?:рука|руки|рукой|руков)?${B}`,
  "iu",
);
const HAND_CANONICAL: Record<string, string> = {
  левая: "левая",
  левой: "левая",
  правая: "правая",
  правой: "правая",
};
const EMPTY_GROUP = /\(\s*[/\s]*\)/gu;
const DATE = /(\d{2})\.(\d{2})\.(\d{4})/;
const NUMBER = /[+-]?\d+(?:\.\d+)?/;
const WIN_LOSS = /(\d+)\s*-\s*(\d+)/;
const ID = /[?&]id=([0-9a-f]+)/;

// lol-html отдаёт текст как есть, без раскодирования сущностей, а
// BeautifulSoup их раскодирует. Без этого «&quot;» попал бы в имя.
const NAMED: Record<string, string> = { amp: "&", lt: "<", gt: ">", quot: '"', apos: "'", nbsp: " " };
function decode(text: string): string {
  return text.replace(/&(#x[0-9a-f]+|#\d+|[a-z]+);/gi, (whole, body: string) => {
    if (body[0] === "#") {
      const code = body[1] === "x" || body[1] === "X" ? parseInt(body.slice(2), 16) : parseInt(body.slice(1), 10);
      return String.fromCodePoint(code);
    }
    return NAMED[body.toLowerCase()] ?? whole;
  });
}

export function clean(text: string): string {
  return decode(text).replace(/\s+/gu, " ").trim();
}

function parseNumber(text: string): number {
  const m = NUMBER.exec(text.replace(/,/g, "."));
  if (!m) throw new ParseError("parse_number", "число", `получено ${JSON.stringify(text)}`);
  return parseFloat(m[0]);
}

function parseInt_(text: string): number {
  return Math.trunc(parseNumber(text));
}

function parseDate(text: string): string {
  const m = DATE.exec(text);
  if (!m) throw new ParseError("parse_date", "DD.MM.YYYY", `получено ${JSON.stringify(text)}`);
  return `${m[3]}-${m[2]}-${m[1]}`;
}

function parseWinLoss(text: string): [number, number] {
  const m = WIN_LOSS.exec(text);
  if (!m) throw new ParseError("parse_win_loss", "В-П", `получено ${JSON.stringify(text)}`);
  return [parseInt(m[1], 10), parseInt(m[2], 10)];
}

function extractId(href: string): string {
  const m = ID.exec(href);
  if (!m) throw new ParseError("extract_id", "?id=", `получено ${JSON.stringify(href)}`);
  return m[1];
}

export function splitHand(name: string): [string, string | null] {
  const m = HAND.exec(name);
  if (!m) return [name, null];
  let rest = name.slice(0, m.index) + name.slice(m.index + m[0].length);
  rest = rest.replace(EMPTY_GROUP, " ").replace(/\(\s+/gu, "(");
  const cleaned = rest.split(/\s+/u).filter(Boolean).join(" ");
  if (!cleaned) return [name, null];
  return [cleaned, HAND_CANONICAL[m[1].toLowerCase()]];
}

const CELLS = ["city", "tournament", "games", "stat", "rating", "delta", "date"] as const;
type Cell = (typeof CELLS)[number];

interface RawRow {
  hasName: boolean;
  href: string | null;
  name: string;
  cells: Record<Cell, string>;
}

export interface Player {
  id: string;
  name: string;
  hand: string | null;
  city: string;
  tournaments: number;
  games: number;
  wins: number;
  losses: number;
  rating_current: number;
  delta: number;
  date: string;
}

export interface SearchResult {
  total_found: number;
  truncated: boolean;
  players: Player[];
}

function toPlayer(row: RawRow): Player {
  if (row.href === null || !clean(row.name)) {
    throw new ParseError(PARSER, "td.player-name-cell a");
  }
  const [wins, losses] = parseWinLoss(clean(row.cells.stat));
  const [name, hand] = splitHand(clean(row.name));
  return {
    id: extractId(row.href),
    name,
    hand,
    city: clean(row.cells.city),
    tournaments: parseInt_(clean(row.cells.tournament)),
    games: parseInt_(clean(row.cells.games)),
    wins,
    losses,
    rating_current: parseNumber(clean(row.cells.rating)),
    delta: parseNumber(clean(row.cells.delta)),
    date: parseDate(clean(row.cells.date)),
  };
}

// Разбирает поток ответа. Тело прокачивается через rewriter и выбрасывается:
// нам нужны только побочные эффекты обработчиков.
export async function parsePlayerSearch(body: Response, limit: number): Promise<SearchResult> {
  if (!Number.isInteger(limit) || limit < 1) {
    throw new InvalidInput(`limit должен быть положительным целым, получено ${limit}`);
  }
  let seenList = false;
  const rows: RawRow[] = [];
  let row: RawRow | null = null;

  // Ссылок в ячейке имени две: аватар и ФИО. Python отсекал первую через
  // :has(img), которого в HTMLRewriter нет. Здесь текст копится со всех
  // ссылок ячейки — у ссылки-аватара текста нет, так что остаётся ФИО.
  let rw = new HTMLRewriter()
    .on("div.player-list", { element() { seenList = true; } })
    .on("div.player-list tr", {
      element() {
        row = { hasName: false, href: null, name: "", cells: { city: "", tournament: "", games: "", stat: "", rating: "", delta: "", date: "" } };
        rows.push(row);
      },
    })
    .on("div.player-list td.player-name-cell", { element() { if (row) row.hasName = true; } })
    .on("div.player-list td.player-name-cell a", {
      element(e) { if (row && row.href === null) row.href = e.getAttribute("href"); },
      text(t) { if (row) row.name += t.text; },
    });
  for (const cell of CELLS) {
    rw = rw.on(`div.player-list td.player-${cell}-cell`, { text(t) { if (row) row.cells[cell] += t.text; } });
  }

  await rw.transform(body).body?.pipeTo(new WritableStream());

  if (!seenList) throw new ParseError(PARSER, "div.player-list");
  const named = rows.filter((r) => r.hasName);
  return {
    total_found: named.length,
    truncated: named.length >= PLAYER_SEARCH_CAP,
    players: named.slice(0, limit).map(toPlayer),
  };
}
