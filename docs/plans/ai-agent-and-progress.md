# Edytor PDF: agent AI w panelu czatu + widoczny postęp OCR i innych operacji

Plan wykonawczy dla zespołu agentów Claude (Claude Code: subagenci w jednej sesji albo kilka sesji/worktree).
Jeden pakiet pracy (WP) = jeden agent = jeden branch. Kontrakty z sekcji 4 są **zamrożone**: agenci implementują
je dokładnie, a zmiany kontraktu idą tylko przez WP0.

## 1. Cel

1. **Agent AI obok dokumentu.** Panel czatu (desktop: prawy sidebar, telefon: pełnoekranowy arkusz), w którym
   użytkownik pisze np. „popraw literówki na tej stronie”, „skróć akapit o cenach”, „przetłumacz strony 2–4 na
   angielski”, „zaczernij wszystkie PESEL-e”. Agent czyta strony, planuje, wywołuje narzędzia i zwraca
   **propozycje zmian** (diff „przed / po”), które użytkownik akceptuje pojedynczo albo hurtem. Każda zaakceptowana
   paczka to jedna pozycja w historii cofania.
2. **Widoczny postęp.** OCR pokazuje etapy na żywo (render → orientacja → wykrywanie linii → rozpoznawanie →
   warstwa tekstu → dobór kroju). Wykryte linie pojawiają się na stronie, zanim tekst zostanie rozpoznany.
   Tak samo widać postęp: tłumaczenia, wyszukiwania, zapisu, podpisu, AI rewrite, indeksu czcionek i odpowiedzi
   agenta. Wszystko trafia do wspólnego „centrum aktywności” w edytorze.

Poza zakresem: zmiana modelu danych edycji. Agent generuje **te same opy**, co UI (`text`, `annot`, `redact`,
`page`…), więc podgląd, zapis, autozapis, cofanie i podpis działają bez zmian.

## 2. Stan obecny (punkt wyjścia)

| Obszar | Gdzie | Uwagi |
|---|---|---|
| Opy edycji, podgląd, zapis | `app/services/pdf_editor.py` (`render_preview`, `apply_ops`, `page_layout`) | podgląd cache'owany (`PREVIEWS`), układ strony = `blocks/images/annots/widgets/words` |
| Trasy edytora | `app/routes/api_pdf.py` (`/pdf/edit/*`) | `resolve_edit_ops`, `get_pdf_job`, `touch_file` |
| LLM | `app/services/llm.py` (LM Studio, `http://localhost:1234/api/v1/chat`) | brak tool-callingu; jest streaming SSE w `chat_with_context` |
| AI rewrite / tłumaczenie | `app/services/pdf_ai.py` (`rewrite`, `translate_page`, `block_text`, `block_op`) | `block_op` generuje poprawny op `text` z `fit: true` |
| Wyszukiwanie wzorców | `app/services/pdf_search.py`, `pdf_editor.search_document` | PESEL/NIP/IBAN… z walidacją |
| OCR | `app/services/pdf_scan.py` (`OcrCache`, `render_orientations`, `recognize_renders`, `OcrPending`) | w tle, klient odpytuje co 2,5 s; **brak informacji o postępie** |
| Klient edytora | `app/static/js/pdf-editor.js` (~2400 linii, IIFE `PdfEditor`) | arkusze `renderSheet`, baner `showBanner`, `pushOps` z grupami cofania |
| Moduły pomocnicze | `pdf-editor-drafts.js`, `pdf-editor-sign.js` | wzorzec do naśladowania dla nowych modułów |
| Realtime | Flask-SocketIO (`app/routes/websocket.py`), klient `io()` w `app.js` | dziś emity są broadcastem do wszystkich |
| i18n | `app/static/js/translations.js` (`en`, `pl`, `de`), `t(key, vars)`, liczba mnoga `_one/_few/_many/_other` | każdy nowy tekst w 3 językach |
| Testy | `tests/test_pdf_editor.py` (unittest), fixtury `tests/fixtures/build_fixtures.py` | e2e dotąd ad hoc w Playwright |

Konwencje repo (obowiązują wszystkich agentów): **bez komentarzy i docstringów w kodzie**, czysty kod, wszystkie
teksty UI w `en/pl/de`, bez nowych CDN-ów, selecty w edytorze przez `CustomSelect` (bez `data-native`),
mobile-first (zasady z sekcji 4.8).

## 3. Architektura docelowa

```
            ┌──────────── pdf-editor.js (rdzeń) ─────────────┐
            │  PdfEditor.bridge  (sekcja 4.6)                 │
            └──────┬───────────────┬─────────────────┬────────┘
                   │               │                 │
     pdf-editor-agent.js   pdf-editor-progress.js   (istniejące: drafts, sign)
     panel czatu, diffy    centrum aktywności,
     akceptacja propozycji overlay OCR, paski
                   │               │
        SSE /agent/…        socket.io "editor_task" + GET /tasks (fallback)
                   │               │
   app/routes/api_pdf_agent.py   app/routes/api_pdf_tasks.py
                   │               │
   services/pdf_agent.py ──► services/pdf_agent_tools.py ──► pdf_editor / pdf_ai / pdf_search
   services/agent_providers.py (LM Studio OpenAI-compat, Fake)
                                   │
                    services/editor_tasks.py  ◄── pdf_scan (OCR), tłumaczenie, wyszukiwanie, zapis
```

## 4. Kontrakty (zamrożone)

