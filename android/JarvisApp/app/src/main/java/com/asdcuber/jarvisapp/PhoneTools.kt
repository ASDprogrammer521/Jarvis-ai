package com.asdcuber.jarvisapp

import android.Manifest
import android.content.ContentValues
import android.content.Context
import android.content.pm.PackageManager
import android.media.AudioAttributes
import android.media.AudioManager
import android.media.Ringtone
import android.media.RingtoneManager
import android.net.Uri
import android.os.Build
import android.os.Environment
import android.os.Handler
import android.os.Looper
import android.os.VibrationEffect
import android.os.Vibrator
import android.provider.ContactsContract
import android.provider.MediaStore
import android.widget.Toast
import androidx.core.content.ContextCompat
import org.json.JSONObject
import java.io.DataOutputStream
import java.io.File
import java.io.FileOutputStream
import java.util.UUID

/** Address book lookups ("call Akam"). */
object Contacts {
    data class Hit(val name: String, val number: String)

    fun allowed(c: Context) = ContextCompat.checkSelfPermission(c, Manifest.permission.READ_CONTACTS) ==
        PackageManager.PERMISSION_GRANTED

    private fun digits(s: String) = s.filter { it.isDigit() }

    /** Best matches first: exact name, then names starting with the query, then containing it. */
    fun search(c: Context, query: String, limit: Int = 8): List<Hit> {
        val q = query.trim()
        if (q.isEmpty() || !allowed(c)) return emptyList()
        val found = LinkedHashMap<String, Pair<Int, Hit>>()
        val terms = listOf(q) + q.split(Regex("\\s+")).filter { it.length >= 2 && it != q }
        for (term in terms) {
            c.contentResolver.query(
                ContactsContract.CommonDataKinds.Phone.CONTENT_URI,
                arrayOf(
                    ContactsContract.CommonDataKinds.Phone.DISPLAY_NAME,
                    ContactsContract.CommonDataKinds.Phone.NUMBER
                ),
                "${ContactsContract.CommonDataKinds.Phone.DISPLAY_NAME} LIKE ?",
                arrayOf("%$term%"),
                "${ContactsContract.CommonDataKinds.Phone.DISPLAY_NAME} ASC"
            )?.use { cur ->
                while (cur.moveToNext()) {
                    val name = cur.getString(0) ?: continue
                    val num = cur.getString(1) ?: continue
                    val key = digits(num).takeLast(9)
                    if (key.length < 3) continue
                    val rank = when {
                        name.equals(q, true) -> 0
                        name.startsWith(q, true) -> 1
                        name.contains(q, true) -> 2
                        else -> 3
                    }
                    val old = found[key]
                    if (old == null || rank < old.first) found[key] = rank to Hit(name, num.trim())
                }
            }
            if (found.isNotEmpty() && term == q) break
        }
        return found.values.sortedBy { it.first }.map { it.second }.take(limit)
    }

    fun nameFor(c: Context, number: String): String? {
        if (number.isBlank() || !allowed(c)) return null
        return try {
            val uri = Uri.withAppendedPath(ContactsContract.PhoneLookup.CONTENT_FILTER_URI, Uri.encode(number))
            c.contentResolver.query(uri, arrayOf(ContactsContract.PhoneLookup.DISPLAY_NAME), null, null, null)
                ?.use { if (it.moveToFirst()) it.getString(0) else null }
        } catch (_: Exception) { null }
    }
}

/** "Where is my phone?" — rings loudly on the alarm stream even if the phone is silent. */
object FindPhone {
    private var ringtone: Ringtone? = null
    private var savedVolume = -1
    private val handler = Handler(Looper.getMainLooper())
    private val autoStop = Runnable { ringtone?.let { stop(appCtx!!) } }
    private var appCtx: Context? = null
    val ringing: Boolean get() = ringtone != null

    private fun event(name: String) {
        JarvisLinkService.sendRaw(JSONObject().put("type", "phone_event").put("event", name).toString())
    }

