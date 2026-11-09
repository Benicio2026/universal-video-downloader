package org.universalvideo.universalvideodownloader;

import android.app.Activity;
import android.content.Intent;
import android.graphics.Color;
import android.os.Bundle;
import android.view.View;
import android.view.ViewGroup;
import android.webkit.CookieManager;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.Button;
import android.widget.LinearLayout;
import android.widget.TextView;
import android.widget.Toast;

import java.io.File;
import java.io.FileOutputStream;
import java.net.URI;
import java.nio.charset.StandardCharsets;

/**
 * 独立的登录页。放在单独的 Activity 里，避免把 WebView 叠加到 Kivy 的
 * SurfaceView 上导致卡死或闪退。登录完成后只把 cookies 写入应用私有目录，
 * App 不接触账号密码。
 */
public class LoginActivity extends Activity {
    private WebView webView;
    private String targetUrl = "";

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        Intent intent = getIntent();
        targetUrl = intent.getStringExtra("url");
        if (targetUrl == null || targetUrl.isEmpty()) {
            targetUrl = "https://www.bilibili.com/";
        }

        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setBackgroundColor(Color.rgb(15, 23, 42));

        LinearLayout bar = new LinearLayout(this);
        bar.setOrientation(LinearLayout.HORIZONTAL);
        bar.setBackgroundColor(Color.rgb(30, 41, 59));
        bar.setPadding(dp(12), dp(8), dp(12), dp(8));

        TextView title = new TextView(this);
        title.setText("登录（完成后点右侧按钮）");
        title.setTextColor(Color.WHITE);
        title.setTextSize(15);
        LinearLayout.LayoutParams titleParams =
                new LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f);
        bar.addView(title, titleParams);

        Button done = new Button(this);
        done.setText("完成登录");
        done.setAllCaps(false);
        done.setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View view) {
                finishLogin();
            }
        });
        bar.addView(done, new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.WRAP_CONTENT,
                ViewGroup.LayoutParams.WRAP_CONTENT));

        Button cancel = new Button(this);
        cancel.setText("取消");
        cancel.setAllCaps(false);
        cancel.setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View view) {
                writeResult("cancel", 0);
                finish();
            }
        });
        bar.addView(cancel, new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.WRAP_CONTENT,
                ViewGroup.LayoutParams.WRAP_CONTENT));

        webView = new WebView(this);
        try {
            WebSettings settings = webView.getSettings();
            settings.setJavaScriptEnabled(true);
            settings.setDomStorageEnabled(true);
            settings.setDatabaseEnabled(true);
            settings.setLoadWithOverviewMode(true);
            settings.setUseWideViewPort(true);
            webView.setWebViewClient(new WebViewClient());
            try {
                CookieManager.getInstance().setAcceptCookie(true);
                CookieManager.getInstance().setAcceptThirdPartyCookies(webView, true);
            } catch (Exception ignored) {
            }
            webView.loadUrl(targetUrl);
        } catch (Throwable error) {
            writeResult("error", 0);
            Toast.makeText(
                    this,
                    "登录页不可用：" + error.getMessage(),
                    Toast.LENGTH_LONG).show();
            finish();
            return;
        }

        root.addView(bar, new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.WRAP_CONTENT));
        root.addView(webView, new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, 0, 1f));
        setContentView(root);
    }

    private int dp(int value) {
        return (int) (value * getResources().getDisplayMetrics().density);
    }

    private void finishLogin() {
        try {
            String cookie = CookieManager.getInstance().getCookie(targetUrl);
            if (cookie == null || cookie.isEmpty()) {
                Toast.makeText(
                        this,
                        "没有获取到 cookies，请先完成登录",
                        Toast.LENGTH_SHORT).show();
                return;
            }

            String host = "";
            try {
                host = URI.create(targetUrl).getHost();
            } catch (Exception ignored) {
            }
            if (host == null) {
                host = "";
            }
            String domain = host;
            String[] parts = host.split("\\.");
            if (parts.length >= 2) {
                domain = "." + parts[parts.length - 2] + "." + parts[parts.length - 1];
            }

            StringBuilder builder = new StringBuilder();
            builder.append("# Netscape HTTP Cookie File\n");
            builder.append("# Generated by Universal Video Downloader\n\n");
            int count = 0;
            for (String pair : cookie.split(";")) {
                pair = pair.trim();
                if (pair.isEmpty() || pair.indexOf('=') <= 0) {
                    continue;
                }
                int index = pair.indexOf('=');
                String name = pair.substring(0, index).trim();
                String value = pair.substring(index + 1).trim();
                if (name.isEmpty()) {
                    continue;
                }
                builder.append(domain)
                        .append("\tTRUE\t/\tFALSE\t0\t")
                        .append(name)
                        .append("\t")
                        .append(value)
                        .append("\n");
                count++;
            }

            File cookieFile = new File(getFilesDir(), "webview_cookies.txt");
            try (FileOutputStream out = new FileOutputStream(cookieFile)) {
                out.write(builder.toString().getBytes(StandardCharsets.UTF_8));
            }
            writeResult("ok", count);
            setResult(RESULT_OK);
            finish();
        } catch (Exception exception) {
            Toast.makeText(
                    this,
                    "保存 cookies 失败：" + exception.getMessage(),
                    Toast.LENGTH_LONG).show();
        }
    }

    private void writeResult(String status, int count) {
        try {
            String json = "{\"status\":\"" + status + "\",\"count\":" + count + "}";
            File resultFile = new File(getFilesDir(), "webview_login_result.json");
            try (FileOutputStream out = new FileOutputStream(resultFile)) {
                out.write(json.getBytes(StandardCharsets.UTF_8));
            }
        } catch (Exception ignored) {
        }
    }

    @Override
    public void onBackPressed() {
        if (webView != null && webView.canGoBack()) {
            webView.goBack();
        } else {
            writeResult("cancel", 0);
            super.onBackPressed();
        }
    }
}
