package io.github.celtill0s.sommets3000;

import android.Manifest;
import android.app.Activity;
import android.app.AlertDialog;
import android.content.ActivityNotFoundException;
import android.content.ContentValues;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.content.res.Configuration;
import android.graphics.drawable.GradientDrawable;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.provider.MediaStore;
import android.util.Base64;
import android.view.Gravity;
import android.view.View;
import android.view.ViewGroup;
import android.view.WindowInsets;
import android.view.WindowInsetsController;
import android.webkit.CookieManager;
import android.webkit.GeolocationPermissions;
import android.webkit.JavascriptInterface;
import android.webkit.ValueCallback;
import android.webkit.WebChromeClient;
import android.webkit.WebResourceRequest;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.FrameLayout;
import android.widget.ImageButton;
import android.widget.Toast;
import android.window.OnBackInvokedDispatcher;

import java.io.OutputStream;
import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.atomic.AtomicBoolean;

/** La carte : le site servi par l'instance, dans une vue web intégrée. */
public class MainActivity extends Activity {
    private static final int REQ_FILES = 1;
    private static final int REQ_LOCATION = 2;

    private WebView webView;
    private final AppChromeClient chromeClient = new AppChromeClient();
    private FrameLayout root;
    private ImageButton exitButton;
    private volatile boolean exitHiddenByPage = false; // écran du site par-dessus la carte
    private Credentials credentials;
    private final AtomicBoolean loggingOut = new AtomicBoolean(false);

    private ValueCallback<Uri[]> pendingFiles;
    private String pendingGeoOrigin;
    private GeolocationPermissions.Callback pendingGeoCallback;
    private View customView;
    private WebChromeClient.CustomViewCallback customViewCallback;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        credentials = Credentials.load(this);
        if (credentials == null) {
            backToLogin(null, null);
            return;
        }
        // Débogage de la vue web (chrome://inspect) uniquement dans les builds de debug.
        WebView.setWebContentsDebuggingEnabled(BuildConfig.DEBUG);

