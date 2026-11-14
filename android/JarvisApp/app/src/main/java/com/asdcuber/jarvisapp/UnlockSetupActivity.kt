package com.asdcuber.jarvisapp

import android.app.Activity
import android.content.Context
import android.content.Intent
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import android.os.Bundle
import android.provider.Settings
import android.text.InputType
import android.view.Gravity
import android.view.MotionEvent
import android.view.View
import android.view.WindowManager
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView
import android.widget.Toast
import kotlin.math.hypot

/**
 * "Unlock setup": tell Jarvis the code that unlocks THIS phone, so a spoken / PC "unlock" can enter it.
 * The secret is stored encrypted on the phone (Android Keystore) and never leaves it.
 */
class UnlockSetupActivity : Activity() {

    private lateinit var status: TextView
    private lateinit var a11yStatus: TextView
    private lateinit var secretBox: LinearLayout
    private lateinit var input1: EditText
    private lateinit var input2: EditText
    private lateinit var patternView: PatternView
    private lateinit var patternHint: TextView
    private val chips = HashMap<Int, TextView>()
    private var kind = 1001                       // 1001 PIN · 1002 password · 1003 pattern
    private var firstPattern: String? = null

    private fun dp(v: Int) = (v * resources.displayMetrics.density).toInt()
    private fun col(id: Int) = androidx.core.content.ContextCompat.getColor(this, id)

    private fun text(t: String, size: Float, color: Int, bold: Boolean = false) = TextView(this).apply {
        text = t; textSize = size; setTextColor(color)
        if (bold) setTypeface(typeface, android.graphics.Typeface.BOLD)
        setLineSpacing(dp(2).toFloat(), 1f)
    }

    private fun card(vararg views: View) = LinearLayout(this).apply {
        orientation = LinearLayout.VERTICAL
        setBackgroundResource(R.drawable.bg_card)
        setPadding(dp(18), dp(16), dp(18), dp(18))
        views.forEach { addView(it) }
        layoutParams = LinearLayout.LayoutParams(-1, -2).apply { topMargin = dp(12) }
    }

    private fun section(t: String) = text(t, 11f, col(R.color.muted), true).apply {
        letterSpacing = 0.14f
        setCompoundDrawablesWithIntrinsicBounds(R.drawable.ic_label_dot, 0, 0, 0)
        compoundDrawablePadding = dp(8)
        setPadding(0, 0, 0, dp(8))
    }

    private fun button(t: String, primary: Boolean, onClick: () -> Unit) = TextView(this).apply {
        text = t; gravity = Gravity.CENTER; textSize = 14f
        setTypeface(typeface, android.graphics.Typeface.BOLD)
        setTextColor(if (primary) Color.WHITE else col(R.color.text_dim))
        setBackgroundResource(if (primary) R.drawable.bg_btn_primary else R.drawable.bg_btn_ghost)
        isClickable = true; isFocusable = true
        setOnClickListener { onClick() }
        layoutParams = LinearLayout.LayoutParams(-1, dp(50)).apply { topMargin = dp(10) }
    }

    private fun field(hintText: String) = EditText(this).apply {
        hint = hintText; textSize = 15f
        setTextColor(col(R.color.text)); setHintTextColor(col(R.color.muted))
        setBackgroundResource(R.drawable.bg_input)
        setPadding(dp(16), 0, dp(16), 0)
        isSingleLine = true
        layoutParams = LinearLayout.LayoutParams(-1, dp(52)).apply { topMargin = dp(10) }
    }

    private fun chip(label: String, id: Int) = TextView(this).apply {
        text = label; gravity = Gravity.CENTER; textSize = 13f
        isClickable = true; isFocusable = true
        layoutParams = LinearLayout.LayoutParams(0, dp(44), 1f).apply { marginEnd = dp(8) }
        setOnClickListener { selectKind(id) }
        chips[id] = this
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        window.addFlags(WindowManager.LayoutParams.FLAG_SECURE)   // no screenshots of the secret being typed

        val root = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(dp(16), dp(20), dp(16), dp(28))
        }
        root.addView(text("🔓  Phone unlock", 24f, col(R.color.text), true))
        root.addView(text(
            "Let Jarvis unlock this phone: it draws your pattern, taps your PIN or types your password on the lock screen. " +
                "The code is stored encrypted on this phone only and is never sent to the PC.",
            13f, col(R.color.muted)).apply { setPadding(0, dp(6), 0, dp(4)) })

