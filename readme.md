# Jarvis-ai

<p align="center">
<img src="https://img.shields.io/badge/Python-3.11%2B-blue?style=for-the-badge&logo=python&logoColor=white" alt="Python">
<img src="https://img.shields.io/badge/Status-Active-success?style=for-the-badge" alt="Status">
<img src="https://img.shields.io/badge/License-MIT-green?style=for-the-badge" alt="License">
<img src="https://img.shields.io/badge/By-ASDcuber-orange?style=for-the-badge" alt="ASDcuber">
</p>

---

## 🌟 Overview

**Jarvis AI** is an advanced intelligent assistant built to automate workflows and simplify everyday computer tasks. It combines a clean modern interface with powerful tools: voice control, screen awareness, desktop automation, a holographic HUD, profiles, plugins, and a full phone companion — all in one system.

Voice, vision, desktop control, holographic HUD, and phone companion — one system.

---

## 🚀 Getting Started

Follow these steps to set up and run the project:

* 📦 **Step 1:** Install dependencies with **`setup.py`**:

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
| 🧑‍🚀 **HUD modes** | Animated face · Reactor core · Holo sphere · Iron Man armor |
| 📊 **Admin Dashboard** | Remote control via pairing key / browser |
| ⚡ **Fast Automation** | Apps, files, browser, system controls, messaging |
| 📱 **Jarvis App (phone)** | Native Android app + web companion — no ADB required |
| 🎙️ **Voice + Wake word** | Push-to-talk, mute, local wake-word detection |
| 🧠 **Memory** | Long-term facts you can view and delete |
| 🔌 **Plugins + store** | Drop-in tools in `plugins/`; list / enable / disable |
| 👤 **Profiles** | `home` · `work` · `game` presets |
| 🔄 **Self-update** | Check GitHub (`ASDcuber/Jarvis-ai`) for updates |
| 🖥️ **Compact mode** | Floating always-on-top mic (F12) |

---

## 📱 Phone connection

### Option A — Android APK (recommended)

<p align="center">
<a href="https://github.com/ASDprogrammer521/Jarvis-ai/raw/main/app-debug.apk">
<img src="https://img.shields.io/badge/Download-Jarvis%20APK-brightgreen?style=for-the-badge&logo=android&logoColor=white" alt="Download APK">
</a>
</p>

1. Install the APK on your phone (allow install from unknown sources if needed).
2. On first open, allow **notifications**, **files**, **location**, **mic**, **camera** as prompted.
3. Start Jarvis on the PC and get a **fresh pairing key** (Remote Control / Dashboard).
4. In the app: enter **PC IP** + **key** → **Connect**.
5. Status should show **● ONLINE** and a persistent **Jarvis Connected** notification.

**Build APK yourself (GitHub Actions):** push the repo → **Actions** → **Build Jarvis App APK** → download artifact `JarvisApp-debug`.

### Option B — Browser companion

```text
http://<PC-IP>:8000/jarvis-app
```

Example: `http://192.168.35.70:8000/jarvis-app`

Same Wi‑Fi required. Use **http** (not https) unless you configured certificates.

### Phone capabilities

| Capability | Notes |
| ---------- | ----- |
| Chat with Jarvis | Type in the bottom bar and send |
| Attach files | **+** button — text files inline; small binaries as base64 |
| Quick actions | YouTube, Lock, Home, Notifs, Location, Camera, Voice |
| Read notifications | Enable **Notification access** for Jarvis App |
| Location | Grant location permission |
| Voice to PC | **Voice** uses on-device speech recognition |
| PC Lock / Shutdown | Quick buttons send secure control commands to the PC |
| Auto-reconnect | Service retries the link if the socket drops |
| Background link | Foreground notification keeps the connection alive |

### PC → phone commands (examples)

- Open YouTube / Chrome / apps on the phone  
- Send a file to the phone (`send_file`)  
- Ask for notifications or location  
- Notify / toast on the phone  

### Quick URLs

| URL | Purpose |
| --- | ------- |
| `/jarvis-app` or `/app` | Web phone companion |
| `/` | Main remote dashboard |
| `/login` | Pairing login |

### Troubleshooting

- Test on the PC: `http://127.0.0.1:8000/jarvis-app`
- Allow port **8000** in Windows Firewall  
- Same Wi‑Fi (not guest isolation)  
- **ADB is optional** — main path is Jarvis App reverse WebSocket  
- Phone battery: set Jarvis App to **Unrestricted** so background link stays alive  

```bash
pip install fastapi "uvicorn[standard]" cryptography
```

---

## 🖥️ UI navigation

| Tab | What it does |
| --- | ------------ |
| **Dashboard** | Main holographic HUD |
| **Chat** | Conversation history (toggle open/close) |
| **Settings** | Full-screen options |

The **Ask anything** command bar stays visible at the bottom.

**Shortcuts:** `F4` mute · `F11` fullscreen · `F12` compact mode  

Top-left shows the live clock and date.

---

## 👤 Profiles & plugins

**Profiles** (`home` / `work` / `game`) store preferred HUD and talk-mode style. Ask Jarvis to list or switch profiles, or use the `profile_switch` tool.

**Plugin store:** drop a `.py` file into `plugins/`, then list / enable / disable via the `plugin_store` tool (or Settings plugins UI where available).

---

## 📁 Project structure

```text
Mark-LIV-main/
├── main.py                 # entry point
├── ui.py                   # user interface + HUD
├── setup.py                # dependency installer
├── requirements.txt
├── actions/                # built-in tools
│   ├── phone_control.py
│   ├── plugin_store.py
│   ├── profile_switch.py
│   └── ...
├── plugins/                # drop-in plugins
├── core/                   # avatar, audio, LLM, updater…
├── dashboard/              # remote server + web companion
│   └── static/jarvis_app.html
├── android/JarvisApp/      # native Android companion source
├── memory/                 # config + long-term memory
├── config/                 # API keys, certificates
└── .github/workflows/      # APK build (GitHub Actions)
```

---

## 📜 License

This project is licensed under the **MIT License**.

---

<p align="center">
<b>By ASDcuber</b>
</p>
