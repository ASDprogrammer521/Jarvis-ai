package com.asdcuber.jarvisapp

import android.content.Context
import java.net.HttpURLConnection
import java.net.URL
import java.security.MessageDigest
import java.security.cert.CertificateException
import java.security.cert.X509Certificate
import javax.net.ssl.HttpsURLConnection
import javax.net.ssl.SSLContext
import javax.net.ssl.TrustManager
import javax.net.ssl.X509TrustManager

/** The PC's certificate does not change the link's mistrust of the network: Jarvis uses its own
 *  self-signed certificate, so the phone pins it. The first time a PC is paired its SHA-256
 *  fingerprint is stored (trust on first use); after that any other certificate is refused. */
class PinMismatch(msg: String) : CertificateException(msg)

object LinkTls {
    private const val PREFS = "jarvis_link"
    @Volatile var lastNote: String = ""

    private fun prefs(c: Context) = c.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
    private fun pinKey(host: String) = "cert_fp_" + host.substringBefore(":")

    fun fingerprint(cert: X509Certificate): String =
        MessageDigest.getInstance("SHA-256").digest(cert.encoded)
            .joinToString(":") { "%02X".format(it) }

    fun pinned(c: Context, host: String): String = prefs(c).getString(pinKey(host), "") ?: ""
    fun forget(c: Context, host: String) { prefs(c).edit().remove(pinKey(host)).apply() }

    fun sslContext(c: Context, host: String): SSLContext {
        val tm = object : X509TrustManager {
            override fun checkClientTrusted(chain: Array<X509Certificate>, authType: String) {}
            override fun checkServerTrusted(chain: Array<X509Certificate>, authType: String) {
                if (chain.isEmpty()) throw CertificateException("Empty certificate chain")
                val fp = fingerprint(chain[0])
                val saved = pinned(c, host)
                if (saved.isEmpty()) {
                    prefs(c).edit().putString(pinKey(host), fp).apply()
                    lastNote = "Trusted this PC's certificate (SHA-256 $fp)"
                } else if (saved != fp) {
                    throw PinMismatch(
                        "The PC's certificate changed. If you reinstalled Jarvis, tap Forget PC certificate, " +
                            "otherwise someone may be impersonating your PC."
                    )
                }
            }
            override fun getAcceptedIssuers(): Array<X509Certificate> = arrayOf()
        }
        val ctx = SSLContext.getInstance("TLS")
        ctx.init(null, arrayOf<TrustManager>(tm), null)
        return ctx
    }

    fun isPinFailure(e: Throwable?): Boolean {
        var t = e
        while (t != null) { if (t is PinMismatch) return true; t = t.cause }
        return false
    }

    fun pinMessage(e: Throwable?): String {
        var t = e
        while (t != null) { if (t is PinMismatch) return t.message ?: "Certificate changed"; t = t.cause }
        return e?.message ?: "Certificate rejected"
    }

    /** "https://host:port" or "http://host:port" — whichever the link established. */
    fun base(c: Context): String = prefs(c).getString("link_base", "") ?: ""
    fun saveBase(c: Context, base: String) { prefs(c).edit().putString("link_base", base).apply() }
    fun token(c: Context): String = prefs(c).getString("session_token", "") ?: ""

    /** Opens a URL on the PC with the right TLS pinning for the link. */
    fun open(c: Context, url: String): HttpURLConnection {
        val conn = URL(url).openConnection() as HttpURLConnection
        if (conn is HttpsURLConnection) {
            val host = URL(url).host
            conn.sslSocketFactory = sslContext(c, host).socketFactory
            conn.hostnameVerifier = javax.net.ssl.HostnameVerifier { _, _ -> true } // identity = pinned fingerprint
        }
        return conn
    }
}