        // step 1 — accessibility
        a11yStatus = text("", 13f, col(R.color.text_dim), true)
        root.addView(card(
            section("STEP 1 · ALLOW"),
            a11yStatus,
            button("Open Accessibility settings", true) { startActivity(Intent(Settings.ACTION_ACCESSIBILITY_SETTINGS)) },
            text("Turn on “Jarvis phone unlock”. If Android says “Restricted setting”: Settings → Apps → Jarvis App → ⋮ → " +
                "Allow restricted settings, then try again.", 11f, col(R.color.muted)).apply { setPadding(0, dp(10), 0, 0) }
        ))

        // step 2 — type + secret
        val chipRow = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            addView(chip("PIN", 1001)); addView(chip("Password", 1002)); addView(chip("Pattern", 1003))
            (getChildAt(2).layoutParams as LinearLayout.LayoutParams).marginEnd = 0
        }
        input1 = field("Enter it"); input2 = field("Enter it again")
        secretBox = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            addView(input1); addView(input2)
        }
        patternHint = text("Draw your unlock pattern (at least 4 dots)", 13f, col(R.color.text_dim)).apply {
            gravity = Gravity.CENTER; setPadding(0, dp(12), 0, dp(8))
        }
        patternView = PatternView(this).apply {
            layoutParams = LinearLayout.LayoutParams(dp(250), dp(250)).apply { gravity = Gravity.CENTER_HORIZONTAL }
            onDone = { seq -> onPatternDrawn(seq) }
        }
        root.addView(card(section("STEP 2 · WHAT UNLOCKS THIS PHONE?"), chipRow, secretBox, patternHint, patternView))

        // step 3 — save
        status = text("", 13f, col(R.color.text_dim), true).apply { gravity = Gravity.CENTER; setPadding(0, dp(12), 0, 0) }
        root.addView(card(
            section("STEP 3 · SAVE"),
            button("Save on this phone", true) { save() },
            button("Remove saved unlock code", false) {
                UnlockVault.clear(this)
                toast("Removed")
                refresh()
            },
            status
        ))
        root.addView(text(
            "Test it: lock the phone, then tell Jarvis “unlock my phone” (or press Unlock on the PC). Jarvis enters the code " +
                "only once per request, so a wrong code can’t lock you out by retrying.",
            11f, col(R.color.muted)).apply { setPadding(dp(4), dp(14), dp(4), 0) })

        setContentView(ScrollView(this).apply {
            addView(root); setBackgroundColor(col(R.color.bg)); isVerticalScrollBarEnabled = false
        })
        window.statusBarColor = col(R.color.bg)
        window.navigationBarColor = col(R.color.bar)

        selectKind(when (UnlockVault.kind(this)) {
            UnlockVault.KIND_PASSWORD -> 1002
            UnlockVault.KIND_PATTERN -> 1003
            else -> 1001
        })
    }

    override fun onResume() {
        super.onResume()
        refresh()
    }

    private fun refresh() {
        val on = JarvisAccessibilityService.isEnabled(this)
        a11yStatus.text = if (on) "●  Accessibility service is ON" else "●  Accessibility service is OFF"
        a11yStatus.setTextColor(col(if (on) R.color.green else R.color.amber))
        val saved = UnlockVault.kind(this)
        status.text = if (saved != null) "✓ Saved: $saved" else "Nothing saved yet"
        status.setTextColor(col(if (saved != null) R.color.green else R.color.muted))
    }

    private fun selectKind(id: Int) {
        kind = id
        for ((cid, v) in chips) {
            val on = cid == id
            v.setBackgroundResource(if (on) R.drawable.bg_btn_primary else R.drawable.bg_btn_ghost)
            v.setTextColor(if (on) Color.WHITE else col(R.color.text_dim))
            v.setTypeface(null, if (on) android.graphics.Typeface.BOLD else android.graphics.Typeface.NORMAL)
        }
        val pattern = id == 1003
        secretBox.visibility = if (pattern) View.GONE else View.VISIBLE
        patternView.visibility = if (pattern) View.VISIBLE else View.GONE
        patternHint.visibility = if (pattern) View.VISIBLE else View.GONE
        input1.setText(""); input2.setText("")
        val type = if (id == 1001) InputType.TYPE_CLASS_NUMBER or InputType.TYPE_NUMBER_VARIATION_PASSWORD
        else InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_VARIATION_PASSWORD
        input1.inputType = type; input2.inputType = type
        firstPattern = null
        patternView.reset()
        patternHint.text = "Draw your unlock pattern (at least 4 dots)"
    }

    private fun onPatternDrawn(seq: String) {
        if (seq.length < 4) {
            patternHint.text = "Too short — connect at least 4 dots"
            patternView.reset(); return
        }
        val first = firstPattern
        if (first == null) {
            firstPattern = seq
            patternHint.text = "Draw it once more to confirm"
            patternView.reset()
        } else if (first == seq) {
            patternHint.text = "Pattern confirmed — press Save"
        } else {
            firstPattern = null
            patternHint.text = "Didn't match — draw your pattern again"
            patternView.reset()
        }
    }

    private fun save() {
        when (kind) {
            1003 -> {
                val p = firstPattern
                if (p == null || p != patternView.sequence()) {
                    toast("Draw the pattern twice first"); return
                }
                UnlockVault.save(this, UnlockVault.KIND_PATTERN, p)
            }
            else -> {
                val a = input1.text.toString()
                val b = input2.text.toString()
                val pin = kind == 1001
                if (a != b) { toast("The two entries don't match"); return }
                if (pin && (a.length < 4 || !a.all { it.isDigit() })) { toast("A PIN is digits only, at least 4"); return }
                if (!pin && a.length < 4) { toast("Password is too short"); return }
                UnlockVault.save(this, if (pin) UnlockVault.KIND_PIN else UnlockVault.KIND_PASSWORD, a)
                input1.setText(""); input2.setText("")
            }
        }
        toast("Saved on this phone ✅")
        refresh()
    }

    private fun toast(t: String) = Toast.makeText(this, t, Toast.LENGTH_SHORT).show()

    /** 3×3 dot grid; reports the dots touched, in order, as digits 1..9 (row by row). */
    class PatternView(context: Context) : View(context) {
        var onDone: ((String) -> Unit)? = null
        private val order = ArrayList<Int>()
        private var fx = 0f
        private var fy = 0f
        private var drawing = false
        private val dot = Paint(Paint.ANTI_ALIAS_FLAG).apply { color = Color.parseColor("#7384A5") }
        private val hit = Paint(Paint.ANTI_ALIAS_FLAG).apply { color = Color.parseColor("#38BDF8") }
        private val line = Paint(Paint.ANTI_ALIAS_FLAG).apply {
            color = Color.parseColor("#38BDF8"); strokeWidth = 8f; strokeCap = Paint.Cap.ROUND
        }

        fun sequence(): String = order.joinToString("") { (it + 1).toString() }
        fun reset() { order.clear(); drawing = false; invalidate() }

        private fun cx(i: Int) = width * ((i % 3) + 0.5f) / 3f
        private fun cy(i: Int) = height * ((i / 3) + 0.5f) / 3f

        override fun onTouchEvent(e: MotionEvent): Boolean {
            when (e.action) {
                MotionEvent.ACTION_DOWN -> { reset(); drawing = true; parent.requestDisallowInterceptTouchEvent(true) }
                MotionEvent.ACTION_UP, MotionEvent.ACTION_CANCEL -> {
                    drawing = false; invalidate()
                    if (order.isNotEmpty()) onDone?.invoke(sequence())
                    return true
                }
            }
            if (!drawing) return true
            fx = e.x; fy = e.y
            for (i in 0 until 9) {
                if (i !in order && hypot(fx - cx(i), fy - cy(i)) < width / 9f) order.add(i)
            }
            invalidate()
            return true
        }

        override fun onDraw(c: Canvas) {
            for (k in 1 until order.size) c.drawLine(cx(order[k - 1]), cy(order[k - 1]), cx(order[k]), cy(order[k]), line)
            if (drawing && order.isNotEmpty()) c.drawLine(cx(order.last()), cy(order.last()), fx, fy, line)
            for (i in 0 until 9) c.drawCircle(cx(i), cy(i), if (i in order) 18f else 12f, if (i in order) hit else dot)
        }
    }
}

// by ASDcuber521
