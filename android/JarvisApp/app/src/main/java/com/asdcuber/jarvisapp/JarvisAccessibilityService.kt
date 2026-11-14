package com.asdcuber.jarvisapp

import android.accessibilityservice.AccessibilityService
import android.accessibilityservice.GestureDescription
import android.app.KeyguardManager
import android.content.ComponentName
import android.content.Context
import android.graphics.Path
import android.graphics.Rect
import android.os.Build
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.os.PowerManager
import android.provider.Settings
import android.util.Log
import android.view.accessibility.AccessibilityEvent
import android.view.accessibility.AccessibilityNodeInfo
import android.widget.Toast

/**
 * Lets Jarvis unlock the phone the way the owner would: swipe up, then draw the saved pattern / tap the saved PIN /
 * type the saved password on the lock screen. It only acts when the paired PC sends "unlock", and it submits the
 * secret exactly ONCE per request, so a wrong stored secret can never burn through the phone's attempt limit.
 */
class JarvisAccessibilityService : AccessibilityService() {

    companion object {
        @Volatile var instance: JarvisAccessibilityService? = null
        private const val TAG = "JarvisUnlock"
        private const val SYSTEMUI_ID = "com.android.systemui:id/"

        fun isEnabled(context: Context): Boolean {
            val me = ComponentName(context, JarvisAccessibilityService::class.java).flattenToString()
            val enabled = Settings.Secure.getString(
                context.contentResolver, Settings.Secure.ENABLED_ACCESSIBILITY_SERVICES
            ) ?: return false
            return enabled.split(':').any { it.equals(me, ignoreCase = true) }
        }
    }

    private val handler = Handler(Looper.getMainLooper())
    private var running = false

    override fun onServiceConnected() {
        super.onServiceConnected()
        instance = this
    }

    override fun onUnbind(intent: android.content.Intent?): Boolean {
        if (instance === this) instance = null
        return super.onUnbind(intent)
    }

    override fun onDestroy() {
        if (instance === this) instance = null
        super.onDestroy()
    }

    override fun onAccessibilityEvent(event: AccessibilityEvent?) {}
    override fun onInterrupt() {}

    // ── public entry point ───────────────────────────────────────────────────────────
    fun startUnlock(): String {
        val kind = UnlockVault.kind(this) ?: return "Phone unlock is not set up — open Jarvis App → Unlock setup."
        val secret = UnlockVault.secret(this) ?: return "The saved unlock secret can't be read — set it up again."
        if (running) return "Unlock already in progress"
        running = true
        wakeScreen()
        val km = getSystemService(Context.KEYGUARD_SERVICE) as KeyguardManager
        handler.postDelayed({
            if (!km.isKeyguardLocked) {
                finish("Phone is already unlocked", toast = false)
                return@postDelayed
            }
            swipeUp()
            handler.postDelayed({ attempt(kind, secret, 0) }, 700)
        }, 600)
        return "Unlocking the phone ($kind)…"
    }

    // ── steps ────────────────────────────────────────────────────────────────────────
    private fun wakeScreen() {
        try {
            val pm = getSystemService(Context.POWER_SERVICE) as PowerManager
            @Suppress("DEPRECATION")
            val wl = pm.newWakeLock(
                PowerManager.SCREEN_BRIGHT_WAKE_LOCK or PowerManager.ACQUIRE_CAUSES_WAKEUP or PowerManager.ON_AFTER_RELEASE,
                "jarvis:unlock"
            )
            wl.acquire(15_000)
        } catch (e: Exception) {
            Log.w(TAG, "wake failed: ${e.message}")
        }
    }

    private fun swipeUp() {
        val dm = resources.displayMetrics
        val x = dm.widthPixels / 2f
        val p = Path().apply {
            moveTo(x, dm.heightPixels * 0.85f)
            lineTo(x, dm.heightPixels * 0.25f)
        }
        gesture(p, 280)
    }

