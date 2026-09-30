package app.gapps306.localeshim;

import android.app.Activity;
import android.app.UiModeManager;
import android.content.ComponentName;
import android.content.ContentValues;
import android.content.Context;
import android.content.Intent;
import android.content.om.IOverlayManager;
import android.content.pm.PackageManager;
import android.content.res.Configuration;
import android.graphics.Color;
import android.graphics.drawable.GradientDrawable;
import android.net.Uri;
import android.os.Bundle;
import android.os.ServiceManager;
import android.provider.Settings;
import android.util.TypedValue;
import android.view.Gravity;
import android.view.View;
import android.view.ViewGroup;
import android.widget.Button;
import android.widget.CheckBox;
import android.widget.LinearLayout;
import android.widget.RadioButton;
import android.widget.RadioGroup;
import android.widget.ScrollView;
import android.widget.TextView;

// Answers the setup wizard's OEM hook to collect the crDroid choices the Pixel
// flow skips: navigation, theme, and telemetry.
public class OemPostSetup extends Activity
        implements View.OnClickListener, RadioGroup.OnCheckedChangeListener {
    private static final String NAV_GESTURAL = "com.android.internal.systemui.navbar.gestural";
    private static final String NAV_3BUTTON = "com.android.internal.systemui.navbar.threebutton";
    private static final int NAV_GESTURE_ID = 1, NAV_3BUTTON_ID = 2, THEME_LIGHT_ID = 10, THEME_DARK_ID = 11;

    private float density;
    private int accent, primary, secondary;
    private RadioGroup nav, theme;
    private CheckBox stats;

    @Override
    protected void onCreate(Bundle saved) {
        super.onCreate(saved);
        density = getResources().getDisplayMetrics().density;
        accent = themeColor(android.R.attr.colorAccent, 0xFF3367D6);
        primary = themeColor(android.R.attr.textColorPrimary, 0xFF202124);
        secondary = themeColor(android.R.attr.textColorSecondary, 0xFF5F6368);

        LinearLayout page = new LinearLayout(this);
        page.setOrientation(LinearLayout.VERTICAL);
        page.setBackgroundColor(themeColor(android.R.attr.colorBackground, 0xFFFFFFFF));

        LinearLayout content = new LinearLayout(this);
        content.setOrientation(LinearLayout.VERTICAL);
        content.setPadding(dp(24), dp(48), dp(24), dp(24));

        content.addView(title("Finish setup"));
        content.addView(body("A few crDroid options the setup wizard doesn't cover."));

        content.addView(section("Navigation"));
        nav = new RadioGroup(this);
        nav.addView(option("Gesture navigation", NAV_GESTURE_ID));
        nav.addView(option("3-button navigation", NAV_3BUTTON_ID));
        nav.check(Settings.Secure.getInt(getContentResolver(), "navigation_mode", 2) == 0
                ? NAV_3BUTTON_ID : NAV_GESTURE_ID);
        nav.setOnCheckedChangeListener(this);
        content.addView(nav);

        content.addView(section("Theme"));
        theme = new RadioGroup(this);
        theme.addView(option("Light", THEME_LIGHT_ID));
        theme.addView(option("Dark", THEME_DARK_ID));
        boolean night = (getResources().getConfiguration().uiMode
                & Configuration.UI_MODE_NIGHT_MASK) == Configuration.UI_MODE_NIGHT_YES;
        theme.check(night ? THEME_DARK_ID : THEME_LIGHT_ID);
        theme.setOnCheckedChangeListener(this);
        content.addView(theme);

        content.addView(section("Privacy"));
        stats = new CheckBox(this);
        stats.setId(20);
        stats.setText("Send anonymous crDroid statistics");
        stats.setTextColor(primary);
        stats.setPadding(dp(8), dp(12), 0, dp(12));
        content.addView(stats);

        ScrollView sv = new ScrollView(this);
        sv.setLayoutParams(new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, 0, 1f));
        sv.addView(content);
        page.addView(sv);
        page.addView(footer());

        setContentView(page);
    }

    @Override
    public void onCheckedChanged(RadioGroup group, int id) {
        if (group == nav) {
            applyNav(id == NAV_3BUTTON_ID);
        } else if (group == theme) {
            applyTheme(id == THEME_DARK_ID);
        }
    }

    @Override
    public void onClick(View v) {
        applyStats(stats.isChecked());
        // We are the last step; finish setup ourselves rather than hand back to
        // the wizard, whose finalization would loop back through this hook.
        try {
            Settings.Global.putInt(getContentResolver(), "device_provisioned", 1);
            Settings.Secure.putInt(getContentResolver(), "user_setup_complete", 1);
        } catch (Exception e) {
        }
        try {
            getPackageManager().setComponentEnabledSetting(
                    new ComponentName(this, OemPostSetup.class),
                    PackageManager.COMPONENT_ENABLED_STATE_DISABLED,
                    PackageManager.DONT_KILL_APP);
        } catch (Exception e) {
        }
        startActivity(new Intent(Intent.ACTION_MAIN)
                .addCategory(Intent.CATEGORY_HOME)
                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_CLEAR_TASK));
        finish();
    }

    private void applyNav(boolean threeButton) {
        try {
            IOverlayManager om = IOverlayManager.Stub.asInterface(ServiceManager.getService("overlay"));
            om.setEnabledExclusiveInCategory(threeButton ? NAV_3BUTTON : NAV_GESTURAL, 0);
        } catch (Exception e) {
        }
    }

    private void applyTheme(boolean dark) {
        try {
            UiModeManager um = (UiModeManager) getSystemService(Context.UI_MODE_SERVICE);
            um.setNightMode(dark ? UiModeManager.MODE_NIGHT_YES : UiModeManager.MODE_NIGHT_NO);
        } catch (Exception e) {
        }
    }

    private void applyStats(boolean on) {
        try {
            ContentValues cv = new ContentValues();
            cv.put("name", "stats_collection");
            cv.put("value", on ? "1" : "0");
            getContentResolver().insert(Uri.parse("content://lineagesettings/secure"), cv);
        } catch (Exception e) {
        }
    }

    private LinearLayout footer() {
        LinearLayout bar = new LinearLayout(this);
        bar.setOrientation(LinearLayout.HORIZONTAL);
        bar.setGravity(Gravity.END);
        bar.setPadding(dp(24), dp(12), dp(24), dp(20));

        Button done = new Button(this);
        done.setText("Done");
        done.setAllCaps(false);
        done.setTextColor(Color.WHITE);
        done.setTextSize(16);
        done.setPadding(dp(28), 0, dp(28), 0);
        GradientDrawable bg = new GradientDrawable();
        bg.setColor(accent);
        bg.setCornerRadius(dp(20));
        done.setBackground(bg);
        done.setOnClickListener(this);
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.WRAP_CONTENT, dp(48));
        bar.addView(done, lp);
        return bar;
    }

    private TextView title(String s) {
        TextView t = new TextView(this);
        t.setText(s);
        t.setTextSize(30);
        t.setTextColor(primary);
        t.setPadding(0, 0, 0, dp(8));
        return t;
    }

    private TextView body(String s) {
        TextView t = new TextView(this);
        t.setText(s);
        t.setTextSize(15);
        t.setTextColor(secondary);
        t.setPadding(0, 0, 0, dp(16));
        return t;
    }

    private TextView section(String s) {
        TextView t = new TextView(this);
        t.setText(s.toUpperCase());
        t.setTextSize(13);
        t.setTextColor(accent);
        t.setLetterSpacing(0.06f);
        t.setPadding(0, dp(20), 0, dp(4));
        return t;
    }

    private RadioButton option(String s, int id) {
        RadioButton r = new RadioButton(this);
        r.setText(s);
        r.setId(id);
        r.setTextSize(16);
        r.setTextColor(primary);
        r.setPadding(dp(8), dp(12), 0, dp(12));
        return r;
    }

    private int dp(float v) {
        return (int) (v * density);
    }

    private int themeColor(int attr, int fallback) {
        try {
            TypedValue tv = new TypedValue();
            if (getTheme().resolveAttribute(attr, tv, true)) {
                return tv.data != 0 ? tv.data : getColor(tv.resourceId);
            }
        } catch (Exception e) {
        }
        return fallback;
    }
}
