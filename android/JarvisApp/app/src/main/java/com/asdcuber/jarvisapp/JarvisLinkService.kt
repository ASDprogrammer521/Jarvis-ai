package com.asdcuber.jarvisapp

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Intent
import android.content.IntentFilter
import android.os.Build
import android.os.BatteryManager
import android.os.Handler
import android.os.IBinder
import android.os.Looper
import androidx.core.app.NotificationCompat
import org.java_websocket.client.WebSocketClient
import org.java_websocket.handshake.ServerHandshake
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URI
import java.net.URL
import java.util.concurrent.Executors
import android.content.Context
import android.provider.Settings
import android.content.BroadcastReceiver
import android.telephony.TelephonyManager

class JarvisLinkService : Service() {

    companion object {
        const val CHANNEL_ID = "jarvis_link"
        const val NOTIF_ID = 1
        const val EXTRA_HOST = "host"
        const val EXTRA_KEY = "key"
        @Volatile var connected: Boolean = false
        @Volatile var lastLog: String = ""
        @Volatile var statusLine: String = "Offline"
        @Volatile private var activeClient: WebSocketClient? = null

        fun sendCommand(text: String): Boolean {
            val c = activeClient ?: return false
            if (!connected) return false
            return try {
                c.send(JSONObject(mapOf("type" to "command", "text" to text)).toString())
                true
            } catch (_: Exception) {
                false
            }
        }

        fun sendRaw(json: String): Boolean {
            val c = activeClient ?: return false
            if (!connected) return false
            return try {
                c.send(json)
                true
            } catch (_: Exception) {
                false
            }
        }

        fun sendPhoneNotification(packageName: String, sender: String, text: String, timestamp: Long): Boolean {
            val payload = JSONObject()
                .put("type", "phone_notification")
                .put("package", packageName)
                .put("sender", sender.take(120))
                .put("text", text.take(2500))
                .put("timestamp", timestamp)
            return sendRaw(payload.toString())
        }
    }

    private var client: WebSocketClient? = null
    private val mainHandler = Handler(Looper.getMainLooper())
    private val io = Executors.newSingleThreadExecutor()
    private var hostRaw: String = ""
    private var keyRaw: String = ""
    private var reconnectAttempts = 0
    private val maxReconnect = 50
    private val phoneStatusTicker = object : Runnable {
        override fun run() {
            if (!connected) return
            sendPhoneStatus()
            mainHandler.postDelayed(this, 5 * 60 * 1000L)
        }
    }

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onCreate() {
        super.onCreate()
        ensureChannel()
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        val host = intent?.getStringExtra(EXTRA_HOST) ?: return START_NOT_STICKY
        val key = intent?.getStringExtra(EXTRA_KEY) ?: return START_NOT_STICKY
        hostRaw = host
        keyRaw = key

        startForeground(NOTIF_ID, buildNotification("Connecting…", connected = false))
        registerCallEvents()
        statusLine = "Connecting…"
        lastLog = "Connecting to $host"
        io.execute { connectPipeline(host, key) }
        return START_STICKY
    }

    private fun sendPhoneStatus() {
        if (!connected) return
        val battery = try { registerReceiver(null, IntentFilter(Intent.ACTION_BATTERY_CHANGED)) } catch (_: Exception) { null }
        val level = battery?.getIntExtra(BatteryManager.EXTRA_LEVEL, -1) ?: -1
        val scale = battery?.getIntExtra(BatteryManager.EXTRA_SCALE, -1) ?: -1
        val percent = if (level >= 0 && scale > 0) (level * 100 / scale).coerceIn(0, 100) else -1
        val batteryState = battery?.getIntExtra(BatteryManager.EXTRA_STATUS, -1) ?: -1
        val charging = batteryState == BatteryManager.BATTERY_STATUS_CHARGING || batteryState == BatteryManager.BATTERY_STATUS_FULL
        val configured = try { Settings.Global.getString(contentResolver, Settings.Global.DEVICE_NAME)?.trim().orEmpty() } catch (_: Exception) { "" }
        val fallback = listOf(Build.MANUFACTURER, Build.MODEL).map { it.trim() }.filter { it.isNotBlank() }.distinct().joinToString(" ")
        val deviceName = configured.ifBlank { fallback.ifBlank { "Android phone" } }.take(80)
        val payload = JSONObject()
            .put("type", "phone_status")
            .put("device_name", deviceName)
            .put("battery_percent", percent)
            .put("charging", charging)
        sendRaw(payload.toString())
    }


    // ── Call events → PC ("kim qo'ng'iroq qilyapti") ────────────────────────
    private var callReceiver: BroadcastReceiver? = null
    private var ringing = false
    private var answered = false
    private var ringNumber = ""
    private var ringAnnounced = false
    private var pendingRing: Runnable? = null

    private fun sendPhoneEvent(event: String, number: String) {
        if (!connected) return
        val name = Contacts.nameFor(applicationContext, number).orEmpty()
        sendRaw(
            JSONObject().put("type", "phone_event").put("event", event)
                .put("number", number).put("name", name).toString()
        )
    }

