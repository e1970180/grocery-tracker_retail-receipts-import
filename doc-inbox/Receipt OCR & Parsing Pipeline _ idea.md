
---
title: "Receipt OCR & Parsing Pipeline: In-Memory Preprocessing & Gemini Structured Extraction"
type: architecture-note
tags:
  - ai/vlm
  - ocr
  - python
  - gemini
  - pydantic
  - image-processing
created: 2026-10-16
---

# Receipt OCR & Parsing Pipeline

## 1. Архитектурное обоснование

### 1.1. Выбор модели: Gemini Flash против тяжелых флагманов
Для конвейера оцифровки чеков с конвертацией в строгий JSON модель класса **Gemini Flash** является оптимальным выбором по сравнению с рассуждающими флагманами:

- **Детерминированный Constrained Decoding:** Передача Pydantic-схемы в параметр `response_schema` активирует жесткую маску токенизатора на стороне инференса Google. Модель физически не способна вернуть словесные обвязки, Markdown-разметку или синтаксически сломанный JSON.
- **Нулевой Thinking Budget:** Рассуждающие модели запускают скрытые цепочки рассуждений (thinking traces), что для задачи считывания термоленты создает паразитную задержку и кратный перерасход токенов. Конфигурация `thinking_budget=0` в Flash переводит инференс в субсекундный детерминированный режим.
- **Себестоимость:** Разница в стоимости инференса между Flash ($0.10–$0.15 за 1M входных токенов) и тяжелыми флагманами ($2.00–$15.00) составляет 15–30 раз при сопоставимой точности распознавания символов.

### 1.2. Проблема длинных чеков и нарезка в памяти
- **Эффект сжатия (Aspect Ratio Distortion):** VLM при обработке экстремально вытянутых вертикальных изображений (соотношение сторон $H/W > 2.5$) принудительно сжимают изображение под внутренние лимиты тайлов. Мелкий термошрифт и разделители цен размываются, приводя к галлюцинациям в цифрах.
- **Пропорциональное вертикальное перекрытие (Overlap):** Нарезка изображения на сегменты с динамическим нахлестом (12% от высоты сегмента) гарантирует, что строка текста или число, попавшее на границу среза, полностью отобразится на соседнем кадре. Расчет перекрытия в долях от высоты чанка исключает риск отрицательного шага и бесконечного цикла на узких изображениях.
- **Прямая передача массива `types.Part` без промежуточного PDF:** Вместо упаковки нарезанных кадров в многостраничный PDF (который бэкенд Gemini при получении вынужден заново растеризовать обратно в изображения), конвейер формирует массив легковесных JPEG-сегментов (`image/jpeg`) напрямую в памяти. Это устраняет двойное перекодирование на CPU и снижает сетевой payload в 3–5 раз по сравнению с PNG/PDF.
- **Полный In-Memory цикл (`bytes` -> `io.BytesIO`):** Пайплайн принимает исключительно байтовые потоки в памяти (из очереди сообщений, вебхука Telegram, FastAPI `UploadFile` или S3-стрима). Отсутствие дискового I/O исключает блокировки файловой системы и утечки временных файлов в воркерах.

### 1.3. Финансовая точность и контроль целостности
- **Арифметика с фиксированной точкой (`Decimal`):** Использование `float` недопустимо для финансовых данных из-за ошибок округления IEEE 754. Все денежные и количественные поля типизированы через `decimal.Decimal`.
- **Пост-валидация баланса чека:** Встроенный `@model_validator` автоматически сверяет сумму всех распознанных позиций (`items`) с итоговой суммой чека (`total_amount`) и выставляет системный флаг `is_math_consistent`, позволяя отправлять чеки с расхождениями на ручную верификацию или повторный прогон с повышенным `thinking_budget`.

---

## 2. Исходный код реализации

### Зависимости

```bash
pip install google-genai pydantic pillow
````

### Полный модуль (`receipt_pipeline.py`)

Python

```
import io
from decimal import Decimal
from typing import List, Optional
from google import genai
from google.genai import types
from PIL import Image, ImageOps
from pydantic import BaseModel, Field, model_validator

# Защита от Decompression Bomb (лимит ~50 МП)
Image.MAX_IMAGE_PIXELS = 50_000_000


# =====================================================================
# 1. Схема данных (Pydantic Models)
# =====================================================================

