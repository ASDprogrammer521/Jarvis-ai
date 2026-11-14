package com.asdcuber.jarvisapp

import android.content.Context
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import android.util.Base64
import java.security.KeyStore
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec

/**
 * Keeps the phone's own unlock secret (PIN / password / pattern) ON THE PHONE ONLY.
 * It is encrypted with a non-exportable Android Keystore key and never sent to the PC or over the network.
 */
object UnlockVault {
    const val KIND_PIN = "pin"
    const val KIND_PASSWORD = "password"
    const val KIND_PATTERN = "pattern"      // secret = dot numbers 1..9 in drawing order, e.g. "14753"

    private const val ALIAS = "jarvis_phone_unlock_key"
    private const val PREFS = "jarvis_phone_unlock"

    private fun key(): SecretKey {
        val ks = KeyStore.getInstance("AndroidKeyStore").apply { load(null) }
        (ks.getKey(ALIAS, null) as? SecretKey)?.let { return it }
        val gen = KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore")
        gen.init(
            KeyGenParameterSpec.Builder(
                ALIAS, KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT
            )
                .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
                .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
                .setKeySize(256)
                .build()
        )
        return gen.generateKey()
    }

    fun save(context: Context, kind: String, secret: String) {
        val c = Cipher.getInstance("AES/GCM/NoPadding")
        c.init(Cipher.ENCRYPT_MODE, key())
        val ct = c.doFinal(secret.toByteArray(Charsets.UTF_8))
        val blob = Base64.encodeToString(c.iv, Base64.NO_WRAP) + ":" + Base64.encodeToString(ct, Base64.NO_WRAP)
        context.getSharedPreferences(PREFS, Context.MODE_PRIVATE).edit()
            .putString("kind", kind).putString("blob", blob).apply()
    }

    fun kind(context: Context): String? =
        context.getSharedPreferences(PREFS, Context.MODE_PRIVATE).getString("kind", null)

    fun isConfigured(context: Context): Boolean =
        kind(context) != null && context.getSharedPreferences(PREFS, Context.MODE_PRIVATE).contains("blob")

    fun secret(context: Context): String? {
        val blob = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE).getString("blob", null) ?: return null
        return try {
            val (iv, ct) = blob.split(":").let {
                Base64.decode(it[0], Base64.NO_WRAP) to Base64.decode(it[1], Base64.NO_WRAP)
            }
            val c = Cipher.getInstance("AES/GCM/NoPadding")
            c.init(Cipher.DECRYPT_MODE, key(), GCMParameterSpec(128, iv))
            String(c.doFinal(ct), Charsets.UTF_8)
        } catch (_: Exception) {
            null
        }
    }

    fun clear(context: Context) {
        context.getSharedPreferences(PREFS, Context.MODE_PRIVATE).edit().clear().apply()
    }
}
