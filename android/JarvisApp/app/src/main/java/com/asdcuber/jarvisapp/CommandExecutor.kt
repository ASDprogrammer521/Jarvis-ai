package com.asdcuber.jarvisapp

import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.admin.DevicePolicyManager
import android.content.ComponentName
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.media.AudioManager
import android.net.Uri
import android.os.BatteryManager
import android.os.Build
import android.provider.Settings
import android.widget.Toast
import androidx.core.app.NotificationCompat
import org.json.JSONObject

object CommandExecutor {

    private const val CMD_CHANNEL = "jarvis_commands"

    fun handle(context: Context, msg: JSONObject): String {
        val action = msg.optString("action", "").lowercase()
        val value = msg.optString("value", msg.optString("text", msg.optString("url", "")))

        return when (action) {
            "notify", "message", "alert", "say" -> {
                val t = value.ifBlank { "Jarvis" }
                Toast.makeText(context, t, Toast.LENGTH_LONG).show()
                postNotice(context, "Jarvis", t, null)
                "Shown: $t"
            }
            "open_url" -> {
                val url = value.ifBlank { return "No URL" }
                val fixed = if (url.startsWith("http")) url else "http://$url"
                val intent = Intent(Intent.ACTION_VIEW, Uri.parse(fixed))
                    .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
                launchFromBackground(context, intent, "Open link")
            }
            "open_app", "app" -> openApp(context, value)
            "home" -> {
                val intent = Intent(Intent.ACTION_MAIN)
                    .addCategory(Intent.CATEGORY_HOME)
                    .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
                launchFromBackground(context, intent, "Home")
            }
            "back" -> "Back requires accessibility service."
            "lock" -> lockScreen(context)
            "unlock" -> "Unlock must be done on the device (security restriction)."
            "volume", "volume_up" -> {
                val am = context.getSystemService(Context.AUDIO_SERVICE) as AudioManager
                am.adjustStreamVolume(AudioManager.STREAM_MUSIC, AudioManager.ADJUST_RAISE, AudioManager.FLAG_SHOW_UI)
                "Volume up"
            }
            "volume_down" -> {
                val am = context.getSystemService(Context.AUDIO_SERVICE) as AudioManager
                am.adjustStreamVolume(AudioManager.STREAM_MUSIC, AudioManager.ADJUST_LOWER, AudioManager.FLAG_SHOW_UI)
                "Volume down"
            }
            "battery" -> {
                val bm = context.getSystemService(Context.BATTERY_SERVICE) as BatteryManager
                val level = bm.getIntProperty(BatteryManager.BATTERY_PROPERTY_CAPACITY)
                "Battery $level%"
            }
            "status" -> {
                "Jarvis App online · ${Build.MODEL} · Android ${Build.VERSION.RELEASE}"
            }
            "settings" -> {
                val intent = Intent(Settings.ACTION_SETTINGS).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
                launchFromBackground(context, intent, "Settings")
            }
            "screenshot" -> {
                "Screenshot needs on-screen MediaProjection consent."
            }
            else -> "Unknown action: $action"
        }
    }

    /**
     * Android 10+ blocks startActivity from background.
     * Try direct start first; on failure post a high-priority notification
     * with full-screen intent so the user (or system) opens the target.
     */
    private fun launchFromBackground(context: Context, intent: Intent, label: String): String {
        intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP)
        return try {
            context.startActivity(intent)
            "Opened $label"
        } catch (e: Exception) {
            postNotice(context, "Jarvis", "Tap to open $label", intent)
            "Queued $label (app was in background — check notification)"
        }
    }

    private fun postNotice(context: Context, title: String, body: String, launch: Intent?) {
        val nm = context.getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            nm.createNotificationChannel(
                NotificationChannel(CMD_CHANNEL, "Jarvis Commands", NotificationManager.IMPORTANCE_HIGH)
            )
        }
        val pi = if (launch != null) {
            PendingIntent.getActivity(
                context, (System.currentTimeMillis() % 100000).toInt(),
                launch,
                PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
            )
        } else null
        val b = NotificationCompat.Builder(context, CMD_CHANNEL)
            .setContentTitle(title)
            .setContentText(body)
            .setSmallIcon(android.R.drawable.ic_menu_mylocation)
            .setPriority(NotificationCompat.PRIORITY_HIGH)
            .setAutoCancel(true)
        if (pi != null) {
            b.setContentIntent(pi)
            b.setFullScreenIntent(pi, true)
        }
        nm.notify((System.currentTimeMillis() % 10000).toInt(), b.build())
    }

    private fun openApp(context: Context, name: String): String {
        if (name.isBlank()) return "No app name"
        val pm = context.packageManager
        val aliases = mapOf(
            "youtube" to "com.google.android.youtube",
            "chrome" to "com.android.chrome",
            "maps" to "com.google.android.apps.maps",
            "whatsapp" to "com.whatsapp",
            "telegram" to "org.telegram.messenger",
            "instagram" to "com.instagram.android",
            "spotify" to "com.spotify.music",
            "settings" to "com.android.settings",
        )
        val lower = name.lowercase().trim()
        val pkgHint = aliases[lower]

        fun tryPkg(pkg: String): Intent? = pm.getLaunchIntentForPackage(pkg)

        if (pkgHint != null) {
            val launch = tryPkg(pkgHint)
            if (launch != null) {
                return launchFromBackground(context, launch, name)
            }
            if (lower == "youtube") {
                val web = Intent(Intent.ACTION_VIEW, Uri.parse("https://youtube.com"))
                    .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
                return launchFromBackground(context, web, "YouTube")
            }
        }
        if (name.contains(".")) {
            val launch = tryPkg(name)
            if (launch != null) {
                return launchFromBackground(context, launch, name)
            }
        }
        val intent = Intent(Intent.ACTION_MAIN).addCategory(Intent.CATEGORY_LAUNCHER)
        val apps = pm.queryIntentActivities(intent, PackageManager.MATCH_ALL)
        val match = apps.firstOrNull {
            val label = it.loadLabel(pm).toString()
            label.equals(name, true) || label.contains(name, true) ||
                it.activityInfo.packageName.contains(name.replace(" ", "").lowercase())
        }
        return if (match != null) {
            val launch = pm.getLaunchIntentForPackage(match.activityInfo.packageName)
            if (launch != null) launchFromBackground(context, launch, match.loadLabel(pm).toString())
            else "Cannot launch ${match.activityInfo.packageName}"
        } else {
            val q = Uri.parse("market://search?q=${Uri.encode(name)}")
            try {
                launchFromBackground(
                    context,
                    Intent(Intent.ACTION_VIEW, q).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK),
                    "Play Store: $name"
                )
            } catch (e: Exception) {
                "App not found: $name"
            }
        }
    }

    private fun lockScreen(context: Context): String {
        val dpm = context.getSystemService(Context.DEVICE_POLICY_SERVICE) as DevicePolicyManager
        val admin = ComponentName(context, JarvisDeviceAdmin::class.java)
        return if (dpm.isAdminActive(admin)) {
            dpm.lockNow()
            "Locked"
        } else {
            "Lock permission not enabled. Open Jarvis App → Enable lock permission."
        }
    }
}
