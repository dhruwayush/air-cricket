package io.github.dhruwayush.aircricket;

import android.app.Activity;
import android.content.pm.ActivityInfo;

import com.getcapacitor.Plugin;
import com.getcapacitor.PluginCall;
import com.getcapacitor.PluginMethod;
import com.getcapacitor.annotation.CapacitorPlugin;

/**
 * Phone as bat: you swing the phone, so the screen must not turn sideways mid-swing.
 * The page calls Capacitor.nativePromise('GameScreen', 'hold', { on }) to lock the
 * screen in whichever way it is facing, and to hand rotation back to the user after.
 */
@CapacitorPlugin(name = "GameScreen")
public class GameScreenPlugin extends Plugin {

    @PluginMethod
    public void hold(PluginCall call) {
        final boolean on = Boolean.TRUE.equals(call.getBoolean("on", false));
        final Activity activity = getActivity();
        activity.runOnUiThread(() -> {
            activity.setRequestedOrientation(on
                    ? ActivityInfo.SCREEN_ORIENTATION_LOCKED
                    : ActivityInfo.SCREEN_ORIENTATION_FULL_USER);
            call.resolve();
        });
    }
}
