<p align="center">
  <img src="assets/banner.png" alt="JARVIS — Your personal AI assistant for PC & phone" width="100%">
</p>

<h1 align="center">🤖 Jarvis AI</h1>

<p align="center">
  <b>Voice · Vision · Desktop control · Holographic HUD · Phone companion — one assistant.</b><br>
  A native desktop AI assistant that listens, sees your screen, controls your computer and your Android phone, and gets things done.
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.11%2B-blue?style=for-the-badge&logo=python&logoColor=white" alt="Python">
  <img src="https://img.shields.io/badge/UI-PyQt6-41CD52?style=for-the-badge&logo=qt&logoColor=white" alt="PyQt6">
  <img src="https://img.shields.io/badge/AI-Gemini%20Live-8E75B2?style=for-the-badge&logo=googlegemini&logoColor=white" alt="Gemini">
  <img src="https://img.shields.io/badge/Windows-EXE-0078D6?style=for-the-badge&logo=windows&logoColor=white" alt="Windows EXE">
  <img src="https://img.shields.io/badge/Android-APK-3DDC84?style=for-the-badge&logo=android&logoColor=white" alt="Android APK">
  <img src="https://img.shields.io/badge/Version-5.2.1-orange?style=for-the-badge" alt="Version">
  <img src="https://img.shields.io/badge/License-MIT-green?style=for-the-badge" alt="License">
</p>

<p align="center">
  <a href="https://github.com/ASDprogrammer521/Jarvis-ai/releases/latest">
    <img src="https://img.shields.io/badge/⬇%20Download-Windows%20EXE-0078D6?style=for-the-badge&logo=windows&logoColor=white" alt="Download Windows">
  </a>
  <a href="https://github.com/ASDprogrammer521/Jarvis-ai/releases/latest">
    <img src="https://img.shields.io/badge/⬇%20Download-Android%20APK-3DDC84?style=for-the-badge&logo=android&logoColor=white" alt="Download APK">
  </a>
</p>

---

## 📑 Table of contents