### 4.1 Zadania i postęp: `app/services/editor_tasks.py`

```python
class EditorTask:      # pola serializowane do JSON 1:1
    id: str            # "tsk_" + token_urlsafe(10)
    owner: str         # client_id() — nigdy nie wysyłany do innych klientów
    file_id: str | None
    kind: str          # "ocr" | "translate" | "search" | "save" | "sign" | "ai" | "agent" | "fonts"
    page: int | None   # id strony w edytorze (nie pozycja)
    status: str        # "queued" | "running" | "done" | "failed" | "cancelled"
    stage: str | None  # dla OCR: "render" | "orientation" | "detect" | "recognize" | "layout" | "fonts"
    progress: float | None   # 0..1, None = nieokreślony
    detail: dict       # {"done": int, "total": int, "boxes": [[x0,y0,x1,y1], ...], "lines": int, "eta_s": float}
    error: dict | None # {"code": "err_…", "message": str}
    created_at: float
    updated_at: float

class TaskRegistry:
    def create(owner, kind, file_id=None, page=None) -> EditorTask
    def update(task_id, **fields) -> None   # throttling: emit max 10/s per task, zawsze emit przy zmianie status/stage
    def finish(task_id, status="done", error=None) -> None
    def list(owner, file_id=None) -> list[EditorTask]   # zadania aktywne + zakończone < 60 s temu
    def cancel(owner, task_id) -> bool                  # ustawia flagę; worker sprawdza task.cancelled
TASKS = TaskRegistry()
```

Transport:

- Socket.IO, zdarzenie **`editor_task`**, payload = `EditorTask` bez `owner`, emit **tylko do pokoju**
  `client:<client_id>`. Klient dołącza do pokoju zdarzeniem `editor_join` (serwer bierze `client_id()` z cookie,
  nie z payloadu).
- Fallback HTTP: `GET /api/pdf/edit/tasks?file_id=…` → `{"tasks": [EditorTask…]}` (klient odpytuje co 1 s tylko
  wtedy, gdy socket nie jest połączony).
- `POST /api/pdf/edit/tasks/<id>/cancel` → `{"cancelled": bool}`.

Zmiana w podglądzie: odpowiedź `ocr_pending` dostaje pole `task_id`, czyli `{"ocr_pending": true, "task_id": "tsk_…"}`.

### 4.2 Sesje agenta: `app/routes/api_pdf_agent.py`

| Metoda i ścieżka | Wejście | Wyjście |
|---|---|---|
| `GET /api/pdf/edit/agent/status` | — | `{"status": "ok" \| "llm_offline" \| "llm_model_missing", "provider": "lmstudio", "model": str}` |
| `POST /api/pdf/edit/agent/sessions` | `{"file_id"}` | `{"session_id"}` |
| `POST /api/pdf/edit/agent/sessions/<sid>/messages` | `{"text", "ops", "scope", "selection"}` | **`text/event-stream`** (zdarzenia z 4.3) |
| `POST /api/pdf/edit/agent/sessions/<sid>/stop` | — | `{"stopped": bool}` |
| `POST /api/pdf/edit/agent/sessions/<sid>/feedback` | `{"proposal_id", "decision": "accepted" \| "rejected"}` | `{}` (trafia do historii rozmowy jako kontekst) |

- `scope`: `{"kind": "page" | "pages" | "document" | "selection", "pages": [int], "block_ids": [str]}`.
- `selection`: `{"page": int, "block_ids": [str], "text": str}` albo `null` (tekst zaznaczony w edytorze).
- `ops`: aktualne `s.ops` klienta. Serwer przepuszcza je przez `resolve_edit_ops` i nie ufa im bardziej niż innym opom.
- Sesje żyją w pamięci (`AgentSessionStore`, TTL 2 h, właściciel = `client_id()`, max 3 sesje na klienta).
- Każda wiadomość tworzy `EditorTask(kind="agent")`, żeby centrum aktywności pokazywało pracę agenta.

### 4.3 Zdarzenia SSE

Każda linia ma postać `event: <typ>\ndata: <json>\n\n`. Typy:

| `event` | `data` |
|---|---|
| `task` | `{"task_id"}` (pierwsze zdarzenie) |
| `delta` | `{"text"}` (fragment odpowiedzi agenta, streaming) |
| `tool` | `{"call_id", "name", "args", "status": "start" \| "done" \| "error", "summary"}` |
| `proposal` | **`Proposal`** (4.5) |
| `message` | `{"role": "assistant", "text"}` (finalna treść tury) |
| `done` | `{"usage": {"steps", "tool_calls"}, "stopped": bool}` |
| `error` | `{"code", "message"}`; kody: `err_ai_llm_offline`, `err_ai_llm_model_missing`, `err_agent_steps`, `err_agent_failed`, `err_agent_context` |

Heartbeat `: ping` co 15 s. Klient używa `fetch` + `ReadableStream`, bo `EventSource` nie obsługuje POST.

### 4.4 Narzędzia agenta: `app/services/pdf_agent_tools.py`

Każde narzędzie to `ToolSpec(name, description, parameters_json_schema, handler)`. Handler dostaje
`ToolContext(path, file_id, ops, working_ops, scope, emit)` i zwraca `ToolResult(content: dict, proposals: list[Proposal])`.
`working_ops` = opy klienta + opy z propozycji wygenerowanych wcześniej w tej turze, więc kolejne odczyty widzą efekt
wcześniejszych zmian agenta.

