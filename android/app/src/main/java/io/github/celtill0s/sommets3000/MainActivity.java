package io.github.celtill0s.sommets3000;

import android.Manifest;
import android.app.Activity;
import android.content.ActivityNotFoundException;
import android.content.ContentValues;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.provider.MediaStore;
import android.util.Base64;
import android.view.View;
import android.view.ViewGroup;
import android.view.WindowInsets;
import android.view.WindowInsetsController;
import android.webkit.GeolocationPermissions;
import android.webkit.HttpAuthHandler;
import android.webkit.JavascriptInterface;
import android.webkit.ServiceWorkerClient;
import android.webkit.ServiceWorkerController;
import android.webkit.ValueCallback;
import android.webkit.WebChromeClient;
import android.webkit.WebResourceRequest;
import android.webkit.WebResourceResponse;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.webkit.WebViewDatabase;
import android.widget.FrameLayout;
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

        // Requêtes du service worker (démarrage, cache hors-ligne) : identifiants ajoutés par
        // l'appli, la vue web ne sachant pas répondre à un 401 dans ce contexte.
        ServiceWorkerController.getInstance().setServiceWorkerClient(new ServiceWorkerClient() {
            @Override
            public WebResourceResponse shouldInterceptRequest(WebResourceRequest request) {
                return AuthHttp.fetch(request, credentials, MainActivity.this::onCredentialsRejected);
            }
        });

        if (Build.VERSION.SDK_INT >= 33) {
            getOnBackInvokedDispatcher().registerOnBackInvokedCallback(
                    OnBackInvokedDispatcher.PRIORITY_DEFAULT, this::handleBack);
        }

        if (savedInstanceState != null) webView.restoreState(savedInstanceState);
        else webView.loadUrl(credentials.serverUrl + "/");
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

    /** Caddy refuse les identifiants (mot de passe changé côté serveur) : retour à la connexion. */
    private void onCredentialsRejected() {
        if (!loggingOut.compareAndSet(false, true)) return;
        runOnUiThread(() -> {
            Credentials.clear(this);
            backToLogin(getString(R.string.error_rejected), null);
        });
    }

    private void backToLogin(String error, String info) {
        WebViewDatabase.getInstance(this).clearHttpAuthUsernamePassword();
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
        public WebResourceResponse shouldInterceptRequest(WebView view, WebResourceRequest request) {
            return AuthHttp.fetch(request, credentials, MainActivity.this::onCredentialsRejected);
        }

        /** Requêtes non rejouables par l'appli (POST/DELETE : coché, commentaire, upload…). */
        @Override
        public void onReceivedHttpAuthRequest(WebView view, HttpAuthHandler handler, String host, String realm) {
            if (host.equalsIgnoreCase(credentials.host()) && handler.useHttpAuthUsernamePassword()) {
                handler.proceed(credentials.username, credentials.password);
            } else {
                handler.cancel();
                if (host.equalsIgnoreCase(credentials.host())) onCredentialsRejected();
            }
        }

        /** Liens vers d'autres sites (Google Maps, sources…) : ouverts dans le navigateur. */
        @Override
        public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest request) {
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

        /** Bouton « Se déconnecter » de la page (affiché uniquement dans l'appli). */
        @JavascriptInterface
        public void logout() {
            runOnUiThread(() -> {
                Credentials.clear(MainActivity.this);
                backToLogin(null, getString(R.string.logged_out));
            });
        }
    }
}