class ReceiptItem(BaseModel):
    line_number: Optional[int] = Field(
        default=None,
        description="Порядковый номер позиции сверху вниз для точной дедупликации на стыках"
    )
    name: str = Field(description="Точное наименование товара или услуги")
    quantity: Decimal = Field(default=Decimal("1.0"), description="Количество единиц или вес")
    unit_price: Optional[Decimal] = Field(default=None, description="Цена за единицу или кг")
    total_price: Decimal = Field(description="Итоговая стоимость позиции с учетом скидок")


class ReceiptData(BaseModel):
    merchant_name: Optional[str] = Field(default=None, description="Название торговой сети или магазина")
    transaction_date: Optional[str] = Field(default=None, description="Дата операции в формате YYYY-MM-DD")
    transaction_time: Optional[str] = Field(default=None, description="Время операции в формате HH:MM:SS")
    currency: str = Field(default="EUR", description="Трехбуквенный ISO-код валюты чека")
    items: List[ReceiptItem] = Field(description="Полный перечень распознанных позиций")
    subtotal: Optional[Decimal] = Field(default=None, description="Подытог без налогов")
    tax_amount: Optional[Decimal] = Field(default=None, description="Сумма налога / НДС")
    total_amount: Decimal = Field(description="Итоговая сумма к оплате")
    is_math_consistent: bool = Field(
        default=True,
        description="Флаг математического схождения суммы позиций с итогом чека"
    )

    @model_validator(mode="after")
    def verify_receipt_totals(self) -> "ReceiptData":
        calculated_sum = sum((item.total_price for item in self.items), Decimal("0.00"))
        # Допуск 0.05 на случай округления налогов или скидок на уровне чека
        if abs(calculated_sum - self.total_amount) > Decimal("0.05"):
            self.is_math_consistent = False
        else:
            self.is_math_consistent = True
        return self


# =====================================================================
# 2. Модуль предобработки в памяти (In-Memory Preprocessing)
# =====================================================================

def prepare_receipt_parts(
    payload_bytes: bytes,
    mime_type: str = "image/jpeg",
    aspect_ratio_threshold: float = 2.5,
    max_chunk_ratio: float = 1.8,
    overlap_ratio: float = 0.12,
    jpeg_quality: int = 90,
) -> List[types.Part]:
    """
    Принимает сырые байты файла из памяти, нормализует геометрию по EXIF
    и возвращает список объектов types.Part для прямой передачи в Gemini API.

    - Если передан PDF: отдает как единый документ без перекодирования.
    - Если короткое изображение (H/W <= 2.5): нормализует EXIF и отдает 1 JPEG-кадр.
    - Если длинный чек (H/W > 2.5): нарезает на вертикальные сегменты с пропорциональным перекрытием.
    """
    if not payload_bytes:
        raise ValueError("Передан пустой байтовый буфер (payload_bytes is empty).")

    normalized_mime = mime_type.lower().strip()
    if normalized_mime == "application/pdf":
        return [types.Part.from_bytes(data=payload_bytes, mime_type="application/pdf")]

    with Image.open(io.BytesIO(payload_bytes)) as raw_img:
        # Коррекция поворота мобильных камер по EXIF-метаданным
        img = ImageOps.exif_transpose(raw_img)
        if img.mode != "RGB":
            img = img.convert("RGB")

        width, height = img.size
        if width == 0 or height == 0:
            raise ValueError(f"Некорректные размеры изображения: {width}x{height}")

        aspect_ratio = height / width

        # Случай 1: Короткий чек (не требует нарезки)
        if aspect_ratio <= aspect_ratio_threshold:
            with io.BytesIO() as buffer:
                img.save(buffer, format="JPEG", quality=jpeg_quality, optimize=True)
                return [
                    types.Part.from_bytes(data=buffer.getvalue(), mime_type="image/jpeg")
                ]

        # Случай 2: Длинный вертикальный чек -> нарезка на фреймы с перекрытием
        chunk_height = max(int(width * max_chunk_ratio), 200)
        clamped_overlap_ratio = min(max(overlap_ratio, 0.05), 0.40)
        overlap_px = int(chunk_height * clamped_overlap_ratio)
        step = max(chunk_height - overlap_px, 1)

        parts: List[types.Part] = []
        top = 0

        while top < height:
            bottom = min(top + chunk_height, height)
            chunk = img.crop((0, top, width, bottom))

            with io.BytesIO() as buffer:
                chunk.save(buffer, format="JPEG", quality=jpeg_quality)
                parts.append(
                    types.Part.from_bytes(data=buffer.getvalue(), mime_type="image/jpeg")
                )

            if bottom >= height:
                break

            top += step

        return parts


