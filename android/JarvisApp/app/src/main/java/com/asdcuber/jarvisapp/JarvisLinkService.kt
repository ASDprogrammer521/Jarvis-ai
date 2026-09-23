package com.asdcuber.jarvisapp

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Intent
import android.os.Build
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

class JarvisLinkService : Service() {

    companion object {
        const val CHANNEL_ID = "jarvis_link"
        const val NOTIF_ID = 1
        const val EXTRA_HOST = "host"
        const val EXTRA_KEY = "key"
        @Volatile var connected: Boolean = false
        @Volatile var lastLog: String = ""
        @Volatile var statusLine: String = "Offline"
    }

    private var client: WebSocketClient? = null
    private val mainHandler = Handler(Looper.getMainLooper())
    private val io = Executors.newSingleThreadExecutor()
    private var hostRaw: String = ""
    private var keyRaw: String = ""

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
        // Persistent notification — keeps service alive in background
        startForeground(NOTIF_ID, buildNotification("Connecting…", connected = false))
        statusLine = "Connecting…"
        lastLog = "Connecting to $host"
        io.execute { connectPipeline(host, key) }
        return START_STICKY
    }

    private fun connectPipeline(hostRaw: String, key: String) {
        try {
            var host = hostRaw.removePrefix("http://").removePrefix("https://").trimEnd('/')
            if (!host.contains(":")) host = "$host:8000"
            val base = "http://$host"

            var token = key.trim().uppercase()
            try {
                val url = URL("$base/login")
                val conn = (url.openConnection() as HttpURLConnection).apply {
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
                if (code in 200..299 && body.contains("token")) {
                    val t = JSONObject(body).optString("token", "")
                    if (t.isNotBlank()) {
                        token = t
                        lastLog = "Login OK — opening socket…"
                        statusLine = "Login OK…"
                        updateNotification("Login OK…", false)
                    }
                } else {
                    lastLog = "Login $code — trying pairing key on socket…"
                }
            } catch (e: Exception) {
                lastLog = "Login skip: ${e.message}"
            }

            val uri = URI("ws://$host/ws?token=${java.net.URLEncoder.encode(token, "UTF-8")}")
            mainHandler.post { openSocket(uri) }
        } catch (e: Exception) {
            connected = false
            statusLine = "Disconnected"
            lastLog = "Connect failed: ${e.message}"
            updateNotification("Disconnected", false)
        }
    }

    private fun openSocket(uri: URI) {
        client?.close()
        lastLog = "WS ${uri.host}…"
        client = object : WebSocketClient(uri) {
            override fun onOpen(handshakedata: ServerHandshake?) {
                connected = true
                statusLine = "Connected"
                lastLog = "Connected ✓"
                try {
                    send(JSONObject(mapOf("type" to "hello", "client" to "jarvis_android")).toString())
                } catch (_: Exception) {}
                // Persistent: Jarvis Connected — stays in notification shade
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
                connected = false
                statusLine = "Disconnected"
                lastLog = "Disconnected ($code) ${reason ?: ""}"
                updateNotification("Disconnected", false)
            }

            override fun onError(ex: Exception?) {
                connected = false
                statusLine = "Disconnected"
                lastLog = "Error: ${ex?.message}"
                updateNotification("Disconnected", false)
            }
        }
        client?.connectionLostTimeout = 30
        client?.connect()
    }

    override fun onDestroy() {
        client?.close()
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
            // LOW importance = ongoing, less noisy, but always visible
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
            .setOngoing(connected)           // cannot swipe away while linked
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
