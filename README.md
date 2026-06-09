# Telegram bot with Groq AI

Простой Telegram-бот на Python, который отвечает через Groq Chat Completions API.

## Что улучшено

В боте добавлен практичный tuning-слой:

- `bot_profile.md` - стиль, роль и правила поведения бота;
- `bot_knowledge.md` - локальная база знаний;
- `recent_db.md` - свежая локальная база фактов и состояния проекта;
- `training_examples.jsonl` - few-shot примеры хороших ответов;
- `data/chat_memory.json` - постоянная память по чатам;
- Internal ground check - скрытая проверка основы, пробелов, свежести и уверенности перед финальным AI-ответом;
- Tavily web search - свежая информация из интернета для актуальных вопросов;
- Cloudflare Workers AI image generation - генерация картинок по обычной фразе вроде "сгенерируй кота в космосе";
- Supabase RAG - чтение PDF/TXT/MD файлов, embeddings и vector search;
- Internal multi-chain reasoning - несколько скрытых reasoning passes для сложных вопросов;
- `/remember` - запомнить факт для текущего чата;
- `/reload` - перечитать профиль, знания и примеры без изменения кода.

Это не настоящее обучение весов модели. Это быстрый способ сделать поведение бота ближе к fine-tuning уже сейчас.

## Быстрый старт

1. Установите Python 3.10+.
2. Скопируйте `.env.example` в `.env`.
3. Вставьте в `.env` свои значения:

```env
TELEGRAM_BOT_TOKEN=...
GROQ_API_KEY=...
```

4. Запустите:

```powershell
python bot.py
```

Фоновый запуск:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\start_background.ps1
```

Остановка фонового процесса:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\stop_bot.ps1
```

## Команды

- `/start` - приветствие
- `/help` - список команд
- `/reset` - очистить историю диалога
- `/model` - показать текущую модель Groq
- `/tuning` - показать статус tuning-слоя
- `/reload` - перечитать `bot_profile.md`, `bot_knowledge.md`, `training_examples.jsonl`
- `/remember текст` - сохранить постоянную память для текущего чата
- `/memory` - показать память текущего чата
- `/forget` - очистить постоянную память текущего чата
- `/ask текст` - задать вопрос в группе
- `/web текст` - принудительно найти свежую информацию в интернете
- `/search текст` - то же самое, что `/web`
- `/image текст` - сгенерировать картинку
- `/draw текст` - нарисовать картинку
- `/rag` - статус Supabase/RAG
- `/rag_search текст` - поиск по загруженным PDF/TXT/MD файлам

При старте бот регистрирует эти команды в Telegram menu panel.

Чтобы сгенерировать картинку, напишите обычным текстом: "сгенерируй кота в космосе", "нарисуй город будущего", "create an image of a robot in a library".

Чтобы добавить файл в RAG, отправьте боту PDF/TXT/MD документ обычным Telegram-файлом.

В личном чате бот отвечает на обычные текстовые сообщения. В группах бот отвечает только на `/ask ...` или на сообщения с упоминанием бота.

## Как настраивать бота

Измените `bot_profile.md`, если хотите другой стиль. Например: "отвечай как строгий наставник", "пиши короче", "делай больше примеров".

Добавьте факты в `bot_knowledge.md`, если бот должен знать что-то о вашем проекте, бизнесе, правилах или услугах.

Обновляйте `recent_db.md`, если хотите, чтобы бот учитывал свежие локальные факты: дату обновления, состояние проекта, актуальные правила, цены, расписания или внутреннюю информацию.

Добавляйте примеры в `training_examples.jsonl` в формате:

```jsonl
{"user":"Вопрос пользователя","assistant":"Идеальный ответ бота"}
```

После изменений отправьте боту в Telegram:

```text
/reload
```

## Настройки `.env`

- `GROQ_MODEL` - модель Groq, по умолчанию `llama-3.3-70b-versatile`
- `GROQ_TEMPERATURE` - креативность ответа, от `0` до `2`
- `GROQ_MAX_TOKENS` - максимальная длина ответа
- `BOT_HISTORY_MESSAGES` - сколько последних сообщений держать в памяти
- `BOT_FEW_SHOT_EXAMPLES` - сколько примеров брать из `training_examples.jsonl`
- `BOT_PROFILE_FILE` - файл профиля
- `BOT_KNOWLEDGE_FILE` - файл базы знаний
- `BOT_RECENT_DB_FILE` - файл свежей локальной базы
- `BOT_EXAMPLES_FILE` - файл примеров
- `BOT_MEMORY_FILE` - файл постоянной памяти
- `BOT_GROUND_CHECK` - включить внутренний ground check перед AI-ответом
- `BOT_GROUND_CHECK_MAX_TOKENS` - максимальная длина внутреннего ground check
- `BOT_MULTI_CHAIN_REASONING` - включить скрытый multi-chain reasoning
- `BOT_MULTI_CHAIN_COUNT` - сколько внутренних passes делать
- `BOT_MULTI_CHAIN_MAX_TOKENS` - лимит токенов на один internal pass
- `TAVILY_API_KEY` - ключ Tavily Search API
- `TAVILY_SEARCH_ENABLED` - включить web search
- `TAVILY_AUTO_SEARCH` - автоматически искать для свежих/актуальных вопросов
- `TAVILY_SEARCH_DEPTH` - `basic` или `advanced`
- `TAVILY_MAX_RESULTS` - сколько результатов Tavily передавать модели
- `CLOUDFLARE_API_TOKEN` - Cloudflare API token для Workers AI
- `CLOUDFLARE_ACCOUNT_ID` - Cloudflare account id
- `CLOUDFLARE_IMAGE_MODEL` - модель, по умолчанию `@cf/stabilityai/stable-diffusion-xl-base-1.0`
- `CLOUDFLARE_IMAGE_WIDTH` - ширина, по умолчанию `1024`
- `CLOUDFLARE_IMAGE_HEIGHT` - высота, по умолчанию `1024`
- `CLOUDFLARE_IMAGE_NUM_STEPS` - число шагов, по умолчанию `20`
- `CLOUDFLARE_IMAGE_GUIDANCE` - guidance, по умолчанию `7.5`
- `SUPABASE_URL` - URL проекта Supabase
- `SUPABASE_ANON_KEY` - anon key
- `SUPABASE_SERVICE_ROLE_KEY` - service role key для серверной записи chunks
- `RAG_ENABLED` - включить RAG
- `RAG_EMBEDDING_MODEL` - модель embeddings Cloudflare, по умолчанию `@cf/baai/bge-small-en-v1.5`
- `RAG_MATCH_COUNT` - сколько chunks подставлять в ответ
- `RAG_SIMILARITY_THRESHOLD` - минимальная похожесть
- `BOT_SYSTEM_PROMPT` - базовая системная инструкция для ИИ

## Supabase RAG schema

Один раз откройте Supabase SQL Editor и выполните файл:

```text
supabase_rag_schema.sql
```

Он создаёт `pgvector`, таблицу `rag_chunks` и RPC-функцию `match_rag_chunks`.

## Настоящий fine-tuning на Groq

Groq поддерживает API для fine-tuning/LoRA в ограниченном режиме. Для обычного бота быстрее и дешевле начать с профиля, базы знаний, примеров и памяти. Если позже будет enterprise-доступ и готовый LoRA-адаптер, можно указать fine-tuned model id в `GROQ_MODEL`.

## Безопасность

Не публикуйте `.env` и не отправляйте его в GitHub. Если токен Telegram или Groq API key где-то засветился, лучше перевыпустить его в BotFather/Groq Console.
