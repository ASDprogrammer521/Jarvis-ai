# Jarvis-ai

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.11%2B-blue?style=for-the-badge&logo=python&logoColor=white" alt="Python">
  <img src="https://img.shields.io/badge/Status-Active-success?style=for-the-badge" alt="Status">
  <img src="https://img.shields.io/badge/License-MIT-green?style=for-the-badge" alt="License">
  <img src="https://img.shields.io/badge/By-ASDcuber-orange?style=for-the-badge" alt="ASDcuber">
</p>

---

## 🌟 Overview

**Jarvis AI** is an advanced intelligent assistant built to automate workflows and simplify everyday computer tasks. It combines a clean modern interface with powerful tools: voice control, screen awareness, desktop automation, a holographic HUD, and a phone companion — all in one system.

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
| --- | --- |
| 💎 **Modern & Clean UI** | Dashboard · Chat · Settings tabs with a cinematic HUD |
|  🧑‍🎤 **3 HUD modes** | Animated face · Reactor core · Holo sphere |
| 📊 **Admin Dashboard** | Remote control via QR code or pairing key |
| ⚡ **Fast Automation** | Apps, files, browser, system controls, messaging |
| 📱 **Jarvis App (phone)** | Reverse connection — no ADB required |
| 🎙️ **Voice + Wake word** | Push-to-talk, mute, local wake-word detection |
| 🧠 **Memory** | Long-term facts you can view and delete |
| 🔌 **Plugins** | Drop-in tools in the `plugins/` folder |

---

## 📱 Phone connection (Jarvis App)

Connect your phone **without ADB**. The phone opens an outbound (reverse) link to the PC.

### Requirements
- PC and phone on the **same Wi‑Fi** network  
- Jarvis running (dashboard server active)  
- Optional but recommended:

```bash
pip install fastapi "uvicorn[standard]" cryptography
```

### Steps
1. Start Jarvis on the PC.
2. Get the **IP address** and **pairing key** from the console or the Dashboard tab.
3. On the phone, open a browser and go to:

```text
http://<PC-IP>:8000/jarvis-app
```

Example:

```text
http://192.168.35.70:8000/jarvis-app
```

If HTTPS is enabled:

```text
https://192.168.35.70:8000/jarvis-app
```

(If the browser warns about the certificate → **Advanced → Proceed**.)

4. Enter the **PC IP** and **pairing key**, then tap **Connect**.
5. You can now send commands from the phone.

### Quick URLs

| URL | Purpose |
| --- | --- |
| `/jarvis-app` or `/app` | Jarvis App (phone companion) |
| `/` | Main remote dashboard |
| `/login` | Pairing login page |

### Troubleshooting
- Test on the PC first: `http://127.0.0.1:8000/jarvis-app`
- Allow port **8000** in Windows Firewall
- Do not use a guest Wi‑Fi network — both devices must be on the same network
- **ADB is optional** (for direct Android control). The main method is the Jarvis App reverse link

---

## 🖥️ UI navigation

| Tab | What it does |
| --- | --- |
| **Dashboard** | Main holographic HUD |
| **Chat** | Conversation history |
| **Settings** | All options (full-screen) |

The **Ask anything** command bar stays visible at the bottom at all times.

---

## 📁 Project structure

```text
Mark-LIV-main/
├── main.py                 # entry point
├── ui.py                   # user interface
├── setup.py                # dependency installer
├── requirements.txt
├── actions/                # built-in tools
├── plugins/                # drop-in plugins
├── core/                   # avatar, audio, LLM…
├── dashboard/              # remote server + Jarvis App
│   └── static/jarvis_app.html
├── memory/                 # config + long-term memory
└── config/                 # API keys, certificates
```

---

## 📜 License

This project is licensed under the **MIT License**.

---

<p align="center">
  <b>By ASDcuber</b>
</p>
