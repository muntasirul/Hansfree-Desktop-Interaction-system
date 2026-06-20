"""
ai_handler.py — Uses Groq to convert natural language commands into structured file operation JSON.
Groq offers fast inference on LLaMA models with a generous free tier.
"""

import os
import json
import re
from dotenv import load_dotenv
from groq import Groq

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), '.env'))

SYSTEM_PROMPT = """You are an AI assistant that converts natural language file management commands into structured JSON actions.

Supported actions: copy, move, delete, list, rename, create_folder, create_file, open, launch_app, close_app, write_file

ALWAYS respond with valid JSON ONLY — no markdown, no explanation, just JSON.

JSON format:
{
  "action": "<action>",
  "source": "<absolute_path_or_empty>",
  "destination": "<absolute_path_or_empty>",
  "filter": "<file_filter_or_*>",
  "new_name": "<new_name_for_rename_or_app_name>",
  "content": "<text_to_write_for_write_file_action>",
  "mode": "<append_or_overwrite>",
  "requires_confirmation": <true_if_destructive>,
  "description": "<1-line human description of what will happen>"
}

filter values:
- "*" = all files
- "images" = jpg, jpeg, png, gif, bmp, webp, tiff, svg, ico, heic
- "videos" = mp4, mkv, avi, mov, wmv, flv, webm
- "audio" = mp3, wav, flac, aac, ogg, wma
- "documents" = pdf, doc, docx, xls, xlsx, txt, csv
- "*.jpg,*.png" = specific extensions

Rules:
- requires_confirmation = true for delete and move actions only
- For "copy all images", use filter = "images"
- For "create_file", the "destination" MUST be a full path INCLUDING filename and extension.
- For "launch_app" and "close_app", put the app name (e.g., "chrome", "notepad", "word") in the "new_name" field.
- For "write_file", **YOU ARE A CONTENT CREATOR**. Generate thorough, high-quality, and informative content. If the user asks for a paragraph, write a substantial one. If they specify a word count (e.g., "20 words"), you MUST meet it. **Never use "..." or placeholders.**
- **PRIORITY RULE**: If a user asks to "open and write" or "create and write", always prioritize the `write_file` or `create_file` action. The backend will handle the file access.
- Use the exact paths the user provides.
- If source or destination not given, leave as empty string.

Examples:
User: "close microsoft word"
{"action":"close_app","source":"","destination":"","filter":"*","new_name":"microsoft word","requires_confirmation":false,"description":"Close Microsoft Word"}

User: "open word.docx in D:/Groq and write me paragraph about cow in 20 words"
{"action":"write_file","source":"","destination":"D:/Groq/word.docx","filter":"*","new_name":"","content":"Cows are remarkable domesticated mammals known for producing milk and meat, serving as vital agricultural assets and beloved gentle giants.","mode":"append","requires_confirmation":false,"description":"Write a 20-word paragraph about a cow to D:/Groq/word.docx"}

User: "copy all images from D:/photos to D:/backup"
{"action":"copy","source":"D:/photos","destination":"D:/backup","filter":"images","new_name":"","requires_confirmation":false,"description":"Copy all images from D:/photos to D:/backup"}

User: "write a paragraph about cats in D:/Groq/notes.txt"
{"action":"write_file","source":"","destination":"D:/Groq/notes.txt","filter":"*","new_name":"","content":"Cats are small carnivorous mammals that have lived alongside humans for thousands of years, known for their agility and companionship.","mode":"append","requires_confirmation":false,"description":"Write a descriptive paragraph about cats to D:/Groq/notes.txt"}

User: "create a word file named report.docx in D:/Groq"
{"action":"create_file","source":"","destination":"D:/Groq/report.docx","filter":"*","new_name":"","requires_confirmation":false,"description":"Create file D:/Groq/report.docx"}

User: "open chrome"
{"action":"launch_app","source":"","destination":"","filter":"*","new_name":"chrome","requires_confirmation":false,"description":"Launch Google Chrome"}

User: "delete D:/test.txt"
{"action":"delete","source":"D:/test.txt","destination":"","filter":"*","new_name":"","requires_confirmation":true,"description":"Delete D:/test.txt"}

User: "create a folder named Projects in C:/"
{"action":"create_folder","source":"","destination":"C:/Projects","filter":"*","new_name":"","requires_confirmation":false,"description":"Create folder C:/Projects"}
"""

# Model list in priority order (all available on Groq free tier)
MODELS = [
    "llama-3.3-70b-versatile",
    "llama3-8b-8192",
    "gemma2-9b-it",
]


class AIHandler:
    def __init__(self):
        api_key = os.getenv("GROQ_API_KEY", "")
        if not api_key or api_key == "your_groq_api_key_here":
            raise ValueError("GROQ_API_KEY not set. Please add it to your .env file.")
        self.client = Groq(api_key=api_key)
        self.history = []  # conversation history for multi-turn context
        self._current_model = MODELS[0]

    def parse_command(self, user_text: str) -> dict:
        """Send user command to Groq LLM and parse the JSON response.
        Auto-retries with fallback models on rate limit errors."""
        self.history.append({"role": "user", "content": user_text})

        last_error = None
        for model in MODELS:
            try:
                response = self.client.chat.completions.create(
                    model=model,
                    messages=[
                        {"role": "system", "content": SYSTEM_PROMPT},
                        *self.history
                    ],
                    temperature=0.3,
                    max_tokens=512,
                )
                raw = response.choices[0].message.content.strip()
                self._current_model = model

                # Strip markdown code fences if present
                raw = re.sub(r'^```(?:json)?\s*', '', raw, flags=re.MULTILINE)
                raw = re.sub(r'\s*```$', '', raw, flags=re.MULTILINE)
                raw = raw.strip()

                try:
                    # Robust JSON extraction: Find the first '{' and use raw_decode
                    start_idx = raw.find('{')
                    if start_idx == -1:
                        raise ValueError("No JSON object found in response")
                    
                    obj, end_idx = json.JSONDecoder().raw_decode(raw[start_idx:])
                    result = obj
                except (json.JSONDecodeError, ValueError) as e:
                    # Last resort fallback with regex
                    match = re.search(r'\{.*\}', raw, re.DOTALL)
                    if match:
                        try:
                            result = json.loads(match.group())
                        except:
                            raise ValueError(f"Failed to parse JSON: {e}\nRaw: {raw[:200]}")
                    else:
                        raise ValueError(f"LLM returned non-JSON: {raw[:300]}")

                # Add assistant reply to history for context
                self.history.append({"role": "assistant", "content": raw})
                return result

            except Exception as e:
                err_str = str(e)
                if any(kw in err_str for kw in ("429", "rate_limit", "quota", "rate limit")):
                    last_error = e
                    continue  # try next model
                raise  # non-rate-limit errors bubble up

        # Remove last user message from history since it failed
        self.history.pop()
        raise Exception(
            f"All models hit their rate limits.\n\n"
            f"Please wait ~1 minute and try again.\n"
            f"Last error: {last_error}"
        )

    @property
    def current_model(self) -> str:
        return self._current_model

    def reset_chat(self):
        """Clear conversation history."""
        self.history = []
