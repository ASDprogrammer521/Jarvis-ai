package com.asdcuber.jarvisapp

import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.admin.DevicePolicyManager
import android.content.ComponentName
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.location.LocationManager
import android.media.AudioManager
import android.net.Uri
import android.os.BatteryManager
import android.os.Build
import android.os.Environment
import android.provider.Settings
import android.telephony.SmsManager
import android.util.Base64
import android.widget.Toast
import androidx.core.app.NotificationCompat
import org.json.JSONObject
import java.io.File
import java.io.FileOutputStream

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
                launchFromBackground(
                    context,
                    Intent(Intent.ACTION_VIEW, Uri.parse(fixed)).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK),
                    "Open link"
                )
            }
            "open_app", "app" -> openApp(context, value)
            "home" -> launchFromBackground(
                context,
                Intent(Intent.ACTION_MAIN).addCategory(Intent.CATEGORY_HOME)
                    .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK),
                "Home"
            )
            "lock" -> lockScreen(context)
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
                "Battery ${bm.getIntProperty(BatteryManager.BATTERY_PROPERTY_CAPACITY)}%"
            }
            "status" -> "Jarvis App online · ${Build.MODEL} · Android ${Build.VERSION.RELEASE}"
            "settings" -> launchFromBackground(
                context,
                Intent(Settings.ACTION_SETTINGS).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK),
                "Settings"
            )
            "notifications", "read_notifications" -> JarvisNotificationListener.snapshot()
            "location", "where" -> readLocation(context)
            "call" -> {
                val num = value.filter { it.isDigit() || it == '+' }
                if (num.isBlank()) return "No number"
                val i = Intent(Intent.ACTION_DIAL, Uri.parse("tel:$num")).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
                launchFromBackground(context, i, "Dial $num")
            }
            "sms" -> {
                // value format: number|message
                val parts = value.split("|", limit = 2)
                if (parts.size < 2) return "Use: number|message"
                val i = Intent(Intent.ACTION_SENDTO, Uri.parse("smsto:${parts[0].trim()}"))
                    .putExtra("sms_body", parts[1].trim())
                    .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
                launchFromBackground(context, i, "SMS")
            }
            "save_file", "receive_file" -> saveFileFromPc(context, msg)
            "screenshot" -> "Screenshot needs MediaProjection consent."
            else -> "Unknown action: $action"
        }
    }

    private fun saveFileFromPc(context: Context, msg: JSONObject): String {
        val name = msg.optString("filename", "jarvis_file.bin").replace("..", "")
        val b64 = msg.optString("data", "")
        if (b64.isBlank()) return "No file data"
        return try {
            val bytes = Base64.decode(b64, Base64.DEFAULT)
            val dir = context.getExternalFilesDir(Environment.DIRECTORY_DOWNLOADS)
                ?: context.filesDir
            val out = File(dir, name)
            FileOutputStream(out).use { it.write(bytes) }
            postNotice(context, "File received", name, null)
            "Saved ${out.absolutePath}"
        } catch (e: Exception) {
            "Save failed: ${e.message}"
        }
    }

    private fun readLocation(context: Context): String {
        return try {
            val lm = context.getSystemService(Context.LOCATION_SERVICE) as LocationManager
            val providers = listOf(LocationManager.GPS_PROVIDER, LocationManager.NETWORK_PROVIDER)
            for (p in providers) {
                if (!lm.isProviderEnabled(p)) continue
                @Suppress("MissingPermission")
                val loc = lm.getLastKnownLocation(p) ?: continue
                return "Lat ${loc.latitude}, Lon ${loc.longitude} (±${loc.accuracy}m)"
            }
            "Location unavailable. Enable GPS and grant location permission."
        } catch (e: Exception) {
            "Location error: ${e.message}"
        }
    }

    private fun launchFromBackground(context: Context, intent: Intent, label: String): String {
        intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP)
        return try {
            context.startActivity(intent)
            "Opened $label"
        } catch (e: Exception) {
            postNotice(context, "Jarvis", "Tap to open $label", intent)
            "Queued $label (background)"
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
        if (pkgHint != null) {
            val launch = pm.getLaunchIntentForPackage(pkgHint)
            if (launch != null) return launchFromBackground(context, launch, name)
            if (lower == "youtube") {
                return launchFromBackground(
                    context,
                    Intent(Intent.ACTION_VIEW, Uri.parse("https://youtube.com"))
                        .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK),
                    "YouTube"
                )
            }
        }
        if (name.contains(".")) {
            val launch = pm.getLaunchIntentForPackage(name)
            if (launch != null) return launchFromBackground(context, launch, name)
        }
        val intent = Intent(Intent.ACTION_MAIN).addCategory(Intent.CATEGORY_LAUNCHER)
        val apps = pm.queryIntentActivities(intent, PackageManager.MATCH_ALL)
        val match = apps.firstOrNull {
            val label = it.loadLabel(pm).toString()
            label.equals(name, true) || label.contains(name, true)
        }
        return if (match != null) {
            val launch = pm.getLaunchIntentForPackage(match.activityInfo.packageName)
            if (launch != null) launchFromBackground(context, launch, match.loadLabel(pm).toString())
            else "Cannot launch"
        } else "App not found: $name"
    }

    private fun lockScreen(context: Context): String {
        val dpm = context.getSystemService(Context.DEVICE_POLICY_SERVICE) as DevicePolicyManager
        val admin = ComponentName(context, JarvisDeviceAdmin::class.java)
        return if (dpm.isAdminActive(admin)) {
            dpm.lockNow(); "Locked"
        } else "Enable lock permission in Jarvis App first."
    }
}
