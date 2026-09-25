package com.asdcuber.jarvisapp

import android.app.Activity
import android.content.Context
import android.content.Intent
import android.graphics.Bitmap
import android.graphics.PixelFormat
import android.hardware.display.DisplayManager
import android.hardware.display.VirtualDisplay
import android.media.ImageReader
import android.media.projection.MediaProjection
import android.media.projection.MediaProjectionManager
import android.os.Bundle
import android.os.Environment
import android.os.Handler
import android.os.Looper
import android.util.DisplayMetrics
import android.widget.Toast
import java.io.File
import java.io.FileOutputStream

/**
 * One-shot screen capture via MediaProjection (user must approve once per session).
 */
class ScreenshotActivity : Activity() {

    companion object {
        private const val REQ = 4401
    }

    private var projection: MediaProjection? = null
    private var virtualDisplay: VirtualDisplay? = null
    private var imageReader: ImageReader? = null

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val mgr = getSystemService(Context.MEDIA_PROJECTION_SERVICE) as MediaProjectionManager
        startActivityForResult(mgr.createScreenCaptureIntent(), REQ)
    }

    @Deprecated("Deprecated in Java")
    override fun onActivityResult(requestCode: Int, resultCode: Int, data: Intent?) {
        super.onActivityResult(requestCode, resultCode, data)
        if (requestCode != REQ) {
            finish(); return
        }
        if (resultCode != RESULT_OK || data == null) {
            Toast.makeText(this, "Screenshot permission denied", Toast.LENGTH_SHORT).show()
            finish(); return
        }
        val mgr = getSystemService(Context.MEDIA_PROJECTION_SERVICE) as MediaProjectionManager
        projection = mgr.getMediaProjection(resultCode, data)
        Handler(Looper.getMainLooper()).postDelayed({ capture() }, 250)
    }

    private fun capture() {
        try {
            val metrics = DisplayMetrics()
            @Suppress("DEPRECATION")
            windowManager.defaultDisplay.getRealMetrics(metrics)
            val width = metrics.widthPixels
            val height = metrics.heightPixels
            val density = metrics.densityDpi

            imageReader = ImageReader.newInstance(width, height, PixelFormat.RGBA_8888, 2)
            virtualDisplay = projection?.createVirtualDisplay(
                "jarvis_cap",
                width, height, density,
                DisplayManager.VIRTUAL_DISPLAY_FLAG_AUTO_MIRROR,
                imageReader?.surface, null, null
            )

            Handler(Looper.getMainLooper()).postDelayed({
                val img = imageReader?.acquireLatestImage()
                if (img == null) {
                    Toast.makeText(this, "Screenshot failed", Toast.LENGTH_SHORT).show()
                    cleanup(); finish(); return@postDelayed
                }
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
                val dir = getExternalFilesDir(Environment.DIRECTORY_PICTURES) ?: filesDir
                val out = File(dir, "jarvis_${System.currentTimeMillis()}.png")
                FileOutputStream(out).use { fos ->
                    cropped.compress(Bitmap.CompressFormat.PNG, 100, fos)
                }
                Toast.makeText(this, "Saved: ${out.name}", Toast.LENGTH_LONG).show()
                JarvisLinkService.sendCommand(
                    "[PHONE_SCREENSHOT] saved=${out.absolutePath}"
                )
                cleanup()
                finish()
            }, 400)
        } catch (e: Exception) {
            Toast.makeText(this, "Screenshot error: ${e.message}", Toast.LENGTH_LONG).show()
            cleanup()
            finish()
        }
    }

    private fun cleanup() {
        try { virtualDisplay?.release() } catch (_: Exception) {}
        try { imageReader?.close() } catch (_: Exception) {}
        try { projection?.stop() } catch (_: Exception) {}
    }
}
