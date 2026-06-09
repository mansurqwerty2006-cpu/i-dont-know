# Recent local DB

Last manually updated: 2026-06-05.

Bot project status:
- The bot is a Python Telegram bot using Telegram Bot API long polling.
- The bot calls Groq Chat Completions API at `https://api.groq.com/openai/v1/chat/completions`.
- The bot can use Tavily Search API at `https://api.tavily.com/search` for live web search.
- The bot can use Cloudflare Workers AI at `https://api.cloudflare.com/client/v4/accounts/{account_id}/ai/run/{model}` for image generation.
- The bot can use Supabase REST API for RAG document chunks and pgvector search.
- Current default model in this project: `llama-3.3-70b-versatile`.
- The bot has a practical tuning layer: advanced profile, local knowledge base, recent DB, few-shot examples, persistent chat memory, internal ground check, and optional Tavily web search.
- The bot supports private multi-chain reasoning for complex prompts without exposing a special command.
- True model weight fine-tuning is not performed in this project.

Groq / tuning notes:
- Groq Chat Completions supports an OpenAI-compatible chat API.
- Groq fine-tuning / LoRA features can require special access depending on account tier and current Groq availability.
- For this bot, `GROQ_MODEL` can be changed to a fine-tuned model id later if the owner gets access to one.

Operation notes:
- The bot only stays online while its Python process is running and the host machine has internet access.
- For 24/7 operation, use a VPS or always-on server with a process manager such as `systemd`.
- On Windows, the local bot can be started with `start_background.ps1`, but PowerShell execution policy may require `-ExecutionPolicy Bypass`.

Known local commands:
- `/start` starts the conversation.
- `/help` shows help.
- `/reset` clears short-term conversation history.
- `/model` shows the current Groq model.
- `/tuning` shows tuning-layer status.
- `/reload` reloads profile, knowledge, recent DB, examples, and memory.
- `/remember text` saves a fact for the current chat.
- `/memory` displays saved chat memory.
- `/forget` clears saved chat memory.
- `/ask text` is used in groups.
- `/web text` forces a Tavily web search before answering.
- `/search text` is an alias for `/web text`.
- `/rag` shows Supabase/RAG status.
- `/rag_search text` searches uploaded PDF/TXT/MD documents.
- Sending a PDF/TXT/MD document to the bot indexes it into Supabase RAG storage.
- Natural image requests like "сгенерируй кота в космосе" or "draw a cat in space" generate an image with Cloudflare Workers AI and send it as a Telegram photo.

Live web behavior:
- Automatic web search is enabled for prompts that look time-sensitive, such as latest news, current prices, weather, schedules, or "today" questions.
- Forced web search is available with `/web`.
- When using web results, the assistant should cite source URLs in the answer.
