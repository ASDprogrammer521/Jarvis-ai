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
import java.net.URI

class JarvisLinkService : Service() {

    companion object {
        const val CHANNEL_ID = "jarvis_link"
        const val EXTRA_HOST = "host"
        const val EXTRA_KEY = "key"
        @Volatile var connected: Boolean = false
        @Volatile var lastLog: String = ""
    }

    private var client: WebSocketClient? = null
    private val mainHandler = Handler(Looper.getMainLooper())

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onCreate() {
        super.onCreate()
        ensureChannel()
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        val host = intent?.getStringExtra(EXTRA_HOST) ?: return START_NOT_STICKY
        val key = intent?.getStringExtra(EXTRA_KEY) ?: return START_NOT_STICKY
        startForeground(1, buildNotification("Connecting…"))
        connect(host, key)
        return START_STICKY
    }

    private fun connect(hostRaw: String, key: String) {
        client?.close()
        var host = hostRaw.removePrefix("http://").removePrefix("https://").trimEnd('/')
        if (!host.contains(":")) host = "$host:8000"
        val uri = URI("ws://$host/ws?token=${key.trim().uppercase()}")
        lastLog = "Connecting $uri"
        client = object : WebSocketClient(uri) {
            override fun onOpen(handshakedata: ServerHandshake?) {
                connected = true
                lastLog = "Connected"
                send(JSONObject(mapOf("type" to "hello", "client" to "jarvis_android")).toString())
                updateNotification("Online")
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
                    } else {
                        lastLog = message
                    }
                } catch (_: Exception) {
                    lastLog = message
                }
            }

            override fun onClose(code: Int, reason: String?, remote: Boolean) {
                connected = false
                lastLog = "Disconnected ($code)"
                updateNotification("Offline")
            }

            override fun onError(ex: Exception?) {
                connected = false
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
