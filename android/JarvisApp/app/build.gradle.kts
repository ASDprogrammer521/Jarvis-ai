plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}

android {
    namespace = "com.asdcuber.jarvisapp"
    compileSdk = 34

    defaultConfig {
        applicationId = "com.asdcuber.jarvisapp"
        minSdk = 26
        targetSdk = 34
        versionCode = 1
        versionName = "1.0.0"
    }

    signingConfigs {
        create("jarvisRelease") {
            val store = System.getenv("JARVIS_KEYSTORE")
            if (!store.isNullOrBlank()) {
                storeFile = rootProject.file(store)
                storePassword = System.getenv("JARVIS_STORE_PASSWORD")
                keyAlias = System.getenv("JARVIS_KEY_ALIAS")
                keyPassword = System.getenv("JARVIS_KEY_PASSWORD")
            }
        }
    }

    buildTypes {
        release {
            signingConfig = signingConfigs.getByName("jarvisRelease")
            isMinifyEnabled = false
            proguardFiles(
                getDefaultProguardFile("proguard-android-optimize.txt"),
                "proguard-rules.pro"
            )
        }
    }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions {
        jvmTarget = "17"
    }
}

dependencies {
    implementation("androidx.core:core-ktx:1.12.0")
    implementation("androidx.appcompat:appcompat:1.6.1")
    implementation("com.google.android.material:material:1.11.0")
    implementation("androidx.constraintlayout:constraintlayout:2.1.4")
    implementation("org.java-websocket:Java-WebSocket:1.5.6")
    implementation("org.jetbrains.kotlinx:kotlinx-coroutines-android:1.7.3")
}

// by ASDcuber521

// Fail closed: never distribute an unsigned APK as a production release.
gradle.taskGraph.whenReady {
    if (allTasks.any { it.name.contains("Release", ignoreCase = true) }) {
        listOf("JARVIS_KEYSTORE", "JARVIS_STORE_PASSWORD", "JARVIS_KEY_ALIAS", "JARVIS_KEY_PASSWORD").forEach {
            require(!System.getenv(it).isNullOrBlank()) { "Missing release signing environment: $it" }
        }
    }
}