**Identyfikatory bloków** (stabilne w obrębie stanu `working_ops`):
`block_id = f"p{page}b{index}-{sha1(text + bbox)[:6]}"`, gdzie `page`, `index` i `bbox` pochodzą z
`render_preview(path, page, page_ops, 100)["blocks"]`. Nieznany albo nieaktualny id daje błąd narzędzia
`{"error": "stale_block"}`, a agent musi ponownie wywołać `read_page`.

| Narzędzie | Parametry | Zwraca / propozycje |
|---|---|---|
| `list_pages` | — | `[{page, position, width, height, blocks, scanned, edited}]` |
| `read_page` | `page`, `max_chars=6000` | `{blocks:[{id, text, bbox, size, bold, italic, color, align}], images, annots, truncated}` |
| `search` | `query?`, `patterns?: [pesel…]`, `pages?` | `[{page, text, kind, rects}]` (przez `search_document`) |
| `replace_text` | `block_id`, `text`, `reason` | propozycja `kind="text"` (op z `pdf_ai.block_op`, `fit: true`) |
| `proofread` | `pages`, `language?` | dla każdego bloku z błędami propozycja `kind="text"`; deterministyczna pętla po blokach z trybem `fix` z `pdf_ai.rewrite`; pomija bloki bez zmian |
| `set_style` | `block_id`, `size?`, `color?`, `bold?`, `italic?`, `align?` | propozycja `kind="style"`: ten sam tekst, zmienione runs |
| `insert_text` | `page`, `x`, `y`, `text`, `like_block_id?` | propozycja `kind="insert"`; styl skopiowany z `like_block_id` |
| `delete_text` | `block_id` | propozycja `kind="delete"` (op `text` z `runs: []`) |
| `highlight` | `page`, `query` \| `block_id`, `color?` | propozycja `kind="annot"` (op `annot` markup z prostokątami z `search`) |
| `add_note` | `page`, `x`, `y`, `text` | propozycja `kind="annot"` (op `annot` `note`) |
| `redact` | `query?`, `patterns?`, `pages?` | propozycja `kind="redact"` (op `redact` z `rects`, jedna na stronę) |
| `translate` | `pages`, `language` | propozycje `kind="text"` (przez `pdf_ai.translate_page`) |
| `page_action` | `action: rotate\|delete\|move\|insert_blank`, `page`, `to?`, `angle?` | propozycja `kind="page"` (op `page`) |
| `finish` | `summary` | kończy turę |

Ograniczenia (egzekwowane w `pdf_agent.py`): max **12 kroków** i **40 wywołań narzędzi** na turę; max
**60 propozycji** na turę; zakres (`scope`) filtruje dozwolone strony (wywołanie poza zakresem daje błąd narzędzia).
Narzędzia nigdy nie zapisują pliku i nie wykonują opów na serwerze, tylko je proponują.

### 4.5 Propozycja

```json
{
  "id": "prp_…",
  "kind": "text | style | insert | delete | annot | redact | page",
  "page": 2,
  "title": "Poprawiona literówka",
  "reason": "„wykladu” → „wykładu”",
  "before": "tekst przed (dla text/style/delete)",
  "after": "tekst po (dla text/insert)",
  "rects": [[x0, y0, x1, y1]],
  "ops": [ { …dokładnie format opów edytora… } ],
  "base": { "count": 3, "last_g": 17 },
  "depends_on": ["prp_…"]
}
```

`depends_on` to wcześniejsze propozycje z tej samej tury, na których stanie (`working_ops`) powstała ta propozycja,
czyli każda wcześniejsza propozycja dotykająca tej samej strony. Reguły klienta:

- Zastosowanie propozycji stosuje też w tej samej grupie cofania wszystkie jej jeszcze niezastosowane `depends_on`,
  w kolejności powstania.
- Odrzucenie propozycji odrzuca też propozycje od niej zależne (UI pokazuje, które).
- Sprawdzenie `base` dotyczy stanu przed zastosowaniem pierwszej propozycji z łańcucha. Kolejne ogniwa są aktualne,
  jeśli od tego momentu jedyne nowe opy strony pochodzą z propozycji tego samego łańcucha.

`base` to stan opów tej strony z żądania, na którym oparto propozycję: liczba opów strony (`opsFor(page)` po stronie
klienta, filtr `op.page == page` po stronie serwera) i pole `g` (grupa cofania) ostatniego z nich albo `null`. Klient
oznacza propozycję jako nieaktualną (status `stale` w UI), jeśli aktualne `opsForPage(page)` mają inną liczbę albo
inne `g` ostatniego opu. Bez haszowania JSON-a, bo Python i JS formatują liczby inaczej.

### 4.6 Most klienta: `PdfEditor.bridge` (dodaje WP0 w `pdf-editor.js`)

```js
PdfEditor.bridge = {
    session(),                          // null albo { fileId, digest, order, current, base }
    ops(),                              // kopia s.ops
    opsForPage(pageId),                 // kopia opów strony (jak opsFor)
    layout(pageId),                     // Promise<layout> z ostatniego podglądu, albo pobiera go
    apply(ops, { label }),              // pushOps jako jedna grupa cofania, zwraca groupId
    focus(pageId, rects, tone),         // przewija i podświetla (tone: "proposal" | "applied" | "error")
    clearFocus(),
    selection(),                        // { page, blockIds, text } albo null
    on(event, fn), off(event, fn),      // eventy: "open", "close", "ops", "page", "preview"
    sheetSlot(),                        // element kontenera paneli bocznych (#peSide)
    t, escapeHtml, icon                 // re-eksport helperów
};
```

