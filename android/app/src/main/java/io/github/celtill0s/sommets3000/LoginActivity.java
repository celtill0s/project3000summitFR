package io.github.celtill0s.sommets3000;

import android.app.Activity;
import android.content.Intent;
import android.net.Uri;
import android.os.Bundle;
import android.view.View;
import android.view.inputmethod.EditorInfo;
import android.widget.Button;
import android.widget.EditText;
import android.widget.ProgressBar;
import android.widget.TextView;

/**
 * Écran de connexion : adresse du serveur + identifiants Basic Auth (ceux de Caddy). Vérifiés
 * auprès du serveur avant d'entrer ; si des identifiants valides sont déjà mémorisés, on passe
 * directement à la carte.
 */
public class LoginActivity extends Activity {
    static final String EXTRA_MESSAGE = "message"; // erreur (en rouge)
    static final String EXTRA_INFO = "info"; // information (couleur neutre)

    private EditText urlField;
    private EditText userField;
    private EditText passwordField;
    private Button loginButton;
    private ProgressBar progress;
    private TextView error;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        if (getIntent().getStringExtra(EXTRA_MESSAGE) == null && getIntent().getStringExtra(EXTRA_INFO) == null
                && Credentials.load(this) != null) {
            openMap();
            return;
        }
        setContentView(R.layout.activity_login);
        urlField = findViewById(R.id.server_url);
        userField = findViewById(R.id.username);
        passwordField = findViewById(R.id.password);
        loginButton = findViewById(R.id.login);
        progress = findViewById(R.id.progress);
        error = findViewById(R.id.error);

        String lastUrl = Credentials.lastServerUrl(this);
        urlField.setText(lastUrl != null ? lastUrl : BuildConfig.DEFAULT_SERVER_URL);
        String lastUser = Credentials.lastUsername(this);
        if (lastUser != null) {
            userField.setText(lastUser);
            passwordField.requestFocus();
        }
        String message = getIntent().getStringExtra(EXTRA_MESSAGE);
        if (message != null) showError(message);
        String info = getIntent().getStringExtra(EXTRA_INFO);
        if (info != null) showInfo(info);

        loginButton.setOnClickListener(v -> attemptLogin());
        passwordField.setOnEditorActionListener((v, actionId, event) -> {
            if (actionId == EditorInfo.IME_ACTION_DONE) {
                attemptLogin();
                return true;
            }
            return false;
        });
    }

    private void attemptLogin() {
        String url = normalizeUrl(urlField.getText().toString());
        String user = userField.getText().toString().trim();
        String password = passwordField.getText().toString();
        if (url == null) {
            showError(getString(R.string.error_url));
            return;
        }
        if (user.isEmpty() || password.isEmpty()) {
            showError(getString(R.string.error_empty));
            return;
        }
        Credentials c = new Credentials(url, user, password);
        setBusy(true);
        new Thread(() -> {
            AuthHttp.CheckResult result = AuthHttp.check(c);
            runOnUiThread(() -> {
                setBusy(false);
                switch (result) {
                    case OK:
                        try {
                            c.save(this);
                        } catch (Exception e) {
                            showError(getString(R.string.error_storage));
                            return;
                        }
                        openMap();
                        break;
                    case BAD_CREDENTIALS:
                        showError(getString(R.string.error_credentials));
                        break;
                    case NOT_THIS_APP:
                        showError(getString(R.string.error_not_this_app));
                        break;
                    default:
                        showError(getString(R.string.error_network));
                }
            });
        }).start();
    }

    /**
     * Ajoute https:// si absent et retire le / final. HTTPS obligatoire (le mot de passe
     * circule dans chaque requête), sauf http://localhost en build de debug (tests).
     */
    private static String normalizeUrl(String raw) {
        String s = raw.trim();
        if (s.isEmpty()) return null;
        if (!s.contains("://")) s = "https://" + s;
        while (s.endsWith("/")) s = s.substring(0, s.length() - 1);
        Uri u = Uri.parse(s);
        if (u.getHost() == null || u.getHost().isEmpty()) return null;
        boolean debugLocalhost = BuildConfig.DEBUG && "http".equals(u.getScheme()) && "localhost".equals(u.getHost());
        if (!"https".equals(u.getScheme()) && !debugLocalhost) return null;
        return s;
    }

    private void setBusy(boolean busy) {
        loginButton.setEnabled(!busy);
        progress.setVisibility(busy ? View.VISIBLE : View.GONE);
        if (busy) error.setVisibility(View.GONE);
    }

    private void showError(String message) {
        error.setTextColor(getColor(R.color.error));
        error.setText(message);
        error.setVisibility(View.VISIBLE);
    }

    private void showInfo(String message) {
        error.setTextColor(getColor(R.color.text));
        error.setText(message);
        error.setVisibility(View.VISIBLE);
    }

    private void openMap() {
        startActivity(new Intent(this, MainActivity.class));
        finish();
    }
}