    private fun gesture(path: Path, durationMs: Long, done: ((Boolean) -> Unit)? = null) {
        val g = GestureDescription.Builder()
            .addStroke(GestureDescription.StrokeDescription(path, 0, durationMs.coerceAtLeast(1)))
            .build()
        val ok = dispatchGesture(g, object : GestureResultCallback() {
            override fun onCompleted(d: GestureDescription?) { done?.invoke(true) }
            override fun onCancelled(d: GestureDescription?) { done?.invoke(false) }
        }, null)
        if (!ok) done?.invoke(false)
    }

    private fun attempt(kind: String, secret: String, n: Int) {
        val roots = keyguardRoots()
        val handled = when (kind) {
            UnlockVault.KIND_PATTERN -> drawPattern(roots, secret)
            UnlockVault.KIND_PIN -> typePin(roots, secret)
            UnlockVault.KIND_PASSWORD -> typePassword(roots, secret)
            else -> false
        }
        if (handled) return
        if (n >= 14) {
            finish("Couldn't find the lock-screen input (${kind}). Is the screen on and the lock type the same as in the setup?")
            return
        }
        if (n == 5 || n == 10) swipeUp()                       // the keypad sometimes needs a second swipe
        handler.postDelayed({ attempt(kind, secret, n + 1) }, 450)
    }

    /** Root nodes of the keyguard / system UI windows only — never read or touch other apps. */
    private fun keyguardRoots(): List<AccessibilityNodeInfo> {
        val out = ArrayList<AccessibilityNodeInfo>()
        try {
            for (w in windows) {
                val r = w.root ?: continue
                val pkg = r.packageName?.toString() ?: ""
                if (pkg.contains("systemui") || pkg.contains("keyguard")) out.add(r)
            }
            if (out.isEmpty()) {
                rootInActiveWindow?.let {
                    val pkg = it.packageName?.toString() ?: ""
                    if (pkg.contains("systemui") || pkg.contains("keyguard")) out.add(it)
                }
            }
        } catch (e: Exception) {
            Log.w(TAG, "windows: ${e.message}")
        }
        return out
    }

    private fun byId(roots: List<AccessibilityNodeInfo>, shortId: String): AccessibilityNodeInfo? {
        for (r in roots) {
            val l = r.findAccessibilityNodeInfosByViewId(SYSTEMUI_ID + shortId)
            if (!l.isNullOrEmpty()) return l[0]
        }
        return null
    }

    private fun findNode(n: AccessibilityNodeInfo?, depth: Int = 0, pred: (AccessibilityNodeInfo) -> Boolean): AccessibilityNodeInfo? {
        if (n == null || depth > 25) return null
        if (pred(n)) return n
        for (i in 0 until n.childCount) {
            findNode(n.getChild(i), depth + 1, pred)?.let { return it }
        }
        return null
    }

    private fun findIn(roots: List<AccessibilityNodeInfo>, pred: (AccessibilityNodeInfo) -> Boolean): AccessibilityNodeInfo? {
        for (r in roots) findNode(r, 0, pred)?.let { return it }
        return null
    }

    // ── pattern ──────────────────────────────────────────────────────────────────────
    private fun drawPattern(roots: List<AccessibilityNodeInfo>, secret: String): Boolean {
        val view = byId(roots, "lockPatternView")
            ?: findIn(roots) { it.className?.toString()?.contains("LockPatternView") == true }
            ?: return false
        val b = Rect().also { view.getBoundsInScreen(it) }
        if (b.width() < 100 || b.height() < 100) return false
        val dots = secret.filter { it in '1'..'9' }.map { it - '1' }
        if (dots.size < 2) { finish("The saved pattern is invalid — set it up again."); return true }
        val cw = b.width() / 3f
        val ch = b.height() / 3f
        val path = Path()
        dots.forEachIndexed { i, d ->
            val x = b.left + (d % 3 + 0.5f) * cw
            val y = b.top + (d / 3 + 0.5f) * ch
            if (i == 0) path.moveTo(x, y) else path.lineTo(x, y)
        }
        gesture(path, 220L * dots.size + 200) { ok ->
            if (!ok) finish("Pattern gesture was cancelled by the system.")
            else handler.postDelayed({ verify() }, 1200)
        }
        return true
    }

