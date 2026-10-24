# Adding a New Retail Chain (Developer & Agent Guide)

This guide provides instructions and architectural specifications for AI agents and software engineers extending `retail-receipts-import` with support for a new retail grocery chain.

---

## 1. Architecture Overview

The receipt ingestion pipeline uses a **two-pass extraction architecture** powered by Google Gemini (`gemini-3.8-flash`):

```
Incoming Receipt (Image/PDF)
            │
            ▼
┌────────────────────────────────────────────────────────┐
│ Pass 1: Chain Classification & Header Detection        │
│ - Dynamically prompted with active chains from DB      │
│ - Uses chain plugin's pass1_time_hint                  │
│ - Extracts chain slug, purchase date and time          │
└───────────────────────────┬────────────────────────────┘
                            │
                            ▼
┌────────────────────────────────────────────────────────┐
│ Early Deduplication Check                              │
│ - Looks up (chain_id, purchased_at) in PostgreSQL      │
│ - Skips Pass 2 if already stored                       │
└───────────────────────────┬────────────────────────────┘
                            │ (If not duplicate)
                            ▼
┌────────────────────────────────────────────────────────┐
│ Pass 2: Structured Itemized Extraction                 │
│ - Uses chain-specific prompt and Pydantic JSON schema  │
│ - Extracts all lines, unit prices, discounts, tenders  │
└───────────────────────────┬────────────────────────────┘
                            │
                            ▼
┌────────────────────────────────────────────────────────┐
│ Plugin Normalization & Arithmetic Balance Verification │
│ - Verifies seller OIB against reference                │
│ - Nets stornos and maps deposit refunds                │
│ - Verifies: sum(effective_amount) == sum(settlements)  │
│ - Constructs canonical NormalizedReceipt               │
└───────────────────────────┬────────────────────────────┘
                            │
                            ▼
           Persist to PostgreSQL & Update Feed
```

