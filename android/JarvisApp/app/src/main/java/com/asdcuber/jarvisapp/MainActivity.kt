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
import android.view.View
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
    private lateinit var callStateLabel: TextView
    private var torchOn = false
    private var lastSeenLog: String = ""

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)

        statusText = findViewById(R.id.statusText)
        logView = findViewById(R.id.logView)
        chatInput = findViewById(R.id.chatInput)
        val hostInput = findViewById<EditText>(R.id.hostInput)
        val keyInput = findViewById<EditText>(R.id.keyInput)
        val connectCard = findViewById<View>(R.id.connectCard)
        val connectedBar = findViewById<View>(R.id.connectedBar)
        val linkedHost = findViewById<TextView>(R.id.linkedHost)
        callStateLabel = findViewById(R.id.callState)
        val linkSecurity = findViewById<TextView>(R.id.linkSecurity)

        val prefs = getSharedPreferences("jarvis", Context.MODE_PRIVATE)
        hostInput.setText(prefs.getString("host", ""))
        keyInput.setText(prefs.getString("key", ""))

        requestStartupPermissions()
        handleJarvisAction(intent)

        findViewById<View>(R.id.connectBtn).setOnClickListener {
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
        findViewById<View>(R.id.disconnectBtn).setOnClickListener {
            stopService(Intent(this, JarvisLinkService::class.java))
            appendLog("Disconnected")
        }

        findViewById<View>(R.id.adminBtn).setOnClickListener {
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

        findViewById<View>(R.id.forgetBtn).setOnClickListener {
            val h = hostInput.text.toString().trim().removePrefix("https://").removePrefix("http://")
            if (h.isEmpty()) appendLog("Enter the PC IP first") else {
                LinkTls.forget(this, h)
                appendLog("Forgot the certificate for $h — the next connect trusts the PC's current one")
            }
        }
        findViewById<View>(R.id.clearLog).setOnClickListener { logView.text = "" }
        findViewById<ImageButton>(R.id.sendBtn).setOnClickListener { sendChat() }
        findViewById<ImageButton>(R.id.attachBtn).setOnClickListener { pickFile() }

        fun exec(action: String, value: String? = null): String {
            val o = org.json.JSONObject().put("action", action)
            if (value != null) o.put("value", value)
            return CommandExecutor.handle(this, o)
        }

        findViewById<View>(R.id.qYoutube).setOnClickListener { appendLog(exec("open_app", "youtube")) }
        findViewById<View>(R.id.qLock).setOnClickListener { appendLog(exec("lock")) }
        findViewById<View>(R.id.qHome).setOnClickListener { appendLog(exec("home")) }
        findViewById<View>(R.id.qNotif).setOnClickListener {
            try {
                startActivity(Intent(Settings.ACTION_NOTIFICATION_LISTENER_SETTINGS))
            } catch (_: Exception) {}
            val snap = JarvisNotificationListener.snapshot()
            appendLog(snap)
            if (JarvisLinkService.connected) JarvisLinkService.sendCommand("[PHONE_NOTIFICATIONS]\n$snap")
        }
        findViewById<View>(R.id.qLoc).setOnClickListener {
            ensureLocationPerm()
            val loc = exec("location")
            appendLog(loc)
            if (JarvisLinkService.connected) JarvisLinkService.sendCommand("[PHONE_LOCATION] $loc")
        }
        findViewById<View>(R.id.qCam).setOnClickListener {
            try {
                startActivityForResult(Intent(android.provider.MediaStore.ACTION_IMAGE_CAPTURE), REQ_CAMERA)
            } catch (e: Exception) {
                appendLog("Camera: ${e.message}")
            }
        }
        findViewById<View>(R.id.qMic).setOnClickListener {
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
        findViewById<View>(R.id.qTorch).setOnClickListener {
            torchOn = !torchOn
            appendLog(exec(if (torchOn) "flashlight" else "flashlight_off"))
        }
        findViewById<View>(R.id.qShot).setOnClickListener { appendLog(exec("screenshot")) }

        findViewById<View>(R.id.qFind).setOnClickListener {
            appendLog(exec(if (FindPhone.ringing) "ring_stop" else "ring"))
        }
        findViewById<View>(R.id.qContacts).setOnClickListener { showContacts() }
        findViewById<View>(R.id.qFiles).setOnClickListener { pickFile() }

        fun pc(cmd: String, label: String) {
            if (JarvisLinkService.sendCommand("[PC_CONTROL] $cmd")) appendLog("Sent: $label")
            else appendLog("Not connected")
        }
        findViewById<View>(R.id.qPcMute).setOnClickListener { pc("mute", "mute PC") }
        findViewById<View>(R.id.qPcVolDown).setOnClickListener { pc("volume_down", "PC volume down") }
        findViewById<View>(R.id.qPcVolUp).setOnClickListener { pc("volume_up", "PC volume up") }
        findViewById<View>(R.id.qPcPlay).setOnClickListener { pc("play_pause", "play / pause") }
        findViewById<View>(R.id.qPcPrev).setOnClickListener { pc("prev", "previous track") }
        findViewById<View>(R.id.qPcNext).setOnClickListener { pc("next", "next track") }
        findViewById<View>(R.id.qPcApp).setOnClickListener {
            val input = EditText(this).apply { hint = "App name, e.g. Discord"; setSingleLine() }
            val actions = arrayOf("Minimize", "Maximize", "Bring to front", "Close")
            val cmds = arrayOf("minimize", "maximize", "focus", "close")
            android.app.AlertDialog.Builder(this)
                .setTitle("Control an app on the PC")
                .setView(input)
                .setItems(actions) { _, i ->
                    val app = input.text.toString().trim()
                    if (app.isEmpty()) appendLog("Type the app name first")
                    else pc("${cmds[i]} $app", "${actions[i].lowercase()} $app")
                }
                .setNegativeButton("Cancel", null)
                .show()
        }

        // ── Calls ────────────────────────────────────────────────────────────
        findViewById<View>(R.id.qDial).setOnClickListener { showDialer() }
        findViewById<View>(R.id.qAnswer).setOnClickListener { runCallAction("answer") }
        findViewById<View>(R.id.qReject).setOnClickListener { runCallAction("reject") }
        findViewById<View>(R.id.qHangup).setOnClickListener { runCallAction("hangup") }
        findViewById<View>(R.id.qCallState).setOnClickListener { runCallAction("call_status") }

        findViewById<View>(R.id.qPcLock).setOnClickListener {
            if (JarvisLinkService.sendCommand("[PC_CONTROL] lock")) appendLog("Sent: lock PC")
            else appendLog("Not connected")
        }
        findViewById<View>(R.id.qPcOff).setOnClickListener {
            android.app.AlertDialog.Builder(this)
                .setTitle("Shut down the PC?")
                .setMessage("Jarvis will ask the PC to shut down.")
                .setNegativeButton("Cancel", null)
                .setPositiveButton("Shut down") { _, _ ->
                    if (JarvisLinkService.sendCommand("[PC_CONTROL] shutdown")) appendLog("Sent: shutdown PC")
                    else appendLog("Not connected")
                }
                .show()
        }

        var tick = 0
        handler.post(object : Runnable {
            override fun run() {
                val online = JarvisLinkService.connected
                val connecting = !online && (
                    JarvisLinkService.statusLine.contains("Connect", true) ||
                        JarvisLinkService.statusLine.contains("Login", true))
                statusText.text = when {
                    online -> "● ONLINE"
                    connecting -> "● CONNECTING"
                    else -> "● OFFLINE"
                }
                statusText.setTextColor(
                    ContextCompat.getColor(
                        this@MainActivity,
                        when {
                            online -> R.color.green
                            connecting -> R.color.amber
                            else -> R.color.red
                        }
                    )
                )
                statusText.setBackgroundResource(
                    when {
                        online -> R.drawable.bg_status_online
                        connecting -> R.drawable.bg_status_connecting
                        else -> R.drawable.bg_status_pill
                    }
                )
                connectCard.visibility = if (online) View.GONE else View.VISIBLE
                connectedBar.visibility = if (online) View.VISIBLE else View.GONE
                if (online) {
                    val h = prefs.getString("host", "") ?: ""
                    linkedHost.text = h
                    val secure = LinkTls.base(this@MainActivity).startsWith("https://")
                    linkSecurity.text = if (secure) "🔒 Encrypted · certificate pinned" else "⚠ Plain HTTP — not encrypted"
                    linkSecurity.setTextColor(ContextCompat.getColor(
                        this@MainActivity, if (secure) R.color.green else R.color.amber))
                }

                val lg = JarvisLinkService.lastLog
                if (lg.isNotBlank() && lg != lastSeenLog) {
                    lastSeenLog = lg; appendLog(lg)
                }
                // Refresh the call banner every ~2 s while we are allowed to read it.
                if (tick++ % 4 == 0 && ContextCompat.checkSelfPermission(
                        this@MainActivity, Manifest.permission.READ_PHONE_STATE
                    ) == PackageManager.PERMISSION_GRANTED
                ) {
                    callStateLabel.text = CommandExecutor.handle(
                        this@MainActivity, org.json.JSONObject().put("action", "call_status")
                    )
                }
                handler.postDelayed(this, 500)
            }
        })
    }

    // ── Dialer bottom sheet ──────────────────────────────────────────────────
    private fun showDialer() {
        val sheet = com.google.android.material.bottomsheet.BottomSheetDialog(this)
        val v = layoutInflater.inflate(R.layout.dialog_dialer, null)
        sheet.setContentView(v)
        (v.parent as? View)?.setBackgroundColor(android.graphics.Color.TRANSPARENT)

        val display = v.findViewById<TextView>(R.id.dialNumber)
        val hint = v.findViewById<TextView>(R.id.dialHint)
        val prefs = getSharedPreferences("jarvis", Context.MODE_PRIVATE)
        val last = prefs.getString("last_number", "") ?: ""
        val number = StringBuilder()

        fun refresh() {
            display.text = number.toString()
            hint.text = when {
                number.isEmpty() && last.isNotEmpty() -> "Tap Call to redial $last"
                number.isEmpty() -> "Enter a number"
                else -> " "
            }
        }

        val keypad = v.findViewById<android.widget.GridLayout>(R.id.keypad)
        for (k in "123456789*0#") {
            val key = TextView(this)
            key.text = k.toString()
            key.gravity = android.view.Gravity.CENTER
            key.setTextColor(ContextCompat.getColor(this, R.color.text))
            key.textSize = 26f
            key.setBackgroundResource(R.drawable.bg_key)
            key.isClickable = true
            key.isFocusable = true
            val lp = android.widget.GridLayout.LayoutParams(
                android.widget.GridLayout.spec(android.widget.GridLayout.UNDEFINED, 1f),
                android.widget.GridLayout.spec(android.widget.GridLayout.UNDEFINED, 1f)
            )
            lp.width = 0
            lp.height = (64 * resources.displayMetrics.density).toInt()
            val m = (5 * resources.displayMetrics.density).toInt()
            lp.setMargins(m, m, m, m)
            key.layoutParams = lp
            key.setOnClickListener {
                if (number.length < 20) number.append(k)
                refresh()
            }
            if (k == '0') key.setOnLongClickListener { number.append('+'); refresh(); true }
            keypad.addView(key)
        }

        v.findViewById<View>(R.id.dialBack).apply {
            setOnClickListener { if (number.isNotEmpty()) number.deleteCharAt(number.length - 1); refresh() }
            setOnLongClickListener { number.clear(); refresh(); true }
        }
        v.findViewById<View>(R.id.dialPaste).setOnClickListener {
            val cm = getSystemService(Context.CLIPBOARD_SERVICE) as android.content.ClipboardManager
            val text = cm.primaryClip?.getItemAt(0)?.text?.toString().orEmpty()
            val cleaned = text.filter { it.isDigit() || it == '+' || it == '*' || it == '#' }.take(20)
            if (cleaned.isNotEmpty()) { number.clear(); number.append(cleaned); refresh() }
        }
        v.findViewById<View>(R.id.dialCall).setOnClickListener {
            val n = if (number.isEmpty()) last else number.toString()
            if (n.filter { it.isDigit() }.length < 3) {
                hint.text = "Enter a valid phone number"; return@setOnClickListener
            }
            if (ContextCompat.checkSelfPermission(this, Manifest.permission.CALL_PHONE) !=
                PackageManager.PERMISSION_GRANTED) {
                ActivityCompat.requestPermissions(this, arrayOf(Manifest.permission.CALL_PHONE), REQ_PERMS)
            }
            prefs.edit().putString("last_number", n).apply()
            val result = CommandExecutor.handle(
                this, org.json.JSONObject().put("action", "call").put("value", n)
            )
            callStateLabel.text = result
            appendLog(result)
            sheet.dismiss()
        }
        refresh()
        sheet.show()
    }

    private fun pickFile() {
        startActivityForResult(
            Intent.createChooser(
                Intent(Intent.ACTION_GET_CONTENT).apply {
                    type = "*/*"; addCategory(Intent.CATEGORY_OPENABLE)
                },
                "Send a file to the PC"
            ),
            REQ_FILE
        )
    }

    private fun showContacts() {
        if (ContextCompat.checkSelfPermission(this, Manifest.permission.READ_CONTACTS) !=
            PackageManager.PERMISSION_GRANTED) {
            ActivityCompat.requestPermissions(this, arrayOf(Manifest.permission.READ_CONTACTS), REQ_PERMS)
            appendLog("Contacts permission requested; allow it, then tap Contacts again.")
            return
        }
        val input = EditText(this).apply { hint = "Name"; setSingleLine() }
        android.app.AlertDialog.Builder(this)
            .setTitle("Call a contact")
            .setView(input)
            .setNegativeButton("Cancel", null)
            .setPositiveButton("Search") { _, _ ->
                val hits = Contacts.search(this, input.text.toString())
                if (hits.isEmpty()) { appendLog("No contact found"); return@setPositiveButton }
                android.app.AlertDialog.Builder(this)
                    .setTitle("Tap to call")
                    .setItems(hits.map { "${it.name}  ·  ${it.number}" }.toTypedArray()) { _, i ->
                        val r = CommandExecutor.handle(
                            this, org.json.JSONObject().put("action", "call").put("value", hits[i].number))
                        callStateLabel.text = r; appendLog(r)
                    }
                    .show()
            }
            .show()
    }

    private fun runCallAction(action: String) {
        val permission = when (action) {
            "call_status" -> Manifest.permission.READ_PHONE_STATE
            "answer", "reject", "hangup" -> Manifest.permission.ANSWER_PHONE_CALLS
            else -> null
        }
        if (permission != null && ContextCompat.checkSelfPermission(this, permission) !=
            PackageManager.PERMISSION_GRANTED) {
            ActivityCompat.requestPermissions(this, arrayOf(permission), REQ_PERMS)
            val note = "Phone permission requested; allow it, then tap again."
            callStateLabel.text = note
            appendLog(note)
            return
        }
        val result = CommandExecutor.handle(this, org.json.JSONObject().put("action", action))
        callStateLabel.text = result
        appendLog(result)
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
        val wanted = mutableListOf(
            Manifest.permission.CAMERA,
            Manifest.permission.ACCESS_FINE_LOCATION,
            Manifest.permission.RECORD_AUDIO,
            Manifest.permission.CALL_PHONE,
            Manifest.permission.SEND_SMS,
            Manifest.permission.READ_PHONE_STATE,   // call state + incoming-call alerts on the PC
            Manifest.permission.READ_CALL_LOG,      // caller's number on Android 9+
            Manifest.permission.READ_CONTACTS       // "call Akam", caller names
        )
        if (Build.VERSION.SDK_INT >= 33) {
            wanted += Manifest.permission.POST_NOTIFICATIONS
            wanted += Manifest.permission.READ_MEDIA_IMAGES
        } else {
            wanted += Manifest.permission.READ_EXTERNAL_STORAGE
        }
        val need = wanted.filter {
            ContextCompat.checkSelfPermission(this, it) != PackageManager.PERMISSION_GRANTED
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

                        if (size > 400_000) {
                            appendLog("Uploading $name (${size / 1024} KB)…")
                            FileTransfer.upload(this, uri, name, mime)
                            return
                        }
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
        // keep the log light: drop the oldest lines past 200
        val lines = logView.text.lines()
        if (lines.size > 200) logView.text = lines.takeLast(200).joinToString("\n")
    }
}

//by ASDcuber521
