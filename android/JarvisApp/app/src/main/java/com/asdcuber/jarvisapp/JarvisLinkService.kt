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
        startForeground(1, buildNotification("Connecting…"))
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

            // 1) Prefer HTTP login → token (same as web app)
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
                    }
                } else {
                    lastLog = "Login $code — trying pairing key on socket…"
                }
            } catch (e: Exception) {
                lastLog = "Login skip: ${e.message}"
            }

            // 2) WebSocket
            val uri = URI("ws://$host/ws?token=${java.net.URLEncoder.encode(token, "UTF-8")}")
            mainHandler.post { openSocket(uri) }
        } catch (e: Exception) {
            connected = false
            statusLine = "Error"
            lastLog = "Connect failed: ${e.message}"
            updateNotification("Error")
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
                updateNotification("Connected")
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
                updateNotification("Offline")
            }

            override fun onError(ex: Exception?) {
                connected = false
                statusLine = "Error"
                lastLog = "Error: ${ex?.message}"
                updateNotification("Error")
            }
        }
        client?.connectionLostTimeout = 30
        client?.connect()
    }

    override fun onDestroy() {
        client?.close()
        connected = false
        statusLine = "Offline"
        super.onDestroy()
    }

    private fun ensureChannel() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            val nm = getSystemService(NotificationManager::class.java)
            nm.createNotificationChannel(
                NotificationChannel(CHANNEL_ID, "Jarvis Link", NotificationManager.IMPORTANCE_LOW)
            )
        }
    }

    private fun buildNotification(text: String): Notification {
        val open = PendingIntent.getActivity(
            this, 0,
            Intent(this, MainActivity::class.java),
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
        )
        return NotificationCompat.Builder(this, CHANNEL_ID)
            .setContentTitle("Jarvis App")
            .setContentText(text)
            .setSmallIcon(android.R.drawable.ic_menu_mylocation)
            .setContentIntent(open)
            .setOngoing(true)
            .build()
    }

    private fun updateNotification(text: String) {
        val nm = getSystemService(NotificationManager::class.java)
        nm.notify(1, buildNotification(text))
    }
}
