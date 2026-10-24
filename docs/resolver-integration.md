# Руководство по интеграции для агентов-потребителей (Resolver Integration Guide)

Данный документ описывает правила и механизмы интеграции внешних сервисов и AI-агентов (в первую очередь сервиса **Resolver**) с сервисом импорта чеков `retail-receipts-import`.

---

## 1. Назначение сервиса и разделение ответственности

### Что делает `retail-receipts-import`:
1. Принимает фотографии и PDF-документы кассовых чеков через Telegram-бота от покупателей.
2. Распознает текст и структуру чеков с помощью мультимодальной модели Google Gemini.
3. Нормализует данные по правилам конкретных торговых сетей Хорватии (Spar, Lidl, Kaufland, dm, Müller).
4. Проверяет арифметический баланс строк, скидок и оплат.
5. Записывает валидные чеки в базу данных PostgreSQL и публикует неизменяемые события в ленту изменений (`resolver_v1.feed`).

### Что делает агент `Resolver`:
1. Инкрементально вычитывает новые чеки из ленты изменений.
2. Сопоставляет неструктурированные текстовые названия позиций (`printed_text`) с каноническим каталогом товаров (продукты, бренды, категории, штрихкоды).
3. Ведет аналитику расходов семьи, отслеживает динамику цен и формирует продуктовый трекер.

### Принцип архитектурной изоляции:
- Проекты **полностью изолированы**: агент Resolver **не должен** импортировать Python-код, внутренние модели или миграции сервиса `retail-receipts-import`.
- Единственная точка соприкосновения — официальный контракт витрин **`resolver_v1`** в PostgreSQL.
- Потребитель вендорит себе контракт [`docs/contracts/resolver_v1.md`](contracts/resolver_v1.md) в режиме только для чтения.

---

## 2. Модель безопасности и подключение к PostgreSQL

Подключение к базе данных осуществляется по локальной сети (LAN).

### Роли и доступы:
- Агент подключается под выделенной учетной записью читателя:
  - **Dev**: `resolver_dev_reader` (база данных `grocery-tracker-dev`)
  - **Prod**: `resolver_prod_reader` (база данных `grocery-tracker`)
- **Разрешенные права**:
  - `USAGE` на схему `resolver_v1`
  - `SELECT` на 4 витрины схемы `resolver_v1`
- **Запрещенные операции**:
  - Запрещены любые изменения данных (`INSERT`, `UPDATE`, `DELETE`, `TRUNCATE`).
  - Запрещен доступ к внутренним таблицам сервиса в схеме `retail_receipts_import`.
  - Запрещен доступ к журналу миграций `schema_migrations`.
  - Запрещен доступ к системным базам данных (`postgres`, `template1`, `data`).

### Параметры подключения:
```env
# Пример конфигурации потребителя (Resolver)
RESOLVER_DB_HOST=192.168.100.218
RESOLVER_DB_PORT=5432
RESOLVER_DB_NAME=grocery-tracker-dev   # или grocery-tracker для прода
RESOLVER_DB_USER=resolver_dev_reader
RESOLVER_DB_PASSWORD=<пароль_читателя>
```

---

## 3. Объекты схемы `resolver_v1`

Все структуры данных в `resolver_v1` представлены в виде предсказуемых, безопасных витрин (`VIEW`).

### 3.1. Лента событий: `resolver_v1.feed`
Позволяет инкрементально отслеживать появление и удаление чеков.

| Колонка | Тип PostgreSQL | Описание и семантика |
| --- | --- | --- |
| `seq` | `bigint` | Монотонно возрастающий номер события. **Может содержать пропуски** (из-за отката транзакций). |
| `receipt_id` | `uuid` | Глобальный уникальный идентификатор чека (UUIDv7). |
| `event` | `text` | Тип события: `'stored'` (чек сохранен) или `'deleted'` (чек удален). |

### 3.2. Заголовки чеков: `resolver_v1.receipts`
Метаданные чека и общая сумма.