    private fun announceRing() {
        if (ringAnnounced) return
        ringAnnounced = true
        pendingRing?.let { mainHandler.removeCallbacks(it) }
        sendPhoneEvent("incoming_call", ringNumber)
    }

    private fun onCallState(state: String, number: String) {
        when (state) {
            TelephonyManager.EXTRA_STATE_RINGING -> {
                if (!ringing) { ringing = true; answered = false; ringAnnounced = false; ringNumber = "" }
                if (number.isNotBlank()) { ringNumber = number; announceRing() }
                else if (!ringAnnounced && pendingRing == null) {
                    // Android 9+ sends the number in a second broadcast; wait briefly for it.
                    val r = Runnable { pendingRing = null; announceRing() }
                    pendingRing = r
                    mainHandler.postDelayed(r, 900)
                }
            }
            TelephonyManager.EXTRA_STATE_OFFHOOK -> {
                if (ringing) answered = true
                sendPhoneEvent("call_active", ringNumber)
            }
            TelephonyManager.EXTRA_STATE_IDLE -> {
                pendingRing?.let { mainHandler.removeCallbacks(it) }
                pendingRing = null
                if (ringing && !answered) sendPhoneEvent("missed_call", ringNumber)
                else sendPhoneEvent("call_ended", ringNumber)
                ringing = false; answered = false; ringAnnounced = false; ringNumber = ""
            }
        }
    }

    private fun registerCallEvents() {
        if (callReceiver != null) return
        val r = object : BroadcastReceiver() {
            override fun onReceive(context: Context, intent: Intent) {
                val state = intent.getStringExtra(TelephonyManager.EXTRA_STATE) ?: return
                val number = intent.getStringExtra(TelephonyManager.EXTRA_INCOMING_NUMBER).orEmpty()
                onCallState(state, number)
            }
        }
        try {
            registerReceiver(r, IntentFilter(TelephonyManager.ACTION_PHONE_STATE_CHANGED))
            callReceiver = r
        } catch (_: Exception) {}
    }


    private fun connectPipeline(hostRaw: String, key: String) {
        try {
            var host = hostRaw.removePrefix("http://").removePrefix("https://").trimEnd('/')
            if (!host.contains(":")) host = "$host:8000"
            val bare = host.substringBefore(":")

            var token = key.trim().uppercase()

            val prefs = getSharedPreferences("jarvis_link", Context.MODE_PRIVATE)
            val saved = prefs.getString("session_token", null)
            if (!saved.isNullOrBlank() && reconnectAttempts > 0) {
                token = saved
                lastLog = "Reconnecting with saved session…"
            }

            // HTTPS first (pinned certificate). Plain HTTP only if this PC has never offered a certificate.
            var useTls = true
            var loginDone = false
            val schemes = if (LinkTls.pinned(this, bare).isNotEmpty()) listOf(true) else listOf(true, false)
            for (tls in schemes) {
                try {
                    val base = (if (tls) "https://" else "http://") + host
                    val conn = LinkTls.open(this, "$base/login").apply {
                        requestMethod = "POST"
                        setRequestProperty("Content-Type", "application/json")
                        doOutput = true
                        connectTimeout = 8000
                        readTimeout = 8000
                    }
                    conn.outputStream.use { os ->
                        os.write("""{"key":"$token"}""".toByteArray(Charsets.UTF_8))
                    }
                    val code = conn.responseCode
                    val body = try {
                        (if (code in 200..299) conn.inputStream else conn.errorStream)
                            ?.bufferedReader()?.readText().orEmpty()
                    } catch (_: Exception) { "" }
                    useTls = tls
                    LinkTls.saveBase(this, base)
                    if (code in 200..299 && body.contains("token")) {
                        val t = JSONObject(body).optString("token", "")
                        if (t.isNotBlank()) {
                            token = t
                            prefs.edit().putString("session_token", t).putString("host", host).apply()
                            lastLog = (if (tls) "Secure login OK" else "Login OK (plain HTTP)") + " — opening socket…"
                            statusLine = "Login OK…"
                            updateNotification("Login OK…", false)
                        }
                    } else {
                        lastLog = "Login $code — trying pairing key on socket…"
                    }
                    loginDone = true
                    break
                } catch (e: Exception) {
                    if (LinkTls.isPinFailure(e)) {
                        connected = false
                        statusLine = "Disconnected"
                        lastLog = "⚠ " + LinkTls.pinMessage(e)
                        updateNotification("Certificate rejected", false)
                        reconnectAttempts = maxReconnect   // never retry (or downgrade) after a pin failure
                        return
                    }
                    lastLog = "Login skip (${if (tls) "https" else "http"}): ${e.message}"
                }
            }
            if (!loginDone) {
                // Nothing answered. Fall back to the scheme we used last time, or HTTPS.
                useTls = !LinkTls.base(this).startsWith("http://")
            }
            if (LinkTls.lastNote.isNotEmpty()) { lastLog = LinkTls.lastNote; LinkTls.lastNote = "" }

            val uri = URI("${if (useTls) "wss" else "ws"}://$host/ws?token=${java.net.URLEncoder.encode(token, "UTF-8")}")
            mainHandler.post { openSocket(uri, useTls, bare) }
        } catch (e: Exception) {
            connected = false
            statusLine = "Disconnected"
            lastLog = "Connect failed: ${e.message}"
            updateNotification("Disconnected", false)
        }
    }

