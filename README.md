# Jarvis-ai

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.11%2B-blue?style=for-the-badge&logo=python&logoColor=white" alt="Python">
  <img src="https://img.shields.io/badge/Status-Active-success?style=for-the-badge" alt="Status">
  <img src="https://img.shields.io/badge/License-MIT-green?style=for-the-badge" alt="License">
  <img src="https://img.shields.io/badge/By-ASDcuber-orange?style=for-the-badge" alt="ASDcuber">
</p>

<p align="center">
  <a href="https://github.com/ASDprogrammer521/Jarvis-ai/raw/main/app-debug.apk">
    <img src="https://img.shields.io/badge/Download-Jarvis%20APK-brightgreen?style=for-the-badge&logo=android&logoColor=white" alt="Download APK">
  </a>
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
🔑 Step 2: Add your Gemini API key.On first launch the app will ask for it, or you can place it in config/api_keys.json.▶️ Step 3: Start the application:Bashpython main.py
✨ FeaturesFeatureDescription💎 Modern & Clean UIDashboard · Chat · Settings tabs with a cinematic HUD🧑‍🎤 3 HUD modesAnimated face · Reactor core · Holo sphere📊 Admin DashboardRemote control via QR code or pairing key⚡ Fast AutomationApps, files, browser, system controls, messaging📱 Jarvis App (phone)Reverse connection — no ADB required🎙️ Voice + Wake wordPush-to-talk, mute, local wake-word detection🧠 MemoryLong-term facts you can view and delete🔌 PluginsDrop-in tools in the plugins/ folder📱 Phone connection (Jarvis App)Connect your phone without ADB. The phone opens an outbound (reverse) link to the PC. You can also download the Android APK directly using the green button at the top of this page.RequirementsPC and phone on the same Wi‑Fi networkJarvis running (dashboard server active)Optional but recommended:Bashpip install fastapi "uvicorn[standard]" cryptography
StepsStart Jarvis on the PC.Get the IP address and pairing key from the console or the Dashboard tab.On the phone, open a browser and go to:Plaintexthttp://<PC-IP>:8000/jarvis-app
Example:Plaintext[http://192.168.35.70:8000/jarvis-app](http://192.168.35.70:8000/jarvis-app)
If HTTPS is enabled:Plaintext[https://192.168.35.70:8000/jarvis-app](https://192.168.35.70:8000/jarvis-app)
(If the browser warns about the certificate → Advanced → Proceed.)Enter the PC IP and pairing key, then tap Connect.You can now send commands from the phone.Quick URLsURLPurpose/jarvis-app or /appJarvis App (phone companion)/Main remote dashboard/loginPairing login pageTroubleshootingTest on the PC first: http://127.0.0.1:8000/jarvis-appAllow port 8000 in Windows FirewallDo not use a guest Wi‑Fi network — both devices must be on the same networkADB is optional (for direct Android control). The main method is the Jarvis App reverse link🖥️ UI navigationTabWhat it doesDashboardMain holographic HUDChatConversation historySettingsAll options (full-screen)The Ask anything command bar stays visible at the bottom at all times.📁 Project structurePlaintextMark-LIV-main/
├── main.py                # entry point
├── ui.py                  # user interface
├── setup.py               # dependency installer
├── requirements.txt
├── actions/               # built-in tools
├── plugins/               # drop-in plugins
├── core/                  # avatar, audio, LLM…
├── dashboard/             # remote server + Jarvis App
│   └── static/jarvis_app.html
├── memory/                # config + long-term memory
└── config/                # API keys, certificates
📜 LicenseThis project is licensed under the MIT License.
