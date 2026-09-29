# ttw-mcp worker (MVP)

Эксперимент: один инструмент `search_players` на Cloudflare Workers,
разбор страницы потоком через `HTMLRewriter` вместо BeautifulSoup. Цель —
замерить CPU на настоящем воркере и понять, укладывается ли разбор в
бесплатный лимит 10 мс на вызов.

MCP по Streamable HTTP без SDK: `POST /mcp`, одно JSON-RPC-сообщение на
запрос, ответ — обычный JSON. Состояния и сессий нет.

Доступ закрыт токеном (`Authorization: Bearer …`): открытый адрес был бы
прокси к сайту, который просит не обходить себя автоматически.

## Запуск

```bash
npm install
echo "AUTH_TOKEN=devtoken" > .dev.vars   # для wrangler dev
npm run dev                              # http://localhost:8787/mcp
```

## Деплой

```bash
npx wrangler login
npx wrangler secret put AUTH_TOKEN
npm run deploy                           # только workers.dev
claude mcp add --transport http ttw-worker https://ttw-mcp.<аккаунт>.workers.dev/mcp \
  --header "Authorization: Bearer <токен>"
```

## Где смотреть время

Часы воркера стоят во время вычислений, поэтому изнутри виден только
`Server-Timing: upstream;dur=…` — ожидание сайта. Процессорное время
каждого вызова — в Workers Logs (включены в `wrangler.toml`) или в
`npx wrangler tail --format json` (поля `cpuTime`, `wallTime`).

Локальный замер на сохранённых страницах (wall time, Apple Silicon, это
верхняя граница CPU):

| выдача | размер | время |
| --- | --- | --- |
| 0 строк | 11 KB | 1.3 мс |
| 177 строк | 174 KB | 33.9 мс |
| 500 строк (потолок) | 473 KB | 97.4 мс |

`limit` не экономит разбор: `total_found` требует пройти все строки.

Парсер сверен с `ttw_mcp/parsers/search.py` на тех же страницах —
расхождений нет.