    // ── PIN ──────────────────────────────────────────────────────────────────────────
    private fun typePin(roots: List<AccessibilityNodeInfo>, secret: String): Boolean {
        val digits = secret.filter { it.isDigit() }
        if (digits.isEmpty()) { finish("The saved PIN is invalid — set it up again."); return true }
        // every digit key must be present before we start, so we never type half a PIN
        val keys = HashMap<Char, AccessibilityNodeInfo>()
        for (d in digits.toSet()) {
            val k = byId(roots, "key$d") ?: findIn(roots) { node ->
                val t = node.text?.toString()?.trim()
                val c = node.contentDescription?.toString()?.trim()
                (t == d.toString() || c == d.toString()) && node.childCount <= 1
            } ?: return false
            keys[d] = k
        }
        var delay = 0L
        for (d in digits) {
            val node = keys.getValue(d)
            handler.postDelayed({ tap(node) }, delay)
            delay += 170
        }
        handler.postDelayed({
            // many Android versions submit by themselves; for the others press Enter
            val enter = byId(keyguardRoots(), "key_enter")
                ?: findIn(keyguardRoots()) {
                    val c = it.contentDescription?.toString()?.lowercase() ?: ""
                    c == "enter" || c == "confirm" || c == "ok"
                }
            if (enter != null) tap(enter)
        }, delay + 150)
        handler.postDelayed({ verify() }, delay + 1500)
        return true
    }

    // ── password ─────────────────────────────────────────────────────────────────────
    private fun typePassword(roots: List<AccessibilityNodeInfo>, secret: String): Boolean {
        val field = byId(roots, "passwordEntry")
            ?: findIn(roots) { it.isEditable || it.className?.toString()?.contains("EditText") == true }
            ?: return false
        field.performAction(AccessibilityNodeInfo.ACTION_FOCUS)
        val args = Bundle().apply {
            putCharSequence(AccessibilityNodeInfo.ACTION_ARGUMENT_SET_TEXT_CHARSEQUENCE, secret)
        }
        if (!field.performAction(AccessibilityNodeInfo.ACTION_SET_TEXT, args)) {
            finish("The lock screen refused typed text on this phone.")
            return true
        }
        handler.postDelayed({
            var sent = false
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
                sent = field.performAction(AccessibilityNodeInfo.AccessibilityAction.ACTION_IME_ENTER.id)
            }
            if (!sent) {
                val enter = byId(keyguardRoots(), "key_enter")
                    ?: findIn(keyguardRoots()) {
                        val c = it.contentDescription?.toString()?.lowercase() ?: ""
                        c == "enter" || c == "confirm" || c == "ok"
                    }
                if (enter != null) tap(enter)
            }
        }, 300)
        handler.postDelayed({ verify() }, 1800)
        return true
    }

    // ── helpers ──────────────────────────────────────────────────────────────────────
    private fun tap(node: AccessibilityNodeInfo) {
        var n: AccessibilityNodeInfo? = node
        var depth = 0
        while (n != null && depth < 4) {
            if (n.isClickable && n.performAction(AccessibilityNodeInfo.ACTION_CLICK)) return
            n = n.parent
            depth++
        }
        val b = Rect().also { node.getBoundsInScreen(it) }
        val p = Path().apply { moveTo(b.exactCenterX(), b.exactCenterY()) }
        gesture(p, 60)
    }

    private fun verify() {
        val km = getSystemService(Context.KEYGUARD_SERVICE) as KeyguardManager
        if (!km.isKeyguardLocked) finish("Phone unlocked ✅")
        else finish("Sent the saved secret, but the phone is still locked — check it in Unlock setup.")
    }

    private fun finish(msg: String, toast: Boolean = true) {
        running = false
        Log.i(TAG, msg)
        if (toast) Toast.makeText(applicationContext, msg, Toast.LENGTH_LONG).show()
    }
}

// by ASDcuber521
