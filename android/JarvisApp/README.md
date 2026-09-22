# Jarvis App (Android) — full phone control without ADB

Native Android companion. Connects **out** to your PC Jarvis dashboard (reverse link).

## Features
- Connect with PC IP + pairing key
- Receive commands from Jarvis (no ADB)
- Open apps / URLs
- Home, volume, battery
- Lock screen (after enabling Device Admin in the app)
- Foreground service keeps the link alive

## Build APK (Android Studio)
1. Install [Android Studio](https://developer.android.com/studio)
2. **Open** the folder `android/JarvisApp`
3. Let Gradle sync
4. **Build → Build Bundle(s) / APK(s) → Build APK(s)**
5. Install the APK on your phone

## Use
1. Start Jarvis on PC
2. Get a pairing key (Remote Control / Dashboard)
3. Open **Jarvis App** on phone
4. Enter PC IP (e.g. `192.168.35.70`) and key → **Connect**
5. Optional: **Enable lock permission** for screen lock
6. Keep phone and PC on the same Wi‑Fi

## Talk to Jarvis
- “phone status”
- “open YouTube on my phone”
- “lock my phone”
- “volume up on phone”
- “send a message to my phone: hello”

By ASDcuber
