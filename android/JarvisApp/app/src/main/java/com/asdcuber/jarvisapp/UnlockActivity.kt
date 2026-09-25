package com.asdcuber.jarvisapp

import android.app.Activity
import android.app.KeyguardManager
import android.os.Build
import android.os.Bundle
import android.view.WindowManager
import android.widget.Toast

/** Brings screen up and requests keyguard dismiss when Android allows it. */
class UnlockActivity : Activity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        window.addFlags(
            WindowManager.LayoutParams.FLAG_SHOW_WHEN_LOCKED or
                WindowManager.LayoutParams.FLAG_TURN_SCREEN_ON or
                WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON
        )
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O_MR1) {
            setShowWhenLocked(true)
            setTurnScreenOn(true)
        }
        val km = getSystemService(KEYGUARD_SERVICE) as KeyguardManager
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            km.requestDismissKeyguard(this, object : KeyguardManager.KeyguardDismissCallback() {
                override fun onDismissSucceeded() {
                    Toast.makeText(this@UnlockActivity, "Unlocked", Toast.LENGTH_SHORT).show()
                    finish()
                }
                override fun onDismissCancelled() {
                    Toast.makeText(
                        this@UnlockActivity,
                        "Unlock cancelled — enter PIN/biometric",
                        Toast.LENGTH_SHORT
                    ).show()
                    finish()
                }
                override fun onDismissError() {
                    Toast.makeText(
                        this@UnlockActivity,
                        "Secure lock cannot be bypassed by apps",
                        Toast.LENGTH_SHORT
                    ).show()
                    finish()
                }
            })
        } else {
            finish()
        }
    }
}
