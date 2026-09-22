package com.asdcuber.jarvisapp

import android.app.admin.DeviceAdminReceiver
import android.content.Context
import android.content.Intent

class JarvisDeviceAdmin : DeviceAdminReceiver() {
    override fun onEnabled(context: Context, intent: Intent) {
        super.onEnabled(context, intent)
    }
}