Rdzeń emituje: `open` (po załadowaniu stron), `close`, `ops` (po każdej zmianie historii, payload `{ops}`),
`page` (zmiana bieżącej strony), `preview` (`{pageId, layout}` po wczytaniu podglądu).

### 4.7 Dostawcy modelu: `app/services/agent_providers.py`

```python
class AgentProvider:
    name: str
    def status(self) -> str                                       # "ok" | "llm_offline" | "llm_model_missing"
    def step(self, messages, tools, on_delta) -> AgentStep         # AgentStep(text, tool_calls=[ToolCall(id, name, args)])
```

- `LmStudioProvider`: endpoint zgodny z OpenAI `POST {base}/v1/chat/completions` z `tools`, `tool_choice: "auto"` i
  `stream: true` (składa delty `tool_calls`). Model z `LLM_AGENT_MODEL`, domyślnie `LLMService.text_model()`.
  Base URL z `LLMService().base_url`.
- `FakeProvider`: skrypt kroków z JSON-a (testy i e2e). `tests/fakes/fake_lm.py` to serwer HTTP udający LM Studio:
  `/api/v1/models`, `/api/v1/chat`, `/v1/chat/completions` z tool-callingiem sterowanym regułami z pliku.
- Jedynym prawdziwym dostawcą jest LM Studio, więc treść dokumentu nigdy nie opuszcza komputera. `AGENT_PROVIDER=fake`
  służy wyłącznie testom; każda inna wartość daje LM Studio. Dostawca Anthropic API został usunięty.

### 4.8 Zasady UI (wspólne)

- Desktop (≥ 761 px): agent jako prawy sidebar 360 px w kontenerze `#peSide`. Strony i dock przesuwają się tak jak
  przy panelu stron po lewej. Oba panele mogą być otwarte naraz.
- Telefon: przycisk agenta w menu „⋯” i jako zakładka w dolnym pasku. Panel otwiera się jako pełnoekranowy arkusz
  z grabberem, pole wpisywania przyklejone nad klawiaturą (`--kb`), cele dotyku ≥ 44 px, inputy 16 px.
- Kolory wyłącznie ze zmiennych motywu. Testy wizualne w ciemnym i jasnym motywie.
- Animacje respektują `prefers-reduced-motion`.

## 5. Pakiety pracy

Kolejność: **WP0 (sekwencyjnie, ~1 h)**, potem **WP1–WP6 równolegle**, na końcu **WP7** (QA, scalanie).

### WP0: Kontrakty i rusztowanie (jeden agent, przed resztą)

Pliki: nowe puste moduły z sygnaturami (`editor_tasks.py`, `pdf_agent.py`, `pdf_agent_tools.py`,
`agent_providers.py`, `api_pdf_agent.py`, `api_pdf_tasks.py`, `pdf-editor-agent.js`, `pdf-editor-progress.js`),
rejestracja blueprintów w `app/routes/api.py`, `<script>`-y w `pdf.html`, kontener `#peSide` i przycisk agenta w
`pdf_editor.html`, **`PdfEditor.bridge` w `pdf-editor.js`** (4.6) z emiterem zdarzeń, helper `I18n.extend(lang, dict)`
w `i18n.js` (moduły rejestrują własne tłumaczenia u siebie, więc nikt poza WP0 nie edytuje `translations.js`),
`tests/fakes/fake_lm.py`, `tests/e2e/` z helperem Playwright (start serwera na porcie z env, upload fixtury,
otwarcie edytora).

Kryteria: aplikacja startuje, stare testy zielone, `PdfEditor.bridge` ma test e2e (`apply` → zmienia licznik zmian,
`on("ops")` się wywołuje), stuby zwracają 501.

### WP1: Rejestr zadań i transport postępu

Pliki (wyłączność): `app/services/editor_tasks.py`, `app/routes/api_pdf_tasks.py`, część socketowa w
`app/routes/websocket.py` (`editor_join`, pokoje), `app/static/js/pdf-editor-progress.js`, CSS w nowym pliku
`app/static/css/pdf-editor-progress.css`.

Zakres:

- `TaskRegistry` zgodny z 4.1: throttling, sprzątanie po 60 s, anulowanie, emit do pokoju właściciela.
- Klient: **centrum aktywności** (ikona w nagłówku z licznikiem; lista zadań z paskiem, etapem, ETA i przyciskiem
  Anuluj), mini pasek pod nagłówkiem dla zadania pierwszoplanowego, pierścień postępu na miniaturze strony w panelu
  stron, toast „Gotowe” z akcją „Pokaż”.
- API JS: `PdfProgress.track(taskId)`, `PdfProgress.onTask(kind, fn)`, `PdfProgress.local(kind, {title, total})`,
  czyli zadania czysto klienckie (np. pętla tłumaczenia).

Testy: unit dla rejestru (throttling, owner isolation, cancel), e2e: zadanie z fake'owym postępem pojawia się w
centrum, anulowanie działa, dwa konteksty przeglądarki nie widzą swoich zadań.

### WP2: OCR z widocznym postępem i podglądem na żywo

Pliki (wyłączność): `app/services/pdf_scan.py`, sekcja OCR w `app/services/pdf_editor.py`
(`op_ocr`, `build_preview` tylko w miejscu `ocr_pending`), nowy `app/static/js/pdf-editor-ocr.js` (overlay).

