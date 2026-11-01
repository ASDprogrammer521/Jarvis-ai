<p align="center">
<img src="assets/banner.png" alt="JARVIS — Your personal AI assistant for PC &amp; phone" width="100%">
</p>

# Jarvis-ai

<p align="center">
<img src="https://img.shields.io/badge/Python-3.11%2B-blue?style=for-the-badge&logo=python&logoColor=white" alt="Python">
<img src="https://img.shields.io/badge/Windows-EXE-0078D6?style=for-the-badge&logo=windows&logoColor=white" alt="Windows EXE">
<img src="https://img.shields.io/badge/Status-Active-success?style=for-the-badge" alt="Status">
<img src="https://img.shields.io/badge/License-MIT-green?style=for-the-badge" alt="License">
<img src="https://img.shields.io/badge/By-ASDcuber-orange?style=for-the-badge" alt="ASDcuber">
</p>

---

## 🌟 Overview

**Jarvis AI** is an advanced intelligent assistant built to automate workflows and simplify everyday computer tasks. It combines a clean modern interface with powerful tools: voice control, screen awareness, desktop automation, a holographic HUD, profiles, plugins, and a full phone companion — all in one system.

Voice, vision, desktop control, holographic HUD, and phone companion — one system. Version **5.x**.

---

## 📥 Download (no Python required)

<p align="center">
<a href="https://github.com/ASDprogrammer521/Jarvis-ai/releases/latest">
<img src="https://img.shields.io/badge/Download-Windows%20EXE-blue?style=for-the-badge&logo=windows&logoColor=white" alt="Download Windows">
</a>
<a href="https://github.com/ASDprogrammer521/Jarvis-ai/releases/latest">
<img src="https://img.shields.io/badge/Download-Android%20APK-brightgreen?style=for-the-badge&logo=android&logoColor=white" alt="Download APK">
</a>
</p>