        root = new FrameLayout(this);
        root.setFitsSystemWindows(true); // pas de contenu sous la barre d'état / de navigation
        webView = new WebView(this);
        root.addView(webView, new FrameLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT));
        addExitButton();
        setContentView(root);

        WebSettings s = webView.getSettings();
        s.setJavaScriptEnabled(true);
        s.setDomStorageEnabled(true);
        s.setGeolocationEnabled(true);
        s.setMediaPlaybackRequiresUserGesture(true);
        s.setUserAgentString(s.getUserAgentString() + " Sommets3000App/" + BuildConfig.VERSION_NAME);

        webView.setWebViewClient(new AppWebViewClient());
        webView.setWebChromeClient(chromeClient);
        webView.addJavascriptInterface(new Bridge(), "SommetsApp");
        webView.setDownloadListener((url, userAgent, contentDisposition, mimeType, length) -> openExternal(Uri.parse(url)));

        if (Build.VERSION.SDK_INT >= 33) {
            getOnBackInvokedDispatcher().registerOnBackInvokedCallback(
                    OnBackInvokedDispatcher.PRIORITY_DEFAULT, this::handleBack);
        }

        // Session : le cookie délivré à la connexion est confié à la vue web, qui l'envoie ensuite
        // d'elle-même avec chaque requête (page, service worker, envois de photos…).
        CookieManager cookies = CookieManager.getInstance();
        cookies.setAcceptCookie(true);
        cookies.setCookie(credentials.serverUrl, credentials.sessionCookie(), ok -> {
            cookies.flush();
            if (savedInstanceState != null) webView.restoreState(savedInstanceState);
            else webView.loadUrl(credentials.serverUrl + "/");
        });
    }

    @Override
    protected void onSaveInstanceState(Bundle outState) {
        super.onSaveInstanceState(outState);
        if (webView != null) webView.saveState(outState);
    }

    @Override
    @SuppressWarnings("deprecation")
    public void onBackPressed() {
        handleBack(); // Android < 13
    }

    /** Retour : ferme d'abord ce qui est ouvert dans la page (visionneuse, panneau…), sinon quitte. */
    private void handleBack() {
        if (customView != null) {
            chromeClient.onHideCustomView();
            return;
        }
        webView.evaluateJavascript("window.__appBack ? window.__appBack() : false", result -> {
            if ("true".equals(result)) return;
            if (webView.canGoBack()) webView.goBack();
            else finish();
        });
    }

    /**
     * Bouton « porte de sortie » (déconnexion), natif : ne dépend pas de la version du site.
     * Téléphone : coin haut droit de la carte (libre sur mobile). Écran large (≥ 760 dp, mise en
     * page « bureau » du site) : sous le sélecteur de calques, qui occupe ce coin.
     */
    private void addExitButton() {
        float dp = getResources().getDisplayMetrics().density;
        exitButton = new ImageButton(this);
        exitButton.setImageResource(R.drawable.ic_exit);
        exitButton.setContentDescription(getString(R.string.logout));
        exitButton.setTooltipText(getString(R.string.logout));
        GradientDrawable bg = new GradientDrawable();
        bg.setShape(GradientDrawable.OVAL);
        bg.setColor(getColor(R.color.brand_dark));
        exitButton.setBackground(bg);
        exitButton.setElevation(4 * dp);
        exitButton.setAlpha(0.92f);
        exitButton.setOnClickListener(v -> confirmLogout());
        root.addView(exitButton);
        positionExitButton();
    }

    private void positionExitButton() {
        float dp = getResources().getDisplayMetrics().density;
        boolean wide = getResources().getConfiguration().screenWidthDp >= 760;
        FrameLayout.LayoutParams lp = new FrameLayout.LayoutParams(Math.round(40 * dp), Math.round(40 * dp), Gravity.TOP | Gravity.END);
        lp.topMargin = Math.round((wide ? 220 : 12) * dp);
        lp.rightMargin = Math.round(12 * dp);
        exitButton.setLayoutParams(lp);
    }

    @Override
    public void onConfigurationChanged(Configuration newConfig) {
        super.onConfigurationChanged(newConfig); // rotation : pas de rechargement (configChanges)
        if (exitButton != null) positionExitButton();
    }

    private void confirmLogout() {
        new AlertDialog.Builder(this)
                .setMessage(R.string.logout_confirm)
                .setPositiveButton(R.string.logout, (d, w) -> {
                    Credentials session = credentials;
                    Credentials.clear(this);
                    new Thread(() -> AuthHttp.logout(session)).start(); // ferme la session côté serveur
                    backToLogin(null, getString(R.string.logged_out));
                })
                .setNegativeButton(R.string.cancel, null)
                .show();
    }

    /**
     * Cache le bouton quand la page affiche un écran par-dessus la carte (visionneuse, vue
     * crampons, liste plein écran) : leurs boutons de fermeture sont eux aussi en haut à droite.
     * Injecté par l'appli ; sans effet si le site n'a pas ces éléments.
     */
    private static final String OVERLAY_WATCHER_JS =
            "(() => { if (window.__exitWatch) return; window.__exitWatch = true;"
            + " let last = null;"
            + " const update = () => {"
            + "   const covered = !!document.querySelector('#photo-lightbox:not([hidden]), #crampon-view:not([hidden]), #app.mobile-list-open');"
            + "   if (covered !== last) { last = covered; SommetsApp.setExitButtonVisible(!covered); }"
            + " };"
            + " new MutationObserver(update).observe(document.body, {subtree: true, attributes: true, attributeFilter: ['hidden', 'class']});"
            + " update(); })();";

    /**
     * Le site renvoie vers sa page de connexion : session expirée ou fermée (mot de passe changé,
     * compte supprimé, déconnexion depuis un autre appareil). Retour à l'écran de connexion natif.
     */
    private void onCredentialsRejected() {
        if (!loggingOut.compareAndSet(false, true)) return;
        runOnUiThread(() -> {
            Credentials.clear(this);
            backToLogin(getString(R.string.error_rejected), null);
        });
    }

    private void backToLogin(String error, String info) {
        CookieManager.getInstance().removeAllCookies(null);
        Intent i = new Intent(this, LoginActivity.class);
        if (error != null) i.putExtra(LoginActivity.EXTRA_MESSAGE, error);
        if (info != null) i.putExtra(LoginActivity.EXTRA_INFO, info);
        i.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_CLEAR_TASK);
        startActivity(i);
        finish();
    }

    private boolean isOwnServer(Uri uri) {
        return uri.getHost() != null && uri.getHost().equalsIgnoreCase(credentials.host())
                && ("https".equals(uri.getScheme()) || "http".equals(uri.getScheme()));
    }

    private void openExternal(Uri uri) {
        try {
            startActivity(new Intent(Intent.ACTION_VIEW, uri));
        } catch (ActivityNotFoundException e) {
            Toast.makeText(this, R.string.error_no_app, Toast.LENGTH_SHORT).show();
        }
    }

    private class AppWebViewClient extends WebViewClient {
        @Override
        public void onPageStarted(WebView view, String url, android.graphics.Bitmap favicon) {
            Uri u = Uri.parse(url);
            if (isOwnServer(u) && "/login".equals(u.getPath())) onCredentialsRejected();
        }

        @Override
        public void onPageFinished(WebView view, String url) {
            if (isOwnServer(Uri.parse(url))) view.evaluateJavascript(OVERLAY_WATCHER_JS, null);
        }

        /** Liens vers d'autres sites (Google Maps, sources…) : ouverts dans le navigateur. */
        @Override
        public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest request) {
            if (isOwnServer(request.getUrl()) && "/login".equals(request.getUrl().getPath())) {
                onCredentialsRejected(); // redirection (ou page) vers la connexion web : session finie
                return true;
            }
            if (isOwnServer(request.getUrl())) return false;
            openExternal(request.getUrl());
            return true;
        }
    }

    private class AppChromeClient extends WebChromeClient {
        @Override
        public void onGeolocationPermissionsShowPrompt(String origin, GeolocationPermissions.Callback callback) {
            if (checkSelfPermission(Manifest.permission.ACCESS_FINE_LOCATION) == PackageManager.PERMISSION_GRANTED
                    || checkSelfPermission(Manifest.permission.ACCESS_COARSE_LOCATION) == PackageManager.PERMISSION_GRANTED) {
                callback.invoke(origin, true, false);
                return;
            }
            pendingGeoOrigin = origin;
            pendingGeoCallback = callback;
            requestPermissions(new String[]{Manifest.permission.ACCESS_FINE_LOCATION, Manifest.permission.ACCESS_COARSE_LOCATION}, REQ_LOCATION);
        }

        @Override
        public boolean onShowFileChooser(WebView view, ValueCallback<Uri[]> callback, FileChooserParams params) {
            if (pendingFiles != null) pendingFiles.onReceiveValue(null);
            pendingFiles = callback;
            Intent intent = new Intent(Intent.ACTION_GET_CONTENT);
            intent.addCategory(Intent.CATEGORY_OPENABLE);
            intent.putExtra(Intent.EXTRA_ALLOW_MULTIPLE, params.getMode() == FileChooserParams.MODE_OPEN_MULTIPLE);
            // accept="image/*,video/*" → filtre par types ; accept=".gpx,…" (extensions) → pas de
            // filtre : Android ne connaît souvent pas le type des fichiers GPX.
            List<String> mimes = new ArrayList<>();
            boolean hasExtension = false;
            for (String a : params.getAcceptTypes()) {
                for (String t : a.split(",")) {
                    t = t.trim();
                    if (t.startsWith(".")) hasExtension = true;
                    else if (!t.isEmpty()) mimes.add(t);
                }
            }
            intent.setType("*/*");
            if (!hasExtension && !mimes.isEmpty()) intent.putExtra(Intent.EXTRA_MIME_TYPES, mimes.toArray(new String[0]));
            try {
                startActivityForResult(intent, REQ_FILES);
            } catch (ActivityNotFoundException e) {
                pendingFiles = null;
                return false;
            }
            return true;
        }

        /** Vidéo en plein écran. */
        @Override
        public void onShowCustomView(View view, CustomViewCallback callback) {
            if (customView != null) {
                callback.onCustomViewHidden();
                return;
            }
            customView = view;
            customViewCallback = callback;
            root.addView(view, new FrameLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT));
            webView.setVisibility(View.GONE);
            exitButton.setVisibility(View.GONE);
            WindowInsetsController c = getWindow().getInsetsController();
            if (c != null) {
                c.hide(WindowInsets.Type.systemBars());
                c.setSystemBarsBehavior(WindowInsetsController.BEHAVIOR_SHOW_TRANSIENT_BARS_BY_SWIPE);
            }
        }

        @Override
        public void onHideCustomView() {
            if (customView == null) return;
            root.removeView(customView);
            customView = null;
            webView.setVisibility(View.VISIBLE);
            exitButton.setVisibility(exitHiddenByPage ? View.GONE : View.VISIBLE);
            WindowInsetsController c = getWindow().getInsetsController();
            if (c != null) c.show(WindowInsets.Type.systemBars());
            if (customViewCallback != null) customViewCallback.onCustomViewHidden();
            customViewCallback = null;
        }
    }

    @Override
    protected void onActivityResult(int requestCode, int resultCode, Intent data) {
        super.onActivityResult(requestCode, resultCode, data);
        if (requestCode != REQ_FILES || pendingFiles == null) return;
        Uri[] result = null;
        if (resultCode == RESULT_OK && data != null) {
            if (data.getClipData() != null) {
                result = new Uri[data.getClipData().getItemCount()];
                for (int i = 0; i < result.length; i++) result[i] = data.getClipData().getItemAt(i).getUri();
            } else if (data.getData() != null) {
                result = new Uri[]{data.getData()};
            }
        }
        pendingFiles.onReceiveValue(result); // null si annulé : obligatoire pour pouvoir rouvrir
        pendingFiles = null;
    }

    @Override
    public void onRequestPermissionsResult(int requestCode, String[] permissions, int[] grantResults) {
        if (requestCode != REQ_LOCATION || pendingGeoCallback == null) return;
        boolean granted = false;
        for (int r : grantResults) granted |= r == PackageManager.PERMISSION_GRANTED;
        pendingGeoCallback.invoke(pendingGeoOrigin, granted, false);
        pendingGeoCallback = null;
        pendingGeoOrigin = null;
    }

    /**
     * Pont JavaScript → appli, exposé sous window.SommetsApp. N'est utilisable que par les pages
     * du serveur configuré (les liens externes s'ouvrent hors de l'appli).
     */
    private class Bridge {
        /** Enregistre un fichier généré par la page (trace GPX) dans « Téléchargements ». */
        @JavascriptInterface
        public boolean saveFile(String filename, String mimeType, String base64) {
            try {
                ContentValues v = new ContentValues();
                v.put(MediaStore.Downloads.DISPLAY_NAME, filename.replaceAll("[\\\\/:*?\"<>|]", "_"));
                v.put(MediaStore.Downloads.MIME_TYPE, mimeType);
                Uri uri = getContentResolver().insert(MediaStore.Downloads.EXTERNAL_CONTENT_URI, v);
                if (uri == null) return false;
                try (OutputStream out = getContentResolver().openOutputStream(uri)) {
                    out.write(Base64.decode(base64, Base64.DEFAULT));
                }
                runOnUiThread(() -> Toast.makeText(MainActivity.this,
                        getString(R.string.file_saved, filename), Toast.LENGTH_LONG).show());
                return true;
            } catch (Exception e) {
                return false;
            }
        }

        /** Appelé par la surveillance injectée (OVERLAY_WATCHER_JS). */
        @JavascriptInterface
        public void setExitButtonVisible(boolean visible) {
            exitHiddenByPage = !visible;
            runOnUiThread(() -> {
                if (customView == null) exitButton.setVisibility(visible ? View.VISIBLE : View.GONE);
            });
        }
    }
}