- [Overview](#-overview)
- [Highlights](#-highlights)
- [Quick start](#-quick-start)
- [Configuration](#️-configuration)
- [Built-in tools (full reference)](#-built-in-tools-full-reference)
- [Voice, speech & AI engines](#️-voice-speech--ai-engines)
- [3D HUD models](#-3d-hud-models)
- [Phone connection](#-phone-connection)
- [Remote dashboard](#-remote-dashboard)
- [Profiles](#-profiles)
- [Plugins — build your own tool](#-plugins--build-your-own-tool)
- [Safety by design](#️-safety-by-design)
- [UI navigation & shortcuts](#️-ui-navigation--shortcuts)
- [Architecture & project structure](#-architecture--project-structure)
- [Building from source](#-building-from-source)
- [Troubleshooting](#-troubleshooting)
- [License](#-license)

---

## 🌟 Overview

**Jarvis AI** is an intelligent assistant that automates everyday computer work through natural conversation. Talk to it (or type), and it will open apps, manage windows and files, browse the web, build Word / Excel / PowerPoint / PDF files, track your habits and finances, play music, count your push-ups through the webcam, and even **make phone calls through your Android phone**.

It runs as a native desktop app with a cinematic holographic HUD, speaks and listens in **any language**, and replies in the language you use.

> **Everything is a tool.** Each capability is a drop-in file in `actions/` that is discovered automatically — adding a new one takes a single file.

---

## ✨ Highlights

| | Feature | Description |
| :-: | ------- | ----------- |
| 💎 | **Modern, clean UI** | Dashboard · Chat · Settings tabs with a cinematic HUD |
| 🧑‍🚀 | **3D HUD models** | Holo · Crystal · Globe · Knot · Helix · Face — or load your own `.obj` |
| 🎙️ | **Voice + wake word** | Push-to-talk, open mic, mute, and an optional local **"Hey Jarvis"** wake word |
| 👁️ | **Vision** | Understands your screen and webcam on request ("what's on my screen?") |
| 📱 | **Jarvis App (phone)** | Native Android app + browser companion — calls, SMS, lock, locate, flashlight — **no ADB** |
| 🪟 | **Window control by name** | "Minimize Discord", "maximize Chrome", "bring Spotify forward" act on *that* app |
| ⚡ | **Fast automation** | Apps, files, browser, system settings, clipboard, screenshots, messaging |
| 🛡️ | **Safe by design** | Shutdown / restart / messages need an on-screen confirm · `undo` reverses your last change |
| 📊 | **Admin dashboard** | Remote control from a browser or phone via a pairing key |
| 🧠 | **Long-term memory** | Remembers facts about you — viewable and deletable |
| 🔌 | **Plugins + store** | Drop-in tools in `plugins/`; list / enable / disable / install from URL |
| 👤 | **Profiles** | `home` · `work` · `game` presets |
| 🔄 | **Self-update** | Checks GitHub, installs updates, can roll back |
| 🖥️ | **Compact mode** | Floating always-on-top mic (`F12`) |
| 💻 | **Windows EXE** | One-folder build via GitHub Releases — no Python needed |

---

## 🚀 Quick start

### Option 1 — Download (no Python required)

1. Open **[Releases](https://github.com/ASDprogrammer521/Jarvis-ai/releases/latest)**
2. Download `Jarvis-Windows-x64-v*.zip`
3. Extract the zip → run **`Jarvis.exe`**
4. Enter your **Gemini API key** on first launch

> Windows may show SmartScreen because the build is unsigned → **More info → Run anyway**.

### Option 2 — Run from source

**Requirements:** Python **3.11+**

```bash
# 1. Get the code
git clone https://github.com/ASDprogrammer521/Jarvis-ai.git
cd Jarvis-ai

# 2. Install dependencies for YOUR operating system + Playwright browsers
python setup.py

# 3. Start Jarvis
python main.py
```

`setup.py` reads the single `requirements.txt`, skips packages meant for other operating systems (Windows-only libs are marked `sys_platform == "win32"`), and fetches the Playwright browsers.

**API key:** on first launch the app asks for your **Gemini API key**. You can also put it in `config/api_keys.json`:

```json
{
  "gemini_api_key": "YOUR_KEY_HERE"
}
```

---

## ⚙️ Configuration

All settings live in `config/api_keys.json` (most can also be changed in **Settings** inside the app).

| Key | Purpose |
| --- | ------- |
| `gemini_api_key` | Google Gemini API key (main brain, voice + vision) |
| `assistant_name`, `user_name` | What Jarvis is called / what it calls you |
| `llm_provider`, `llm_url`, `llm_model` | Use a **local LLM** instead of the cloud — `ollama` (default) or `openai` (LM Studio, Jan, LocalAI, llama.cpp, vLLM…) |
| `stt_engine` | Speech-to-text engine (Whisper / Vosk, offline) |
| `tts_engine`, `tts_voice`, `elevenlabs_api_key` | Text-to-speech engine and voice |
| `wake_word_enabled` | Enable local "Hey Jarvis" detection |
| `auto_update_check` | Check GitHub for new versions on start |
| `spotify_client_id`, `spotify_client_secret` | Optional — one-step "play my playlist" |
| `output_dir` | Where generated files are saved (default `Documents/Jarvis/`) |
| `os_system` | Force `windows` / `mac` / `linux` (auto-detected by default) |

Environment template (`config/env.example`):

```ini
GEMINI_API_KEY=
JARVIS_BIND_HOST=127.0.0.1   # dashboard bind address (loopback by default)
JARVIS_TLS=0                 # set to 1 to serve the dashboard over HTTPS
```

---

## 🧰 Built-in tools (full reference)

Jarvis exposes **40+ tools** to the AI. You never call them by name — just talk. The "Try saying" column shows the idea.

### 🖥️ Computer & system

| Tool | What it does | Try saying |
| ---- | ------------ | ---------- |
| `open_app` | Opens any application, program or website | "Open Chrome", "launch Steam" |
| `app_manager` | Close / **minimize / maximize / restore / focus** a *named* app; top RAM/CPU apps; startup programs | "Minimize Discord", "what's eating my RAM?" |
| `computer_settings` | Volume, brightness, mute, window snapping & centering, dark mode, Wi-Fi, tabs, zoom, scrolling, shortcuts, screenshots, lock, shutdown/restart (with on-screen confirm) | "Volume to 30", "snap this window left" |
| `computer_control` | Direct mouse & keyboard: type, click, hotkeys, scroll, find things on screen, smart click/type | "Click the Submit button" |
| `power_tools` | Battery, uptime, lock, sleep, scheduled shutdown/restart, cancel | "How much battery is left?" |
| `system_status` | Live CPU, RAM, GPU load, CPU temperature, uptime, process count | "How is my PC doing?" |
| `network_tools` | Online check, public/local IP, Wi-Fi name & signal, ping, speed test | "Test my internet speed" |
| `storage_analyzer` | Free space per drive, biggest folders/files/types, junk estimate, safe temp cleanup | "What's using my disk?" |
| `appearance_tools` | Wallpaper (file or random from a folder), dark/light mode | "Random wallpaper from Pictures" |
| `clipboard_tools` | Read, write or clear the clipboard | "What did I copy?" |
| `screen_capture` | Screenshots (full / monitor / region / delayed), screen **recording** to MP4, **OCR** of the screen | "Record my screen" |
| `screen_process` | Captures screen or webcam and lets the AI **look** at it | "What's on my screen?" |
| `close_camera` | Closes the live camera view | "Close the camera" |

### 📁 Files & folders

| Tool | What it does | Try saying |
| ---- | ------------ | ---------- |
| `file_controller` | List, create, delete, move, copy, rename, read, write, find, largest files, disk usage, organize desktop | "Move report.docx to Documents" |
| `file_tools` | Find **duplicate files**, move extras to a safe folder, sort a messy folder (e.g. Downloads) — both undoable | "Clean up my Downloads" |
| `desktop_control` | Wallpaper, organize / clean the desktop, list items, stats | "Organize my desktop" |
| `file_processor` | Work on **dropped/uploaded files**: images (describe, OCR, resize, compress, convert), PDF, Word/text, CSV/Excel (analyze, stats, filter, sort), JSON/XML, code (explain, review, fix, run, test), audio & video (transcribe, trim, convert, extract audio/frames), archives | "Summarize this PDF" |

### 🌐 Web & information

| Tool | What it does | Try saying |
| ---- | ------------ | ---------- |
| `browser_control` | Any browser (Chrome, Edge, Firefox…): open sites, search, click, fill forms, scroll, tabs, screenshots | "Open Edge and search for…" |
| `web_search` | Live web search with modes: **search · news · research · price · compare** | "Latest news on SpaceX" |
| `knowledge_lookup` | Wikipedia summaries (any language) and English dictionary definitions | "Who is Ada Lovelace?" |
| `weather_report` | Weather for any city | "Weather in Tashkent" |
| `flight_finder` | Searches Google Flights and reads out the best options | "Flights Tashkent → Istanbul on Friday" |
| `manage_monitor` | Watches topics daily and alerts you to new headlines | "Monitor AI news" |

### 🗂️ Productivity & learning

| Tool | What it does | Try saying |
| ---- | ------------ | ---------- |
| `notes_tasks` | To-do list (shown on the Dashboard) and quick notes | "Add a task: call the bank" |
| `reminder` | Timed reminders | "Remind me at 6 pm to…" |
| `focus_timer` | Pomodoro sessions with breaks and rounds | "Start a 45-minute focus session" |
| `habit_tracker` | Daily habits with goals and **streaks** (water, steps, reading, sleep…) | "I drank two glasses of water" |
| `finance_tracker` | Expenses & income, auto-categories, monthly summaries, **budgets** with warnings, Excel export with chart | "I spent 50 on lunch" |
| `study_cards` | **Spaced-repetition flashcards** (Leitner boxes): AI-generated decks, voice quiz, stats | "Quiz me on Spanish verbs" |
| `text_assistant` | Translate, summarize, rewrite in a tone, fix grammar, explain simply, expand, bullet-ize, draft replies (can use the clipboard) | "Translate my clipboard to English" |
| `utility_tools` | Calculator, unit & **live currency** conversion, secure password generator, QR codes, time in any city, days until a date, dice / coin / random pick | "Convert 100 USD to UZS" |

### 📄 Office documents

| Tool | What it does | Try saying |
| ---- | ------------ | ---------- |
| `create_presentation` | Full **PowerPoint** decks: title, bullet / two-column / comparison / process / timeline / stats / quote slides, speaker notes, closing slide | "Make a presentation about solar energy" |
| `word_document` | **Word** documents: create, append, find-and-replace, read — real typography, headings, lists, tables, page numbers | "Write a CV as a Word file" |
| `generate_spreadsheet` | Designs an **Excel** workbook from a plain description (budgets, trackers, invoices, grade books…) with formulas & charts | "Make a monthly budget spreadsheet" |
| `build_spreadsheet` | Builds Excel from structured data or CSV: styled headers, formulas, totals, charts, conditional formatting, filters | "Turn this CSV into a formatted sheet" |
| `pdf_tools` | **Merge, split, extract text, OCR, extract tables → Excel, convert to PDF, info** | "Merge these two PDFs" |

### 🏋️ Fitness & health

| Tool | What it does | Try saying |
| ---- | ------------ | ---------- |
| `pushup_counter` | Live webcam **push-up counter** with AI pose detection, form checks (depth, hips, lockout), spoken feedback and workout history | "Count my push-ups" |
| `calorie_counter` | Logs meals by **text or photo**, estimates calories & macros, personal daily budget, history | "I had a chicken wrap" |

### 🎵 Media & games

| Tool | What it does | Try saying |
| ---- | ------------ | ---------- |
| `spotify_controller` | Play song / artist / album / playlist, pause, skip, volume, now playing | "Play Believer" |
| `youtube_video` | Play videos, get info, **summarize from transcript**, trending | "Summarize this YouTube video" |
| `play_hud_video` | Plays a local or direct-URL video silently inside the HUD | "Play this video in the HUD" |
| `game_updater` | **Steam & Epic**: install, update, list games, download status, scheduled updates (optional shutdown when done) | "Update all my Steam games at 3 am" |

### 💬 Communication & phone

| Tool | What it does | Try saying |
| ---- | ------------ | ---------- |
| `send_message` | Drafts a message for **WhatsApp, Telegram, Instagram** or other desktop apps — sent **only after you confirm** on the HUD | "Send Ali a WhatsApp: I'm late" |
| `phone_control` | Android control: **call, answer, reject, hang up**, SMS, open apps/links, lock/unlock, flashlight, location, battery, notifications, screenshot, volume | "Call +998 90 123 45 67" |

### 👨‍💻 Developer

| Tool | What it does | Try saying |
| ---- | ------------ | ---------- |
| `code_helper` | Write, edit, explain, **run** or build code files | "Write a Python script that…" |
| `dev_agent` | Builds **complete multi-file projects**: plans, writes files, installs deps, opens VS Code, runs and fixes errors | "Build me a Flask to-do app" |

### 🧠 Assistant core

| Tool | What it does | Try saying |
| ---- | ------------ | ---------- |
| `save_memory` / `recall_memory` | Long-term memory of facts about you (identity, preferences, projects, relationships, wishes, notes) | "What do you remember about me?" |
| `undo` | Reverses Jarvis's last change: files moved/renamed/written, volume, brightness, dark mode, Wi-Fi | "Undo that" |
| `profile_switch` | Switch / list `home`, `work`, `game` profiles | "Switch to work mode" |
| `plugin_store` | List, enable, disable, install plugins | "List my plugins" |
| `self_update` | Check, install, **roll back** updates; restart Jarvis | "Check for updates" |
| `shutdown_jarvis` | Ends the session ("goodbye") | "That's all, goodbye" |

> 💡 **Note on Spotify:** works out of the box with the desktop app (media keys, volume, search). For "play my chill playlist" in one step, add `spotify_client_id` / `spotify_client_secret` (free from [developer.spotify.com](https://developer.spotify.com/dashboard)), register `http://127.0.0.1:8888/callback` as the Redirect URI, then say **"log in to Spotify"** once.

### Tool-specific requirements

| Tool | Needs |
| ---- | ----- |
| `pushup_counter` | `opencv-python`, `mediapipe` — downloads a ~6 MB pose model to `config/models/` on first use. Put the camera at your side so your whole body is visible. |
| PDF OCR | [Tesseract](https://github.com/tesseract-ocr/tesseract) installed on your system |
| Word/PowerPoint/Excel → PDF | [LibreOffice](https://www.libreoffice.org) (or Microsoft Word + `docx2pdf` on Windows) |
| `play_hud_video` (YouTube) | `yt-dlp` + OpenCV |
| `system_monitor` / GPU meter | `pynvml` (NVIDIA GPUs) |

Generated files are saved under `Documents/Jarvis/` (change with `output_dir`). Workout and nutrition logs live in `memory/`.

---

## 🎙️ Voice, speech & AI engines

| Layer | Options |
| ----- | ------- |
| **Brain** | **Gemini Live** (real-time voice + vision + tool calling) — or a **local LLM** through `llm_client` (Ollama, or any OpenAI-compatible server: LM Studio, Jan, LocalAI, llama.cpp, vLLM) |
| **Speech-to-text** | **Whisper** (offline, `faster-whisper`) · **Vosk** (offline, lightweight) |
| **Text-to-speech** | **EdgeTTS** (free, internet) · **Kokoro** (fully offline neural, ~330 MB) · **ElevenLabs** (cloud, best quality) |
| **Wake word** | Local **"Hey Jarvis"** via `openwakeword` — zero cost when disabled |
| **Talk modes** | Push-to-talk (hold a key), open mic, mute (`F4`) |
| **Audio devices** | Pick your microphone and speakers explicitly (no more "wrong default device" after plugging in a headset) |
| **Echo guard** | Jarvis won't hear and answer its own voice coming back through the speakers |
| **Lip-sync** | Text + audio fused viseme engine drives the avatar's mouth |
| **Language** | Replies in the language of your **most recent message** — speak any language |

---

## 🧊 3D HUD models

The centre of the Dashboard shows an animated 3D model. Switch it in **Settings → Appearance** (or double-click it).

Built-in: **Holo** (golden hologram sphere) · **Crystal** · **Globe** · **Knot** · **Helix** · **Face**.

Models are plain `.obj` files in `assets/models/`. Drop yours there and it appears in the list after a restart. Layers are OBJ groups named `kind:key=value,...`:

```obj
g lines:w=1.5,a=1,mix=.3,spin=.6,add=1
l 1 2 3 4
g points:size=6,mix=.5,scan=lon
p 1 2 3
g faces:amp=.16,spec=1
f 1 2 3
```

| | |
| --- | --- |
| **Kinds** | `lines`, `points`, `faces`, `sparks`, `pulse` |
| **Keys** | `w` width · `a` opacity · `mix` colour blend (0 = main, 1 = accent) · `spin` rotation (negative = reverse) · `tilt` · `scale` · `amp` (grows with voice) · `blink` · `add` (glow blending) · `lite=0` (hidden in lightweight mode) |
| **File options** | `#@hud 1` · `#@glow 1` · `#@rim 1` · `#@palette gold` |

The built-in models are generated by `python tools/make_models.py`.

**GPU hologram:** with GPU acceleration on, the Holo model is drawn by a shader. If the shader can't run, Jarvis checks itself and falls back to the standard renderer automatically (**Settings → Appearance → Performance**).

---

## 📱 Phone connection

Jarvis connects **out** from the phone to your PC (reverse WebSocket) — nothing to port-forward, **no ADB**.

### Option A — Android APK (recommended)

1. Install the APK on your phone (allow unknown sources if asked).
2. On first open, grant **notifications**, **phone / calls**, **SMS**, **location**, **mic** and **camera** as prompted.
3. Start Jarvis on the PC and get a **fresh pairing key** (Remote Control / Dashboard).
4. In the app enter **PC IP** + **key** → **Connect**.
5. The status pill turns **● ONLINE** and a persistent *Jarvis Connected* notification appears.
6. Optional: **Enable lock permission** (Device Admin) so Jarvis can lock the screen.

**Build the APK yourself:** open `android/JarvisApp` in Android Studio, or push to GitHub → **Actions → Build Jarvis App APK** → download the `JarvisApp-debug` artifact.

### In the app

- **Header** — live status (online / connecting / offline)
- **Phone card** — call state, big **Make a call** button, **Answer / Reject / Hang up**
- **Dialer** — full keypad, long-press `0` for `+`, **Paste**, backspace (long-press clears), redial
- **Quick actions** — YouTube, Lock, Home, Notifications, Location, Camera, Voice, Torch, Screenshot
- **Control the PC** — lock or shut down the PC (shutdown asks for confirmation)
- **Activity log** and a chat bar with file attach

### Calling & messaging

| From | How |
| ---- | --- |
| **The phone** | Tap **Make a call**, type or paste a number, press green |
| **Your voice, on the PC** | "Call +998 90 123 45 67" → the PC tells the phone to dial *(a number is required — Jarvis asks if you only give a name and never invents one)* |
| **Incoming calls** | "Answer the call" · "reject it" · "hang up" · "is anyone calling?" |
| **SMS** | "Text 901234567: I'll be there in ten minutes" |

### Phone capabilities

| Capability | Notes |
| ---------- | ----- |
| Calls & SMS | Dial, answer, reject, hang up, call state, send SMS |
| Chat with Jarvis | Type in the bottom bar |
| Attach files | **+** button — text inline, small binaries as base64 |
| Message previews | With **Notification access**: SMS, WhatsApp and Telegram previews appear in the Phone section on the PC (read-only — no replies, SMS storage is never read) |
| Phone status | Name, battery and charging state every 5 minutes |
| Voice to PC | **Voice** uses on-device speech recognition |
| Screen share | Phone screen can be viewed from the dashboard |
| Auto-reconnect | The service retries if the socket drops |
| Background link | A foreground notification keeps the connection alive |

### Option B — Browser companion

```text
http://<PC-IP>:8000/jarvis-app
```

Same Wi-Fi required; use **http** (not https) unless you configured certificates. It has a phone-style keypad (**Call** hands the number to the phone's own dialer), chats with Jarvis and receives messages/links. Answering and hanging up need the APK.

---

## 📊 Remote dashboard

A FastAPI/Uvicorn server runs on port **8000** (loopback by default) and powers remote control and the phone link.

| Route | Purpose |
| ----- | ------- |
| `/` · `/login` | Web dashboard and login |
| `/jarvis-app` · `/app` | Browser phone companion |
| `/plugin-store` | Web plugin manager |
| `/ws` | Main WebSocket |
| `/ws/phone-audio` | Phone audio stream |
| `/api/command` · `/api/wake` | Send a command / wake Jarvis |
| `/api/upload` · `/api/files` | Upload and list files |
| `/api/plugins` (+ `enable` / `disable` / `install`) | Plugin management |
| `/api/phone_screen` | Phone screen view |
| `/api/device-login` · `/api/revoke-devices` | Pairing and device revocation |

> 🔒 Bind address and TLS are controlled by `JARVIS_BIND_HOST` and `JARVIS_TLS`. For access beyond your own machine, use explicit **TLS** and a trusted network.

---

## 👤 Profiles

Profiles change the 3D model, push-to-talk / open mic and graphics quality. Use **Settings → General → Profile** or say *"switch to work mode"*.

| Profile | HUD model | Notes |
| ------- | --------- | ----- |
| 🏠 `home` | Holo | Full visual effects |
| 💼 `work` | Crystal | Calm, focused |
| 🎮 `game` | Globe | **Lightweight** graphics to save resources |

---

## 🔌 Plugins — build your own tool

Every tool is auto-discovered. To add your own, copy `plugins/_template.py`, rename it (no leading underscore) and fill it in — **no other file needs to change**.

```python
PLUGIN = {
    "name": "my_plugin",
    "description": "When should the AI call this? Mention trigger phrases.",
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "example_arg": {"type": "STRING", "description": "What this argument means"},
        },
        "required": [],
    },
}

def run(parameters: dict, player=None, session_memory=None) -> str:
    example_arg = parameters.get("example_arg", "")
    try:
        return f"Did the thing with {example_arg}."   # spoken back to the user
    except Exception as e:
        return f"Sir, my_plugin failed: {e}"          # never raise
```

Manage plugins by voice (*"list my plugins"*), from `/plugin-store`, or via the `plugin_store` tool: **list / enable / disable / install from URL**.

**Built-in actions work the same way:** any `actions/*.py` exposing a module-level `TOOL` dict (`name`, `description`, `parameters`, `handler`) is picked up by `core/action_loader.py`. Broken files are logged and skipped — they never crash the app.

> ⚡ **Keep memory low:** heavy libraries (`python-pptx`, `python-docx`, `openpyxl`, `pypdf`, `mediapipe`, OpenCV) are imported only on first use. For your own lazy tool, keep `TOOL` in a small file and import heavy code inside the handler.

---

## 🛡️ Safety by design

- **Unforgeable confirmations** — shutdown, restart, Wi-Fi toggle, message sending and disk cleanup ask for confirmation on your **screen** (`core/confirm.py`); the AI cannot approve them for itself.
- **Undo stack** — `undo` reverses files you moved/renamed/wrote and settings like volume, brightness, dark mode, Wi-Fi.
- **Never claims success it didn't achieve** — tools that need confirmation report "waiting for you", not "done".
- **No uninvited tracking** — background monitoring only covers topics *you* add (and never crypto/finance).
- **Phone privacy** — notification previews are read-only; SMS storage is never read.
- **Local-first dashboard** — loopback by default, optional TLS, revocable paired devices.
- **Passwords** are copied to the clipboard and **never read aloud**.

---

## 🖥️ UI navigation & shortcuts

| Tab | What it does |
| --- | ------------ |
| **Dashboard** | Main holographic HUD with live clock and date |
| **Chat** | Conversation history (toggle open/close) |
| **Settings** | Full-screen options (appearance, voice, profile, plugins, performance…) |

The **Ask anything** command bar stays visible at the bottom.

| Key | Action |
| --- | ------ |
| `F4` | Mute / unmute |
| `F11` | Fullscreen |
| `F12` | Compact mode (floating always-on-top mic) |

**Window commands:** say the app's name — *"minimize Discord"*, *"maximize Chrome"*, *"restore Spotify"*, *"bring Steam to the front"*. Jarvis finds that app's own window and never minimizes itself by mistake. Without a name it asks which app you mean.

---

## 📁 Architecture & project structure

```text
Jarvis-ai/
├── main.py                  # entry point: Gemini Live session, audio, tool dispatch
├── setup.py                 # OS-aware dependency installer (+ Playwright browsers)
├── requirements.txt         # the only requirements file
├── Jarvis.spec              # PyInstaller spec (Windows EXE)
├── VERSION                  # current version (5.2.1)
│
├── actions/                 # 40+ built-in tools — auto-discovered via TOOL dict
├── plugins/                 # drop-in plugins (+ _template.py)
├── core/                    # engine room
│   ├── action_loader.py     #   tool discovery, validation, dispatch
│   ├── plugin_loader.py     #   plugin discovery & enable/disable
│   ├── gemini.py            #   one-shot Gemini calls with fallbacks & timeouts
│   ├── llm_client.py        #   local LLM (Ollama / OpenAI-compatible)
│   ├── stt.py · tts.py      #   speech-to-text / text-to-speech engines
│   ├── wake_word.py         #   "Hey Jarvis" detection
│   ├── hotkey.py            #   push-to-talk
│   ├── audio_devices.py     #   microphone / speaker selection
│   ├── echo.py              #   echo-tail guard
│   ├── viseme.py            #   lip-sync
│   ├── confirm.py           #   on-screen confirmations
│   ├── undo.py              #   shared undo stack
│   ├── updater.py           #   self-update & rollback
│   └── prompt.txt           #   the assistant's core protocol
│
├── ui/                      # PyQt6 window, pages, panels, widgets, 3D stage, effects, theme
├── dashboard/               # FastAPI server + web companion (jarvis_app, plugin store)
├── memory/                  # long-term memory + config manager
├── config/                  # api_keys.json, env.example, icon
├── assets/                  # banner + 3D models (assets/models/*.obj)
├── tools/make_models.py     # regenerates the built-in .obj models
├── scripts/build_exe.ps1    # local Windows packaging
├── android/JarvisApp/       # native Android companion (Kotlin)
└── .github/workflows/       # APK + Windows EXE release pipelines
```

### Android app (Kotlin)

| File | Role |
| ---- | ---- |
| `MainActivity.kt` | UI: dialer, phone card, quick actions, chat |
| `JarvisLinkService.kt` | Foreground service keeping the reverse WebSocket alive |
| `CommandExecutor.kt` | Executes commands from the PC (calls, SMS, apps, lock, torch…) |
| `JarvisNotificationListener.kt` | Read-only SMS / WhatsApp / Telegram previews |
| `ScreenShareService.kt` · `ScreenshotActivity.kt` | Screen sharing and screenshots |
| `JarvisDeviceAdmin.kt` · `UnlockActivity.kt` | Screen lock / unlock support |

---

## 🔨 Building from source

**Windows EXE (local):**

```powershell
powershell -ExecutionPolicy Bypass -File scripts\build_exe.ps1
```

**Publish a release (maintainers):**

```bash
git tag v5.2.1
git push origin v5.2.1
```

Or run **Actions → Build Python to EXE** manually. The workflow builds with PyInstaller and publishes `Jarvis-Windows-x64-v<version>.zip` to GitHub Releases.

**Android APK:** open `android/JarvisApp` in Android Studio (**Build → Build APK**), or use **Actions → Build Jarvis App APK**.

---

## 🩺 Troubleshooting

| Problem | Fix |
| ------- | --- |
| Jarvis can't hear me | Pick the correct microphone in **Settings**; the OS default can change when a headset is plugged in |
| Phone won't connect | Test `http://127.0.0.1:8000/jarvis-app` on the PC · allow port **8000** in Windows Firewall · same Wi-Fi (no guest isolation) |
| Phone link drops in background | Set Jarvis App battery to **Unrestricted** |
| A call only opens the dialer | Grant **Phone** permission: Android → Apps → Jarvis App → Permissions |
| Push-up counter sees nothing | Place the camera at your side so your whole body is visible |
| PDF OCR fails | Install Tesseract |
| Office → PDF fails | Install LibreOffice (or Word + `docx2pdf` on Windows) |
| Holo model looks plain | Shader fallback is automatic — see **Settings → Appearance → Performance** |
| SmartScreen warning | Build is unsigned → **More info → Run anyway** |

> ADB is **optional** — the main path is the Jarvis App reverse WebSocket.

---

## 📜 License

Released under the **[MIT License](LICENSE)** — © 2026 ASDprogrammer521.

---

<p align="center">
  <b>Made with ❤️ by ASDcuber</b><br>
  <sub>If Jarvis helps you, give the repo a ⭐</sub>
</p>