1. Open **[Releases](https://github.com/ASDprogrammer521/Jarvis-ai/releases/latest)**
2. Download `Jarvis-Windows-x64-v*.zip`
3. Extract the zip → run **`Jarvis.exe`**
4. Enter your **Gemini API key** on first launch


> Windows may show SmartScreen (unsigned build) → **More info → Run anyway**.

### Publish a new release (for maintainers)

```bash
git tag v1.0.1
git push origin v1.0.1
```

Or: **Actions → Build Windows EXE + Release → Run workflow** (optional tag input).

Local build on Windows:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\build_exe.ps1
```

---

## 🚀 Getting Started (from source)

Follow these steps if you prefer Python source:

* 📦 **Step 1:** Install dependencies with **`setup.py`** (it reads the single `requirements.txt`, skips packages for other operating systems and fetches the Playwright browsers):

```bash
python setup.py
```

* 🔑 **Step 2:** Add your **Gemini API key**.  
  On first launch the app will ask for it, or you can place it in `config/api_keys.json`.

* ▶️ **Step 3:** Start the application:

```bash
python main.py
```

---

## ✨ Features

| Feature | Description |
| ------- | ----------- |
| 💎 **Modern & Clean UI** | Dashboard · Chat · Settings tabs with a cinematic HUD |
| 🧑‍🚀 **HUD modes & 3D models** | Holo · Crystal · Globe · Knot · Helix · Face — or drop in your own `.obj` |
| 🎙️ **Voice + Wake word** | Push-to-talk, open mic, mute, optional local "Hey Jarvis" wake word |
| 📱 **Jarvis App (phone)** | Native Android app — **call by name or number**, incoming-call alerts on the PC, find my phone, big file transfer, SMS, lock, locate — no ADB. A lightweight browser page covers chat and basic commands |
| 🔒 **Encrypted link** | HTTPS / WSS by default. Jarvis makes its own certificate automatically — nothing to buy or install |
| 🧩 **Modes** | "Work mode" opens and arranges a whole set-up; save your own by voice |
| 🪟 **Window control by name** | "Minimize Discord", "snap Chrome left", "Chrome and Discord side by side", "move Chrome to the other monitor" act on *that* app's window |
| ⌨️ **Custom shortcuts** | Mute, fullscreen and compact mode keys are yours to change in Settings → Shortcuts |
| ⚡ **Fast Automation** | Apps, files, browser, system controls, clipboard, screenshots, messaging |
| 🛡️ **Safe by design** | Shutdown / restart / messages need an on-screen confirm · `undo` reverses volume, brightness, files and more |
| 📊 **Admin Dashboard** | Remote control from a browser or the phone via pairing key |
| 🧠 **Memory** | Long-term facts you can view and delete |
| 🔌 **Plugins + store** | Drop-in tools in `plugins/`; list / enable / disable / install from URL |
| 👤 **Profiles** | `home` · `work` · `game` presets |
| 🔄 **Self-update** | Checks GitHub for updates and applies them |
| 🖥️ **Compact mode** | Floating always-on-top mic (F12) |
| 💻 **Windows EXE** | Single-folder build via GitHub Releases — no Python install |

### Built-in tools

| Area | Tools — try saying |
| ---- | ------------------ |
| **Computer** | `computer_settings` volume, brightness, dark mode, Wi-Fi · `app_manager` close / **minimize / maximize / restore / focus / snap / tile / next monitor** for a named app, minimize everything, top RAM/CPU apps, startup list · `macros` **modes** (work, game, relax, clean, or your own) · `screen_process` "what does this error mean?" — it looks at your screen and explains · `power_tools` battery, uptime, lock, sleep · `network_tools` IP, Wi-Fi, speed · `storage_analyzer` biggest folders and file types · `file_tools` duplicates and cleanup · `clipboard_tools` · `screen_capture` screenshots and recordings · `appearance_tools` wallpaper |
| **Phone** | `phone_control` — "call Akam" · "call +998 90 123 45 67" · "answer" / "reject" / "hang up" · "who called?" · "find my phone" · "send report.pdf to my phone" · "text 901234567: I'm late" · "lock my phone" |
| **Productivity** | `notes_tasks` to-do list and notes · `reminder` · `focus_timer` Pomodoro · `habit_tracker` streaks · `finance_tracker` expenses and income · `study_cards` spaced-repetition flashcards · `text_assistant` translate, summarize, rewrite, fix grammar |
| **Office** | PowerPoint decks · Word documents · Excel workbooks with formulas and charts · PDF merge / split / convert / OCR |
| **Fitness & health** | `pushup_counter` webcam rep counting with form checks · `calorie_counter` meals by text or photo |
| **Media & games** | `spotify_controller` · `youtube_video` summaries · `play_hud_video` muted video in the HUD · `game_updater` Steam / Epic installs and updates |
| **Info** | `web_search` · `knowledge_lookup` · `weather_report` · `flight_finder` · `utility_tools` calculator, units, live currency |
| **Developer** | `code_helper` write / edit / run code · `dev_agent` multi-file projects |

Each tool is a drop-in file in `actions/`, discovered automatically.

---

## 🧊 3D HUD models

The centre of the home screen shows an animated 3D model. Switch it in **Settings → Appearance** (or double-click it).
Built-in: **Holo** (golden hologram sphere), **Crystal**, **Globe**, **Knot**, **Helix** and **Face**.

Models are plain `.obj` files in `assets/models/`. Drop your own file there and it appears in the list after a restart.
Layers are OBJ groups named `kind:key=value,...`, for example:

```
g lines:w=1.5,a=1,mix=.3,spin=.6,add=1
l 1 2 3 4
g points:size=6,mix=.5,scan=lon
p 1 2 3
g faces:amp=.16,spec=1
f 1 2 3
```

Kinds: `lines`, `points`, `faces`, `sparks`, `pulse`. Useful keys: `w` width, `a` opacity, `mix` colour blend (0 = main, 1 = accent),
`spin` rotation speed (negative = reverse), `tilt`, `scale`, `amp` (grows with voice), `blink`, `add` (glow blending), `lite=0` (hidden in lightweight mode).
File-level options use `#@hud 1`, `#@glow 1`, `#@rim 1`, `#@palette gold`. The built-in models are generated by `python tools/make_models.py`.

---

## 🧰 Tool setup notes

Setup notes:

* **Memory:** heavy tools (PowerPoint, Word, PDF, Excel, push-up counter) are loaded only when you ask for them. At startup only a tiny declaration file is read; the libraries (`python-pptx`, `python-docx`, `openpyxl`, `pypdf`, `mediapipe`, OpenCV) are imported on first use. To make your own action lazy, keep `TOOL` in a small file and import the heavy code inside the handler.
* **GPU hologram:** with GPU acceleration on, the Holo model is drawn by a shader on the graphics card. If the shader cannot run, Jarvis checks itself and switches to the standard renderer automatically (Settings → Appearance → Performance).
* **Profiles:** Settings → General → Profile (or "switch to work mode") changes the 3D model, push-to-talk / open mic and graphics quality: Home = Holo, Work = Crystal, Game = Globe + lightweight.
* **Push-up counter** needs `opencv-python` and `mediapipe`. On first use it downloads a small pose model (about 6 MB) to `config/models/`. Place the camera at your side so your whole body is visible.
* **PDF OCR** needs the free [Tesseract](https://github.com/tesseract-ocr/tesseract) program installed. Converting Word/PowerPoint/Excel to PDF needs [LibreOffice](https://www.libreoffice.org) (or Microsoft Word with `docx2pdf` on Windows).
* **Spotify** works out of the box with the desktop app (media keys, volume, search page). For one-step "play my chill playlist", add `spotify_client_id` and `spotify_client_secret` (free, from developer.spotify.com/dashboard) to `config/api_keys.json`, register `http://127.0.0.1:8888/callback` as the Redirect URI, then say "log in to Spotify" once.
* Generated files are saved under `Documents/Jarvis/` (change with `"output_dir"` in `config/api_keys.json`). Workout and nutrition logs live in `memory/`.

---

## 📱 Phone connection

Jarvis connects **out** from the phone to your PC (reverse WebSocket), so there is nothing to forward and no ADB.

### Option A — Android APK (recommended)

<p align="center">
<a href="https://github.com/ASDprogrammer521/Jarvis-ai/releases/latest">
<img src="https://img.shields.io/badge/Download-Jarvis%20APK-brightgreen?style=for-the-badge&logo=android&logoColor=white" alt="Download APK">
</a>
</p>

1. Install the APK on your phone (allow install from unknown sources if needed).
2. On first open, allow **notifications**, **phone / calls**, **call log**, **contacts**, **SMS**, **location**, **mic** and **camera** as prompted.
3. Start Jarvis on the PC and get a **fresh pairing key** (Remote Control / Dashboard).
4. In the app: enter **PC IP** + **key** → **Connect**.
5. The pill in the corner turns **● ONLINE** and a persistent **Jarvis Connected** notification appears.
6. Optional: **Enable lock permission** so Jarvis can lock the screen.

**Build the APK yourself:** open `android/JarvisApp` in Android Studio, or push to GitHub → **Actions** → **Build Jarvis App APK** → download the `JarvisApp-debug` artifact.

### The app

* **Header** — live status pill (online / connecting / offline).
* **Phone card** — current call state (refreshed every two seconds), a big **Make a call** button, and **Answer / Reject / Hang up**.
* **Dialer** — bottom sheet with a full keypad, long-press `0` for `+`, **Paste**, backspace (long-press clears) and redial of the last number.
* **Quick actions** — YouTube, Lock, Home, Notifications, Location, Camera, Voice, Torch, Screenshot, **Find phone**, **Contacts**, **Send file**.
* **Control the PC** — lock, mute, volume, play / pause / next / previous, **App…** (minimize, maximize, bring forward or close any app by name) and shut down (asks for confirmation).
* **Link line** — 🔒 shows the link is encrypted and the certificate is pinned; **Forget PC certificate** is for after you reinstall Jarvis.
* **Activity log** and a chat bar with file attach.

### Phone calls

| From | How |
| ---- | --- |
| **The phone** | Tap **Make a call**, type or paste a number, press the green button. |
| **Your voice, on the PC** | "Call +998 90 123 45 67" → the PC tells the phone to dial. Jarvis needs a **number**; it will ask if you only give a name. |
| **By name** | "Call Akam" — the phone searches its contacts. If two people match, Jarvis asks which one. |
| **Incoming calls** | The PC shows a banner (Phone page, plus a pop-up), Jarvis tells you who is calling and asks: *answer* or *reject*? |
| **SMS** | "Text 901234567: I'll be there in ten minutes" |

Caller names need **Contacts** and caller numbers need **Call log** (Android 9+ hides the number without it). Calls need the **Phone** permission. Without it Jarvis opens the dialer with the number filled in instead of dialling. Answer / reject / hang up need **Answer phone calls** (Android 8+); on some phones the system dialer may still refuse to be controlled.

### Option B — Browser page (no install)

```text
https://<PC-IP>:8000/jarvis-app
```

Same Wi‑Fi required. Enter the pairing key (or scan the QR code from Remote Control). The page lets you:

* chat with Jarvis and send quick commands (status, mute, unmute);
* read Jarvis's replies, notifications and links.

**Calls are not available in the browser.** A web page cannot place, answer, reject or hang up phone calls — and has no access to contacts or the call log. Use the Android APK (Option A) for calling, SMS, incoming-call alerts and file transfer.

### Phone capabilities (Android app)

| Capability | Notes |
| ---------- | ----- |
| Calls and SMS | Dial by number or name, answer, reject, hang up, call state, incoming-call alerts, send SMS |
| Chat with Jarvis | Type in the bottom bar and send |
| Files, phone → PC | **+** or **Send file** — any size (up to the server limit) over the encrypted link; saved in the dashboard uploads folder |
| Files, PC → phone | "Send report.pdf to my phone" — a one-file link that expires in 15 minutes; the file lands in `Downloads/Jarvis` |
| Find my phone | Rings on the alarm channel at full volume (even when silent) for up to 90 s; "stop ringing" or the tile stops it |
| Quick actions | YouTube, Lock, Home, Notifs, Location, Camera, Voice, Torch, Screenshot |
| Message previews | Enable **Notification access**; SMS, WhatsApp and Telegram previews show in the Phone section on the PC (read-only — no replies, SMS storage is never read) |
| Phone status | Name, battery and charging state reported every five minutes |
| Voice to PC | **Voice** uses on-device speech recognition |
| PC Lock / Shutdown | Secure control commands to the PC |
| Auto-reconnect | The service retries the link if the socket drops |
| Background link | A foreground notification keeps the connection alive |

### Do I need a certificate?

**No — you do not need to buy, create or install anything.** Jarvis handles it for you:

| Question | Answer |
| -------- | ------ |
| Who creates the certificate? | Jarvis, automatically, the first time the dashboard starts (`config/certs/`). It is generated on *your* PC, so every install has its own key. |
| Is it a "real" (CA-signed) certificate? | No. It is **self-signed**, which is fine for a private LAN link. A public certificate (Let's Encrypt etc.) needs a domain name and is meant for websites on the internet — not for `192.168.x.x`. |
| Does the Android app need it? | The app pins the certificate's SHA-256 fingerprint the **first time** it pairs (trust on first use). Nothing to install on the phone. |
| Does the browser need it? | Browsers show a **warning once** because the certificate is self-signed. Compare the SHA-256 fingerprint with the one shown in Jarvis → Phone, then continue. |
| What does it need to work? | The `cryptography` Python package (installed by `setup.py`). Without it Jarvis falls back to plain HTTP and prints a warning. |
| Can I turn it off? | Yes: set `JARVIS_TLS=0` (see `config/env.example`). The link then becomes **unencrypted** — use only on a network you fully trust. |
| When is a new one created? | When your PC's LAN IP changes, or if you delete `config/certs/`. Then tap **Forget PC certificate** in the app and pair again. |

### Troubleshooting

| Problem | Fix |
| ------- | --- |
| Can't open the page | Test on the PC first: `https://127.0.0.1:8000/jarvis-app` (accept the warning once). |
| Phone can't reach the PC | Allow port **8000** in Windows Firewall, and use the same Wi‑Fi (not a guest network with client isolation). |
| "Invalid or expired key" | Pairing keys last 10 minutes and work once. Get a fresh one from Remote Control. |
| "Certificate changed" in the app | You reinstalled Jarvis or your PC's IP changed → tap **Forget PC certificate** and connect again. If you changed nothing, treat it as a warning. |
| Link keeps dropping | Set Jarvis App to **Unrestricted** battery use. |
| A call only opens the dialer | Grant the **Phone** permission: Android → Apps → Jarvis App → Permissions. |
| Need plain HTTP on a trusted network | Set `JARVIS_TLS=0` before starting Jarvis (not recommended). |

> ADB is **not** required — the link is the Jarvis App's reverse WebSocket.

---

## 🖥️ UI navigation

There is no top bar — the whole window is the page. Navigation lives in a slim **side rail** on the left:

* At rest it shows **icons only** (plus a status dot, the time and the fullscreen / compact-mode controls).
* **Move the mouse onto it** and it slides open with the labels, the date and the version; move away and it folds back.
* The microphone state (**Live / Muted / Listening / Speaking …**) is the dot at the bottom of the rail; it shows its name when the rail is open.

| Item | What it does |
| --- | --- |
| **Home** | Main holographic HUD with the **Ask anything** command bar |
| **Chat** | Conversation history |
| **Dashboard** | System stats, tasks, activity and music |
| **Phone** | Paired phone, calls, files and quick actions |
| **Voice & AI** / **Settings** | Full-screen options |

**Shortcuts:** `F4` mute · `F11` fullscreen · `F12` compact mode  

**Window commands:** say the app's name — "minimize Discord", "maximize Chrome", "restore Spotify", "bring Steam to the front". Jarvis finds that app's own window; it never minimizes itself by mistake. Without a name, minimize / maximize act on the focused window — which is Jarvis while you talk to it — so it refuses and asks which app you mean.


---

## 👤 Profiles & plugins

**Profiles** (`home` / `work` / `game`) store preferred HUD and talk-mode style. Ask Jarvis to list or switch profiles, or use the `profile_switch` tool.

**Plugin store:** drop a `.py` file into `plugins/`, then list / enable / disable via the `plugin_store` tool (or Settings plugins UI where available).

---

## 📁 Project structure

```text
Jarvis-ai/
├── main.py                 # entry point
├── ui/                     # window, pages, 3D stage, settings, theme
├── assets/models/          # 3D HUD models (.obj)
├── tools/make_models.py    # regenerates the built-in .obj models
├── setup.py                # dependency installer
├── Jarvis.spec             # PyInstaller (Windows EXE)
├── requirements.txt        # the only requirements file
├── actions/                # built-in tools
├── plugins/                # drop-in plugins
├── core/                   # avatar, audio, LLM, updater…
├── dashboard/              # remote server + web companion
├── android/JarvisApp/      # native Android companion (Kotlin) — dialer, calls, quick actions
├── scripts/build_exe.ps1   # local Windows packaging
├── memory/                 # config + long-term memory
├── config/                 # API keys, certificates
└── .github/workflows/      # APK + Windows EXE releases
```

---

## 🔒 Security

* **Encrypted link.** The dashboard serves HTTPS and the app connects over WSS. Jarvis creates a self-signed certificate in `config/certs/` automatically (and a new one if your PC's LAN address changes). The private key is never shipped with the project. The Android app pins its SHA-256 fingerprint the first time it pairs and refuses any other certificate afterwards — it never silently drops back to plain HTTP once a certificate is pinned.
* **Pairing key.** A one-time key (valid ten minutes) turns into a session token; "revoke devices" ends all sessions.
* **Confirmations.** Shutdown, restart and outgoing messages need your click on the PC. A shutdown asked for from the phone starts a 15-second countdown (`shutdown /a` cancels it).
* **Files.** PC → phone transfers are single-file links that expire; keys, certificates and `api_keys.json` are never sent.

---

## 📜 License

This project is licensed under the **MIT License**.

---

<p align="center">
<b>By ASDcuber</b>
</p>
