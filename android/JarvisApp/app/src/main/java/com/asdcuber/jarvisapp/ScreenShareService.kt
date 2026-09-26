
package com.asdcuber.jarvisapp

import android.app.Activity
import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.Service
import android.content.Context
import android.content.Intent
import android.graphics.Bitmap
import android.graphics.PixelFormat
import android.hardware.display.DisplayManager
import android.hardware.display.VirtualDisplay
import android.media.ImageReader
import android.media.projection.MediaProjection
import android.media.projection.MediaProjectionManager
import android.os.Build
import android.os.Handler
import android.os.IBinder
import android.os.Looper
import android.util.Base64
import android.util.DisplayMetrics
import androidx.core.app.NotificationCompat
import org.json.JSONObject
import java.io.ByteArrayOutputStream

class ScreenShareService : Service() {

    companion object {
        const val EXTRA_RESULT_CODE = "result_code"
        const val EXTRA_DATA = "data"
        private const val CH = "jarvis_share"
        private const val NID = 42
        @Volatile var running = false
    }

    private var projection: MediaProjection? = null
    private var virtualDisplay: VirtualDisplay? = null
    private var imageReader: ImageReader? = null
    private val handler = Handler(Looper.getMainLooper())
    private var width = 720
    private var height = 1280
    private var density = 320

    private val tick = object : Runnable {
        override fun run() {
            if (!running) return
            captureFrame()
            handler.postDelayed(this, 800)
        }
    }

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        val code = intent?.getIntExtra(EXTRA_RESULT_CODE, 0) ?: 0
        @Suppress("DEPRECATION")
        val data = intent?.getParcelableExtra<Intent>(EXTRA_DATA)
        if (code == 0 || data == null) {
            stopSelf()
            return START_NOT_STICKY
        }
        startForeground(NID, buildNotif())
        val mgr = getSystemService(Context.MEDIA_PROJECTION_SERVICE) as MediaProjectionManager
        projection = mgr.getMediaProjection(code, data)
        val metrics = DisplayMetrics()
        @Suppress("DEPRECATION")
        val dm = resources.displayMetrics
        // Scale down for bandwidth
        val fullW = dm.widthPixels
        val fullH = dm.heightPixels
        density = dm.densityDpi
        width = minOf(720, fullW)
        height = (fullH * (width.toFloat() / fullW)).toInt().coerceAtLeast(1)
        imageReader = ImageReader.newInstance(width, height, PixelFormat.RGBA_8888, 2)
        virtualDisplay = projection?.createVirtualDisplay(
            "jarvis_share",
            width, height, density,
            DisplayManager.VIRTUAL_DISPLAY_FLAG_AUTO_MIRROR,
            imageReader?.surface, null, null
        )
        running = true
        handler.post(tick)
        return START_STICKY
    }

    private fun captureFrame() {
        try {
            val img = imageReader?.acquireLatestImage() ?: return
            val plane = img.planes[0]
            val buffer = plane.buffer
            val pixelStride = plane.pixelStride
            val rowStride = plane.rowStride
            val rowPadding = rowStride - pixelStride * width
            val bmp = Bitmap.createBitmap(
                width + rowPadding / pixelStride,
                height,
                Bitmap.Config.ARGB_8888
            )
            bmp.copyPixelsFromBuffer(buffer)
            img.close()
            val cropped = Bitmap.createBitmap(bmp, 0, 0, width, height)
            val baos = ByteArrayOutputStream()
            cropped.compress(Bitmap.CompressFormat.JPEG, 45, baos)
            val b64 = Base64.encodeToString(baos.toByteArray(), Base64.NO_WRAP)
            val payload = JSONObject()
                .put("type", "screen_frame")
                .put("width", width)
                .put("height", height)
                .put("data", b64)
            JarvisLinkService.sendRaw(payload.toString())
        } catch (_: Exception) {
        }
    }

    private fun buildNotif(): Notification {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            val nm = getSystemService(NotificationManager::class.java)
            nm.createNotificationChannel(
                NotificationChannel(CH, "Jarvis Screen Share", NotificationManager.IMPORTANCE_LOW)
            )
        }
        return NotificationCompat.Builder(this, CH)
            .setContentTitle("Jarvis Screen Share")
            .setContentText("Sharing screen with PC")
            .setSmallIcon(android.R.drawable.ic_menu_camera)
            .setOngoing(true)
            .build()
    }

    override fun onDestroy() {
        running = false
        handler.removeCallbacks(tick)
        try { virtualDisplay?.release() } catch (_: Exception) {}
        try { imageReader?.close() } catch (_: Exception) {}
        try { projection?.stop() } catch (_: Exception) {}
        super.onDestroy()
    }
}