    fun start(c: Context): String {
        if (ringtone != null) return "Already ringing"
        appCtx = c.applicationContext
        return try {
            val am = c.getSystemService(Context.AUDIO_SERVICE) as AudioManager
            savedVolume = am.getStreamVolume(AudioManager.STREAM_ALARM)
            am.setStreamVolume(AudioManager.STREAM_ALARM, am.getStreamMaxVolume(AudioManager.STREAM_ALARM), 0)
            val uri = RingtoneManager.getDefaultUri(RingtoneManager.TYPE_ALARM)
                ?: RingtoneManager.getDefaultUri(RingtoneManager.TYPE_RINGTONE)
            val r = RingtoneManager.getRingtone(c, uri)
            r.audioAttributes = AudioAttributes.Builder()
                .setUsage(AudioAttributes.USAGE_ALARM)
                .setContentType(AudioAttributes.CONTENT_TYPE_SONIFICATION)
                .build()
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.P) r.isLooping = true
            r.play()
            ringtone = r
            try {
                @Suppress("DEPRECATION")
                val v = c.getSystemService(Context.VIBRATOR_SERVICE) as Vibrator
                v.vibrate(VibrationEffect.createWaveform(longArrayOf(0, 700, 400), 0))
            } catch (_: Exception) {}
            handler.postDelayed(autoStop, 90_000)
            event("ring_started")
            "Phone is ringing (stops by itself after 90 s)"
        } catch (e: Exception) {
            "Could not ring: ${e.message}"
        }
    }

    fun stop(c: Context): String {
        handler.removeCallbacks(autoStop)
        val r = ringtone ?: return "Not ringing"
        try { r.stop() } catch (_: Exception) {}
        ringtone = null
        try {
            @Suppress("DEPRECATION")
            (c.getSystemService(Context.VIBRATOR_SERVICE) as Vibrator).cancel()
            if (savedVolume >= 0) {
                (c.getSystemService(Context.AUDIO_SERVICE) as AudioManager)
                    .setStreamVolume(AudioManager.STREAM_ALARM, savedVolume, 0)
            }
        } catch (_: Exception) {}
        event("ring_stopped")
        return "Ringing stopped"
    }
}

/** Large files in both directions over the paired link (the socket only carries small ones). */
object FileTransfer {
    private val ui = Handler(Looper.getMainLooper())

    private fun report(c: Context, text: String) {
        JarvisLinkService.lastLog = text
        ui.post { Toast.makeText(c.applicationContext, text, Toast.LENGTH_LONG).show() }
    }

    /** PC → phone. `path` is a short-lived /api/share/<token> link from the PC. */
    fun download(c: Context, path: String, name: String): String {
        val base = LinkTls.base(c)
        if (base.isEmpty() || !path.startsWith("/api/share/")) return "No link to download from"
        val safe = name.replace(Regex("[\\\\/:*?\"<>|]"), "_").ifBlank { "jarvis_file" }
        Thread {
            try {
                val conn = LinkTls.open(c, base + path)
                conn.connectTimeout = 10_000
                conn.readTimeout = 30_000
                if (conn.responseCode !in 200..299) { report(c, "Download failed: HTTP ${conn.responseCode}"); return@Thread }
                val where: String
                if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
                    val values = ContentValues().apply {
                        put(MediaStore.Downloads.DISPLAY_NAME, safe)
                        put(MediaStore.Downloads.RELATIVE_PATH, Environment.DIRECTORY_DOWNLOADS + "/Jarvis")
                    }
                    val uri = c.contentResolver.insert(MediaStore.Downloads.EXTERNAL_CONTENT_URI, values)
                        ?: throw IllegalStateException("cannot create file")
                    c.contentResolver.openOutputStream(uri)!!.use { out -> conn.inputStream.use { it.copyTo(out) } }
                    where = "Downloads/Jarvis"
                } else {
                    val dir = c.getExternalFilesDir(Environment.DIRECTORY_DOWNLOADS) ?: c.filesDir
                    FileOutputStream(File(dir, safe)).use { out -> conn.inputStream.use { it.copyTo(out) } }
                    where = dir.absolutePath
                }
                report(c, "Received $safe → $where")
            } catch (e: Exception) {
                report(c, "Download failed: ${e.message}")
            }
        }.start()
        return "Receiving $safe from the PC…"
    }

    /** Phone → PC, any size up to the server limit. */
    fun upload(c: Context, uri: Uri, name: String, mime: String) {
        val base = LinkTls.base(c)
        val token = LinkTls.token(c)
        if (base.isEmpty() || token.isEmpty()) { report(c, "Connect to the PC first"); return }
        Thread {
            try {
                val boundary = "----jarvis" + UUID.randomUUID().toString().replace("-", "")
                val fname = name.replace("\"", "_")
                val conn = LinkTls.open(c, "$base/api/upload")
                conn.requestMethod = "POST"
                conn.doOutput = true
                conn.connectTimeout = 10_000
                conn.readTimeout = 120_000
                conn.setChunkedStreamingMode(0)
                conn.setRequestProperty("Authorization", "Bearer $token")
                conn.setRequestProperty("Content-Type", "multipart/form-data; boundary=$boundary")
                DataOutputStream(conn.outputStream).use { out ->
                    out.writeBytes("--$boundary\r\n")
                    out.writeBytes("Content-Disposition: form-data; name=\"file\"; filename=\"$fname\"\r\n")
                    out.writeBytes("Content-Type: $mime\r\n\r\n")
                    c.contentResolver.openInputStream(uri)!!.use { it.copyTo(out) }
                    out.writeBytes("\r\n--$boundary--\r\n")
                }
                val code = conn.responseCode
                report(c, if (code in 200..299) "Sent $name to the PC" else "Upload failed: HTTP $code")
            } catch (e: Exception) {
                report(c, "Upload failed: ${e.message}")
            }
        }.start()
    }
}