Zakres:

- `OcrCache.lines` tworzy `EditorTask(kind="ocr", page)` i raportuje etapy: `render` (po każdej z 3 orientacji),
  `orientation`, `detect` (z `detail.boxes` w współrzędnych strony), `recognize` (`detail.lines`, `done/total`
  partii), `layout`, `fonts`.
- Rozdzielenie detekcji i rozpoznawania w RapidOCR: najpierw sama detekcja (wywołanie silnika z wyłączonym
  rozpoznawaniem; agent **sprawdza w zainstalowanej wersji `rapidocr==3.10.0`**, jakie parametry przyjmuje
  `__call__`). Potem rozpoznawanie paczkami po 8 linii, żeby `progress` rósł płynnie. Jeśli rozdzielenie jest
  niemożliwe, zostaje postęp etapowy bez pudełek.
- Overlay na stronie: linia skanowania (CSS), szkic wykrytych linii jako obrysy, które wypełniają się, gdy dana
  partia zostanie rozpoznana, licznik „Rozpoznano 34/120 linii”, przycisk Anuluj.
- **OCR wielu stron:** baner „Ten dokument ma 12 zeskanowanych stron. Rozpoznaj wszystkie” dodaje opy `ocr` dla
  wszystkich i pokazuje kolejkę w centrum aktywności (WP1).
- Estymacja czasu: średnia z ostatnich stron (zapamiętana w `localStorage`), pokazywana jako „ok. 40 s”.

Testy: unit z podmienionym silnikiem (fałszywe boxy i paczki) sprawdza kolejność etapów i `progress` rosnący
monotonicznie. E2e: overlay pokazuje pudełka przed tekstem, anulowanie zatrzymuje kolejne paczki.

### WP3: Postęp pozostałych funkcji

Pliki (wyłączność): nowy `app/static/js/pdf-editor-activity-hooks.js` (podpina się przez `bridge` i
`PdfProgress`), minimalne zmiany w `app/routes/api_pdf.py` **tylko** w trasach: `translate`, `search`, `ai`,
`certificate`; w `pdf_tools.tool_edit` raportowanie etapów zapisu (`apply_ops` per strona, subset, zapis, podpis).

Zakres: tłumaczenie dokumentu (strony i ETA, dziś są tylko w arkuszu), wyszukiwanie wielostronicowe
(`search_document` z callbackiem postępu per strona), zapis i podpis (etapy z joba, istniejący `emit_progress`
mapowany na `EditorTask`), AI rewrite (nieokreślony postęp + streaming tokenów do podglądu w arkuszu), indeks czcionek
przy starcie („Przygotowuję czcionki systemowe…”, `FontLibrary` raportuje liczbę plików), ładowanie podglądów (pasek,
gdy kolejka > 3 stron).

Testy: unit dla callbacków postępu, e2e dla tłumaczenia z fake LM (pasek dochodzi do 100%, Stop przerywa).

### WP4: Silnik agenta

Pliki (wyłączność): `app/services/pdf_agent.py`, `app/services/agent_providers.py`, `app/routes/api_pdf_agent.py`.

Zakres:

- Pętla tury: prompt systemowy (rola, zasady: najpierw `read_page`, tylko propozycje, krótkie odpowiedzi w języku
  użytkownika, `finish` na końcu), komunikat użytkownika z `scope` i `selection`, wywołania narzędzi, zdarzenia SSE
  z 4.3, limity z 4.4, obsługa `stop` (flaga sprawdzana między krokami i w trakcie streamingu).
- Zarządzanie kontekstem: wyniki narzędzi przycinane do 6000 znaków. Przy przekroczeniu budżetu (domyślnie 24 k
  tokenów, szacowane jako znaki / 3.5) starsze wyniki narzędzi są zastępowane podsumowaniem `{"omitted": true,
  "summary"}`.
- Dostawcy z 4.7, w tym parser strumienia `tool_calls` (składanie argumentów z delt) i fallback: gdy model nie
  obsługuje narzędzi, tryb „JSON w treści” (`{"tool": …, "args": …}`) z walidacją schematem.
- Sesje (`AgentSessionStore`), feedback akceptacji jako wiadomość systemowa w historii.

Testy: unit z `FakeProvider` (wielokrokowa tura, limit kroków, stop, błąd narzędzia wraca do modelu jako
`tool_result` z `error`, przycięcie kontekstu), test parsera delt `tool_calls`, test endpointu SSE (kolejność zdarzeń).

### WP5: Narzędzia agenta

Pliki (wyłączność): `app/services/pdf_agent_tools.py`, ewentualnie drobne publiczne helpery dopisane na końcu
`app/services/pdf_ai.py` (bez zmiany istniejących funkcji).

Zakres: wszystkie narzędzia z 4.4, `block_id`, `working_ops`, filtr zakresu, budowa `Proposal` z `before/after/rects/base/depends_on` (4.5),
`proofread` jako deterministyczne narzędzie (iteracja po blokach, tryb `fix`, diff po słowach, pomijanie bloków bez
zmian i bloków ze skanów z pewnością OCR poniżej progu).

Testy: unit dla każdego narzędzia na fixturze `pe_test.pdf` z mockiem `pdf_ai.ask`. Zastosowanie opów z propozycji
przez `render_preview` musi dać oczekiwany tekst, a `stale_block` musi działać po zmianie strony.