Every supported retail chain is encapsulated as a standalone plug-in implementing the [`ChainPlugin`](file:///d:/MyGitProjects/grocery-tracker/retail-receipts-import/src/retail_receipts_import/domain/chains/registry.py#L19-L53) protocol.

---

## 2. Directory Structure of a Chain Plugin

Each chain plugin lives in its own package under [`src/retail_receipts_import/domain/chains/<chain_slug>/`](file:///d:/MyGitProjects/grocery-tracker/retail-receipts-import/src/retail_receipts_import/domain/chains/):

```
src/retail_receipts_import/domain/chains/<chain_slug>/
├── __init__.py      # Exports singleton instance implementing ChainPlugin
├── prompt.py        # Pass 2 Gemini prompt tailored to the chain's receipt layout
├── schema.py        # Pydantic models defining Pass 2 structured JSON schema
└── normalize.py     # Parses raw JSON into canonical NormalizedReceipt domain model
```

---

## 3. Step-by-Step Implementation Guide

### Step 1: Database Reference (`public.chains_v1`)

Before writing any Python code, determine the chain's metadata according to the [`chains_v1` contract](file:///d:/MyGitProjects/grocery-tracker/retail-receipts-import/docs/contracts/chains_v1.md):
- **`chain_id`**: Lowercase alphanumeric slug (e.g., `konzum`, `tommy`, `studenac`), matching regex `^[a-z][a-z0-9_]{0,31}$`.
- **`display_name`**: Human-readable name (e.g., `"Konzum"`).
- **`aliases`**: Common OCR printed variants (e.g., `["KONZUM PLUS d.o.o.", "KONZUM"]`).
- **`seller_oibs`**: Text array of 11-digit Croatian tax numbers (OIB) printed on receipts (e.g., `{"12345678901"}`).

> [!IMPORTANT]
> **Reference Parity Alert:** The service continuously checks registered plug-ins against `public.chains_v1`. If a chain exists in the Python registry but is absent or inactive in the database view, the service issues an operational alert (`chain_reference`). Ensure the admin seeds `public.chains_v1` in both dev and production.

---

### Step 2: Define Pass 2 Schema (`schema.py`)

Create `src/retail_receipts_import/domain/chains/<chain_slug>/schema.py`.

#### Critical Schema Rules:
1. **Never use floats:** All monetary amounts, quantities, and prices must be extracted as **printed strings** (`str`, e.g., `"1,99"`, `"0,500"`). Gemini outputs strings directly, preventing floating-point precision loss before parsing with `Decimal`.
2. **Never extract payment card slips:** Do not ask for card numbers, authorization codes, AID, or terminal IDs. Only extract the tender row label (e.g., `"Kartica"`) and paid amount.
3. **Use descriptive field docs:** Gemini uses Pydantic `Field(description=...)` to guide vision reasoning.

```python
"""What Gemini returns for a <Chain> receipt: printed values only, as printed strings."""

from pydantic import BaseModel, Field


class ExampleLine(BaseModel):
    """Raw printed line item extracted from a receipt."""

    text: str = Field(description="Item name as printed on the receipt.")
    quantity: str | None = Field(default=None, description="Printed quantity, e.g. '1', '2', '0,750'.")
    unit: str | None = Field(default=None, description="'kg' on weighed items, else null.")
    unit_price: str | None = Field(default=None, description="Printed price per unit, e.g. '1,99'.")
    amount: str = Field(description="Printed line amount, e.g. '3,98' or '-1,00'.")


class ExamplePayment(BaseModel):
    """Raw printed settlement or payment tender."""

    text: str = Field(description="Payment row label, e.g. 'Kartica', 'Gotovina'.")
    amount: str = Field(description="Printed payment amount, e.g. '15,20'.")


class ExamplePass2(BaseModel):
    """Structured pass-2 extraction schema."""

    seller_oib: str | None = Field(default=None, description="Company OIB from receipt header (11 digits).")
    store_name: str | None = Field(default=None, description="Store or branch name.")
    store_address: str | None = Field(default=None, description="Store street address.")
    receipt_number: str | None = Field(default=None, description="Invoice / receipt number as printed.")
    purchase_date: str = Field(description="Date of purchase as printed, DD.MM.YYYY.")
    purchase_time: str = Field(description="Time of purchase as printed, HH:MM.")
    total: str = Field(description="Total amount on the receipt ('Ukupno').")
    lines: list[ExampleLine]
    payments: list[ExamplePayment]
```

---

### Step 3: Define Pass 2 Prompt (`prompt.py`)

Create `src/retail_receipts_import/domain/chains/<chain_slug>/prompt.py`.

The prompt instructs Gemini on the layout specifics of this chain's receipts:
- Where the fiscal line / date / time is located.
- How to distinguish item sales from separate discounts (e.g., discount coupons printed under an item).
- How bottle returns (`Povratna naknada`) or storno cancellations are labeled.

```python
"""Pass 2 prompt for <Chain> receipts."""

PASS2_PROMPT = """Extract the line items, payment tenders, and receipt header from this <Chain> receipt.

Specific layout guidelines:
- seller_oib: 11-digit OIB printed near the top under the company title.
- date and time: use the fiscal line timestamp (do NOT use payment card slip timestamps).
- lines: extract each grocery item in print order.
- payments: extract each tender method (cash, card, etc.) and amount.
"""
```

---

### Step 4: Implement Normalizer (`normalize.py`)

Create `src/retail_receipts_import/domain/chains/<chain_slug>/normalize.py`.

This module transforms the raw Pydantic response into the canonical [`NormalizedReceipt`](file:///d:/MyGitProjects/grocery-tracker/retail-receipts-import/src/retail_receipts_import/domain/receipt.py#L153-L178) model.

#### Responsibilities:
1. **Timestamp Conversion**:
   - Parse date and time into local wall-clock time (`purchase_time(...)`).
   - Convert Zagreb local time to UTC with zero seconds/microseconds using [`zagreb_to_utc(...)`](file:///d:/MyGitProjects/grocery-tracker/retail-receipts-import/src/retail_receipts_import/domain/receipt.py#L257-L270).
2. **Numeric Conversions**:
   - Convert comma-separated currency strings into `Decimal` using [`money(...)`](file:///d:/MyGitProjects/grocery-tracker/retail-receipts-import/src/retail_receipts_import/domain/chains/printed.py#L32-L37).
   - Convert quantity strings into `Decimal` using [`quantity(...)`](file:///d:/MyGitProjects/grocery-tracker/retail-receipts-import/src/retail_receipts_import/domain/chains/printed.py#L39-L44).
3. **Discount Categorization**:
   - `included_discount`: shelf discounts already deducted in `printed_amount` (`regular_amount = printed_amount + included_discount`).
   - `separate_discount`: line discounts subtracted from `printed_amount` (`effective_amount = printed_amount - separate_discount`).
4. **Storno & Return Lines**:
   - For regular purchases: `kind = LineKind.SALE` (quantity > 0, amount > 0).
   - For cancellations: `kind = LineKind.STORNO` (quantity < 0, amount < 0, `cancels_line` = 1-based index of cancelled sale).
   - For bottle deposit refunds: map to [`SettlementKind.DEPOSIT_REFUND`](file:///d:/MyGitProjects/grocery-tracker/retail-receipts-import/src/retail_receipts_import/domain/receipt.py#L34-L40).
5. **Reconciliation & Balance Checking**:
   - Verify that all line effective amounts and deposit refunds match payments:
     `sum(lines.effective_amount) + refunds == sum(settlements.amount)`
   - Verify that `total == sum(settlements.amount)`.
   - On mismatch, raise [`UnreadableReceipt`](file:///d:/MyGitProjects/grocery-tracker/retail-receipts-import/src/retail_receipts_import/domain/chains/errors.py#L1-L4).

---

### Step 5: Implement the Plug-in (`__init__.py`)

Create `src/retail_receipts_import/domain/chains/<chain_slug>/__init__.py`.

Implement the [`ChainPlugin`](file:///d:/MyGitProjects/grocery-tracker/retail-receipts-import/src/retail_receipts_import/domain/chains/registry.py#L19-L53) protocol:

```python
"""The <Chain> chain plug-in."""

from dataclasses import dataclass
from datetime import datetime

from pydantic import BaseModel, ValidationError

from retail_receipts_import.domain.chains.<chain_slug>.normalize import normalize, normalize_pass1_time
from retail_receipts_import.domain.chains.<chain_slug>.prompt import PASS2_PROMPT
from retail_receipts_import.domain.chains.<chain_slug>.schema import ExamplePass2
from retail_receipts_import.domain.receipt import NormalizedReceipt


@dataclass(frozen=True)
class ExamplePlugin:
    """Chain extraction plugin for <Chain> receipts."""

    chain_id: str = "<chain_slug>"
    pass1_time_hint: str = 'Line "Datum: DD.MM.YYYY. HH:MM" (never the card slip).'
    pass2_prompt: str = PASS2_PROMPT
    pass2_schema: type[BaseModel] = ExamplePass2

    def normalize_pass1_time(self, purchase_date: str, purchase_time: str) -> datetime | None:
        """Converts <Chain> pass-1 printed date and time strings to UTC."""
        return normalize_pass1_time(purchase_date, purchase_time)

    def seller_oib(self, response: str) -> str | None:
        """Extracts the seller OIB tax identification number from pass-2 response JSON."""
        try:
            oib = ExamplePass2.model_validate_json(response).seller_oib
        except ValidationError:
            return None
        return (oib or "").strip() or None

    def normalize(self, response: str) -> NormalizedReceipt:
        """Parses and normalizes pass-2 JSON into canonical NormalizedReceipt."""
        return normalize(response, self.chain_id)


EXAMPLE = ExamplePlugin()
```

---

### Step 6: Register the Plug-in in Registry

Open [`src/retail_receipts_import/domain/chains/registry.py`](file:///d:/MyGitProjects/grocery-tracker/retail-receipts-import/src/retail_receipts_import/domain/chains/registry.py):

1. Import your plugin instance:
   ```python
   from retail_receipts_import.domain.chains.<chain_slug> import EXAMPLE
   ```
2. Add it to `PLUGINS`:
   ```python
   PLUGINS: dict[str, ChainPlugin] = {
       plugin.chain_id: plugin for plugin in (SPAR, LIDL, KAUFLAND, DM, MUELLER, EXAMPLE)
   }
   ```

---

## 4. Testing & Verification Standards

### Test Fixtures

1. Do **not** commit unredacted personal receipt photos or PDFs to git.
2. Create test cases in `tests/fixtures/<chain_slug>/<case_id>/`:
   - `pass2.json`: recorded or synthetic Pass 2 JSON response.
   - `expected.json`: hand-verified `NormalizedReceipt` JSON representation.
3. Create test file `tests/test_<chain_slug>_fixtures.py` (copying the pattern from [`tests/test_dm_fixtures.py`](file:///d:/MyGitProjects/grocery-tracker/retail-receipts-import/tests/test_dm_fixtures.py)):
   - Test 1: all fixture cases are present and loaded.
   - Test 2: `normalize(pass2.json)` produces exact match with `expected.json`.
   - Test 3: arithmetic mismatches (off by 0.01 EUR) raise `UnreadableReceipt`.
   - Test 4: seller OIB guard rejects responses with missing or invalid OIB.

### Running Verification Checks (in WSL)

Follow the repository verification commands:

```bash
# 1. Code style & formatting
wsl -- bash -l scratch/wsl-run.sh run ruff check
wsl -- bash -l scratch/wsl-run.sh run ruff format --check

# 2. Strict static typing
wsl -- bash -l scratch/wsl-run.sh run mypy

# 3. Unit & fixture tests
wsl -- bash -l scratch/wsl-run.sh run pytest tests/test_<chain_slug>_fixtures.py
wsl -- bash -l scratch/wsl-run.sh run pytest
```

---

## 5. Agent Pre-Submission Checklist

Before finalizing changes:
- [ ] `chain_id` matches regex `^[a-z][a-z0-9_]{0,31}$`.
- [ ] `public.chains_v1` includes the chain slug, aliases, and valid 11-digit OIBs.
- [ ] Schema fields extract numbers as `str`, never `float`.
- [ ] Payment card slip data (PAN, terminal ID) is never requested.
- [ ] `seller_oib(...)` returns OIB extracted through the model schema.
- [ ] `normalize(...)` validates line-to-settlement balance to the cent.
- [ ] `purchased_at` has zero seconds and microseconds and is aware UTC.
- [ ] No unredacted personal data or live API calls in default tests.
- [ ] All public modules, classes, and methods have English docstrings explaining "why".
- [ ] Standard check suite (`ruff`, `mypy`, `pytest`) passes completely.