    private fun openSocket(uri: URI, tls: Boolean, bareHost: String) {
        client?.close()
        lastLog = "WS ${uri.host}…"
        client = object : WebSocketClient(uri) {
            override fun onOpen(handshakedata: ServerHandshake?) {
                activeClient = this
                connected = true
                reconnectAttempts = 0
                statusLine = "Connected"
                lastLog = "Connected ✓"
                try {
                    send(JSONObject(mapOf("type" to "hello", "client" to "jarvis_android")).toString())
                } catch (_: Exception) {}
                sendPhoneStatus()
                mainHandler.removeCallbacks(phoneStatusTicker)
                mainHandler.postDelayed(phoneStatusTicker, 5 * 60 * 1000L)

                updateNotification("Jarvis Connected", true)
            }

            override fun onMessage(message: String?) {
                if (message.isNullOrBlank()) return
                try {
                    val obj = JSONObject(message)
                    if (obj.optString("type") == "phone_cmd") {
                        mainHandler.post {
                            val result = CommandExecutor.handle(applicationContext, obj)
                            lastLog = result
                            try {
                                send(
                                    JSONObject(
                                        mapOf(
                                            "type" to "command",
                                            "text" to "[phone_result] $result"
                                        )
                                    ).toString()
                                )
                            } catch (_: Exception) {}
                        }
                    } else if (obj.optString("type") == "sys") {
                        lastLog = obj.optString("text", message)
                    }
                } catch (_: Exception) {
                    lastLog = message.take(120)
                }
            }

            override fun onClose(code: Int, reason: String?, remote: Boolean) {
                mainHandler.removeCallbacks(phoneStatusTicker)
                activeClient = null
                connected = false
                statusLine = "Disconnected"
                lastLog = "Disconnected ($code) ${reason ?: ""}"
                updateNotification("Disconnected", false)

                if (hostRaw.isNotBlank() && reconnectAttempts < maxReconnect) {
                    reconnectAttempts++
                    val delay = (3000L * reconnectAttempts.coerceAtMost(5))
                    lastLog = "Reconnecting in ${delay/1000}s… ($reconnectAttempts)"
                    statusLine = "Connecting…"
                    updateNotification("Reconnecting…", false)
                    mainHandler.postDelayed({
                        io.execute { connectPipeline(hostRaw, keyRaw) }
                    }, delay)
                }
            }

            override fun onError(ex: Exception?) {
                mainHandler.removeCallbacks(phoneStatusTicker)
                connected = false
                statusLine = "Disconnected"
                lastLog = "Error: ${ex?.message}"
                updateNotification("Disconnected", false)
            }
        }
        client?.connectionLostTimeout = 30
        if (tls) {
            try { client?.setSocketFactory(LinkTls.sslContext(this, bareHost).socketFactory) } catch (_: Exception) {}
        }
        client?.connect()
    }

    override fun onDestroy() {
        mainHandler.removeCallbacks(phoneStatusTicker)
        callReceiver?.let { try { unregisterReceiver(it) } catch (_: Exception) {} }
        callReceiver = null
        client?.close()
        activeClient = null
        connected = false
        statusLine = "Offline"
        try {
            val nm = getSystemService(NotificationManager::class.java)
            nm.cancel(NOTIF_ID)
        } catch (_: Exception) {}
        super.onDestroy()
    }

    private fun ensureChannel() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            val nm = getSystemService(NotificationManager::class.java)

            val ch = NotificationChannel(
                CHANNEL_ID,
                "Jarvis Link",
                NotificationManager.IMPORTANCE_LOW
            )
            ch.description = "Shows while Jarvis is connected to your PC"
            ch.setShowBadge(false)
            nm.createNotificationChannel(ch)
        }
    }

    private fun buildNotification(text: String, connected: Boolean): Notification {
        val open = PendingIntent.getActivity(
            this, 0,
            Intent(this, MainActivity::class.java),
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
        )
        val title = if (connected) "Jarvis Connected" else "Jarvis"
        return NotificationCompat.Builder(this, CHANNEL_ID)
            .setContentTitle(title)
            .setContentText(text)
            .setSmallIcon(android.R.drawable.ic_menu_mylocation)
            .setContentIntent(open)
            .setOngoing(connected)
            .setOnlyAlertOnce(true)
            .setPriority(
                if (connected) NotificationCompat.PRIORITY_LOW
                else NotificationCompat.PRIORITY_DEFAULT
            )
            .setCategory(NotificationCompat.CATEGORY_SERVICE)
            .build()
    }

    private fun updateNotification(text: String, connected: Boolean) {
        val nm = getSystemService(NotificationManager::class.java)
        nm.notify(NOTIF_ID, buildNotification(text, connected))
    }
}

//by ASDcuber
