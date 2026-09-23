package com.asdcuber.jarvisapp

import android.service.notification.NotificationListenerService
import android.service.notification.StatusBarNotification
import org.json.JSONObject

class JarvisNotificationListener : NotificationListenerService() {

    companion object {
        @Volatile var lastNotifications: MutableList<String> = mutableListOf()
        @Volatile var instance: JarvisNotificationListener? = null

        fun snapshot(limit: Int = 15): String {
            val list = lastNotifications.takeLast(limit)
            return if (list.isEmpty()) "No notifications captured yet. Enable Notification access for Jarvis App."
            else list.joinToString("\n")
        }
    }

    override fun onListenerConnected() {
        instance = this
        try {
            activeNotifications?.forEach { capture(it) }
        } catch (_: Exception) {}
    }

    override fun onListenerDisconnected() {
        instance = null
    }

    override fun onNotificationPosted(sbn: StatusBarNotification?) {
        if (sbn == null) return
        capture(sbn)
    }

    private fun capture(sbn: StatusBarNotification) {
        try {
            val extras = sbn.notification?.extras ?: return
            val title = extras.getCharSequence("android.title")?.toString() ?: ""
            val text = extras.getCharSequence("android.text")?.toString() ?: ""
            val pkg = sbn.packageName ?: "?"
            if (title.isBlank() && text.isBlank()) return
            val line = "[$pkg] $title — $text".take(300)
            synchronized(lastNotifications) {
                lastNotifications.add(line)
                if (lastNotifications.size > 40) {
                    lastNotifications = lastNotifications.takeLast(30).toMutableList()
                }
            }
        } catch (_: Exception) {}
    }
}
