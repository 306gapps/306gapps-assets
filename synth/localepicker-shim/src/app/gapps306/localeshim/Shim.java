package app.gapps306.localeshim;

import android.app.Activity;
import android.content.Intent;
import android.os.Bundle;
import android.provider.Settings;

/**
 * Answers com.google.android.settings.localepicker.LOCALE_REGION_PICKER, which
 * the Pixel setup wizard fires but only Google's Settings app provides. Hands
 * off to the ROM's own language picker (ACTION_LOCALE_SETTINGS), which sets the
 * system locale; the wizard then re-reads it. Invisible itself (NoDisplay).
 */
public class Shim extends Activity {
    @Override
    protected void onCreate(Bundle saved) {
        super.onCreate(saved);
        if (saved == null) {
            try {
                startActivityForResult(new Intent(Settings.ACTION_LOCALE_SETTINGS), 1);
                return;
            } catch (Exception e) {
                // No locale settings to hand off to; just satisfy the caller.
            }
            setResult(RESULT_OK);
            finish();
        }
    }

    @Override
    protected void onActivityResult(int req, int res, Intent data) {
        setResult(RESULT_OK, data);
        finish();
    }
}