### WP6: Panel czatu (UI)

Pliki (wyłączność): `app/static/js/pdf-editor-agent.js`, `app/static/css/pdf-editor-agent.css`.

Zakres:

- Panel: nagłówek (model, status LM Studio, przełącznik zakresu: strona / zaznaczone strony / cały dokument /
  zaznaczenie), lista wiadomości (markdown-lite: akapity, listy, `code`, bez HTML z modelu), chipy wywołań narzędzi
  z animowanym stanem, karty propozycji (diff słów: usunięte przekreślone na czerwono, dodane na zielono; miniatura
  miejsca na stronie; przyciski Zastosuj / Odrzuć / Pokaż), pasek „Zastosuj wszystkie (N)”, Stop, pole wpisywania z
  Enter / Shift+Enter, podpowiedzi startowe („Popraw literówki na tej stronie”, „Przetłumacz dokument na…”,
  „Znajdź i zaczernij dane osobowe”).
- Integracja wyłącznie przez `PdfEditor.bridge`: `apply` z etykietą (cofanie grupy), `focus` przy najechaniu na
  kartę, propozycje `stale` po zdarzeniu `ops`, zaznaczenie bloków jako kontekst (`selection()`).
- Historia czatu w `sessionStorage` per `digest` (jak autozapis), przycisk „Nowa rozmowa”.
- Mobile wg 4.8, dostępność (role `log` dla listy, `aria-live="polite"`, fokus w polu po otwarciu, Escape zamyka).

Testy: e2e z fake LM (scenariusze: literówki → 3 propozycje → zastosuj 2, odrzuć 1 → licznik zmian i undo; Stop w
trakcie; zakres „cały dokument”; mobile: arkusz, klawiatura, przewijanie), zrzuty desktop/iPhone/iPad × ciemny/jasny.

### WP7: QA, wydajność, scalanie

Pliki: `tests/e2e/*`, ewentualne poprawki zgłaszane do właścicieli WP.

Zakres: pełny zestaw e2e (dotychczasowe scenariusze z sesji: tekst, obrazy, formularze, autozapis, multi-select,
panel stron, find & redact, podpisy, skany, tłumaczenie, PAdES + nowe), test regresji wizualnej (piksele ±2%),
pomiar: tura agenta z fake LM < 300 ms narzutu serwera, emit postępu nie częściej niż 10/s, brak wycieków (sesje,
zadania, wątki OCR) po 50 cyklach otwórz/zamknij. Scalanie w kolejności WP1 → WP2 → WP3 → WP5 → WP4 → WP6 i finalny
review.

## 6. Własność plików (żeby agenci się nie blokowali)

| Plik | Właściciel | Inni |
|---|---|---|
| `app/static/js/pdf-editor.js` | **WP0** (bridge) | po WP0 nikt; potrzebne haki zgłaszać do WP0 |
| `app/static/js/translations.js`, `i18n.js` | **WP0** | moduły używają `I18n.extend` we własnych plikach |
| `app/templates/pdf_editor.html`, `pdf.html` | **WP0** | — |
| `app/routes/api.py`, `websocket.py` | WP0 / WP1 | — |
| `app/services/pdf_scan.py` | WP2 | — |
| `app/services/pdf_editor.py` | WP2 (OCR), WP3 (callback w `search_document`) | zmiany w rozłącznych funkcjach |
| `app/routes/api_pdf.py` | WP3 | — |
| `app/services/pdf_tools.py` | WP3 | — |
| `app/services/pdf_ai.py` | WP5 (tylko dopisywanie) | — |
| nowe pliki z sekcji 5 | właściciel WP | — |
| `tests/test_pdf_editor.py` | nikt (zamrożony) | każdy WP: własny `tests/test_<wp>.py` |

## 7. Jak to uruchomić wieloma agentami Claude

1. **Agent prowadzący** (ta sama sesja): wykonuje WP0, commituje na `feat/editor-agent-base` i pushuje.
2. Startuje **6 subagentów równolegle** (`Agent` z `isolation: "worktree"`) albo 6 sesji Claude Code w chmurze.
   Każdy dostaje prompt z sekcji 8, pracuje na branchu `feat/editor-agent-wpN` od `feat/editor-agent-base`.
3. Każdy WP kończy się zielonymi testami własnymi + starymi (`python -m unittest discover tests`), pushuje branch
   i zgłasza listę zmienionych plików. Zmiana poza własnymi plikami = blokada i pytanie do prowadzącego.
4. Prowadzący (lub WP7) scala w kolejności z WP7, odpala pełne e2e i robi review.

Szacunek: WP0 ~1 h, równoległe WP1–WP6 ~2–3 h zegarowo, WP7 ~1 h, razem ~4–5 h zamiast ~2 dni sekwencyjnie.

## 8. Prompty dla agentów (do wklejenia)

Wspólny nagłówek każdego promptu:

> Pracujesz w repo OmniConv na branchu `feat/editor-agent-wpN` (od `feat/editor-agent-base`). Przeczytaj
> `docs/plans/ai-agent-and-progress.md` w całości. Realizujesz wyłącznie **WPN**, trzymasz się kontraktów z sekcji 4
> i własności plików z sekcji 6. Bez komentarzy i docstringów w kodzie. Każdy tekst UI w en/pl/de przez
> `I18n.extend`. Testy: własne w `tests/test_wpN.py` + e2e w `tests/e2e/`; uruchom też istniejące testy. Na końcu
> commit, push i raport: co zrobione, jakie pliki, jakie testy, co nie wyszło.

