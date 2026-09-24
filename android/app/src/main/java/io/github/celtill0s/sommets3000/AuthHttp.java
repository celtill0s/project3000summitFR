package io.github.celtill0s.sommets3000;

import android.webkit.WebResourceRequest;
import android.webkit.WebResourceResponse;

import java.io.ByteArrayInputStream;
import java.io.InputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.util.HashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Set;

/**
 * Requêtes HTTP authentifiées (Basic Auth de Caddy) faites par l'appli elle-même.
 *
 * Pourquoi : la vue web ne sait répondre à un « 401 identifiants requis » que pour les requêtes
 * de la page, pas pour celles du service worker (démarrage, hors-ligne) ni de façon fiable pour
 * les vidéos. On rejoue donc nous-mêmes toutes les requêtes GET vers le serveur, avec l'en-tête
 * Authorization — Caddy vérifie exactement comme pour un navigateur.
 */
final class AuthHttp {
    private AuthHttp() {}

    enum CheckResult { OK, BAD_CREDENTIALS, NOT_THIS_APP, NETWORK_ERROR }

    /** En-têtes de requête non recopiés : gérés par HttpURLConnection, ou qui provoqueraient un
     *  304 (réponse sans corps que la vue web n'accepte pas d'une interception). */
    private static final Set<String> SKIPPED_REQUEST_HEADERS = Set.of(
            "authorization", "accept-encoding", "if-none-match", "if-modified-since", "host", "connection");
    /** En-têtes de réponse non transmis : le corps est déjà décompressé par HttpURLConnection. */
    private static final Set<String> SKIPPED_RESPONSE_HEADERS = Set.of(
            "content-encoding", "transfer-encoding", "content-length", "connection");

    /** Vérifie les identifiants sur l'écran de connexion (appel bloquant, hors thread UI). */
    static CheckResult check(Credentials c) {
        HttpURLConnection conn = null;
        try {
            conn = (HttpURLConnection) new URL(c.serverUrl + "/healthz").openConnection();
            conn.setConnectTimeout(15000);
            conn.setReadTimeout(15000);
            conn.setRequestProperty("Authorization", c.authorizationHeader());
            int code = conn.getResponseCode();
            if (code == 401 || code == 403) return CheckResult.BAD_CREDENTIALS;
            if (code != 200) return CheckResult.NOT_THIS_APP;
            // /healthz de notre backend répond {"ok": true} : évite d'accepter n'importe quel site.
            String body = new String(conn.getInputStream().readAllBytes());
            return body.contains("\"ok\"") ? CheckResult.OK : CheckResult.NOT_THIS_APP;
        } catch (Exception e) {
            return CheckResult.NETWORK_ERROR;
        } finally {
            if (conn != null) conn.disconnect();
        }
    }

    /**
     * Rejoue une requête GET de la vue web (page ou service worker) avec les identifiants.
     * Renvoie null pour laisser la vue web la traiter elle-même (autre serveur, autre méthode…).
     */
    static WebResourceResponse fetch(WebResourceRequest req, Credentials c, Runnable onUnauthorized) {
        if (!"GET".equalsIgnoreCase(req.getMethod())) return null;
        String host = req.getUrl().getHost();
        if (host == null || !host.equalsIgnoreCase(c.host())) return null;
        try {
            HttpURLConnection conn = (HttpURLConnection) new URL(req.getUrl().toString()).openConnection();
            conn.setConnectTimeout(15000);
            conn.setReadTimeout(60000);
            conn.setInstanceFollowRedirects(true);
            for (Map.Entry<String, String> h : req.getRequestHeaders().entrySet()) {
                if (!SKIPPED_REQUEST_HEADERS.contains(h.getKey().toLowerCase(Locale.ROOT))) {
                    conn.setRequestProperty(h.getKey(), h.getValue());
                }
            }
            conn.setRequestProperty("Authorization", c.authorizationHeader());
            int code = conn.getResponseCode();
            // La vue web refuse les 3xx dans une réponse interceptée : on la laisse faire.
            if (code >= 300 && code < 400) {
                conn.disconnect();
                return null;
            }
            if (code == 401) onUnauthorized.run();

            Map<String, String> headers = new HashMap<>();
            for (Map.Entry<String, List<String>> h : conn.getHeaderFields().entrySet()) {
                if (h.getKey() == null) continue; // ligne de statut
                if (SKIPPED_RESPONSE_HEADERS.contains(h.getKey().toLowerCase(Locale.ROOT))) continue;
                headers.put(h.getKey(), String.join(", ", h.getValue()));
            }
            String contentType = conn.getContentType();
            String mime = "application/octet-stream";
            String charset = null;
            if (contentType != null) {
                String[] parts = contentType.split(";");
                mime = parts[0].trim();
                for (String p : parts) {
                    String t = p.trim();
                    if (t.toLowerCase(Locale.ROOT).startsWith("charset=")) charset = t.substring(8);
                }
            }
            InputStream body = code >= 400 ? conn.getErrorStream() : conn.getInputStream();
            if (body == null) body = new ByteArrayInputStream(new byte[0]);
            String reason = conn.getResponseMessage();
            if (reason == null || reason.isEmpty()) reason = code < 400 ? "OK" : "Error";
            return new WebResourceResponse(mime, charset, code, reason, headers, body);
        } catch (Exception e) {
            // Hors-ligne : on laisse la vue web (et le service worker) gérer l'échec réseau.
            return null;
        }
    }
}