| Колонка | Тип | Формат / Значения | Описание |
| --- | --- | --- | --- |
| `receipt_id` | `uuid` | UUIDv7 | Уникальный ID чека. |
| `chain_id` | `text` | `^[a-z][a-z0-9_]{0,31}$` | Идентификатор торговой сети: `spar`, `lidl`, `kaufland`, `dm`, `mueller`. |
| `store_name` | `text` \| `null` | Строка | Название магазина/филиала, если напечатано на чеке. |
| `branch_number` | `text` \| `null` | Строка | Номер филиала/магазина (например, `"0269"`). |
| `receipt_number` | `text` \| `null` | Строка | Номер чека как напечатан (формат не гарантируется). |
| `store_address` | `text` \| `null` | Строка | Адрес магазина. |
| `currency` | `text` | `"EUR"` | Фиксированная валюта чека (всегда Евро). |
| `purchased_at` | `text` | ISO-8601 UTC (`...Z`) | Время покупки в UTC с точностью до минуты, e.g. `"2026-07-15T12:05:00Z"`. |
| `purchased_at_local` | `text` | ISO-8601 (`...±HH:MM`) | Местное время покупки (`Europe/Zagreb`), e.g. `"2026-07-15T14:05:00+02:00"`. |
| `buyer_name` | `text` | Строка | Имя покупателя (члена семьи), приславшего чек в Telegram. |
| `total` | `text` | Десятичная строка (`"0.00"`) | **Полная стоимость товаров** (сумма всех оплат, включая купоны и скидки). |

### 3.3. Строки покупок: `resolver_v1.receipt_lines`
Детализированные товарные позиции чека.

| Колонка | Тип | Формат | Описание |
| --- | --- | --- | --- |
| `line_id` | `uuid` | UUIDv7 | Уникальный ID строки. |
| `receipt_id` | `uuid` | UUIDv7 | Ссылка на чек. |
| `line_no` | `integer` | `1, 2, ...` | Порядковый номер строки в чеке (1-based). |
| `printed_text` | `text` | Строка | Название товара, как напечатано на чеке (основной вход для резолвера). |
| `quantity` | `text` | 3 знака (`"1.000"`) | Количество товара (штуки или килограммы). |
| `unit` | `text` \| `null` | `"kg"`, `"kom"`, null | Единица измерения, если напечатана. |
| `unit_price` | `text` \| `null` | 2 знака (`"2.50"`) | Цена за единицу товара, если напечатана. |
| `printed_amount` | `text` | 2 знака (`"5.00"`) | Напечатанная стоимость строки. |
| `included_discount` | `text` | 2 знака (`>= 0.00`) | Скидка, включенная в цену полки. |
| `separate_discount` | `text` | 2 знака (`>= 0.00`) | Отдельная строчная скидка (акция, купон). |
| `discount_text` | `text` \| `null` | Строка | Текст акции/скидки, если напечатан. |
| `regular_amount` | `text` | 2 знака (`"0.00"`) | Базовая цена без скидок: `printed_amount + included_discount`. |
| `effective_amount` | `text` | 2 знака (`"0.00"`) | Фактически уплаченная стоимость позиции: `printed_amount - separate_discount`. |

### 3.4. Оплаты и взаимозачеты: `resolver_v1.receipt_settlements`
Способы оплаты и закрытия чека.

| Колонка | Тип | Значения | Описание |
| --- | --- | --- | --- |
| `receipt_id` | `uuid` | UUIDv7 | Ссылка на чек. |
| `settlement_no` | `integer` | `1, 2, ...` | Порядковый номер оплаты (1-based). |
| `kind` | `text` | `card`, `cash`, `bonus_points`, `coupon`, `deposit_refund` | Категория оплаты. |
| `printed_text` | `text` | Строка | Текст платежной строки (например, `"MASTERCARD EUR"`). |
| `amount` | `text` | 2 знака (`"0.00"`) | Сумма. Отрицательная только при выдаче сдачи/возврате на карту. |

---

## 4. Паттерн работы агента (Алгоритм потребления)

Агент-потребитель реализует паттерн **Transactional Outbox / Log-centric Polling** с сохранением локального смещения (курсора `last_seq`).

### Пошаговый алгоритм:

```
[Старт / Пробуждение агента]
        │
        ▼
Загрузить `last_seq` из локального состояния Resolver'а (на старте 0)
        │
        ▼
Опросить `resolver_v1.feed`:
WHERE seq > :last_seq ORDER BY seq LIMIT :batch_size
        │
   ┌────┴──────────────────────────┐
   ▼ Есть события?                ▼ Нет событий
   │                              │
   │                              ▼
   │                      Уснуть на N секунд
   ▼
Для каждого события (seq, receipt_id, event):
   ├─ event == 'stored':
   │    1. Прочитать заголовок из `resolver_v1.receipts`
   │    2. Прочитать строки из `resolver_v1.receipt_lines`
   │    3. Выполнить сопоставление товаров (LLM / Embeddings)
   │    4. Записать результаты сопоставления в БД Resolver'а
   │
   ├─ event == 'deleted':
   │    1. Отозвать / пометить удаленным чек `receipt_id` в Resolver'е
   │
   └─ Обновить `last_seq = seq`
        │
        ▼
Атомарно зафиксировать транзакцию в БД Resolver'а
```

---

## 5. Практические SQL-запросы для агента

### 1. Получение пачки новых событий:
```sql
SELECT seq, receipt_id, event
FROM resolver_v1.feed
WHERE seq > :last_seq
ORDER BY seq ASC
LIMIT 50;
```

### 2. Получение данных чека по `receipt_id`:
> **ВАЖНО**: Всегда явно перечисляйте имена колонок! Никогда не делайте `SELECT *`. В минорных версиях контракта в витрины могут добавляться новые колонки — явный список защищает ваш код от поломок.

```sql
SELECT
    receipt_id,
    chain_id,
    store_name,
    branch_number,
    receipt_number,
    store_address,
    currency,
    purchased_at,
    purchased_at_local,
    buyer_name,
    total
FROM resolver_v1.receipts
WHERE receipt_id = :receipt_id;
```

### 3. Получение товарных позиций чека:
```sql
SELECT
    line_id,
    receipt_id,
    line_no,
    printed_text,
    quantity,
    unit,
    unit_price,
    printed_amount,
    included_discount,
    separate_discount,
    discount_text,
    regular_amount,
    effective_amount
FROM resolver_v1.receipt_lines
WHERE receipt_id = :receipt_id
ORDER BY line_no ASC;
```

### 4. Получение полного чека в виде единого вложенного JSON (удобно для LLM-промпта):
```sql
SELECT json_build_object(
    'receipt_id', r.receipt_id,
    'chain_id', r.chain_id,
    'store_name', r.store_name,
    'purchased_at', r.purchased_at,
    'buyer_name', r.buyer_name,
    'total', r.total,
    'lines', COALESCE((
        SELECT json_agg(json_build_object(
            'line_no', l.line_no,
            'printed_text', l.printed_text,
            'quantity', l.quantity,
            'unit', l.unit,
            'unit_price', l.unit_price,
            'effective_amount', l.effective_amount
        ) ORDER BY l.line_no)
        FROM resolver_v1.receipt_lines l
        WHERE l.receipt_id = r.receipt_id
    ), '[]'::json),
    'settlements', COALESCE((
        SELECT json_agg(json_build_object(
            'kind', s.kind,
            'amount', s.amount,
            'printed_text', s.printed_text
        ) ORDER BY s.settlement_no)
        FROM resolver_v1.receipt_settlements s
        WHERE s.receipt_id = r.receipt_id
    ), '[]'::json)
) AS receipt_json
FROM resolver_v1.receipts r
WHERE r.receipt_id = :receipt_id;
```

---

## 6. Важные тонкости предметной области (Gotchas & Best Practices)

1. **Типы данных и округления**:
   - Денежные суммы и количества передаются из витрин как **строки (`text`)**, а не как `float`/`double precision`.
   - В Python используйте строго `decimal.Decimal` (например, `Decimal(row["total"])`). Никогда не приводите суммы через `float`, чтобы избежать ошибок округления с плавающей запятой.

2. **Очищенные строки покупок (Net Purchases)**:
   - В витрине `receipt_lines` присутствуют **только чистые покупки**.
   - Если кассир нажал сторно («отмена строки»), сервис автоматически аннулирует соответствующую строку до сохранения.
   - Строки возврата пустых бутылок вынесены в `receipt_settlements` с типом `deposit_refund` (или учтены в сторно), поэтому строки в `receipt_lines` представляют реальные приобретенные товары.