Dopiski per WP:

- **WP1:** „Zaimplementuj rejestr zadań, transport Socket.IO w pokojach klienta, fallback HTTP i centrum aktywności
  (`pdf-editor-progress.js`) z API `PdfProgress`.”
- **WP2:** „Zainstrumentuj OCR etapami i pudełkami detekcji; najpierw sprawdź API RapidOCR 3.10 w `.venv`. Zrób
  overlay i OCR wszystkich zeskanowanych stron.”
- **WP3:** „Dodaj postęp do tłumaczenia, wyszukiwania, zapisu, podpisu, AI rewrite i indeksu czcionek przez
  `EditorTask` i `PdfProgress`.”
- **WP4:** „Zbuduj pętlę agenta, dostawców (LM Studio tool-calling, Fake), endpoint SSE i
  sesje. Używaj tylko interfejsu narzędzi z 4.4 (WP5 dostarcza implementacje; do czasu scalenia użyj stubów z WP0).”
- **WP5:** „Zaimplementuj wszystkie narzędzia z 4.4, w tym `proofread`, `block_id`, `working_ops` i `Proposal`.”
- **WP6:** „Zbuduj panel czatu wyłącznie na `PdfEditor.bridge` i zdarzeniach SSE z 4.3, z kartami propozycji i
  diffem, desktop i mobile, oba motywy. Do e2e użyj `tests/fakes/fake_lm.py`.”
- **WP7:** „Zbierz e2e, regresję wizualną i pomiary z sekcji 5/WP7; scal branche w podanej kolejności.”

## 9. Ryzyka i decyzje

| Ryzyko | Decyzja |
|---|---|
| Lokalny model 8B słabo planuje wieloetapowo | narzędzia „makro” (`proofread`, `translate`, `redact`) robią ciężką pracę deterministycznie; agent tylko je wybiera i komentuje; prompt z przykładami wywołań |
| Model bez tool-callingu | fallback „JSON w treści” z walidacją; status w panelu |
| Duże dokumenty przekraczają kontekst | `read_page` per strona, przycinanie, podsumowania; `scope` domyślnie „ta strona” |
| Agent psuje dokument | tylko propozycje, ręczna akceptacja, grupa cofania, `base` wykrywa nieaktualne propozycje |
| Prywatność | tylko LM Studio lokalnie; brak dostawców zewnętrznych |
| Rozjazd stanu klient–serwer | serwer zawsze liczy na opach z żądania, nie trzyma stanu dokumentu |
| Konflikty przy równoległej pracy | tabela własności plików, `I18n.extend`, zamrożone kontrakty, WP0 przed resztą |

## 10. Definition of Done

- Polecenie „popraw literówki na tej stronie” na fixturze z celowymi błędami daje propozycje z poprawnym diffem.
  „Zastosuj wszystkie” daje jedną pozycję cofania, a zapisany PDF zawiera poprawiony tekst w oryginalnym kroju.
- „Przetłumacz strony 1–2 na angielski” i „zaczernij PESEL-e” działają przez agenta.
- OCR skanu pokazuje etapy, pudełka linii przed tekstem, licznik linii, ETA i działa Anuluj. Kolejka „rozpoznaj
  wszystkie” pokazuje postęp stron.
- Centrum aktywności pokazuje OCR, tłumaczenie, wyszukiwanie, zapis/podpis, AI i indeks czcionek.
- Wszystko działa w en/pl/de, w ciemnym i jasnym motywie, na desktopie, iPadzie, telefonie w pionie i w poziomie.
- Testy unit + e2e zielone; brak komentarzy w kodzie; bez nowych CDN-ów.

## 11. Stan po WP0 (obowiązuje zamiast wcześniejszych zapisów, jeśli się różnią)

WP0 jest zrobione i scalone na branchu bazowym. Ustalenia wiążące dla WP1–WP7:

- **Kolejność skryptów:** `pdf.html` ładuje moduły edytora **przed** `translations.js` / `i18n.js` z `base.html`.
  W czasie ładowania modułu nie istnieją `t`, `I18n`, `escapeHtml`, `i18n`. Tłumaczenia rejestruje się przez
  `PdfEditor.bridge.translations({ en: {…}, pl: {…}, de: {…} })` (odkłada do `DOMContentLoaded`), a helpery woła się
  dopiero w handlerach/funkcjach. `I18n.extend(lang, dict)` istnieje i wywołuje `i18n.apply()`.
- **Globalne obiekty modułów:** `const PdfProgress`, `const PdfOcrView`, `const PdfActivityHooks`, `const PdfAgent`
  (top-level `const`, nie właściwości `window`; w Playwright używaj `typeof X !== 'undefined'`).
- **`PdfEditor.bridge`** (zaimplementowany): `session()`, `ops()`, `opsForPage(id)` (ścisły filtr `op.page === id`),
  `layout(id)` (Promise; świeży podgląd albo `POST /api/pdf/edit/page` z `width: 200`), `apply(ops, {label})` (jedna
  grupa cofania, zwraca `g`; `label` trafia do opów), `focus(id, rects, tone)`, `clearFocus()`, `selection()`,
  `on/off(event, fn)`, `sheetSlot()`, `side(open?)`, `button('agent' | 'activity')`, `addMenuItem({id, icon, labelKey, run})`,
  `compact()`, `translations(dicts)`, `t`, `escapeHtml`, `icon(name)`, `postJson(url, body)`.
  Zdarzenia: `open`, `close`, `ops` (`{ops}`), `page` (`{pageId}`), `preview` (`{pageId, layout}`), `side` (`{open}`).
