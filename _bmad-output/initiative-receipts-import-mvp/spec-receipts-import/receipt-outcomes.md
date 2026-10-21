# Receipt outcomes

Each trigger leads to one outcome. All texts come from the external texts file. The legacy reference emoji are not pinned. Reaction names describe the meaning only. Every Telegram send follows Telegram's retry rules and is then only logged; a failed send never changes the outcome. The local file copy is deleted once the outcome is final.

The tolerance used in the "Items and settlement disagree" row is ±0.01 EUR.

| Trigger | Written to DB | Sender sees | Admin gets |
|---|---|---|---|
| Valid receipt, consistent, new | Yes, atomically | Success reaction | Nothing |
| Same purchase already stored | No | Dedicated duplicate reaction and the message "Данный чек уже внесен в систему" | Nothing |
| Chain not in the supported list | No | A message saying the chain is unsupported | A Telegram message |
| Items and settlement disagree beyond tolerance | No | Failure reaction and a message explaining the problem | A notification with the reason and a copy of the file |
| Extraction service responds but gives no valid result (including an unreadable store or purchase date), after the bounded attempts | No | Failure reaction and a message explaining the problem | A notification with the reason and a copy of the file |
| Extraction service unavailable | Not yet; the receipt waits durably with no deadline | In-progress reaction | Nothing extra; the outcome follows once the service returns |
| Internal service error | Depends on the stage reached; never a partial write | — | A Telegram alert |
| Unsupported content (not a photo, image or PDF) | No | "Not accepted" reaction only, no message | Nothing |
| Sender not allowlisted, or a non-private chat | No | Nothing | Nothing |
