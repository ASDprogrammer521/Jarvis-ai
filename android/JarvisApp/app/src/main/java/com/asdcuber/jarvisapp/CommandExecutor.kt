package com.asdcuber.jarvisapp

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
import org.json.JSONObject

object CommandExecutor {

    fun handle(context: Context, msg: JSONObject): String {
        val action = msg.optString("action", "").lowercase()
        val value = msg.optString("value", msg.optString("text", msg.optString("url", "")))

        return when (action) {
            "notify", "message", "alert", "say" -> {
                Toast.makeText(context, value.ifBlank { "Jarvis" }, Toast.LENGTH_LONG).show()
                "Shown: $value"
            }
            "open_url" -> {
                val url = value.ifBlank { return "No URL" }
                val fixed = if (url.startsWith("http")) url else "http://$url"
                context.startActivity(
                    Intent(Intent.ACTION_VIEW, Uri.parse(fixed)).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
                )
                "Opened URL"
            }
            "open_app", "app" -> openApp(context, value)
            "home" -> {
                context.startActivity(
                    Intent(Intent.ACTION_MAIN)
                        .addCategory(Intent.CATEGORY_HOME)
                        .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
                )
                "Home"
            }
            "back" -> {
                // Best-effort: open recents is not back; true back needs accessibility.
                "Back requires accessibility service; use Home instead from app."
            }
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
                context.startActivity(
                    Intent(Settings.ACTION_SETTINGS).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
                )
                "Opened settings"
            }
            "screenshot" -> {
                "Screenshot from the app needs MediaProjection user consent each time; use phone's built-in screenshot for now."
            }
            else -> "Unknown action: $action"
        }
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
        if (pkgHint != null) {
            val launch = pm.getLaunchIntentForPackage(pkgHint)
            if (launch != null) {
                launch.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
                context.startActivity(launch)
                return "Opened $name"
            }
            // fallback URL for youtube
            if (lower == "youtube") {
                context.startActivity(
                    Intent(Intent.ACTION_VIEW, Uri.parse("https://youtube.com"))
                        .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
                )
                return "Opened YouTube in browser"
            }
        }
        // Package id?
        if (name.contains(".")) {
            val launch = pm.getLaunchIntentForPackage(name)
            if (launch != null) {
                launch.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
                context.startActivity(launch)
                return "Opened $name"
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
            if (launch != null) {
                launch.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
                context.startActivity(launch)
                "Opened ${match.loadLabel(pm)}"
            } else "Cannot launch ${match.activityInfo.packageName}"
        } else {
            // Play Store search
            val q = Uri.parse("market://search?q=${Uri.encode(name)}")
            try {
                context.startActivity(Intent(Intent.ACTION_VIEW, q).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
                "App not installed — opened Play Store for $name"
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