- **`selection()`** zwraca `{ page, block_indexes: [int], text }` albo `null` (indeksy w `layout.blocks`). Serwer
  zamienia je na `block_id` z 4.4, więc w żądaniu `messages` pole `selection` ma ten kształt.
- **Przyciski w nagłówku:** `#peAgentBtn` i `#peActivityBtn` (z `<span class="pe-badge">`) są w szablonie z atrybutem
  `hidden`. Moduł właściciela zdejmuje `hidden` i podpina obsługę przez `bridge.button(...)`. Na telefonie wejście do
  agenta i aktywności idzie przez `bridge.addMenuItem` (menu „⋯”).
- **Panel boczny:** `#peSide` (`bridge.sheetSlot()`), CSS układu (desktop 360 px po prawej, przesuwa strony i dock,
  telefon pełny ekran) jest w `pdf-editor.css`. Zawartość panelu i jej style należą do WP6
  (`pdf-editor-agent.css`).
- **Podświetlenia:** `.pe-focus` z tonami `proposal` / `applied` / `error` w `pdf-editor.css`, przetrwa odświeżenie
  warstwy strony.
- **`PdfProgress` (WP0: działa przez polling `GET /api/pdf/edit/tasks` co 1 s przy aktywnych zadaniach, 3 s bez;
  WP1 dokłada Socket.IO, UI centrum aktywności i anulowanie, bez zmiany API):** `onTask(kind | '*', fn)`, `track(taskId)`, `get(taskId)`,
  `local(kind, {titleKey, total, page, cancel})` zwraca `{ task, update(fields), done(), fail(code), cancelled() }`.
  WP2/WP3 kodują przeciw temu API już teraz.
- **Backend:** `editor_tasks.py` ma działający minimalny `TaskRegistry` z `subscribe(listener)` (WP1 dokłada throttling,
  emit do pokojów i UI, nie zmienia sygnatur). `agent_providers.py` ma `ToolCall`, `AgentStep`, `AgentProvider`,
  działający `FakeProvider` (`AGENT_PROVIDER=fake`, kroki w `AGENT_FAKE_STEPS`) i pustą klasę LM Studio
  (WP4). `pdf_agent_tools.py` ma `ToolContext`, `ToolResult`, `ToolSpec`, `block_id`, `page_base`, `make_proposal`,
  `register`, `tool_specs` (WP5 rejestruje narzędzia). `pdf_agent.py` ma `AgentSession`, `AgentSessionStore`,
  stałe limitów i stub `run_turn(session, text, ctx, provider, emit)` (WP4). Trasy agenta zwracają 501, trasy zadań
  działają (`GET /api/pdf/edit/tasks`, `POST …/cancel`).
- **Socket.IO:** pokoje (`editor_join`) i emit `editor_task` robi WP1 w `websocket.py`, podłączając się do
  `TASKS.subscribe`.
- **Testy e2e:** `tests/e2e/helpers.js` (`startApp`, `startFakeLm({rules})`, `openEditor`, `check`),
  `tests/e2e/run.sh [nazwa]`, pliki `tests/e2e/<nazwa>.e2e.js` (Node + globalny Playwright). Port aplikacji z
  `E2E_PORT` (domyślnie 5099; **każdy WP używa innego portu**: WP1 5101, WP2 5102, WP3 5103, WP4 5104, WP5 5105,
  WP6 5106). Fake LM: port z `FAKE_LM_PORT` (WP1 1301 … WP6 1306); `startFakeLm()` zwraca `env` z
  `LMSTUDIO_API_URL`, który trzeba przekazać do `startApp({ env })` (LLMService czyta adres z tej zmiennej).
  W worktree bez `.venv` ustaw `E2E_PYTHON=/home/user/OmniConv/.venv/bin/python`.
- **`tests/fakes/fake_lm.py`:** `/api/v1/models`, `/api/v1/chat` (tłumaczenie segmentów `<<n>>`, tryb `fix` poprawia
  „wykladu/Zazolc/teskt”), `/v1/chat/completions` z `tools` (stream i bez), sterowany regułami
  `[{match, steps:[{text, tool_calls:[{name, args}]}]}]` z pliku `FAKE_LM_RULES`; krok = liczba odpowiedzi asystenta od
  ostatniej wiadomości użytkownika.
- **Branche:** subagenci pracują w izolowanych worktree na lokalnych branchach i **nie pushują**. Scalanie robi
  prowadzący do `claude/exciting-sagan-psmedl`.
- **Zdarzenia zadań rdzenia:** `bridge.on('task', fn)` dostaje `{id, kind: 'translate' | 'search' | 'ai', status,
  done, total, cancellable}` z istniejących przepływów edytora (tłumaczenie dokumentu, wyszukiwanie, AI rewrite);
  `bridge.cancelTask(id)` zatrzymuje tłumaczenie. WP3 mapuje je na `PdfProgress.local`.
- **OCR i właściciel zadania:** trasa podglądu ustawia `flask.g.edit_file_id`; `pdf_scan` w kontekście żądania bierze
  właściciela z `client_id()` i plik z `g.edit_file_id` (poza żądaniem, np. w jobie zapisu, nie tworzy zadania).
