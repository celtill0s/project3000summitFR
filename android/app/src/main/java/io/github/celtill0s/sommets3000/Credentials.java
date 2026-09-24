package io.github.celtill0s.sommets3000;

import android.content.Context;
import android.content.SharedPreferences;
import android.net.Uri;
import android.security.keystore.KeyGenParameterSpec;
import android.security.keystore.KeyProperties;
import android.util.Base64;

import java.nio.charset.StandardCharsets;
import java.security.KeyStore;

import javax.crypto.Cipher;
import javax.crypto.KeyGenerator;
import javax.crypto.SecretKey;
import javax.crypto.spec.GCMParameterSpec;

/**
 * Identifiants Basic Auth mémorisés sur l'appareil. Le mot de passe est chiffré (AES-GCM) avec
 * une clé du coffre Android (AndroidKeyStore), qui ne quitte jamais le matériel sécurisé du
 * téléphone ; les préférences ne sont pas sauvegardées dans le cloud (allowBackup="false").
 */
final class Credentials {
    private static final String PREFS = "auth";
    private static final String KEY_ALIAS = "sommets3000-credentials";

    final String serverUrl; // ex. https://sommets.example.org (sans / final)
    final String username;
    final String password;

    Credentials(String serverUrl, String username, String password) {
        this.serverUrl = serverUrl;
        this.username = username;
        this.password = password;
    }

    String host() {
        return Uri.parse(serverUrl).getHost();
    }

    /** Valeur de l'en-tête Authorization (Basic). */
    String authorizationHeader() {
        String raw = username + ":" + password;
        return "Basic " + Base64.encodeToString(raw.getBytes(StandardCharsets.UTF_8), Base64.NO_WRAP);
    }

    static Credentials load(Context ctx) {
        SharedPreferences p = ctx.getSharedPreferences(PREFS, Context.MODE_PRIVATE);
        String url = p.getString("url", null);
        String user = p.getString("user", null);
        String iv = p.getString("pw_iv", null);
        String ct = p.getString("pw_ct", null);
        if (url == null || user == null || iv == null || ct == null) return null;
        try {
            Cipher c = Cipher.getInstance("AES/GCM/NoPadding");
            c.init(Cipher.DECRYPT_MODE, key(), new GCMParameterSpec(128, Base64.decode(iv, Base64.NO_WRAP)));
            String pw = new String(c.doFinal(Base64.decode(ct, Base64.NO_WRAP)), StandardCharsets.UTF_8);
            return new Credentials(url, user, pw);
        } catch (Exception e) {
            // Clé du coffre perdue (réinitialisation, restauration…) : on redemande la connexion.
            clear(ctx);
            return null;
        }
    }

    void save(Context ctx) throws Exception {
        Cipher c = Cipher.getInstance("AES/GCM/NoPadding");
        c.init(Cipher.ENCRYPT_MODE, key());
        byte[] ct = c.doFinal(password.getBytes(StandardCharsets.UTF_8));
        ctx.getSharedPreferences(PREFS, Context.MODE_PRIVATE).edit()
                .putString("url", serverUrl)
                .putString("user", username)
                .putString("pw_iv", Base64.encodeToString(c.getIV(), Base64.NO_WRAP))
                .putString("pw_ct", Base64.encodeToString(ct, Base64.NO_WRAP))
                .apply();
    }

    /** Déconnexion : oublie le mot de passe (l'adresse et l'identifiant restent préremplis). */
    static void clear(Context ctx) {
        ctx.getSharedPreferences(PREFS, Context.MODE_PRIVATE).edit()
                .remove("pw_iv").remove("pw_ct").apply();
    }

    static String lastServerUrl(Context ctx) {
        return ctx.getSharedPreferences(PREFS, Context.MODE_PRIVATE).getString("url", null);
    }

    static String lastUsername(Context ctx) {
        return ctx.getSharedPreferences(PREFS, Context.MODE_PRIVATE).getString("user", null);
    }

    private static SecretKey key() throws Exception {
        KeyStore ks = KeyStore.getInstance("AndroidKeyStore");
        ks.load(null);
        if (!ks.containsAlias(KEY_ALIAS)) {
            KeyGenerator kg = KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore");
            kg.init(new KeyGenParameterSpec.Builder(KEY_ALIAS,
                    KeyProperties.PURPOSE_ENCRYPT | KeyProperties.PURPOSE_DECRYPT)
                    .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
                    .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
                    .build());
            kg.generateKey();
        }
        return (SecretKey) ks.getKey(KEY_ALIAS, null);
    }
}
