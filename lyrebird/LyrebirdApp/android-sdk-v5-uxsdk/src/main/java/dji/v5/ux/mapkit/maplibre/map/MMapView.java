package dji.v5.ux.mapkit.maplibre.map;

import android.content.Context;
import androidx.annotation.NonNull;
import androidx.annotation.Nullable;

import dji.v5.ux.mapkit.core.maps.DJIMapView;
import dji.v5.ux.mapkit.core.maps.DJIMapViewInternal;

import org.maplibre.android.maps.MapView;
import org.maplibre.android.maps.MapLibreMap;
import org.maplibre.android.maps.MapLibreMapOptions;
import org.maplibre.android.maps.OnMapReadyCallback;
import org.maplibre.android.maps.Style;

/**
 * Created by joeyang on 11/3/17.
 */
public class MMapView extends MapView implements DJIMapViewInternal {

    public MMapView(@NonNull Context context) {
        super(context);
    }

    public MMapView(@NonNull Context context, @Nullable MapLibreMapOptions options) {
        super(context, options);
    }

    @Override
    public void getDJIMapAsync(final DJIMapView.OnDJIMapReadyCallback callback) {
        if(callback != null) {
            getMapAsync(mapboxMap -> mapboxMap.setStyle(MaplibreStyle.MAPBOX_STREETS, style -> {
                MaplibreMapDelegate map = new MaplibreMapDelegate(mapboxMap, getContext(), MMapView.this, style);
                callback.onDJIMapReady(map);
            }));
        }
    }

    @Override
    public boolean performClick() {
        return super.performClick();
    }
}
