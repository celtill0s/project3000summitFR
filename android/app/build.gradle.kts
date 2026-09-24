// Appli Android autonome (vue web intégrée) : ne dépend d'aucun navigateur installé.
// Aucune dépendance externe : uniquement les API du SDK Android.
plugins {
    id("com.android.application")
}

// Numéro de version dérivé du tag de release (v1.2.3 → versionName 1.2.3, versionCode 10203),
// transmis par la CI ; valeurs par défaut pour un build local.
val appVersionName: String = (project.findProperty("appVersionName") as String?) ?: "0.0.0-dev"
val appVersionCode: Int = (project.findProperty("appVersionCode") as String?)?.toInt() ?: 1
// Adresse préremplie sur l'écran de connexion. Vide par défaut : aucune adresse d'instance dans
// le code public. La CI peut en fournir une (variable de dépôt DEFAULT_SERVER_URL), mais elle
// est alors lisible dans l'APK publié.
val defaultServerUrl: String = (project.findProperty("defaultServerUrl") as String?) ?: ""

android {
    namespace = "io.github.celtill0s.sommets3000"
    compileSdk = 36

    defaultConfig {
        applicationId = "io.github.celtill0s.sommets3000"
        minSdk = 29
        targetSdk = 36
        versionCode = appVersionCode
        versionName = appVersionName
        buildConfigField("String", "DEFAULT_SERVER_URL", "\"$defaultServerUrl\"")
    }

    buildFeatures {
        buildConfig = true
    }

    // Signature de release : clé fournie par la CI (secrets GitHub), jamais dans le dépôt.
    val keystorePath = System.getenv("ANDROID_KEYSTORE_PATH")
    signingConfigs {
        if (keystorePath != null) {
            create("release") {
                storeFile = file(keystorePath)
                storePassword = System.getenv("ANDROID_KEYSTORE_PASSWORD")
                keyAlias = System.getenv("ANDROID_KEY_ALIAS")
                keyPassword = System.getenv("ANDROID_KEY_PASSWORD")
            }
        }
    }

    buildTypes {
        release {
            isMinifyEnabled = false
            if (keystorePath != null) signingConfig = signingConfigs.getByName("release")
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
}
