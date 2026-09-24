package io.github.celtill0s.sommets3000;

import org.json.JSONObject;

import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.util.List;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * Connexion et déconnexion auprès du serveur (appels bloquants : jamais sur le thread UI).
 * Une fois connecté, c'est la vue web qui porte la session (cookie), y compris pour le service
 * worker : l'appli n'a plus à intervenir dans les requêtes.
 */
final class AuthHttp {
    private AuthHttp() {}

    /** Résultat d'une tentative de connexion. */
    static final class LoginResult {
        enum Status { OK, BAD_CREDENTIALS, THROTTLED, NOT_THIS_APP, NETWORK_ERROR }

        final Status status;
        final String token;   // si OK
        final String message; // si THROTTLED : message du serveur (délai)

        LoginResult(Status status, String token, String message) {
            this.status = status;
            this.token = token;
            this.message = message;
        }
    }

    private static final Pattern SESSION_COOKIE = Pattern.compile("(?:^|;\\s*)session=([^;]+)");
    // En-tête exigé par le serveur sur toute écriture (protection contre les requêtes forgées).
    private static final String CSRF_HEADER = "X-Requested-With";
    private static final String CSRF_VALUE = "SommetsApp";

    static LoginResult login(String serverUrl, String username, String password) {
        HttpURLConnection conn = null;
        try {
            conn = (HttpURLConnection) new URL(serverUrl + "/api/login").openConnection();
            conn.setConnectTimeout(15000);
            conn.setReadTimeout(30000);
            conn.setRequestMethod("POST");
            conn.setDoOutput(true);
            conn.setRequestProperty("Content-Type", "application/json");
            conn.setRequestProperty(CSRF_HEADER, CSRF_VALUE);
            byte[] body = new JSONObject().put("username", username).put("password", password)
                    .toString().getBytes(StandardCharsets.UTF_8);
            try (OutputStream out = conn.getOutputStream()) {
                out.write(body);
            }
            int code = conn.getResponseCode();
            if (code == 401) return new LoginResult(LoginResult.Status.BAD_CREDENTIALS, null, null);
            if (code == 429) {
                String msg = new JSONObject(new String(conn.getErrorStream().readAllBytes(), StandardCharsets.UTF_8))
                        .optString("error", "réessaie plus tard");
                return new LoginResult(LoginResult.Status.THROTTLED, null, msg);
            }
            if (code != 200) return new LoginResult(LoginResult.Status.NOT_THIS_APP, null, null);
            List<String> cookies = conn.getHeaderFields().get("Set-Cookie");
            if (cookies != null) {
                for (String c : cookies) {
                    Matcher m = SESSION_COOKIE.matcher(c);
                    if (m.find()) return new LoginResult(LoginResult.Status.OK, m.group(1), null);
                }
            }
            return new LoginResult(LoginResult.Status.NOT_THIS_APP, null, null);
        } catch (Exception e) {
            return new LoginResult(LoginResult.Status.NETWORK_ERROR, null, null);
        } finally {
            if (conn != null) conn.disconnect();
        }
    }

    /** Ferme la session côté serveur (au mieux : hors-ligne, elle expirera d'elle-même). */
    static void logout(Credentials c) {
        HttpURLConnection conn = null;
        try {
            conn = (HttpURLConnection) new URL(c.serverUrl + "/api/logout").openConnection();
            conn.setConnectTimeout(10000);
            conn.setReadTimeout(10000);
            conn.setRequestMethod("POST");
            conn.setRequestProperty(CSRF_HEADER, CSRF_VALUE);
            conn.setRequestProperty("Cookie", "session=" + c.token);
            conn.setFixedLengthStreamingMode(0);
            conn.setDoOutput(true);
            conn.getOutputStream().close();
            conn.getResponseCode();
        } catch (Exception ignored) {
            // pas de réseau : tant pis, le jeton est de toute façon oublié par l'appli
        } finally {
            if (conn != null) conn.disconnect();
        }
    }
}
