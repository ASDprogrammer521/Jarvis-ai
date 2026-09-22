package com.asdcuber.jarvisapp

import android.app.admin.DevicePolicyManager
import android.content.ComponentName
import android.content.Context
import android.content.Intent
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.widget.Button
import android.widget.EditText
import android.widget.TextView
import androidx.appcompat.app.AppCompatActivity

class MainActivity : AppCompatActivity() {

    private val handler = Handler(Looper.getMainLooper())
    private lateinit var statusText: TextView
    private lateinit var logView: TextView

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)

        statusText = findViewById(R.id.statusText)
        logView = findViewById(R.id.logView)
        val hostInput = findViewById<EditText>(R.id.hostInput)
        val keyInput = findViewById<EditText>(R.id.keyInput)
        val connectBtn = findViewById<Button>(R.id.connectBtn)
        val adminBtn = findViewById<Button>(R.id.adminBtn)

        val prefs = getSharedPreferences("jarvis", Context.MODE_PRIVATE)
        hostInput.setText(prefs.getString("host", ""))
        keyInput.setText(prefs.getString("key", ""))

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
        }

        adminBtn.setOnClickListener {
            val dpm = getSystemService(DEVICE_POLICY_SERVICE) as DevicePolicyManager
            val admin = ComponentName(this, JarvisDeviceAdmin::class.java)
            if (dpm.isAdminActive(admin)) {
                appendLog("Lock permission already enabled")
            } else {
                val intent = Intent(DevicePolicyManager.ACTION_ADD_DEVICE_ADMIN)
                intent.putExtra(DevicePolicyManager.EXTRA_DEVICE_ADMIN, admin)
                intent.putExtra(DevicePolicyManager.EXTRA_ADD_EXPLANATION, "Allow Jarvis to lock the screen.")
                startActivity(intent)
            }
        }

        handler.post(object : Runnable {
            override fun run() {
                statusText.text = if (JarvisLinkService.connected) "Online" else "Offline"
                statusText.setTextColor(
                    if (JarvisLinkService.connected) 0xFF37FF8B.toInt() else 0xFFFF4D6D.toInt()
                )
                if (JarvisLinkService.lastLog.isNotBlank()) {
                    // refresh last line only when changed
                }
                handler.postDelayed(this, 1000)
            }
        })
    }

    private fun appendLog(line: String) {
        logView.append(line + "\n")
    }
}
