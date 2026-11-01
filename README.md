# Jarvis AI

Jarvis AI is a desktop voice assistant powered by Gemini. It helps with computer tasks, files, applications, browser workflows, and conversations.

## Features

- Voice interaction and wake-word support
- Desktop, application, file, and browser actions
- Gemini-powered conversations and memory
- Phone companion through the Jarvis App web page
- Window management, keyboard shortcuts, and system controls
- Emoji-styled terminal messages

The phone companion currently supports connection status, on-screen notifications, and opening HTTP(S) URLs. Sensitive dashboard API endpoints continue to require authentication.

## Requirements

- Python 3.11 or newer is recommended
- A Gemini API key

## Installation

Create a virtual environment and install dependencies:

```bash
python -m venv .venv
python -m pip install -r requirements.txt
```

Configure the Gemini API key in `config/api_keys.json`:

```json
{
  "gemini_api_key": "YOUR_API_KEY"
}
```

Start Jarvis:

```bash
python main.py
```

## Open the dashboard on a phone

1. Start Jarvis on the computer.
2. Connect the phone and computer to the same trusted Wi-Fi network.
3. Read the LAN address printed by Jarvis in the desktop terminal. The default dashboard port is `8000`.
4. On the phone, open `http://<COMPUTER-LAN-IP>:8000/jarvis-app`.
5. Follow the page instructions and pair using the connection key shown by Jarvis.

If the phone cannot connect, allow inbound TCP port `8000` for the computer's private network in the operating-system firewall. If the detected address is for another network adapter, set `JARVIS_BIND_HOST` to the computer's Wi-Fi IPv4 address before starting Jarvis. By default, Jarvis binds to the detected LAN address rather than every network interface; sensitive API endpoints retain token authentication. LAN HTTP is unencrypted, so use a trusted network only.

## Security notes

- Do not commit API keys, pairing keys, or other secrets to a public repository.
- Pair phones only on trusted networks; do not expose the service to an untrusted public network.
- Install plugins only from sources you trust; plugins may execute code on the computer running Jarvis.

## Tests

```bash
python -m unittest discover -s tests
```

## Project structure

- `actions/` — assistant actions and tools
- `core/` — shared utilities and runtime components
- `dashboard/` — local server and web interface
- `dashboard/static/jarvis_app.html` — phone companion page
- `android/` — Android application source
- `tests/` — automated tests




## Phone integration

The existing native Android app in `android/JarvisApp` connects to the Jarvis desktop over the authenticated local WebSocket. When Android Notification Access is enabled, it relays previews from supported SMS, WhatsApp, and Telegram notifications to the desktop **Phone** section. It also reports the phone display name, battery level, and charging state while connected.

### Build and connect

1. Open `android/JarvisApp` in Android Studio and sync the included Gradle project.
2. Start Jarvis on the PC and create a fresh pairing key from Remote Control.
3. Enter the PC address and pairing key in the existing Jarvis App, then connect on the same trusted private Wi-Fi network.
4. In the Jarvis App, open the Notifications control and enable Jarvis Notification Access in Android settings.
5. On the PC, select **Phone** in the Jarvis sidebar to view supported message previews and phone status.

The project has one Android app: `android/JarvisApp`. Notification Access is a broad Android permission, but only the supported messaging app packages are relayed automatically. The app does not read SMS storage or send replies. Previews are kept in the desktop UI's memory, not written to server history or disk. Default HTTP/WebSocket traffic is unencrypted; use trusted private Wi-Fi and do not expose Jarvis publicly.
