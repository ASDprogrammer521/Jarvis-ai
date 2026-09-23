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

class MainActivity : AppCompatActivity() {

    companion object {
        private const val REQ_PERMS = 1001
        private const val REQ_FILE = 1002
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

        // Ask for needed permissions on first open
        requestStartupPermissions()

        connectBtn.setOnClickListener {
            val host = hostInput.text.toString().trim()
            val key = keyInput.text.toString().trim()
            if (host.isEmpty() || key.isEmpty()) {
                appendLog("Enter IP and pairing key")
                return@setOnClickListener
            }
            prefs.edit().putString("host", host).putString("key", key).apply()
            val i = Intent(this, JarvisLinkService::class.java)
            i.putExtra(JarvisLinkService.EXTRA_HOST, host)
            i.putExtra(JarvisLinkService.EXTRA_KEY, key)
            startForegroundService(i)
            appendLog("Starting link…")
            statusText.text = "● CONNECTING"
            statusText.setTextColor(0xFFFFB428.toInt())
        }

        adminBtn.setOnClickListener {
            val dpm = getSystemService(DEVICE_POLICY_SERVICE) as DevicePolicyManager
            val admin = ComponentName(this, JarvisDeviceAdmin::class.java)
            if (dpm.isAdminActive(admin)) {
                appendLog("Lock permission already enabled")
            } else {
                val intent = Intent(DevicePolicyManager.ACTION_ADD_DEVICE_ADMIN)
                intent.putExtra(DevicePolicyManager.EXTRA_DEVICE_ADMIN, admin)
                intent.putExtra(
                    DevicePolicyManager.EXTRA_ADD_EXPLANATION,
                    "Allow Jarvis to lock the screen when you ask."
                )
                startActivity(intent)
            }
        }

        sendBtn.setOnClickListener { sendChat() }
        chatInput.setOnEditorActionListener { _, _, _ ->
            sendChat(); true
        }

        attachBtn.setOnClickListener {
            val intent = Intent(Intent.ACTION_GET_CONTENT).apply {
                type = "*/*"
                addCategory(Intent.CATEGORY_OPENABLE)
            }
            startActivityForResult(Intent.createChooser(intent, "Attach file"), REQ_FILE)
        }

        handler.post(object : Runnable {
            override fun run() {
                val online = JarvisLinkService.connected
                statusText.text = when {
                    online -> "● ONLINE"
                    JarvisLinkService.statusLine.startsWith("Connect") ||
                        JarvisLinkService.statusLine.startsWith("Login") -> "● CONNECTING"
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
                    lastSeenLog = lg
                    appendLog(lg)
                }
                handler.postDelayed(this, 500)
            }
        })
    }

    private fun sendChat() {
        val text = chatInput.text.toString().trim()
        if (text.isEmpty()) return
        if (!JarvisLinkService.connected) {
            Toast.makeText(this, "Not connected", Toast.LENGTH_SHORT).show()
            return
        }
        val ok = JarvisLinkService.sendCommand(text)
        if (ok) {
            appendLog("You: $text")
            chatInput.setText("")
        } else {
            Toast.makeText(this, "Send failed", Toast.LENGTH_SHORT).show()
        }
    }

    private fun requestStartupPermissions() {
        val need = mutableListOf<String>()
        if (Build.VERSION.SDK_INT >= 33) {
            if (ContextCompat.checkSelfPermission(this, Manifest.permission.POST_NOTIFICATIONS)
                != PackageManager.PERMISSION_GRANTED
            ) {
                need.add(Manifest.permission.POST_NOTIFICATIONS)
            }
            if (ContextCompat.checkSelfPermission(this, Manifest.permission.READ_MEDIA_IMAGES)
                != PackageManager.PERMISSION_GRANTED
            ) {
                need.add(Manifest.permission.READ_MEDIA_IMAGES)
            }
        } else if (Build.VERSION.SDK_INT >= 23) {
            if (ContextCompat.checkSelfPermission(this, Manifest.permission.READ_EXTERNAL_STORAGE)
                != PackageManager.PERMISSION_GRANTED
            ) {
                need.add(Manifest.permission.READ_EXTERNAL_STORAGE)
            }
        }
        if (need.isNotEmpty()) {
            ActivityCompat.requestPermissions(this, need.toTypedArray(), REQ_PERMS)
            appendLog("Requesting permissions…")
        }
    }

    override fun onRequestPermissionsResult(
        requestCode: Int,
        permissions: Array<out String>,
        grantResults: IntArray
    ) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults)
        if (requestCode == REQ_PERMS) {
            val granted = grantResults.count { it == PackageManager.PERMISSION_GRANTED }
            appendLog("Permissions: $granted / ${grantResults.size} granted")
        }
    }

    @Deprecated("Deprecated in Java")
    override fun onActivityResult(requestCode: Int, resultCode: Int, data: Intent?) {
        super.onActivityResult(requestCode, resultCode, data)
        if (requestCode != REQ_FILE || resultCode != Activity.RESULT_OK) return
        val uri = data?.data ?: return
        if (!JarvisLinkService.connected) {
            Toast.makeText(this, "Connect first", Toast.LENGTH_SHORT).show()
            return
        }
        try {
            val name = queryName(uri) ?: "file"
            val mime = contentResolver.getType(uri) ?: "application/octet-stream"
            // Send text files inline (capped); others as metadata note
            val isText = mime.startsWith("text/") || name.endsWith(".txt") ||
                name.endsWith(".md") || name.endsWith(".json") || name.endsWith(".csv")
            if (isText) {
                val body = contentResolver.openInputStream(uri)?.use { ins ->
                    BufferedReader(InputStreamReader(ins)).readText()
                }?.take(12000) ?: ""
                val msg =
                    "[FILE_FROM_PHONE] name=$name mime=$mime\n$body\n---\nPlease acknowledge this file from my phone and wait for instructions."
                if (JarvisLinkService.sendCommand(msg)) {
                    appendLog("File sent: $name")
                }
            } else {
                val size = querySize(uri)
                val msg =
                    "[FILE_FROM_PHONE] name=$name mime=$mime size=$size\n" +
                        "(Binary file — content not inlined.) User attached this from Jarvis App."
                if (JarvisLinkService.sendCommand(msg)) {
                    appendLog("File noted: $name ($size bytes)")
                }
            }
        } catch (e: Exception) {
            appendLog("File error: ${e.message}")
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

    private fun appendLog(line: String) {
        logView.append(line + "\n")
    }
}
