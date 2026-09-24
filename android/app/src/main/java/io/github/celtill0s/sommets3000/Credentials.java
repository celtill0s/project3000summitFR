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
 * Session mémorisée sur l'appareil : adresse du serveur, identifiant, et jeton de session (le
 * mot de passe, lui, n'est jamais conservé). Le jeton est chiffré (AES-GCM) avec une clé du
 * coffre Android (AndroidKeyStore), qui ne quitte jamais le matériel sécurisé du téléphone ; les
 * préférences ne sont pas sauvegardées dans le cloud (allowBackup="false").
 */
final class Credentials {
    private static final String PREFS = "auth";
    private static final String KEY_ALIAS = "sommets3000-credentials";

    final String serverUrl; // ex. https://sommets.example.org (sans / final)
    final String username;
    final String token;     // cookie « session » délivré par le serveur à la connexion

    Credentials(String serverUrl, String username, String token) {
        this.serverUrl = serverUrl;
        this.username = username;
        this.token = token;
    }

    String host() {
        return Uri.parse(serverUrl).getHost();
    }

    /**
     * Cookie de session, au format attendu par CookieManager. « Secure » dès que l'adresse est en
     * HTTPS (toujours le cas en release) ; omis pour http://localhost, accepté uniquement par les
     * builds de debug pour les tests, où la vue web refuserait sinon d'envoyer le cookie.
     */
    String sessionCookie() {
        String secure = serverUrl.startsWith("https://") ? "; Secure" : "";
        return "session=" + token + "; Path=/; HttpOnly; SameSite=Lax" + secure;
    }

    static Credentials load(Context ctx) {
        SharedPreferences p = ctx.getSharedPreferences(PREFS, Context.MODE_PRIVATE);
        String url = p.getString("url", null);
        String user = p.getString("user", null);
        if (p.contains("pw_ct")) {
            // Versions d'avant les comptes : mot de passe Basic Auth, plus utilisé → reconnexion.
            p.edit().remove("pw_iv").remove("pw_ct").apply();
        }
        String iv = p.getString("tok_iv", null);
        String ct = p.getString("tok_ct", null);
        if (url == null || user == null || iv == null || ct == null) return null;
        try {
            Cipher c = Cipher.getInstance("AES/GCM/NoPadding");
            c.init(Cipher.DECRYPT_MODE, key(), new GCMParameterSpec(128, Base64.decode(iv, Base64.NO_WRAP)));
            String token = new String(c.doFinal(Base64.decode(ct, Base64.NO_WRAP)), StandardCharsets.UTF_8);
            return new Credentials(url, user, token);
        } catch (Exception e) {
            // Clé du coffre perdue (réinitialisation, restauration…) : on redemande la connexion.
            clear(ctx);
            return null;
        }
    }

    void save(Context ctx) throws Exception {
        Cipher c = Cipher.getInstance("AES/GCM/NoPadding");
        c.init(Cipher.ENCRYPT_MODE, key());
        byte[] ct = c.doFinal(token.getBytes(StandardCharsets.UTF_8));
        ctx.getSharedPreferences(PREFS, Context.MODE_PRIVATE).edit()
                .putString("url", serverUrl)
                .putString("user", username)
                .putString("tok_iv", Base64.encodeToString(c.getIV(), Base64.NO_WRAP))
                .putString("tok_ct", Base64.encodeToString(ct, Base64.NO_WRAP))
                .apply();
    }

    /** Déconnexion : oublie le jeton (l'adresse et l'identifiant restent préremplis). */
    static void clear(Context ctx) {
        ctx.getSharedPreferences(PREFS, Context.MODE_PRIVATE).edit()
                .remove("tok_iv").remove("tok_ct").apply();
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
