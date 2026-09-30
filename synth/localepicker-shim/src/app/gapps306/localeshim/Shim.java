package app.gapps306.localeshim;

import android.app.Activity;
import android.os.Bundle;
import android.provider.Settings;

import com.android.internal.app.LocalePicker;
import com.android.internal.app.LocalePickerWithRegion;
import com.android.internal.app.LocaleStore;

/**
 * Answers com.google.android.settings.localepicker.LOCALE_REGION_PICKER, which
 * the Pixel setup wizard fires but only Google's Settings app provides. Hosts
 * the platform's own language/region picker and sets the system locale on
 * selection; the wizard re-reads it on resume.
 */
public class Shim extends Activity implements LocalePickerWithRegion.LocaleSelectedListener {
    @Override
    protected void onCreate(Bundle saved) {
        super.onCreate(saved);
        if (saved == null) {
            LocalePickerWithRegion picker =
                    LocalePickerWithRegion.createLanguagePicker(this, this, false);
            getFragmentManager().beginTransaction()
                    .replace(android.R.id.content, picker)
                    .commit();
        }
    }

    @Override
    public void onLocaleSelected(LocaleStore.LocaleInfo locale) {
        if (locale != null) {
            LocalePicker.updateLocale(locale.getLocale());
            // Or the wizard re-applies its region default on resume.
            Settings.Global.putInt(getContentResolver(), "is_locale_set", 1);
        }
        setResult(RESULT_OK);
        finish();
    }
}