3. **Смысл поля `total`**:
   - `total` в `receipts` отражает **полную стоимость товаров (value of goods)**.
   - Если покупатель оплатил часть чека купоном на 5€, списал 2€ бонусов и сдал бутылок на 1€, а картой доплатил 10€, то:
     $$\text{total} = 10 + 5 + 2 + 1 = 18.00\text{ EUR}$$
   - Сумма `effective_amount` по всем строкам `receipt_lines` плюс возвраты строго совпадает с суммой оплат `receipt_settlements`.

4. **Идемпотентность и пропуски в `seq`**:
   - В последовательности `seq` могут быть пропуски (например, `1, 2, 5, 6...`). Это нормальное поведение PostgreSQL при откатах транзакций. **Никогда не инкрементируйте курсор вручную на +1**, всегда используйте условие `seq > :last_seq`.
   - При сбое сети или перезапуске агент может перечитать уже обработанные события. Обработка должна быть идемпотентной (проверяйте, сохранен ли уже результат для данного `receipt_id`).

5. **Независимость от таймзон**:
   - `purchased_at` отформатирован в UTC с маркером `Z`.
   - `purchased_at_local` отформатирован с локальным смещением времени Хорватии.
   - Витрины генерируют эти поля как готовый текст, поэтому вывод не зависит от настройки `SET TimeZone` сессии подключения к БД.

---

## 7. Пример реализации потребителя на Python (агент-воркер)

```python
"""Пример фонового агента для вычитки чеков через resolver_v1."""

import asyncio
from decimal import Decimal
import psycopg
from psycopg.rows import dict_row

DB_URI = "postgresql://resolver_dev_reader:password@192.168.100.218:5432/grocery-tracker-dev"


async def run_consumer():
    cursor_seq = 0  # В реальном сервисе читается из локальной БД Resolver'а

    while True:
        async with await psycopg.AsyncConnection.connect(DB_URI, row_factory=dict_row) as conn:
            # 1. Запрашиваем новые события из ленты
            async with conn.cursor() as cur:
                await cur.execute(
                    """
                    SELECT seq, receipt_id, event
                    FROM resolver_v1.feed
                    WHERE seq > %s
                    ORDER BY seq ASC
                    LIMIT 20
                    """,
                    (cursor_seq,),
                )
                events = await cur.fetchall()

            if not events:
                await asyncio.sleep(10)
                continue

            for ev in events:
                seq = ev["seq"]
                receipt_id = ev["receipt_id"]
                event_type = ev["event"]

                if event_type == "stored":
                    # 2. Получаем заголовок чека
                    async with conn.cursor() as cur:
                        await cur.execute(
                            """
                            SELECT receipt_id, chain_id, store_name, purchased_at, total, buyer_name
                            FROM resolver_v1.receipts
                            WHERE receipt_id = %s
                            """,
                            (receipt_id,),
                        )
                        receipt = await cur.fetchone()

                        # 3. Получаем товарные позиции для резолвинга
                        await cur.execute(
                            """
                            SELECT line_no, printed_text, quantity, effective_amount
                            FROM resolver_v1.receipt_lines
                            WHERE receipt_id = %s
                            ORDER BY line_no ASC
                            """,
                            (receipt_id,),
                        )
                        lines = await cur.fetchall()

                    # 4. Бизнес-логика агента Resolver (сопоставление товаров)
                    print(
                        f"Обработка чека {receipt_id} ({receipt['chain_id']}), "
                        f"сумма: {Decimal(receipt['total'])} EUR, позиций: {len(lines)}"
                    )
                    for line in lines:
                        # Агент отправляет printed_text в классификатор / каталог товаров
                        print(f"  [{line['line_no']}] {line['printed_text']} -> {line['effective_amount']} EUR")

                elif event_type == "deleted":
                    print(f"Чек {receipt_id} удален в источнике. Очистка связанных данных.")

                # 5. Сохраняем обновленный курсор
                cursor_seq = seq
                # save_cursor_to_resolver_db(cursor_seq)


if __name__ == "__main__":
    asyncio.run(run_consumer())
```