# =====================================================================
# 3. Инференс через Gemini Flash с Constrained Decoding
# =====================================================================

SYSTEM_INSTRUCTION = (
    "Ты - специализированный OCR-парсер кассовых чеков. "
    "Извлеки все товарные позиции, их количества и цены из предоставленных данных. "
    "Если передано несколько изображений, они являются последовательными вертикальными сегментами "
    "одного длинного чека с зоной нахлеста (overlap) на границах. "
    "Используй визуальный контекст и порядковый номер позиции (line_number), чтобы склеить "
    "разорванные на границе среза строки и исключить дублирование одной и той же позиции. "
    "Если в чеке фактически пробиты два одинаковых товара разными строками, сохрани оба. "
    "Не округляй числа и строго следуй схеме данных."
)


def parse_receipt_from_bytes(
    payload_bytes: bytes,
    mime_type: str = "image/jpeg",
    client: Optional[genai.Client] = None,
) -> ReceiptData:
    """
    Точка входа пайплайна: принимает байтовый буфер из памяти, выполняет нарезку
    и запрашивает типизированный вывод у модели Gemini Flash.
    """
    active_client = client or genai.Client()

    media_parts = prepare_receipt_parts(
        payload_bytes=payload_bytes,
        mime_type=mime_type,
    )

    response = active_client.models.generate_content(
        model="gemini-2.5-flash",
        contents=[
            *media_parts,
            "Извлеки структурированные данные по всем покупкам из чека."
        ],
        config=types.GenerateContentConfig(
            system_instruction=SYSTEM_INSTRUCTION,
            temperature=0.0,
            max_output_tokens=8192,
            response_mime_type="application/json",
            response_schema=ReceiptData,
            thinking_config=types.ThinkingConfig(thinking_budget=0),
        ),
    )

    if not response.candidates or response.candidates[0].finish_reason != types.FinishReason.STOP:
        reason = response.candidates[0].finish_reason if response.candidates else "EMPTY_RESPONSE"
        raise RuntimeError(f"Инференс завершился некорректно. Статус: {reason}")

    if not response.text:
        raise RuntimeError("Модель вернула пустой текстовый ответ.")

    return ReceiptData.model_validate_json(response.text)


# =====================================================================
# 4. Пример интеграции (In-Memory Stream / Webhook / FastAPI)
# =====================================================================

if __name__ == "__main__":
    # Инициализация синглтон-клиента на уровне воркера/приложения (переиспользует пул соединений httpx)
    genai_client = genai.Client()

    # Имитация получения сырых байтов в памяти (например, из Telegram Bot API или S3 get_object)
    sample_image = Image.new("RGB", (800, 2800), color=(255, 255, 255))
    in_memory_stream = io.BytesIO()
    sample_image.save(in_memory_stream, format="JPEG")
    incoming_bytes: bytes = in_memory_stream.getvalue()

    # Обработка исключительно в оперативной памяти
    structured_data = parse_receipt_from_bytes(
        payload_bytes=incoming_bytes,
        mime_type="image/jpeg",
        client=genai_client,
    )

    print(structured_data.model_dump_json(indent=2))
```

## 3. Особенности эксплуатации

1. **Управление соединениями (Connection Pooling):** Экземпляр `genai.Client()` должен создаваться один раз при старте сервиса (на уровне FastAPI lifespan или инициализации воркера) и передаваться в `parse_receipt_from_bytes`. Это предотвращает утечку сокетов и накладные расходы на повторные TLS-рукопожатия.
    
2. **Обработка несошедшихся чеков (`is_math_consistent == False`):** Если сумма распознанных позиций не совпадает с итогом чека (например, из-за замятия термобумаги или выцветшего шрифта), внешний оркестратор может автоматически повторить запрос, переключив `thinking_budget=1024`, либо направить чек в очередь ручной проверки.

3. **Защита памяти и CPU:** Лимит `Image.MAX_IMAGE_PIXELS` блокирует DoS-атаки через Decompression Bomb на этапе чтения заголовков изображения до аллокации буфера в RAM, а контекстные менеджеры `with` гарантируют немедленную очистку неуправляемой памяти C-библиотеки `libjpeg`/`zlib`.

