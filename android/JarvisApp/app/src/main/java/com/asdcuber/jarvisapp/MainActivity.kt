package com.asdcuber.jarvisapp

import android.Manifest
import android.app.Activity
import android.app.admin.DevicePolicyManager
import android.content.ComponentName
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.provider.OpenableColumns
import android.provider.Settings
import android.speech.RecognizerIntent
import android.widget.Button
import android.widget.EditText
import android.widget.ImageButton
import android.widget.TextView
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity
import androidx.core.app.ActivityCompat
import androidx.core.content.ContextCompat
import java.io.BufferedReader
import java.io.InputStreamReader
import java.util.Locale

class MainActivity : AppCompatActivity() {

    companion object {
        private const val REQ_PERMS = 1001
        private const val REQ_FILE = 1002
        private const val REQ_VOICE = 1003
        private const val REQ_CAMERA = 1004
    }

    private val handler = Handler(Looper.getMainLooper())
    private lateinit var statusText: TextView
    private lateinit var logView: TextView
    private lateinit var chatInput: EditText
    private var lastSeenLog: String = ""

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)

        statusText = findViewById(R.id.statusText)
        logView = findViewById(R.id.logView)
        chatInput = findViewById(R.id.chatInput)
        val hostInput = findViewById<EditText>(R.id.hostInput)
        val keyInput = findViewById<EditText>(R.id.keyInput)
        val connectBtn = findViewById<Button>(R.id.connectBtn)
        val adminBtn = findViewById<Button>(R.id.adminBtn)
        val sendBtn = findViewById<ImageButton>(R.id.sendBtn)
        val attachBtn = findViewById<ImageButton>(R.id.attachBtn)

        val prefs = getSharedPreferences("jarvis", Context.MODE_PRIVATE)
        hostInput.setText(prefs.getString("host", ""))
        keyInput.setText(prefs.getString("key", ""))

        requestStartupPermissions()

        // Deep-link from notification (screenshot etc.)
        handleJarvisAction(intent)

        connectBtn.setOnClickListener {
            val host = hostInput.text.toString().trim()
            val key = keyInput.text.toString().trim()
            if (host.isEmpty() || key.isEmpty()) {
                appendLog("Enter IP and pairing key"); return@setOnClickListener
            }
            prefs.edit().putString("host", host).putString("key", key).apply()
            val i = Intent(this, JarvisLinkService::class.java)
            i.putExtra(JarvisLinkService.EXTRA_HOST, host)
            i.putExtra(JarvisLinkService.EXTRA_KEY, key)
            startForegroundService(i)
            appendLog("Starting link…")
        }

        adminBtn.setOnClickListener {
            val dpm = getSystemService(DEVICE_POLICY_SERVICE) as DevicePolicyManager
            val admin = ComponentName(this, JarvisDeviceAdmin::class.java)
            if (dpm.isAdminActive(admin)) appendLog("Lock permission already enabled")
            else {
                startActivity(Intent(DevicePolicyManager.ACTION_ADD_DEVICE_ADMIN).apply {
                    putExtra(DevicePolicyManager.EXTRA_DEVICE_ADMIN, admin)
                    putExtra(DevicePolicyManager.EXTRA_ADD_EXPLANATION, "Allow Jarvis to lock the screen.")
                })
            }
        }

        sendBtn.setOnClickListener { sendChat() }
        attachBtn.setOnClickListener {
            startActivityForResult(
                Intent.createChooser(
                    Intent(Intent.ACTION_GET_CONTENT).apply {
                        type = "*/*"; addCategory(Intent.CATEGORY_OPENABLE)
                    },
                    "Attach file"
                ),
                REQ_FILE
            )
        }

        // Quick actions
        findViewById<Button>(R.id.qYoutube).setOnClickListener {
            localOrSend("open youtube") { CommandExecutor.handle(this, org.json.JSONObject(mapOf("action" to "open_app", "value" to "youtube"))) }
        }
        findViewById<Button>(R.id.qLock).setOnClickListener {
            appendLog(CommandExecutor.handle(this, org.json.JSONObject(mapOf("action" to "lock"))))
        }
        findViewById<Button>(R.id.qHome).setOnClickListener {
            appendLog(CommandExecutor.handle(this, org.json.JSONObject(mapOf("action" to "home"))))
        }
        findViewById<Button>(R.id.qNotif).setOnClickListener {
            // Open notification access settings if needed
            try {
                startActivity(Intent(Settings.ACTION_NOTIFICATION_LISTENER_SETTINGS))
            } catch (_: Exception) {}
            val snap = JarvisNotificationListener.snapshot()
            appendLog(snap)
            if (JarvisLinkService.connected) JarvisLinkService.sendCommand("[PHONE_NOTIFICATIONS]\n$snap")
        }
        findViewById<Button>(R.id.qLoc).setOnClickListener {
            ensureLocationPerm()
            val loc = CommandExecutor.handle(this, org.json.JSONObject(mapOf("action" to "location")))
            appendLog(loc)
            if (JarvisLinkService.connected) JarvisLinkService.sendCommand("[PHONE_LOCATION] $loc")
        }
        findViewById<Button>(R.id.qCam).setOnClickListener {
            val i = Intent(android.provider.MediaStore.ACTION_IMAGE_CAPTURE)
            try {
                startActivityForResult(i, REQ_CAMERA)
            } catch (e: Exception) {
                appendLog("Camera: ${e.message}")
            }
        }
        findViewById<Button>(R.id.qMic).setOnClickListener {
            val i = Intent(RecognizerIntent.ACTION_RECOGNIZE_SPEECH).apply {
                putExtra(RecognizerIntent.EXTRA_LANGUAGE_MODEL, RecognizerIntent.LANGUAGE_MODEL_FREE_FORM)
                putExtra(RecognizerIntent.EXTRA_LANGUAGE, Locale.getDefault())
                putExtra(RecognizerIntent.EXTRA_PROMPT, "Speak to Jarvis…")
            }
            try {
                startActivityForResult(i, REQ_VOICE)
            } catch (e: Exception) {
                appendLog("Voice not available: ${e.message}")
            }
        }
        findViewById<Button>(R.id.qPcLock).setOnClickListener {
            if (JarvisLinkService.sendCommand("[PC_CONTROL] lock")) appendLog("Sent: lock PC")
            else appendLog("Not connected")
        }
        findViewById<Button>(R.id.qPcOff).setOnClickListener {
            if (JarvisLinkService.sendCommand("[PC_CONTROL] shutdown")) appendLog("Sent: shutdown PC")
            else appendLog("Not connected")
        }

        handler.post(object : Runnable {
            override fun run() {
                val online = JarvisLinkService.connected
                statusText.text = when {
                    online -> "● ONLINE"
                    JarvisLinkService.statusLine.contains("Connect", true) ||
                        JarvisLinkService.statusLine.contains("Login", true) -> "● CONNECTING"
                    else -> "● OFFLINE"
                }
                statusText.setTextColor(
                    when {
                        online -> 0xFF37FF8B.toInt()
                        statusText.text.contains("CONNECT") -> 0xFFFFB428.toInt()
                        else -> 0xFFFF4D6D.toInt()
                    }
                )
                val lg = JarvisLinkService.lastLog
                if (lg.isNotBlank() && lg != lastSeenLog) {
                    lastSeenLog = lg; appendLog(lg)
                }
                handler.postDelayed(this, 500)
            }
        })
    }

    private fun localOrSend(label: String, local: () -> String) {
        appendLog(local())
    }

    private fun sendChat() {
        val text = chatInput.text.toString().trim()
        if (text.isEmpty()) return
        if (!JarvisLinkService.connected) {
            Toast.makeText(this, "Not connected", Toast.LENGTH_SHORT).show(); return
        }
        if (JarvisLinkService.sendCommand(text)) {
            appendLog("You: $text"); chatInput.setText("")
        } else Toast.makeText(this, "Send failed", Toast.LENGTH_SHORT).show()
    }

    private fun requestStartupPermissions() {
        val need = mutableListOf<String>()
        if (Build.VERSION.SDK_INT >= 33) {
            if (ContextCompat.checkSelfPermission(this, Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED)
                need.add(Manifest.permission.POST_NOTIFICATIONS)
            if (ContextCompat.checkSelfPermission(this, Manifest.permission.READ_MEDIA_IMAGES) != PackageManager.PERMISSION_GRANTED)
                need.add(Manifest.permission.READ_MEDIA_IMAGES)
            if (ContextCompat.checkSelfPermission(this, Manifest.permission.CAMERA) != PackageManager.PERMISSION_GRANTED)
                need.add(Manifest.permission.CAMERA)
            if (ContextCompat.checkSelfPermission(this, Manifest.permission.ACCESS_FINE_LOCATION) != PackageManager.PERMISSION_GRANTED)
                need.add(Manifest.permission.ACCESS_FINE_LOCATION)
            if (ContextCompat.checkSelfPermission(this, Manifest.permission.RECORD_AUDIO) != PackageManager.PERMISSION_GRANTED)
                need.add(Manifest.permission.RECORD_AUDIO)
            if (ContextCompat.checkSelfPermission(this, Manifest.permission.CALL_PHONE) != PackageManager.PERMISSION_GRANTED)
                need.add(Manifest.permission.CALL_PHONE)
            if (ContextCompat.checkSelfPermission(this, Manifest.permission.SEND_SMS) != PackageManager.PERMISSION_GRANTED)
                need.add(Manifest.permission.SEND_SMS)
        } else {
            listOf(
                Manifest.permission.READ_EXTERNAL_STORAGE,
                Manifest.permission.CAMERA,
                Manifest.permission.ACCESS_FINE_LOCATION,
                Manifest.permission.RECORD_AUDIO,
                Manifest.permission.CALL_PHONE,
                Manifest.permission.SEND_SMS
            ).forEach {
                if (ContextCompat.checkSelfPermission(this, it) != PackageManager.PERMISSION_GRANTED) need.add(it)
            }
        }
        if (need.isNotEmpty()) {
            ActivityCompat.requestPermissions(this, need.toTypedArray(), REQ_PERMS)
            appendLog("Requesting permissions…")
        }
    }

    private fun ensureLocationPerm() {
        if (ContextCompat.checkSelfPermission(this, Manifest.permission.ACCESS_FINE_LOCATION)
            != PackageManager.PERMISSION_GRANTED
        ) {
            ActivityCompat.requestPermissions(this, arrayOf(Manifest.permission.ACCESS_FINE_LOCATION), REQ_PERMS)
        }
    }

    @Deprecated("Deprecated in Java")
    override fun onActivityResult(requestCode: Int, resultCode: Int, data: Intent?) {
        super.onActivityResult(requestCode, resultCode, data)
        if (resultCode != Activity.RESULT_OK) return
        when (requestCode) {
            REQ_VOICE -> {
                val matches = data?.getStringArrayListExtra(RecognizerIntent.EXTRA_RESULTS)
                val text = matches?.firstOrNull()?.trim().orEmpty()
                if (text.isNotEmpty()) {
                    appendLog("Voice: $text")
                    if (JarvisLinkService.connected) JarvisLinkService.sendCommand(text)
                    else chatInput.setText(text)
                }
            }
            REQ_CAMERA -> {
                appendLog("Photo captured — send via + attach if you need full file transfer.")
                if (JarvisLinkService.connected)
                    JarvisLinkService.sendCommand("[PHONE_CAMERA] User took a photo on phone. Ask them to attach it if analysis is needed.")
            }
            REQ_FILE -> {
                val uri = data?.data ?: return
                if (!JarvisLinkService.connected) {
                    Toast.makeText(this, "Connect first", Toast.LENGTH_SHORT).show(); return
                }
                try {
                    val name = queryName(uri) ?: "file"
                    val mime = contentResolver.getType(uri) ?: "application/octet-stream"
                    val isText = mime.startsWith("text/") || name.endsWith(".txt") ||
                        name.endsWith(".md") || name.endsWith(".json") || name.endsWith(".csv")
                    if (isText) {
                        val body = contentResolver.openInputStream(uri)?.use {
                            BufferedReader(InputStreamReader(it)).readText()
                        }?.take(12000) ?: ""
                        JarvisLinkService.sendCommand(
                            "[FILE_FROM_PHONE] name=$name mime=$mime\n$body\n---\nFile from phone."
                        )
                        appendLog("File sent: $name")
                    } else {
                        val size = querySize(uri)
                        // Try base64 for small files (<400KB)
                        if (size in 1..400_000) {
                            val bytes = contentResolver.openInputStream(uri)?.use { it.readBytes() }
                            if (bytes != null) {
                                val b64 = android.util.Base64.encodeToString(bytes, android.util.Base64.NO_WRAP)
                                JarvisLinkService.sendCommand(
                                    "[FILE_FROM_PHONE_B64] name=$name mime=$mime\n$b64"
                                )
                                appendLog("Binary file sent: $name")
                                return
                            }
                        }
                        JarvisLinkService.sendCommand(
                            "[FILE_FROM_PHONE] name=$name mime=$mime size=$size (too large to inline)"
                        )
                        appendLog("File noted: $name")
                    }
                } catch (e: Exception) {
                    appendLog("File error: ${e.message}")
                }
            }
        }
    }

    private fun queryName(uri: Uri): String? {
        contentResolver.query(uri, null, null, null, null)?.use { c ->
            val i = c.getColumnIndex(OpenableColumns.DISPLAY_NAME)
            if (i >= 0 && c.moveToFirst()) return c.getString(i)
        }
        return uri.lastPathSegment
    }

    private fun querySize(uri: Uri): Long {
        contentResolver.query(uri, null, null, null, null)?.use { c ->
            val i = c.getColumnIndex(OpenableColumns.SIZE)
            if (i >= 0 && c.moveToFirst()) return c.getLong(i)
        }
        return -1L
    }


    override fun onNewIntent(intent: Intent?) {
        super.onNewIntent(intent)
        setIntent(intent)
        handleJarvisAction(intent)
    }

    private fun handleJarvisAction(intent: Intent?) {
        when (intent?.getStringExtra("jarvis_action")) {
            "screenshot" -> {
                try {
                    startActivity(
                        Intent(this, ScreenshotActivity::class.java)
                            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
                    )
                    appendLog("Screenshot requested…")
                } catch (e: Exception) {
                    appendLog("Screenshot open failed: ${e.message}")
                }
            }
            "unlock" -> {
                try {
                    startActivity(
                        Intent(this, UnlockActivity::class.java)
                            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
                    )
                    appendLog("Unlock/wake…")
                } catch (e: Exception) {
                    appendLog("Unlock: ${e.message}")
                }
            }
            "screenshare" -> {
                try {
                    startActivity(
                        Intent(this, ScreenshotActivity::class.java)
                            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
                            .putExtra("mode", "share")
                    )
                    appendLog("Screen share permission…")
                } catch (e: Exception) {
                    appendLog("Share: ${e.message}")
                }
            }
        }
    }

    private fun appendLog(line: String) {
        logView.append(line + "\n")
    }
}
